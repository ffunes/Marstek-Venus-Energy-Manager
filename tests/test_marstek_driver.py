"""Unit tests for the Marstek Modbus driver (driver abstraction Phase 1).

The driver is exercised with an injected fake Modbus client, so no hardware and
no Home Assistant are needed. These pin the brand-specific logic that later
phases move out of the coordinator and control loop:

* capabilities derived from the firmware version,
* the logical-key -> register telemetry read,
* the signed-net-power -> force_mode + charge/discharge translation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.marstek_venus_energy_manager.drivers import (
    DriverCapabilities,
    MarstekModbusDriver,
)
from custom_components.marstek_venus_energy_manager.const import REGISTER_MAP


def _fake_client():
    client = AsyncMock()
    client.async_write_register = AsyncMock(return_value=True)
    client.async_read_register = AsyncMock(return_value=0)
    return client


def _driver(version="v3", definitions=None, client=None, **kw):
    return MarstekModbusDriver(
        "1.2.3.4", 502, version,
        definitions=definitions or [],
        client=client or _fake_client(),
        **kw,
    )


_DEFS = [
    {"key": "battery_soc", "register": 37005, "data_type": "uint16"},
    {"key": "battery_power", "register": 30001, "data_type": "int16", "count": 1},
    {"key": "no_register", "name": "calc-only"},  # no register -> not indexed
]


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    """Skip the real 0.2 s post-write settle so readback tests stay fast."""
    async def _instant(*_a, **_k):
        return None

    monkeypatch.setattr(
        "custom_components.marstek_venus_energy_manager.drivers.marstek.asyncio.sleep",
        _instant,
    )


# ----------------------------------------------------------------------
# capabilities
# ----------------------------------------------------------------------
def test_v2_reports_hardware_soc_cutoff():
    assert _driver("v2").capabilities.hardware_soc_cutoff is True


@pytest.mark.parametrize("version", ["v3", "vA", "vD"])
def test_v3_family_has_no_hardware_cutoff(version):
    assert _driver(version).capabilities.hardware_soc_cutoff is False


def test_capabilities_carry_power_envelope_and_force_mode():
    caps = _driver("v3", max_charge_power_w=800, max_discharge_power_w=1200).capabilities
    assert isinstance(caps, DriverCapabilities)
    assert caps.max_charge_power_w == 800
    assert caps.max_discharge_power_w == 1200
    assert caps.has_force_mode is True
    assert caps.push_telemetry is False


def test_mppt_pv_capability_derived_from_definitions():
    # MPPT/PV presence comes from the seeded entity definitions (Venus D/A),
    # not the version string.
    no_pv = _driver("v3", definitions=_DEFS).capabilities
    assert no_pv.has_mppt_pv is False
    with_pv = _driver(
        "vD",
        definitions=_DEFS + [{"key": "mppt1_power", "register": 33000, "data_type": "uint16"}],
    ).capabilities
    assert with_pv.has_mppt_pv is True


def test_alarm_registers_capability_derived_from_definitions():
    no_alarm = _driver("v3", definitions=_DEFS).capabilities
    assert no_alarm.has_alarm_registers is False
    with_alarm = _driver(
        "v2",
        definitions=_DEFS + [{"key": "alarm_status", "register": 36000, "data_type": "uint32"}],
    ).capabilities
    assert with_alarm.has_alarm_registers is True


@pytest.mark.parametrize("version", ["v2", "v3", "vA", "vD"])
def test_rs485_control_capability(version):
    assert _driver(version).capabilities.has_rs485_control is True


# ----------------------------------------------------------------------
# entity definitions (loaded from the version, Phase 4b)
# ----------------------------------------------------------------------
def test_definitions_loaded_from_version_when_not_injected():
    # Production passes no definitions: the driver loads this version's real set.
    from custom_components.marstek_venus_energy_manager.const import (
        SENSOR_DEFINITIONS,
        NUMBER_DEFINITIONS,
        SELECT_DEFINITIONS,
        SWITCH_DEFINITIONS,
        BINARY_SENSOR_DEFINITIONS,
        BUTTON_DEFINITIONS,
    )
    drv = MarstekModbusDriver("1.2.3.4", 502, "v2", client=_fake_client())
    assert drv.sensor_definitions is SENSOR_DEFINITIONS
    assert drv.button_definitions is BUTTON_DEFINITIONS
    assert drv.all_definitions == (
        SENSOR_DEFINITIONS + NUMBER_DEFINITIONS + SELECT_DEFINITIONS
        + SWITCH_DEFINITIONS + BINARY_SENSOR_DEFINITIONS
    )
    # all_definitions is the polled union; buttons (stateless) are excluded.
    assert len(drv.all_definitions) == (
        len(drv.sensor_definitions) + len(drv.number_definitions)
        + len(drv.select_definitions) + len(drv.switch_definitions)
        + len(drv.binary_sensor_definitions)
    )
    assert drv.button_definitions  # buttons exist, just not polled


def test_injected_definitions_leave_per_platform_lists_empty():
    # Test/override path: a flat list seeds telemetry only, no per-platform split.
    drv = _driver("v3", definitions=_DEFS)
    assert drv.sensor_definitions == []
    assert drv.all_definitions == _DEFS


def test_capabilities_use_version_loaded_definitions():
    # vD really exposes MPPT/PV; v2 does not but carries alarm registers. Pins
    # that the version-loaded definitions (not just the version string) feed the
    # capability derivation / telemetry index.
    vd = MarstekModbusDriver("1.2.3.4", 502, "vD", client=_fake_client()).capabilities
    assert vd.has_mppt_pv is True
    v2 = MarstekModbusDriver("1.2.3.4", 502, "v2", client=_fake_client()).capabilities
    assert v2.has_mppt_pv is False
    assert v2.has_alarm_registers is True


# ----------------------------------------------------------------------
# read_telemetry
# ----------------------------------------------------------------------
async def test_read_telemetry_reads_requested_keys_unscaled():
    client = _fake_client()
    client.async_read_register = AsyncMock(side_effect=[47, -612])
    drv = _driver("v3", definitions=_DEFS, client=client)

    snap = await drv.read_telemetry(["battery_soc", "battery_power"])

    assert snap == {"battery_soc": 47, "battery_power": -612}
    # battery_power read uses the int16 type / count from the definition.
    call = client.async_read_register.call_args_list[1]
    assert call.kwargs["register"] == 30001
    assert call.kwargs["data_type"] == "int16"


async def test_read_telemetry_skips_unknown_and_failed_keys():
    client = _fake_client()
    # battery_soc returns a value; battery_power read fails (None).
    client.async_read_register = AsyncMock(side_effect=[47, None])
    drv = _driver("v3", definitions=_DEFS, client=client)

    snap = await drv.read_telemetry(["battery_soc", "battery_power", "not_a_key"])

    assert snap == {"battery_soc": 47}  # None dropped, unknown key skipped


async def test_read_telemetry_defaults_to_all_indexed_keys():
    drv = _driver("v3", definitions=_DEFS, client=_fake_client())
    snap = await drv.read_telemetry()
    assert set(snap) == {"battery_soc", "battery_power"}  # no_register excluded


# ----------------------------------------------------------------------
# read_groups + block-read internalisation (Phase 4d)
# ----------------------------------------------------------------------
def test_read_groups_partition_telemetry_into_blocks_and_singletons():
    # Production path (no injected definitions): the driver loads the version's
    # register blocks and exposes them as multi-key groups, every other polled key
    # as its own singleton group, with no key appearing twice.
    drv = MarstekModbusDriver("1.2.3.4", 502, "v3", client=_fake_client())
    groups = drv.read_groups

    multi_key = {g.keys for g in groups if len(g.keys) > 1}
    assert ("max_cell_voltage", "min_cell_voltage") in multi_key
    assert ("set_charge_power", "set_discharge_power") in multi_key
    assert ("max_charge_power", "max_discharge_power") in multi_key

    all_keys = [k for g in groups for k in g.keys]
    assert len(all_keys) == len(set(all_keys))  # blocks not also polled as singletons
    assert ("battery_soc",) in {g.keys for g in groups}  # ordinary key -> singleton
    assert all(g.scan_interval for g in groups)  # every group carries a cadence


def test_injected_definitions_have_no_block_groups():
    # The test/override path polls every key individually (no block table loaded).
    drv = _driver("v3", definitions=_DEFS)
    assert all(len(g.keys) == 1 for g in drv.read_groups)
    assert {g.keys for g in drv.read_groups} == {("battery_soc",), ("battery_power",)}


async def test_read_telemetry_collapses_full_block_into_single_request():
    client = _fake_client()
    client.async_read_block = AsyncMock(return_value=[3580, 3479])  # raw words
    drv = MarstekModbusDriver("1.2.3.4", 502, "v3", client=client)

    snap = await drv.read_telemetry(["max_cell_voltage", "min_cell_voltage"])

    client.async_read_block.assert_awaited_once()
    assert client.async_read_register.await_count == 0  # served by the block read
    # raw decoded values, unscaled (the coordinator applies scale/precision)
    assert snap == {"max_cell_voltage": 3580, "min_cell_voltage": 3479}


async def test_read_telemetry_partial_block_falls_back_to_per_register():
    client = _fake_client()
    client.async_read_register = AsyncMock(return_value=3580)
    drv = MarstekModbusDriver("1.2.3.4", 502, "v3", client=client)

    # Only one of the block's two members requested -> cannot block-read it.
    snap = await drv.read_telemetry(["max_cell_voltage"])

    client.async_read_block.assert_not_awaited()
    assert client.async_read_register.await_count == 1
    assert snap == {"max_cell_voltage": 3580}


async def test_read_telemetry_mixes_block_and_singleton():
    client = _fake_client()
    client.async_read_block = AsyncMock(return_value=[100, 200])
    client.async_read_register = AsyncMock(return_value=55)
    drv = MarstekModbusDriver("1.2.3.4", 502, "v3", client=client)

    snap = await drv.read_telemetry(
        ["set_charge_power", "set_discharge_power", "battery_soc"]
    )

    client.async_read_block.assert_awaited_once()       # the set-point block
    assert client.async_read_register.await_count == 1  # battery_soc singleton
    assert snap == {"set_charge_power": 100, "set_discharge_power": 200, "battery_soc": 55}


async def test_read_telemetry_omits_block_members_when_block_read_fails():
    client = _fake_client()
    client.async_read_block = AsyncMock(return_value=None)  # block request failed
    drv = MarstekModbusDriver("1.2.3.4", 502, "v3", client=client)

    snap = await drv.read_telemetry(["max_cell_voltage", "min_cell_voltage"])

    client.async_read_block.assert_awaited_once()
    assert client.async_read_register.await_count == 0  # no per-register retry
    assert snap == {}  # failed block -> members omitted, not None


# ----------------------------------------------------------------------
# apply_setpoint
# ----------------------------------------------------------------------
async def test_apply_setpoint_charge_sets_force_mode_1():
    client = _fake_client()
    drv = _driver("v3", client=client)

    res = await drv.apply_setpoint(600, read_back=False)

    assert res.ok is True
    assert res.net_power_w == 600
    assert res.confirmed is False
    # write-only cycle: optimistic set-point echo, no battery_power
    assert res.applied == {"force_mode": 1, "set_charge_power": 600, "set_discharge_power": 0}
    assert res.battery_power_w is None
    reg = REGISTER_MAP["v3"]
    writes = {c.args[0]: c.args[1] for c in client.async_write_register.call_args_list}
    assert writes[reg["set_charge_power"]] == 600
    assert writes[reg["set_discharge_power"]] == 0
    assert writes[reg["force_mode"]] == 1


async def test_apply_setpoint_discharge_sets_force_mode_2():
    client = _fake_client()
    drv = _driver("v3", client=client)

    res = await drv.apply_setpoint(-450, read_back=False)

    assert res.net_power_w == -450
    reg = REGISTER_MAP["v3"]
    writes = {c.args[0]: c.args[1] for c in client.async_write_register.call_args_list}
    assert writes[reg["set_discharge_power"]] == 450
    assert writes[reg["set_charge_power"]] == 0
    assert writes[reg["force_mode"]] == 2


async def test_apply_setpoint_zero_idles_force_mode_0():
    client = _fake_client()
    drv = _driver("v3", client=client)

    await drv.apply_setpoint(0, read_back=False)

    reg = REGISTER_MAP["v3"]
    writes = {c.args[0]: c.args[1] for c in client.async_write_register.call_args_list}
    assert writes[reg["force_mode"]] == 0
    assert writes[reg["set_charge_power"]] == 0
    assert writes[reg["set_discharge_power"]] == 0


async def test_apply_setpoint_clamps_to_envelope():
    drv = _driver("v3", max_charge_power_w=800, client=_fake_client())
    res = await drv.apply_setpoint(5000, read_back=False)
    assert res.net_power_w == 800


async def test_apply_setpoint_reports_write_failure():
    client = _fake_client()
    client.async_write_register = AsyncMock(return_value=False)
    drv = _driver("v3", client=client)

    res = await drv.apply_setpoint(600)

    assert res.ok is False
    assert res.failure_reason == "modbus_write_failed"


async def test_apply_setpoint_confirms_on_matching_readback():
    client = _fake_client()
    # readback order in driver: force, charge, discharge, battery_power
    client.async_read_register = AsyncMock(side_effect=[1, 600, 0, 590])
    drv = _driver("v3", client=client)

    res = await drv.apply_setpoint(600, read_back=True)

    assert res.ok is True and res.confirmed is True
    # delivered power surfaced for non-delivery detection + telemetry echo
    assert res.battery_power_w == 590
    assert res.applied == {
        "force_mode": 1, "set_charge_power": 600, "set_discharge_power": 0,
        "battery_power": 590,
    }


async def test_apply_setpoint_unconfirmed_on_mismatched_readback():
    client = _fake_client()
    client.async_read_register = AsyncMock(side_effect=[1, 500, 0, 480])  # charge != 600
    drv = _driver("v3", client=client)

    res = await drv.apply_setpoint(600, read_back=True)

    assert res.ok is True and res.confirmed is False
    # echo carries the *readback* values, not the commanded ones
    assert res.applied["set_charge_power"] == 500
    assert res.battery_power_w == 480


async def test_apply_setpoint_feedback_timeout_when_readback_fails():
    client = _fake_client()
    # battery_power read (4th) returns None -> readback incomplete
    client.async_read_register = AsyncMock(side_effect=[1, 600, 0, None])
    drv = _driver("v3", client=client)

    res = await drv.apply_setpoint(600, read_back=True)

    assert res.ok is True  # the writes themselves succeeded
    assert res.confirmed is False
    assert res.failure_reason == "feedback_timeout"
    # no telemetry echo -> coordinator leaves coordinator.data to the next poll
    assert res.applied is None
    assert res.battery_power_w is None


async def test_apply_setpoint_write_only_echoes_setpoints_without_battery_power():
    drv = _driver("v3", client=_fake_client())

    res = await drv.apply_setpoint(-450, read_back=False)

    assert res.applied == {"force_mode": 2, "set_charge_power": 0, "set_discharge_power": 450}
    assert "battery_power" not in res.applied
    assert res.battery_power_w is None


async def test_apply_setpoint_addresses_configured_slave():
    client = _fake_client()
    drv = _driver("v3", slave_id=7, client=client)

    await drv.apply_setpoint(100, read_back=False)

    assert client.unit_id == 7


# ----------------------------------------------------------------------
# write_control (generic entity-write path: number/select/switch/button)
# ----------------------------------------------------------------------
async def test_write_control_resolves_key_to_register():
    client = _fake_client()
    drv = _driver("v3", client=client)

    ok = await drv.write_control("force_mode", 2)

    assert ok is True
    reg = REGISTER_MAP["v3"]["force_mode"]
    client.async_write_register.assert_awaited_once_with(reg, 2)


async def test_write_control_addresses_configured_slave():
    client = _fake_client()
    drv = _driver("v3", slave_id=7, client=client)

    await drv.write_control("force_mode", 1)

    assert client.unit_id == 7


async def test_write_control_returns_false_for_unknown_key():
    client = _fake_client()
    drv = _driver("v3", client=client)

    ok = await drv.write_control("not_a_real_control", 1)

    assert ok is False  # no register for the key -> nothing written
    client.async_write_register.assert_not_awaited()


async def test_write_control_propagates_write_failure():
    client = _fake_client()
    client.async_write_register = AsyncMock(return_value=False)
    drv = _driver("v3", client=client)

    assert await drv.write_control("force_mode", 1) is False


# ----------------------------------------------------------------------
# set_rs485_control
# ----------------------------------------------------------------------
async def test_set_rs485_control_enable_writes_0x55aa():
    client = _fake_client()
    drv = _driver("v3", client=client)

    ok = await drv.set_rs485_control(True)

    assert ok is True
    reg = REGISTER_MAP["v3"]["rs485_control"]
    client.async_write_register.assert_awaited_once_with(reg, 21930)  # 0x55AA


async def test_set_rs485_control_disable_writes_0x55bb():
    client = _fake_client()
    drv = _driver("v3", client=client)

    await drv.set_rs485_control(False)

    reg = REGISTER_MAP["v3"]["rs485_control"]
    client.async_write_register.assert_awaited_once_with(reg, 21947)  # 0x55BB


async def test_set_rs485_control_addresses_configured_slave():
    client = _fake_client()
    drv = _driver("v3", slave_id=7, client=client)

    await drv.set_rs485_control(True)

    assert client.unit_id == 7


async def test_set_rs485_control_returns_false_when_register_missing():
    client = _fake_client()
    drv = _driver("vX", client=client)  # unknown version -> no rs485_control register

    ok = await drv.set_rs485_control(True)

    assert ok is False
    client.async_write_register.assert_not_awaited()


async def test_set_rs485_control_propagates_write_failure():
    client = _fake_client()
    client.async_write_register = AsyncMock(return_value=False)
    drv = _driver("v3", client=client)

    assert await drv.set_rs485_control(True) is False


# ----------------------------------------------------------------------
# apply_config
# ----------------------------------------------------------------------
async def test_apply_config_v2_writes_cutoffs_and_power_caps():
    client = _fake_client()
    drv = _driver("v2", client=client)

    ok = await drv.apply_config(
        max_soc_pct=100, min_soc_pct=10,
        max_charge_power_w=800, max_discharge_power_w=1200,
    )

    assert ok is True
    regs = REGISTER_MAP["v2"]
    # SOC percentages are written in the cut-off register's deci-percent units;
    # use the identical expression so the test tracks any float quirk in int(/0.1).
    client.async_write_register.assert_any_await(regs["charging_cutoff_capacity"], int(100 / 0.1))
    client.async_write_register.assert_any_await(regs["discharging_cutoff_capacity"], int(10 / 0.1))
    client.async_write_register.assert_any_await(regs["max_charge_power"], 800)
    client.async_write_register.assert_any_await(regs["max_discharge_power"], 1200)
    assert client.async_write_register.await_count == 4


async def test_apply_config_v3_skips_absent_cutoffs():
    client = _fake_client()
    drv = _driver("v3", client=client)

    await drv.apply_config(
        max_soc_pct=90, min_soc_pct=20,
        max_charge_power_w=2500, max_discharge_power_w=2500,
    )

    regs = REGISTER_MAP["v3"]
    # cutoffs are None on v3 -> only the two power caps are written
    assert client.async_write_register.await_count == 2
    client.async_write_register.assert_any_await(regs["max_charge_power"], 2500)
    client.async_write_register.assert_any_await(regs["max_discharge_power"], 2500)


async def test_apply_config_addresses_configured_slave():
    client = _fake_client()
    drv = _driver("v3", slave_id=7, client=client)

    await drv.apply_config(
        max_soc_pct=90, min_soc_pct=20,
        max_charge_power_w=2500, max_discharge_power_w=2500,
    )

    assert client.unit_id == 7


async def test_apply_config_propagates_write_failure():
    client = _fake_client()
    client.async_write_register = AsyncMock(return_value=False)
    drv = _driver("v3", client=client)

    ok = await drv.apply_config(
        max_soc_pct=90, min_soc_pct=20,
        max_charge_power_w=2500, max_discharge_power_w=2500,
    )

    assert ok is False


# ----------------------------------------------------------------------
# set_charge_cutoff (weekly-full-charge / active-balance ceiling)
# ----------------------------------------------------------------------
async def test_set_charge_cutoff_v2_raises_ceiling_to_deci_percent():
    client = _fake_client()
    drv = _driver("v2", client=client)

    ok = await drv.set_charge_cutoff(100)

    assert ok is True
    reg = REGISTER_MAP["v2"]["charging_cutoff_capacity"]
    # 100% raises the BMS ceiling to the register's deci-percent max (1000), and
    # only the charge cut-off is touched — not the discharge cut-off or power caps.
    client.async_write_register.assert_awaited_once_with(reg, int(100 / 0.1))


async def test_set_charge_cutoff_restore_value_scaled():
    client = _fake_client()
    drv = _driver("v2", client=client)

    await drv.set_charge_cutoff(80)

    reg = REGISTER_MAP["v2"]["charging_cutoff_capacity"]
    client.async_write_register.assert_awaited_once_with(reg, int(80 / 0.1))


@pytest.mark.parametrize("version", ["v3", "vA", "vD"])
async def test_set_charge_cutoff_returns_false_when_register_absent(version):
    client = _fake_client()
    drv = _driver(version, client=client)

    ok = await drv.set_charge_cutoff(100)

    assert ok is False  # v3 family has no hardware cutoff register
    client.async_write_register.assert_not_awaited()


async def test_set_charge_cutoff_addresses_configured_slave():
    client = _fake_client()
    drv = _driver("v2", slave_id=7, client=client)

    await drv.set_charge_cutoff(100)

    assert client.unit_id == 7


async def test_set_charge_cutoff_propagates_write_failure():
    client = _fake_client()
    client.async_write_register = AsyncMock(return_value=False)
    drv = _driver("v2", client=client)

    assert await drv.set_charge_cutoff(100) is False


# ----------------------------------------------------------------------
# standby (teardown)
# ----------------------------------------------------------------------
async def test_standby_zeros_setpoints_and_force_mode():
    client = _fake_client()
    drv = _driver("v3", client=client)

    ok = await drv.standby()

    assert ok is True
    reg = REGISTER_MAP["v3"]
    writes = {c.args[0]: c.args[1] for c in client.async_write_register.call_args_list}
    assert writes[reg["set_discharge_power"]] == 0
    assert writes[reg["set_charge_power"]] == 0
    assert writes[reg["force_mode"]] == 0
    assert client.async_write_register.await_count == 3


async def test_standby_addresses_configured_slave():
    client = _fake_client()
    drv = _driver("v3", slave_id=7, client=client)

    await drv.standby()

    assert client.unit_id == 7


async def test_standby_propagates_write_failure():
    client = _fake_client()
    client.async_write_register = AsyncMock(return_value=False)
    drv = _driver("v3", client=client)

    assert await drv.standby() is False
