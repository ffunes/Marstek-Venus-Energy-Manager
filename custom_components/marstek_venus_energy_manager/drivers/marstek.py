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
from ..modbus_client import MarstekModbusClient, decode_registers
from .base import (
    BatteryDriver,
    DriverCapabilities,
    ReadGroup,
    SetpointResult,
    TelemetrySnapshot,
)

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


def _load_definitions(version: str) -> dict[str, list[dict]]:
    """Return this Marstek version's per-platform entity definitions.

    Owns the version branch that used to live in the coordinator: each Marstek
    firmware family exposes a different register/entity set. The keys are the HA
    platforms plus ``all`` (the polled union — everything except buttons, which
    are stateless commands and never read). Which registers a version has is
    brand detail, so it belongs in the driver; the coordinator and platform
    setups read these back instead of branching on the version string.
    """
    from ..const import (
        SENSOR_DEFINITIONS,
        NUMBER_DEFINITIONS,
        SELECT_DEFINITIONS,
        SWITCH_DEFINITIONS,
        BINARY_SENSOR_DEFINITIONS,
        BUTTON_DEFINITIONS,
    )

    if version == "v3":
        from ..const import (
            SENSOR_DEFINITIONS_V3,
            NUMBER_DEFINITIONS_V3,
            SELECT_DEFINITIONS_V3,
            SWITCH_DEFINITIONS_V3,
            BINARY_SENSOR_DEFINITIONS_V3,
            BUTTON_DEFINITIONS_V3,
        )
        sensor = SENSOR_DEFINITIONS_V3
        number = NUMBER_DEFINITIONS_V3
        select = SELECT_DEFINITIONS_V3
        switch = SWITCH_DEFINITIONS_V3
        binary_sensor = BINARY_SENSOR_DEFINITIONS_V3
        button = BUTTON_DEFINITIONS_V3
    elif version in ("vA", "vD"):
        from ..const import (
            SENSOR_DEFINITIONS_VA,
            NUMBER_DEFINITIONS_VA,
            NUMBER_DEFINITIONS_VD,
            SELECT_DEFINITIONS_VA,
            SELECT_DEFINITIONS_VD,
            SWITCH_DEFINITIONS_V3,
            BINARY_SENSOR_DEFINITIONS_V3,
            BUTTON_DEFINITIONS_V3,
        )
        sensor = SENSOR_DEFINITIONS_VA  # identical for vA and vD
        number = NUMBER_DEFINITIONS_VA if version == "vA" else NUMBER_DEFINITIONS_VD
        select = SELECT_DEFINITIONS_VA if version == "vA" else SELECT_DEFINITIONS_VD
        switch = SWITCH_DEFINITIONS_V3
        binary_sensor = BINARY_SENSOR_DEFINITIONS_V3
        button = BUTTON_DEFINITIONS_V3
    else:  # v2 (default)
        sensor = SENSOR_DEFINITIONS
        number = NUMBER_DEFINITIONS
        select = SELECT_DEFINITIONS
        switch = SWITCH_DEFINITIONS
        binary_sensor = BINARY_SENSOR_DEFINITIONS
        button = BUTTON_DEFINITIONS

    return {
        "sensor": sensor,
        "number": number,
        "select": select,
        "switch": switch,
        "binary_sensor": binary_sensor,
        "button": button,
        "all": sensor + number + select + switch + binary_sensor,
    }


def _load_register_blocks(version: str) -> list[dict]:
    """Return this Marstek version's contiguous register-block table (issue #361).

    Block reads collapse already-adjacent registers into a single Modbus request so
    the weak v3 MCU sees fewer frames. v3/vA/vD share the v3 register map and reuse
    the v3 blocks; v2 has its own table. Which registers are contiguous is brand/
    register detail, so this table — like the entity definitions — belongs in the
    driver, not the coordinator.
    """
    if version in _V3_FAMILY:
        from ..const import REGISTER_BLOCKS_V3
        return REGISTER_BLOCKS_V3
    if version == "v2":
        from ..const import REGISTER_BLOCKS_V2
        return REGISTER_BLOCKS_V2
    return []


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

        ``definitions`` overrides the entity definition list (each item a dict
        with ``key``/``register``/``data_type``/``count``); it seeds the
        telemetry index used by :meth:`read_telemetry`. Production passes None
        and the driver loads this version's real per-platform definitions
        itself; tests inject a flat list to drive telemetry/capabilities in
        isolation. ``client`` is injectable so unit tests can supply a fake;
        production passes None and a real :class:`MarstekModbusClient` is built
        with version-correct timing.
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

        # Per-platform entity definitions. Production passes ``definitions=None``
        # and the driver loads this version's real register/entity set (the
        # version branch that used to live in the coordinator); the coordinator
        # and platform setups read them back instead of branching on the version
        # string. Tests inject a flat list to exercise telemetry/capabilities in
        # isolation, in which case the per-platform lists stay empty.
        if definitions is None:
            self._definitions = _load_definitions(version)
        else:
            self._definitions = {
                "sensor": [], "number": [], "select": [],
                "switch": [], "binary_sensor": [], "button": [],
                "all": list(definitions),
            }

        # logical key -> (register, data_type, count) for telemetry reads.
        self._telemetry_index: dict[str, tuple[int, str, Optional[int]]] = {}
        for defn in self._definitions["all"]:
            register = defn.get("register")
            if register is None:
                continue
            self._telemetry_index[defn["key"]] = (
                register,
                defn.get("data_type", "uint16"),
                defn.get("count"),
            )

        # Contiguous register-block table for the production path; the injected-
        # definition test path polls every key individually (no blocks). Block
        # batching is an internal read optimisation — see :meth:`read_telemetry`.
        self._register_blocks = _load_register_blocks(version) if definitions is None else []

        # Telemetry grouped into schedulable poll units (see :class:`ReadGroup`):
        # one group per block (read in a single request) plus a singleton group per
        # remaining indexed key. The coordinator iterates these to schedule, gate
        # and lock per group without seeing the register layout.
        self._read_groups = self._build_read_groups()

        # Static capabilities, derived from the register map + the seeded entity
        # definitions so the control layer never branches on the version string.
        # Hardware SOC cut-off registers only exist on v2 (v3/vA/vD enforce in
        # software — REGISTER_MAP carries None). MPPT/PV and alarm registers exist
        # only when their logical keys are present in this model's definitions.
        self._capabilities = DriverCapabilities(
            hardware_soc_cutoff=REGISTER_MAP.get(version, {}).get("charging_cutoff_capacity") is not None,
            has_force_mode=REGISTER_MAP.get(version, {}).get("force_mode") is not None,
            push_telemetry=False,
            max_charge_power_w=max_charge_power_w,
            max_discharge_power_w=max_discharge_power_w,
            has_mppt_pv="mppt1_power" in self._telemetry_index,
            has_alarm_registers="alarm_status" in self._telemetry_index,
            has_rs485_control=REGISTER_MAP.get(version, {}).get("rs485_control") is not None,
        )

    # --- identity -----------------------------------------------------------

    @property
    def capabilities(self) -> DriverCapabilities:
        return self._capabilities

    # --- entity definitions -------------------------------------------------
    # The driver owns this version's register/entity set; the coordinator and
    # platform setups read these back instead of branching on the version
    # string. ``all_definitions`` is the polled union (buttons excluded).

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

    def _build_read_groups(self) -> list[ReadGroup]:
        """Group the polled keys into schedulable read units (see :class:`ReadGroup`).

        Each contiguous register block becomes one group (collapsed to a single
        request by :meth:`read_telemetry`); every other indexed key becomes its own
        singleton group, in definition order. The group's ``scan_interval`` comes
        from the block table or, for singletons, the entity definition.
        """
        groups: list[ReadGroup] = []
        grouped: set[str] = set()
        for block in self._register_blocks:
            member_keys = tuple(m["key"] for m in block["members"])
            groups.append(ReadGroup(scan_interval=block.get("scan_interval"), keys=member_keys))
            grouped.update(member_keys)
        for defn in self._definitions["all"]:
            key = defn["key"]
            if key in grouped or key not in self._telemetry_index:
                continue
            groups.append(ReadGroup(scan_interval=defn.get("scan_interval"), keys=(key,)))
        return groups

    @property
    def read_groups(self) -> list[ReadGroup]:
        return self._read_groups

    async def read_telemetry(self, keys: Optional[list[str]] = None) -> TelemetrySnapshot:
        """Read the requested logical keys and return raw decoded values.

        Values are *unscaled* — the coordinator applies scale/precision and the
        backward-jump guard, exactly as it does today. Keys not in this version's
        index, or whose read fails, are omitted.

        When the requested keys fully cover a contiguous register block, that block
        is fetched in a single Modbus request (issue #361) and the members decoded
        from the response; the rest are read one register at a time. The coordinator
        passes one :class:`ReadGroup`'s keys per call, so a block group resolves to
        a single block read and a singleton group to one register read.
        """
        wanted = list(keys) if keys is not None else list(self._telemetry_index)
        pending = set(wanted)
        snapshot: TelemetrySnapshot = {}

        # Collapse any fully-requested contiguous block into one request.
        for block in self._register_blocks:
            member_keys = [m["key"] for m in block["members"]]
            if not all(k in pending for k in member_keys):
                continue
            pending.difference_update(member_keys)
            regs = await self._client.async_read_block(
                block["start"], block["count"], block_key=f"block_{block['start']}",
            )
            if regs is None:
                continue
            for member in block["members"]:
                words = regs[member["offset"]:member["offset"] + member["count"]]
                value = decode_registers(words, member["data_type"])
                if value is not None:
                    snapshot[member["key"]] = value

        # Per-register reads for everything not served by a block (preserve order).
        for key in wanted:
            if key not in pending:
                continue
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

    async def write_control(self, key: str, value: int) -> bool:
        """Write a single logical control register by key (entity-write path).

        Resolves the logical key to its register for this version and writes the
        already-encoded ``value`` (scaling/command-value choice stays in the entity,
        which owns the user-facing units). Used by the number/select/switch/button
        platforms so they never touch a register address. Returns True if the write
        was accepted, False if this version has no register for the key or the write
        failed.
        """
        reg = self.get_register(key)
        if reg is None:
            return False
        self._client.unit_id = self._slave_id
        return bool(await self._client.async_write_register(reg, value))

    async def apply_config(
        self,
        *,
        max_soc_pct: float,
        min_soc_pct: float,
        max_charge_power_w: int,
        max_discharge_power_w: int,
    ) -> bool:
        """Write the one-time per-battery configuration to the hardware.

        Hardware SOC cut-offs (``charging``/``discharging_cutoff_capacity``) exist
        only on v2; on v3/vA/vD those registers are absent and SOC is enforced in
        software, so the cut-off writes are skipped. Max charge/discharge power
        caps exist on every version. The SOC percentages are converted to the
        cut-off register's deci-percent units here — register detail that belongs
        in the driver. Registers absent for this version are skipped silently.
        Returns True if every applicable write was accepted.

        Concrete to this driver (not on :class:`BatteryDriver`): the exact set of
        config registers is Marstek-specific. Hoist with a semantic name only when
        a second brand needs it.
        """
        self._client.unit_id = self._slave_id
        ok = True
        cutoff_charge_reg = self.get_register("charging_cutoff_capacity")
        if cutoff_charge_reg is not None:
            ok &= await self._client.async_write_register(cutoff_charge_reg, int(max_soc_pct / 0.1))
        cutoff_discharge_reg = self.get_register("discharging_cutoff_capacity")
        if cutoff_discharge_reg is not None:
            ok &= await self._client.async_write_register(cutoff_discharge_reg, int(min_soc_pct / 0.1))
        max_charge_reg = self.get_register("max_charge_power")
        if max_charge_reg is not None:
            ok &= await self._client.async_write_register(max_charge_reg, max_charge_power_w)
        max_discharge_reg = self.get_register("max_discharge_power")
        if max_discharge_reg is not None:
            ok &= await self._client.async_write_register(max_discharge_reg, max_discharge_power_w)
        return bool(ok)

    async def set_charge_cutoff(self, soc_pct: float) -> bool:
        """Write only the hardware charge-cutoff register to a SOC percentage.

        Used by the weekly-full-charge and active-balance flows to temporarily
        raise the BMS charge ceiling to 100% and later restore the configured
        max_soc, *without* disturbing the discharge cut-off or the power caps
        that :meth:`apply_config` writes together. The register exists only on
        v2; on v3/vA/vD it is absent (SOC is enforced in software) and this
        returns False so the caller can fall back to software enforcement. The
        deci-percent scaling and the post-write settle are register detail kept
        here, not in the control layer. Returns True only when the write was
        accepted.

        Concrete to this driver (not on :class:`BatteryDriver`): a hardware SOC
        cut-off register is Marstek-specific. Hoist with a semantic name only
        when a second brand needs it.
        """
        reg = self.get_register("charging_cutoff_capacity")
        if reg is None:
            return False
        self._client.unit_id = self._slave_id
        ok = await self._client.async_write_register(reg, int(soc_pct / 0.1))
        await asyncio.sleep(0.1)
        return bool(ok)

    async def standby(self) -> bool:
        """Idle the battery (zero set-points, no force mode) for teardown.

        Distinct from ``apply_setpoint(0)``: this runs during integration unload,
        when the client's inter-message pacing is suppressed (so the connection
        can be released quickly). It therefore paces the three writes itself —
        the same ~50 ms gap the shutdown path used before the driver move — to
        keep the v3 single TCP slot from being hit back-to-back. No readback and
        no telemetry echo: the connection closes immediately after. Returns True
        if every write was accepted, False if a required register is missing.
        """
        discharge_reg = self.get_register("set_discharge_power")
        charge_reg = self.get_register("set_charge_power")
        force_reg = self.get_register("force_mode")
        if None in (discharge_reg, charge_reg, force_reg):
            return False
        self._client.unit_id = self._slave_id
        ok = True
        ok &= await self._client.async_write_register(discharge_reg, 0)
        await asyncio.sleep(0.05)
        ok &= await self._client.async_write_register(charge_reg, 0)
        await asyncio.sleep(0.05)
        ok &= await self._client.async_write_register(force_reg, _FORCE_NONE)
        await asyncio.sleep(0.05)
        return bool(ok)

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
