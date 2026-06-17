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

smartMode=1 keeps real-time writes off flash; omit it for config writes that should
survive a reboot (apply_config, write_control).

battery_power is synthesised: outputPackPower − packInputPower
  (+charge: outputPackPower > 0; −discharge: packInputPower > 0)
"""

from __future__ import annotations

import asyncio
import logging
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
    "solarInputPower":  "solar_input_power",
    "gridInputPower":   "grid_input_power",
    "packInputPower":   "pack_input_power",
    "outputPackPower":  "output_pack_power",
    "hyperTmp":         "device_temperature",
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
}

# Reverse map for write_control: logical key → API property name.
_KEY_TO_PROP: dict[str, str] = {v: k for k, v in _PROP_TO_KEY.items()}

_AC_MODE_CHARGE = 1
_AC_MODE_DISCHARGE = 2


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
    {"key": "solar_input_power",    "name": "Solar Input Power",        "unit": "W",
     "device_class": "power",       "state_class": "measurement",       "scale": 1, "precision": 0,
     "scan_interval": "high",       "enabled_by_default": True},
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
    {"key": "device_temperature",   "name": "Device Temperature",       "unit": "°C",
     "device_class": "temperature", "state_class": "measurement",       "scale": 1, "precision": 1,
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

        self._capabilities = DriverCapabilities(
            hardware_soc_cutoff=True,    # minSoc + socSet exist on the device
            has_force_mode=False,        # no explicit force_mode register; control via limits
            push_telemetry=False,        # HTTP poll, not MQTT push
            max_charge_power_w=max_charge_power_w,
            max_discharge_power_w=max_discharge_power_w,
            has_mppt_pv=False,           # no DC-coupled MPPT; solar is AC-side
            has_alarm_registers=True,    # faultLevel + is_error
            has_rs485_control=False,
        )

        self._definitions: dict[str, list[dict]] = {
            "sensor":        SENSOR_DEFINITIONS,
            "number":        NUMBER_DEFINITIONS,
            "select":        [],
            "switch":        [],
            "binary_sensor": [],
            "button":        [],
            "all":           SENSOR_DEFINITIONS + NUMBER_DEFINITIONS,
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

    # --- identity -----------------------------------------------------------

    @property
    def capabilities(self) -> DriverCapabilities:
        return self._capabilities

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

        props = data.get("properties", {})
        snapshot: TelemetrySnapshot = {}

        for prop, key in _PROP_TO_KEY.items():
            if prop in props:
                snapshot[key] = props[prop]

        # Synthesise signed battery_power: +charge / −discharge.
        pack_in = props.get("packInputPower", 0)
        out_pack = props.get("outputPackPower", 0)
        snapshot["battery_power"] = out_pack - pack_in

        if keys is not None:
            snapshot = {k: v for k, v in snapshot.items() if k in keys}

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

        smartMode=1 is included in every setpoint write so the device does not
        wear its flash during real-time control.  The coordinator calls this on
        every PD cycle when the setpoint changes.
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

        await asyncio.sleep(0.5)

        data = await self._get_report()
        if data is None:
            return SetpointResult(
                ok=True, net_power_w=applied_net, confirmed=False,
                failure_reason="feedback_timeout", applied=applied,
            )

        props = data.get("properties", {})
        pack_in = props.get("packInputPower", 0)
        out_pack = props.get("outputPackPower", 0)
        battery_power = out_pack - pack_in

        if net_power_w > 0:
            confirmed = props.get("inputLimit") == power
        elif net_power_w < 0:
            confirmed = props.get("outputLimit") == power
        else:
            confirmed = props.get("outputLimit") == 0

        # Full snapshot echo so the coordinator cache reflects the readback.
        echo: dict[str, Any] = {}
        for prop, key in _PROP_TO_KEY.items():
            if prop in props:
                echo[key] = props[prop]
        echo["battery_power"] = battery_power

        return SetpointResult(
            ok=True,
            net_power_w=applied_net,
            confirmed=confirmed,
            battery_power_w=battery_power,
            applied=echo,
        )

    async def write_control(self, key: str, value: int) -> bool:
        """Write a single logical control property by key (entity-write path).

        No smartMode: user-facing configuration writes (soc_set, min_soc,
        inverse_max_power) should persist across reboots.
        """
        prop = _KEY_TO_PROP.get(key)
        if prop is None:
            _LOGGER.debug("ZendureLocalDriver: no property mapping for key %r", key)
            return False
        return await self._post_write({prop: value})

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
        """Write SOC limits to the device (persists to flash, no smartMode).

        Zendure uses socSet (70-100 %) and minSoc (0-50 %).  The power caps
        are not written here; use the inverseMaxPower number entity instead.
        """
        soc_set = max(70, min(100, int(max_soc_pct)))
        min_soc = max(0, min(50, int(min_soc_pct)))
        return await self._post_write({"socSet": soc_set, "minSoc": min_soc})

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
