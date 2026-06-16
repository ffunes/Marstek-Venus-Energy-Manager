"""Marstek Modbus-TCP driver.

Implements :class:`base.BatteryDriver` for the Marstek Venus family (v2/v3/vA/vD).
Owns the brand-specific knowledge that is currently spread across the coordinator
and control loop:

* which pymodbus timing/timeout/packet-correction a given firmware needs,
* the logical-key -> register/data-type mapping (``REGISTER_MAP`` + the per-model
  entity definitions),
* how a signed net power becomes ``force_mode`` + charge/discharge set-points.

This phase builds and unit-tests the driver in isolation; it is **not yet wired
into the coordinator** (no live behaviour change). Later phases route the
coordinator's connection, read and write paths through it and delete the
duplicated logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..const import MESSAGE_WAIT_MS, READ_TIMEOUT_S, REGISTER_MAP
from ..modbus_client import MarstekModbusClient
from .base import BatteryDriver, DriverCapabilities, SetpointResult, TelemetrySnapshot

_LOGGER = logging.getLogger(__name__)

# Firmware families that share the v3 quirks: single TCP slot, int16 power, no
# hardware SOC cut-off registers, packet correction.
_V3_FAMILY = ("v3", "vA", "vD")

# Marstek force_mode register values.
_FORCE_NONE = 0
_FORCE_CHARGE = 1
_FORCE_DISCHARGE = 2

# RS485 control-mode toggle. The rs485_control register is a write-command
# register, not a plain bool: 0x55AA enables external (Modbus) control, 0x55BB
# disables it. v3 firmware rejects a plain 0/1 with Modbus exception 3.
_RS485_ENABLE = 21930   # 0x55AA
_RS485_DISABLE = 21947  # 0x55BB


class MarstekModbusDriver(BatteryDriver):
    """Modbus-TCP driver for a single Marstek battery."""

    def __init__(
        self,
        host: str,
        port: int,
        version: str,
        slave_id: int = 1,
        *,
        max_charge_power_w: int = 2500,
        max_discharge_power_w: int = 2500,
        definitions: Optional[list[dict]] = None,
        client: Optional[MarstekModbusClient] = None,
    ) -> None:
        """Build the driver.

        ``definitions`` is the version's entity definition list (each item a dict
        with ``key``/``register``/``data_type``/``count``); it seeds the telemetry
        index used by :meth:`read_telemetry`. ``client`` is injectable so unit
        tests can supply a fake; production passes None and a real
        :class:`MarstekModbusClient` is built with version-correct timing.
        """
        self._version = version
        self._is_v3_family = version in _V3_FAMILY
        self._slave_id = slave_id

        if client is None:
            client = MarstekModbusClient(
                host,
                port,
                message_wait_ms=MESSAGE_WAIT_MS.get(version, 50),
                timeout=READ_TIMEOUT_S.get(version, 10),
                is_v3=self._is_v3_family,
                slave_id=slave_id,
            )
        self._client = client

        # Hardware SOC cut-off registers only exist on v2; v3/vA/vD enforce in
        # software (REGISTER_MAP carries None for them).
        self._capabilities = DriverCapabilities(
            hardware_soc_cutoff=REGISTER_MAP.get(version, {}).get("charging_cutoff_capacity") is not None,
            has_force_mode=REGISTER_MAP.get(version, {}).get("force_mode") is not None,
            push_telemetry=False,
            max_charge_power_w=max_charge_power_w,
            max_discharge_power_w=max_discharge_power_w,
        )

        # logical key -> (register, data_type, count) for telemetry reads.
        self._telemetry_index: dict[str, tuple[int, str, Optional[int]]] = {}
        for defn in definitions or []:
            register = defn.get("register")
            if register is None:
                continue
            self._telemetry_index[defn["key"]] = (
                register,
                defn.get("data_type", "uint16"),
                defn.get("count"),
            )

    # --- identity -----------------------------------------------------------

    @property
    def capabilities(self) -> DriverCapabilities:
        return self._capabilities

    @property
    def client(self) -> MarstekModbusClient:
        """The underlying Modbus client (transitional: the coordinator still uses
        register-level primitives directly until the read/write paths migrate)."""
        return self._client

    def get_register(self, key: str) -> Optional[int]:
        """Resolve a logical control-register name for this version, or None."""
        return REGISTER_MAP.get(self._version, {}).get(key)

    @property
    def _power_dtype(self) -> str:
        return "int16" if self._is_v3_family else "int32"

    # --- connection lifecycle ----------------------------------------------

    @property
    def connected(self) -> bool:
        return self._client.connected

    async def connect(self) -> bool:
        return await self._client.async_connect()

    async def close(self) -> None:
        await self._client.async_close()

    def set_shutting_down(self, value: bool) -> None:
        self._client.set_shutting_down(value)

    # --- telemetry (read) ---------------------------------------------------

    async def read_telemetry(self, keys: Optional[list[str]] = None) -> TelemetrySnapshot:
        """Read the requested logical keys and return raw decoded values.

        Values are *unscaled* — the coordinator applies scale/precision and the
        backward-jump guard, exactly as it does today. Keys not in this version's
        index, or whose read fails, are omitted.
        """
        wanted = keys if keys is not None else list(self._telemetry_index)
        snapshot: TelemetrySnapshot = {}
        for key in wanted:
            spec = self._telemetry_index.get(key)
            if spec is None:
                continue
            register, data_type, count = spec
            value = await self._client.async_read_register(
                register=register,
                data_type=data_type,
                count=count,
                sensor_key=key,
            )
            if value is not None:
                snapshot[key] = value
        return snapshot

    # --- control (write) ----------------------------------------------------

    async def apply_setpoint(
        self,
        net_power_w: int,
        *,
        mode_hint: Optional[str] = None,
        read_back: bool = True,
    ) -> SetpointResult:
        """Translate a signed net power into Marstek's force_mode + set-points.

        +net = charge, -net = discharge, 0 = idle. Magnitude is clamped to the
        capability envelope. Writes all three registers, then optionally reads
        them back (after a settle delay) to confirm and to capture delivered
        power. The three writes happen back-to-back; the coordinator holds its
        lock around this call so a poll read cannot interleave (v3 atomicity).
        """
        self._client.unit_id = self._slave_id

        if net_power_w > 0:
            charge = min(net_power_w, self._capabilities.max_charge_power_w)
            discharge = 0
            force_mode = _FORCE_CHARGE
            applied_net = charge
        elif net_power_w < 0:
            charge = 0
            discharge = min(-net_power_w, self._capabilities.max_discharge_power_w)
            force_mode = _FORCE_DISCHARGE
            applied_net = -discharge
        else:
            charge = discharge = 0
            force_mode = _FORCE_NONE
            applied_net = 0

        charge_reg = self.get_register("set_charge_power")
        discharge_reg = self.get_register("set_discharge_power")
        force_reg = self.get_register("force_mode")
        if None in (charge_reg, discharge_reg, force_reg):
            return SetpointResult(ok=False, net_power_w=0, confirmed=False, failure_reason="missing_registers")

        ok1 = await self._client.async_write_register(discharge_reg, discharge)
        ok2 = await self._client.async_write_register(charge_reg, charge)
        ok3 = await self._client.async_write_register(force_reg, force_mode)
        if not (ok1 and ok2 and ok3):
            return SetpointResult(
                ok=False, net_power_w=applied_net, confirmed=False,
                failure_reason="modbus_write_failed",
            )

        # Brand-native echo for the coordinator's telemetry cache. On a write-only
        # cycle the regular poll refreshes battery_power, so only the set-points
        # are reported (optimistic).
        if not read_back:
            applied = {
                "force_mode": force_mode,
                "set_charge_power": charge,
                "set_discharge_power": discharge,
            }
            return SetpointResult(ok=True, net_power_w=applied_net, confirmed=False, applied=applied)

        # Let the battery process the commands before reading them back.
        await asyncio.sleep(0.2)

        force_fb = await self._client.async_read_register(force_reg, "uint16")
        charge_fb = await self._client.async_read_register(charge_reg, "uint16")
        discharge_fb = await self._client.async_read_register(discharge_reg, "uint16")
        power_reg = self.get_register("battery_power")
        power_fb = (
            await self._client.async_read_register(power_reg, self._power_dtype)
            if power_reg is not None else None
        )
        if None in (force_fb, charge_fb, discharge_fb, power_fb):
            # Writes were accepted but the readback never followed. No telemetry
            # echo — the coordinator leaves coordinator.data to the next poll.
            return SetpointResult(
                ok=True, net_power_w=applied_net, confirmed=False, failure_reason="feedback_timeout",
            )

        confirmed = force_fb == force_mode and charge_fb == charge and discharge_fb == discharge
        applied = {
            "force_mode": force_fb,
            "set_charge_power": charge_fb,
            "set_discharge_power": discharge_fb,
            "battery_power": power_fb,
        }
        return SetpointResult(
            ok=True, net_power_w=applied_net, confirmed=confirmed,
            battery_power_w=power_fb, applied=applied,
        )

    async def set_rs485_control(self, enable: bool) -> bool:
        """Enable or disable RS485 (external Modbus) control mode.

        RS485 control mode must be on for the battery to accept power commands;
        a new TCP connection or a standby slip can drop it. ``enable=True`` writes
        the enable command, ``False`` returns control to the battery's internal
        logic. The 0x55AA / 0x55BB toggle values are Marstek transport detail and
        live here, not in the control layer. Returns True if the write was
        accepted, False if this version has no rs485_control register or the write
        failed.

        Concrete to this driver (not on :class:`BatteryDriver`): RS485 is a
        Marstek-specific control gate. A push/MQTT brand has no equivalent; hoist
        with a semantic name only when a second brand needs it.
        """
        reg = self.get_register("rs485_control")
        if reg is None:
            return False
        self._client.unit_id = self._slave_id
        return await self._client.async_write_register(
            reg, _RS485_ENABLE if enable else _RS485_DISABLE
        )
