"""Zendure SolarFlow local HTTP driver.

Implements BatteryDriver for Zendure SolarFlow devices (2400 AC+, 1600 AC+, etc.)
via the local REST API.

One-time device prerequisite:
  Enable HEMS in the Zendure app, then exit. This activates the local HTTP server.
  (EN 18031 compliance keeps HTTP off by default; HEMS toggles it on.)

Transport: aiohttp polling.
  - Read:  GET  /properties/report  → full property snapshot every poll
  - Write: POST /properties/write   → property dict + optional smartMode

Control mapping (net_power_w sign: +charge / -discharge, same as Marstek convention):
  net > 0  → acMode=1 (charge from grid), inputLimit=power,  smartMode=1
  net < 0  → acMode=2 (discharge to home), outputLimit=|power|, smartMode=1
  net == 0 → acMode=2, outputLimit=0, smartMode=1

smartMode=1 on a write keeps the setpoint in RAM instead of flash, so the per-cycle
real-time PD writes don't wear the flash. It obeys the commanded acMode and holds the
setpoint as long as HEMS is DISABLED (required for this integration). With HEMS enabled
the device's smart-matching loop ignores acMode and reverts manual control after ~10-14 s
(the "charge 2 s then back to 0" symptom). smartMode is a sticky device property, so
the per-cycle power loop holds it at 1; config writes (apply_config, write_control)
must send smartMode=0 explicitly to commit to flash and survive reboots.

battery_power is synthesised: outputPackPower − packInputPower
  (+charge: outputPackPower > 0; −discharge: packInputPower > 0)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

import aiohttp

from .base import (
    BatteryDriver,
    DriverCapabilities,
    ReadGroup,
    SetpointResult,
    TelemetrySnapshot,
)

_LOGGER = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5)

# Zendure API property name → logical coordinator key.
_PROP_TO_KEY: dict[str, str] = {
    "electricLevel":    "battery_soc",
    "outputHomePower":  "output_home_power",
    "solarInputPower":  "solar_power",
    "gridInputPower":   "grid_input_power",
    "packInputPower":   "pack_input_power",
    "outputPackPower":  "output_pack_power",
    "hyperTmp":         "internal_temperature",
    "faultLevel":       "fault_level",
    "acStatus":         "ac_status",
    "remainOutTime":    "remain_discharge_time",
    "packNum":          "pack_count",
    "is_error":         "is_error",
    "outputLimit":      "output_limit",
    "inputLimit":       "input_limit",
    "acMode":           "ac_mode",
    "socSet":           "soc_set",
    "minSoc":           "min_soc",
    "inverseMaxPower":  "inverse_max_power",
    # Off-grid output port mode (3-state enum, confirmed on a 2400 AC+):
    # 0=normal, 1=economy, 2=off. Exposed as a select; write_control sends
    # smartMode=0 so the flash write survives reboots.
    "gridOffMode":      "grid_off_mode",
    # Device's real AC charge ceiling (distinct from inverseMaxPower, which caps
    # discharge/inverter output). Mapped to the control-layer max_charge_power so
    # the coordinator syncs it and PD stops allocating charge the device cannot
    # accept (it hard-clamps charge to this, e.g. 800 W on a 2400 AC+).
    "chargeMaxLimit":   "max_charge_power",
    # Per-MPPT solar inputs, battery voltage, WiFi RSSI and off-grid output are
    # exposed via the same logical keys as the Marstek driver for cross-brand
    # homogeneity (shared translations + dashboard cards). Cell voltages come
    # from packData[], not properties, so they are not mapped here.
    "solarPower1":      "mppt1_power",
    "solarPower2":      "mppt2_power",
    "solarPower3":      "mppt3_power",
    "solarPower4":      "mppt4_power",
    "BatVolt":          "battery_voltage",
    "rssi":             "wifi_signal_strength",
    "gridOffPower":     "ac_offgrid_power",
}

# Reverse map for write_control: logical key → API property name.
_KEY_TO_PROP: dict[str, str] = {v: k for k, v in _PROP_TO_KEY.items()}

_AC_MODE_CHARGE = 1
_AC_MODE_DISCHARGE = 2

# socSet / minSoc are deci-percent on the device (1000 = 100.0%), unlike the
# whole-percent entity definitions and the rest of the integration. Converted on
# read (÷10) and write (×10). Confirmed on a 2400 AC+: writing socSet=100 set the
# device target to 10%, so it refused to charge a battery already above 10%.
_DECIPERCENT_KEYS = frozenset({"soc_set", "min_soc"})

# remainOutTime reports 59940 (999 h, expressed in minutes) when the device is
# idle / not discharging. Surface that as unknown rather than a bogus ~41-day
# duration.
_REMAIN_TIME_SENTINEL = 59940

# Per-pack telemetry from packData[] is exposed as `pack{N}_{suffix}` logical
# keys (N is 1-based). They are not in SENSOR_DEFINITIONS — the platform builds
# one ZendurePackSensor per (pack, spec) from PACK_FIELD_SPECS at setup, sized to
# the real pack count — so the driver pre-scales the values here (the coordinator
# only scales keys that have a definition). Matches this regex; preserved through
# the read_telemetry key filter even though no definition lists them.
_PACK_KEY_RE = re.compile(r"^pack\d+_")

# Numeric per-pack sensor fields. Each becomes a sensor entity per pack; sn /
# model / state ride along as attributes on the SoC sensor (see ZendurePackSensor).
PACK_FIELD_SPECS: list[dict] = [
    {"suffix": "soc",              "name": "SOC",              "unit": "%",  "device_class": "battery",     "precision": 0, "icon": "mdi:battery"},
    {"suffix": "voltage",          "name": "Voltage",          "unit": "V",  "device_class": "voltage",     "precision": 2},
    {"suffix": "max_cell_voltage", "name": "Max Cell Voltage", "unit": "V",  "device_class": "voltage",     "precision": 3},
    {"suffix": "min_cell_voltage", "name": "Min Cell Voltage", "unit": "V",  "device_class": "voltage",     "precision": 3},
    {"suffix": "temperature",      "name": "Temperature",      "unit": "°C", "device_class": "temperature", "precision": 1},
    {"suffix": "power",            "name": "Power",            "unit": "W",  "device_class": "power",       "precision": 0},
]


# ---------------------------------------------------------------------------
# Entity definitions
# ---------------------------------------------------------------------------
# No "register" or "data_type" fields — the driver maps properties → keys
# directly.  "scale": 1 means the API value is used as-is.

SENSOR_DEFINITIONS: list[dict] = [
    {"key": "battery_soc",          "name": "Battery SOC",              "unit": "%",
     "device_class": "battery",     "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "medium",     "enabled_by_default": True},
    {"key": "output_home_power",    "name": "Output to Home",           "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "solar_power",          "name": "Solar Power",              "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "icon": "mdi:solar-power",     "scan_interval": "high",            "enabled_by_default": True},
    {"key": "grid_input_power",     "name": "Grid Input Power",         "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "pack_input_power",     "name": "Battery Discharge Power",  "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "output_pack_power",    "name": "Battery Charge Power",     "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "battery_power",        "name": "Battery Power",            "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "internal_temperature", "name": "Internal Temperature",     "unit": "°C",
     "device_class": "temperature", "state_class": "measurement",       "scale": 0.01, "precision": 2,
     "scan_interval": "low",        "enabled_by_default": True},
    {"key": "remain_discharge_time","name": "Remaining Discharge Time", "unit": "min",
     "device_class": "duration",    "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "medium",     "enabled_by_default": True},
    {"key": "fault_level",          "name": "Fault Level",              "unit": None,
     "device_class": None,          "state_class": None,                "scale": 1, "precision": 0,
     "scan_interval": "low",        "enabled_by_default": False},
    {"key": "pack_count",           "name": "Battery Pack Count",       "unit": None,
     "device_class": None,          "state_class": None,                "scale": 1, "precision": 0,
     "scan_interval": "low",        "enabled_by_default": False},
    {"key": "output_limit",         "name": "Output Limit",             "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "medium",     "enabled_by_default": False},
    {"key": "input_limit",          "name": "Input Limit",              "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "medium",     "enabled_by_default": False},
    {"key": "ac_mode",              "name": "AC Mode",                  "unit": None,
     "device_class": None,          "state_class": None,                "scale": 1, "precision": 0,
     "scan_interval": "medium",     "enabled_by_default": False},
    # Reused Marstek logical keys (shared translations + dashboard cards).
    {"key": "mppt1_power",          "name": "MPPT1 Power",              "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "mppt2_power",          "name": "MPPT2 Power",              "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "mppt3_power",          "name": "MPPT3 Power",              "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "mppt4_power",          "name": "MPPT4 Power",              "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "battery_voltage",      "name": "Battery Voltage",          "unit": "V",
     "device_class": "voltage",     "state_class": "measurement",       "scale": 0.01, "precision": 1,
     "scan_interval": "medium",     "enabled_by_default": True},
    {"key": "ac_offgrid_power",     "name": "AC Offgrid Power",         "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "max_cell_voltage",     "name": "Max Cell Voltage",         "unit": "V",
     "device_class": "voltage",     "state_class": "measurement",       "scale": 0.01, "precision": 3,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "min_cell_voltage",     "name": "Min Cell Voltage",         "unit": "V",
     "device_class": "voltage",     "state_class": "measurement",       "scale": 0.01, "precision": 3,
     "scan_interval": "high",       "enabled_by_default": True},
    {"key": "wifi_signal_strength", "name": "WiFi Signal Strength",     "unit": "dBm",
     "device_class": "signal_strength", "state_class": "measurement",   "scale": 1, "precision": 0,
     "category": "diagnostic",      "scan_interval": "low",             "enabled_by_default": True},
]

NUMBER_DEFINITIONS: list[dict] = [
    {"key": "soc_set",          "name": "Target SOC",           "unit": "%",
     "device_class": "battery", "min": 70,   "max": 100, "step": 1,
     "scale": 1, "precision": 0, "scan_interval": "low",  "enabled_by_default": True},
    {"key": "min_soc",          "name": "Minimum SOC",          "unit": "%",
     "device_class": "battery", "min": 0,    "max": 50,  "step": 1,
     "scale": 1, "precision": 0, "scan_interval": "low",  "enabled_by_default": True},
    {"key": "inverse_max_power","name": "Max Inverter Output",  "unit": "W",
     "device_class": "power",   "min": 100,  "max": 2400,"step": 10,
     "scale": 1, "precision": 0, "scan_interval": "low",  "enabled_by_default": True},
]

SELECT_DEFINITIONS: list[dict] = [
    # Off-grid output port mode. "options" maps the canonical option key (localised
    # via translations) to the device's gridOffMode wire value. No "scale" — the
    # coordinator stores the raw enum value, which current_option matches back.
    {"key": "grid_off_mode", "name": "Off-Grid Mode",
     "options": {"normal": 0, "economy": 1, "off": 2},
     "scan_interval": "low", "enabled_by_default": True},
]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class ZendureLocalDriver(BatteryDriver):
    """Local HTTP driver for a single Zendure SolarFlow device."""

    def __init__(
        self,
        host: str,
        *,
        port: int = 80,
        max_charge_power_w: int = 2400,
        max_discharge_power_w: int = 2400,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Build the driver.

        ``session`` is injectable so unit tests can supply a fake; production
        passes None and the driver creates its own aiohttp.ClientSession on
        the first connect() call.
        """
        self._host = host
        self._port = port
        self._base_url = f"http://{host}" if port == 80 else f"http://{host}:{port}"
        self._owns_session = session is None
        self._session: Optional[aiohttp.ClientSession] = session
        self._connected = False
        self._shutting_down = False
        self._sn: Optional[str] = None  # populated from first GET response
        self._product: Optional[str] = None  # device model from the report root

        self._capabilities = DriverCapabilities(
            hardware_soc_cutoff=True,    # minSoc + socSet exist on the device
            has_force_mode=False,        # no explicit force_mode register; control via limits
            push_telemetry=False,        # HTTP poll, not MQTT push
            max_charge_power_w=max_charge_power_w,
            max_discharge_power_w=max_discharge_power_w,
            has_mppt_pv=False,           # no DC-coupled MPPT; solar is AC-side
            has_alarm_registers=True,    # faultLevel + is_error
            has_rs485_control=False,
            has_energy_counters=False,   # no kWh / capacity in the report; synthesised
        )

        self._definitions: dict[str, list[dict]] = {
            "sensor":        SENSOR_DEFINITIONS,
            "number":        NUMBER_DEFINITIONS,
            "select":        SELECT_DEFINITIONS,
            "switch":        [],
            "binary_sensor": [],
            "button":        [],
            "all":           SENSOR_DEFINITIONS + NUMBER_DEFINITIONS + SELECT_DEFINITIONS,
        }

        # Single read group: one HTTP GET returns all properties, so there is
        # no benefit to splitting by scan_interval (that would cause multiple
        # round-trips per poll cycle).  The coordinator gates per-key by its
        # own scan_interval schedule, but we return all keys every call.
        self._read_groups: list[ReadGroup] = [
            ReadGroup(
                scan_interval="high",
                keys=tuple(d["key"] for d in self._definitions["all"]),
            )
        ]

    # --- entity definitions -------------------------------------------------
    # Same pattern as MarstekModbusDriver; coordinator and platforms read these
    # back instead of branching on a version string.

    @property
    def sensor_definitions(self) -> list[dict]:
        return self._definitions["sensor"]

    @property
    def number_definitions(self) -> list[dict]:
        return self._definitions["number"]

    @property
    def select_definitions(self) -> list[dict]:
        return self._definitions["select"]

    @property
    def switch_definitions(self) -> list[dict]:
        return self._definitions["switch"]

    @property
    def binary_sensor_definitions(self) -> list[dict]:
        return self._definitions["binary_sensor"]

    @property
    def button_definitions(self) -> list[dict]:
        return self._definitions["button"]

    @property
    def all_definitions(self) -> list[dict]:
        return self._definitions["all"]

    @property
    def pack_field_specs(self) -> list[dict]:
        """Numeric per-pack sensor fields (see PACK_FIELD_SPECS).

        The sensor platform reads this back to build one entity per (pack, field),
        sized to the live pack count. Absent on the Marstek driver, so the platform
        getattr's it and skips per-pack entities for brands that don't expose packs.
        """
        return PACK_FIELD_SPECS

    # --- identity -----------------------------------------------------------

    @property
    def capabilities(self) -> DriverCapabilities:
        return self._capabilities

    @property
    def model_label(self) -> Optional[str]:
        return self._product

    # --- connection lifecycle -----------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Open an HTTP session and verify the device responds."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True

        data = await self._get_report()
        if data is None:
            self._connected = False
            return False

        self._sn = data.get("sn")
        self._product = data.get("product")
        self._connected = True
        _LOGGER.info("Connected to Zendure device at %s (sn=%s)", self._base_url, self._sn)
        return True

    async def close(self) -> None:
        """Close the HTTP session."""
        self._connected = False
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    def set_shutting_down(self, value: bool) -> None:
        self._shutting_down = value

    # --- telemetry (read) ---------------------------------------------------

    @property
    def read_groups(self) -> list[ReadGroup]:
        return self._read_groups

    async def read_telemetry(self, keys: Optional[list[str]] = None) -> TelemetrySnapshot:
        """Fetch /properties/report and return a logical-key snapshot.

        One HTTP GET always returns all properties, so the ``keys`` filter is
        applied after mapping rather than before the request.  battery_power is
        synthesised from outputPackPower and packInputPower so the coordinator
        and control loop see the same signed convention as Marstek
        (+charge / −discharge).
        """
        data = await self._get_report()
        if data is None:
            return {}

        if self._sn is None:
            self._sn = data.get("sn")
        if self._product is None:
            self._product = data.get("product")

        snapshot = self._snapshot_from_report(data)

        if keys is not None:
            # max_charge_power is a control attribute (it drives PD allocation),
            # not an entity, so it is never in the requested key list — keep it
            # regardless so the coordinator syncs the device's real charge cap.
            snapshot = {
                k: v for k, v in snapshot.items()
                if k in keys or k == "max_charge_power" or _PACK_KEY_RE.match(k)
            }

        return snapshot

    def _snapshot_from_report(self, data: dict) -> TelemetrySnapshot:
        """Map a /properties/report payload to a logical-key snapshot.

        Shared by read_telemetry and the apply_setpoint readback echo so the
        property→key mapping, unit scaling, packData cell voltages and the
        synthesised battery_power stay in one place.
        """
        props = data.get("properties", {})
        snapshot: TelemetrySnapshot = {}
        for prop, key in _PROP_TO_KEY.items():
            if prop in props:
                snapshot[key] = props[prop]

        # socSet/minSoc arrive in deci-percent; expose as whole percent.
        for key in _DECIPERCENT_KEYS:
            if snapshot.get(key) is not None:
                snapshot[key] = snapshot[key] / 10

        # hyperTmp (centi-°C) and BatVolt (centi-volt) are returned raw; the
        # coordinator applies the ×0.01 scale from the entity definition, the
        # same path Marstek register sensors use. Scaling here would double it.

        # remainOutTime reports a 999 h sentinel when idle / not discharging;
        # surface as unknown (None) rather than a bogus ~41-day duration.
        remain = snapshot.get("remain_discharge_time")
        if remain is not None and remain >= _REMAIN_TIME_SENTINEL:
            snapshot["remain_discharge_time"] = None

        # Device-level cell-voltage extremes from packData[] (raw centi-volt;
        # the coordinator applies the ×0.01 scale from the entity definition).
        packs = data.get("packData") or []
        max_vols = [p["maxVol"] for p in packs if p.get("maxVol")]
        min_vols = [p["minVol"] for p in packs if p.get("minVol")]
        if max_vols:
            snapshot["max_cell_voltage"] = max(max_vols)
        if min_vols:
            snapshot["min_cell_voltage"] = min(min_vols)

        # Per-pack telemetry → pack{N}_* logical keys (1-based). Pre-scaled here
        # because these keys have no entity definition for the coordinator to
        # scale (voltages/temps are centi-units; soc/power are already correct).
        # sn / model / state ride along for the SoC sensor's attributes.
        for idx, pack in enumerate(packs, start=1):
            prefix = f"pack{idx}_"
            if pack.get("socLevel") is not None:
                snapshot[prefix + "soc"] = pack["socLevel"]
            if pack.get("totalVol") is not None:
                snapshot[prefix + "voltage"] = round(pack["totalVol"] / 100, 2)
            if pack.get("maxVol") is not None:
                snapshot[prefix + "max_cell_voltage"] = round(pack["maxVol"] / 100, 3)
            if pack.get("minVol") is not None:
                snapshot[prefix + "min_cell_voltage"] = round(pack["minVol"] / 100, 3)
            if pack.get("maxTemp") is not None:
                snapshot[prefix + "temperature"] = round(pack["maxTemp"] / 100, 2)
            if pack.get("power") is not None:
                snapshot[prefix + "power"] = pack["power"]
            if pack.get("sn") is not None:
                snapshot[prefix + "sn"] = pack["sn"]
            if pack.get("packType") is not None:
                snapshot[prefix + "model"] = pack["packType"]
            if pack.get("state") is not None:
                snapshot[prefix + "state"] = pack["state"]

        # Synthesise signed battery_power: +charge / −discharge.
        pack_in = props.get("packInputPower", 0)
        out_pack = props.get("outputPackPower", 0)
        snapshot["battery_power"] = out_pack - pack_in
        return snapshot

    # --- control (write) ----------------------------------------------------

    async def apply_setpoint(
        self,
        net_power_w: int,
        *,
        mode_hint: Optional[str] = None,
        read_back: bool = True,
    ) -> SetpointResult:
        """Translate a signed net power into Zendure's acMode + limit properties.

        smartMode=1 is included in every setpoint write so the real-time PD
        writes land in RAM rather than flash — the controller rewrites the
        setpoint frequently, and wearing the flash on every cycle would shorten
        device life. With HEMS DISABLED (a prerequisite for this integration)
        smartMode=1 still obeys the commanded acMode and holds the setpoint
        indefinitely (verified on a 2400 AC+). The acMode-ignoring "auto /
        smart-matching" behavior only appears when HEMS is enabled, where its
        loop reverts manual control after ~10-14 s. Config writes (apply_config,
        write_control) send smartMode=0 so they commit to flash and survive
        reboots — smartMode is sticky, so they can't rely on omitting it (the
        power loop leaves the device in smartMode=1).
        """
        if net_power_w > 0:
            power = min(net_power_w, self._capabilities.max_charge_power_w)
            payload: dict[str, Any] = {"acMode": _AC_MODE_CHARGE, "inputLimit": power, "smartMode": 1}
            applied_net = power
        elif net_power_w < 0:
            power = min(-net_power_w, self._capabilities.max_discharge_power_w)
            payload = {"acMode": _AC_MODE_DISCHARGE, "outputLimit": power, "smartMode": 1}
            applied_net = -power
        else:
            power = 0
            payload = {"acMode": _AC_MODE_DISCHARGE, "outputLimit": 0, "smartMode": 1}
            applied_net = 0

        ok = await self._post_write(payload)
        if not ok:
            return SetpointResult(
                ok=False, net_power_w=applied_net, confirmed=False,
                failure_reason="http_write_failed",
            )

        # Echo the written state (minus smartMode) for the coordinator's cache.
        applied: dict[str, Any] = {k: v for k, v in payload.items() if k != "smartMode"}

        if not read_back:
            return SetpointResult(ok=True, net_power_w=applied_net, confirmed=False, applied=applied)

        # The device does not apply a write to its reported properties
        # immediately: measured on a 2400 AC+, acMode/inputLimit/outputLimit
        # still echo the *previous* command at 0.5–1.0 s and only reflect the
        # new one at ~2 s. Reading back too early compares the just-sent
        # setpoint against stale values and falsely reports ack_mismatch every
        # cycle. Settle past the observed apply latency before reading back.
        await asyncio.sleep(2.5)

        data = await self._get_report()
        if data is None:
            return SetpointResult(
                ok=True, net_power_w=applied_net, confirmed=False,
                failure_reason="feedback_timeout", applied=applied,
            )

        props = data.get("properties", {})

        # The device clamps inputLimit/outputLimit to its own charge/discharge
        # caps (chargeMaxLimit / inverseMaxPower), so an exact == against the
        # commanded power reports ack_mismatch whenever the setpoint exceeds the
        # cap — even though the write was accepted. Confirm against the clamped
        # value the device will actually honour.
        if net_power_w > 0:
            cap = props.get("chargeMaxLimit", power)
            confirmed = props.get("inputLimit") == min(power, cap)
        elif net_power_w < 0:
            cap = props.get("inverseMaxPower", power)
            confirmed = props.get("outputLimit") == min(power, cap)
        else:
            confirmed = props.get("outputLimit") == 0

        # Full snapshot echo so the coordinator cache reflects the readback.
        echo = self._snapshot_from_report(data)
        battery_power = echo["battery_power"]

        return SetpointResult(
            ok=True,
            net_power_w=applied_net,
            confirmed=confirmed,
            battery_power_w=battery_power,
            applied=echo,
        )

    async def write_control(self, key: str, value: int) -> bool:
        """Write a single logical control property by key (entity-write path).

        smartMode=0: user-facing configuration writes (soc_set, min_soc,
        inverse_max_power, grid_off_mode) must persist across reboots. smartMode
        is a sticky device property and the per-cycle power loop holds it at 1
        (RAM), so omitting it here would inherit that 1 and land the config in
        RAM, lost on the next reboot. Set it to 0 explicitly to commit to flash.
        """
        prop = _KEY_TO_PROP.get(key)
        if prop is None:
            _LOGGER.debug("ZendureLocalDriver: no property mapping for key %r", key)
            return False
        if key in _DECIPERCENT_KEYS:
            value = int(round(value * 10))  # whole percent → device deci-percent
        return await self._post_write({prop: value, "smartMode": 0})

    def net_power_from_data(self, data: dict):
        ac_mode = data.get("ac_mode")
        if ac_mode is None:
            return None
        if int(ac_mode) == _AC_MODE_CHARGE:
            limit = data.get("input_limit")
            return int(limit) if limit is not None else None
        # _AC_MODE_DISCHARGE or idle: output_limit (0 = idle/hold)
        limit = data.get("output_limit")
        return -int(limit) if limit is not None else None

    @property
    def control_dependency_keys(self) -> frozenset:
        # ac_mode + input/output_limit feed net_power_from_data, which the
        # skip-if-unchanged guard uses to avoid rewriting an unchanged setpoint.
        # Their entities are disabled by default, so without declaring them as
        # control dependencies they would never be polled, net_power_from_data
        # would always return None, the skip would never fire, and the device
        # would be rewritten every PD cycle for nothing.
        return frozenset({"ac_mode", "input_limit", "output_limit"})

    # --- concrete methods (not on BatteryDriver ABC) ------------------------
    # These mirror the Marstek-side concrete API so the coordinator can call
    # them without isinstance guards.

    async def apply_config(
        self,
        *,
        max_soc_pct: float,
        min_soc_pct: float,
        max_charge_power_w: int,
        max_discharge_power_w: int,
    ) -> bool:
        """Write SOC limits to the device (smartMode=0 → persists to flash).

        Zendure uses socSet (70-100 %) and minSoc (0-50 %).  The power caps
        are not written here; use the inverseMaxPower number entity instead.
        The device stores both in deci-percent (1000 = 100.0%), so values are
        scaled ×10 on the wire.
        """
        soc_set = max(70, min(100, int(max_soc_pct)))
        min_soc = max(0, min(50, int(min_soc_pct)))
        return await self._post_write({"socSet": soc_set * 10, "minSoc": min_soc * 10, "smartMode": 0})

    async def standby(self) -> bool:
        """Stop discharge for teardown (smartMode=1, does not persist)."""
        return await self._post_write(
            {"acMode": _AC_MODE_DISCHARGE, "outputLimit": 0, "smartMode": 1}
        )

    async def set_rs485_control(self, enable: bool) -> bool:
        """No-op: Zendure has no RS485 control mode."""
        return False

    # --- internal HTTP helpers ----------------------------------------------

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _get_report(self) -> Optional[dict]:
        """GET /properties/report, return the parsed JSON or None on failure."""
        url = f"{self._base_url}/properties/report"
        try:
            session = self._ensure_session()
            async with session.get(url, timeout=_HTTP_TIMEOUT) as resp:
                if resp.status != 200:
                    if not self._shutting_down:
                        _LOGGER.warning("Zendure GET %s → HTTP %s", url, resp.status)
                    return None
                return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            if not self._shutting_down:
                _LOGGER.warning("Zendure GET %s timed out", url)
            return None
        except Exception as exc:
            if not self._shutting_down:
                _LOGGER.warning("Zendure GET %s failed: %s", url, exc)
            return None

    async def _post_write(self, properties: dict) -> bool:
        """POST /properties/write with the given property dict."""
        if not self._sn:
            _LOGGER.warning(
                "Zendure POST /properties/write: device SN unknown — call connect() first"
            )
            return False
        url = f"{self._base_url}/properties/write"
        body = {"sn": self._sn, "properties": properties}
        try:
            session = self._ensure_session()
            async with session.post(url, json=body, timeout=_HTTP_TIMEOUT) as resp:
                if resp.status != 200:
                    if not self._shutting_down:
                        _LOGGER.warning("Zendure POST %s → HTTP %s", url, resp.status)
                    return False
                return True
        except asyncio.TimeoutError:
            if not self._shutting_down:
                _LOGGER.warning("Zendure POST %s timed out", url)
            return False
        except Exception as exc:
            if not self._shutting_down:
                _LOGGER.warning("Zendure POST %s failed: %s", url, exc)
            return False

    @classmethod
    async def probe(cls, host: str, port: int = 80) -> bool:
        """Test whether a Zendure device responds at host:port.

        Creates a temporary session, GETs /properties/report, and checks for
        the ``properties`` key.  Used by the config/options flow to validate
        the device IP before committing it.
        """
        port_suffix = f":{port}" if port != 80 else ""
        url = f"http://{host}{port_suffix}/properties/report"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=_PROBE_TIMEOUT) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json(content_type=None)
                    return "properties" in data
        except Exception as exc:
            _LOGGER.debug("Zendure probe of %s failed: %s", host, exc)
            return False
