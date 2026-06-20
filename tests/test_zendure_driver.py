"""Unit tests for the Zendure local HTTP driver.

All HTTP calls are intercepted via an injected aiohttp.ClientSession fake,
so no network access or Home Assistant runtime is required.
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.marstek_venus_energy_manager.drivers.zendure import (
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    SENSOR_DEFINITIONS,
    ZendureLocalDriver,
)


# ---------------------------------------------------------------------------
# HTTP fakes
# ---------------------------------------------------------------------------

def _resp(status: int = 200, json_data: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status = status
    r.json = AsyncMock(return_value=json_data if json_data is not None else {})
    return r


def _cm(resp: MagicMock) -> MagicMock:
    """Wrap a fake response in an async context manager."""
    m = MagicMock()
    m.__aenter__ = AsyncMock(return_value=resp)
    m.__aexit__ = AsyncMock(return_value=False)
    return m


def _session(
    get_status: int = 200,
    get_data: dict | None = None,
    post_status: int = 200,
) -> MagicMock:
    s = MagicMock()
    s.closed = False
    s.get = MagicMock(return_value=_cm(_resp(get_status, get_data)))
    s.post = MagicMock(return_value=_cm(_resp(post_status)))
    return s


_REPORT = {
    "sn": "ZB123456",
    "product": "Solarflow 2400 AC",
    "properties": {
        "electricLevel": 80,
        "outputHomePower": 200,
        "solarInputPower": 150,
        "gridInputPower": 150,
        "packInputPower": 0,
        "outputPackPower": 50,
        "hyperTmp": 3035,         # centi-°C → 30.35 °C
        "faultLevel": 0,
        "acStatus": 1,
        "remainOutTime": 120,
        "packNum": 1,
        "is_error": 0,
        "outputLimit": 0,
        "inputLimit": 0,
        "acMode": 1,
        "socSet": 100,
        "minSoc": 10,
        "inverseMaxPower": 2400,
        "solarPower1": 100,
        "solarPower2": 50,
        "solarPower3": 0,
        "solarPower4": 0,
        "BatVolt": 5010,          # centi-volt → 50.10 V
        "rssi": -58,
        "gridOffPower": 0,
        "gridOffMode": 1,         # off-grid port mode enum (1 = economy)
    },
    "packData": [
        {"maxVol": 334, "minVol": 333},
        {"maxVol": 330, "minVol": 320},
    ],
}


def _driver(
    host: str = "192.168.1.100",
    port: int = 80,
    max_charge: int = 2400,
    max_discharge: int = 2400,
    session: MagicMock | None = None,
    sn: str | None = "ZB123456",
) -> ZendureLocalDriver:
    drv = ZendureLocalDriver(
        host,
        port=port,
        max_charge_power_w=max_charge,
        max_discharge_power_w=max_discharge,
        session=session or _session(get_data=_REPORT),
    )
    if sn is not None:
        drv._sn = sn
    return drv


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    """Skip the 0.5 s post-write settle so readback tests stay fast."""
    monkeypatch.setattr(
        "custom_components.marstek_venus_energy_manager.drivers.zendure.asyncio.sleep",
        AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------

def test_capabilities_flags():
    caps = _driver().capabilities
    assert caps.hardware_soc_cutoff is True
    assert caps.has_force_mode is False
    assert caps.push_telemetry is False
    assert caps.has_rs485_control is False
    assert caps.has_mppt_pv is False
    assert caps.has_alarm_registers is True
    assert caps.has_energy_counters is False  # no kWh / capacity in the report


def test_capabilities_power_envelope():
    caps = _driver(max_charge=1200, max_discharge=800).capabilities
    assert caps.max_charge_power_w == 1200
    assert caps.max_discharge_power_w == 800


# ---------------------------------------------------------------------------
# entity definitions
# ---------------------------------------------------------------------------

def test_sensor_definitions_include_core_keys():
    keys = {d["key"] for d in _driver().sensor_definitions}
    assert {"battery_soc", "battery_power", "output_home_power"} <= keys


def test_sensor_definitions_reuse_marstek_logical_keys():
    # Cross-brand homogeneity: shared concepts use the same logical keys as the
    # Marstek driver so they share translations and dashboard cards.
    keys = {d["key"] for d in _driver().sensor_definitions}
    assert {
        "internal_temperature", "solar_power",
        "mppt1_power", "mppt2_power", "mppt3_power", "mppt4_power",
        "battery_voltage", "ac_offgrid_power",
        "max_cell_voltage", "min_cell_voltage", "wifi_signal_strength",
    } <= keys


def test_number_definitions_include_soc_and_power_controls():
    keys = {d["key"] for d in _driver().number_definitions}
    assert {"soc_set", "min_soc", "inverse_max_power"} <= keys


def test_switch_binary_sensor_button_empty():
    drv = _driver()
    assert drv.switch_definitions == []
    assert drv.binary_sensor_definitions == []
    assert drv.button_definitions == []


def test_select_definitions_include_grid_off_mode():
    by_key = {d["key"]: d for d in _driver().select_definitions}
    assert "grid_off_mode" in by_key
    # Confirmed on a 2400 AC+: 0=normal, 1=economy, 2=off.
    assert by_key["grid_off_mode"]["options"] == {"normal": 0, "economy": 1, "off": 2}


def test_all_definitions_is_sensor_plus_number_plus_select():
    assert _driver().all_definitions == (
        SENSOR_DEFINITIONS + NUMBER_DEFINITIONS + SELECT_DEFINITIONS
    )


# ---------------------------------------------------------------------------
# read_groups
# ---------------------------------------------------------------------------

def test_single_read_group_covers_all_keys():
    drv = _driver()
    groups = drv.read_groups
    assert len(groups) == 1
    assert groups[0].scan_interval == "high"
    assert groups[0].keys == tuple(d["key"] for d in drv.all_definitions)


def test_control_dependency_keys_cover_net_power_inputs():
    # net_power_from_data reads these; they must stay polled though their
    # entities are disabled, so the skip-if-unchanged guard can fire.
    assert _driver().control_dependency_keys == frozenset(
        {"ac_mode", "input_limit", "output_limit"}
    )


# ---------------------------------------------------------------------------
# read_telemetry
# ---------------------------------------------------------------------------

async def test_read_telemetry_maps_properties_to_keys():
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["battery_soc"] == 80         # electricLevel
    assert snap["output_home_power"] == 200  # outputHomePower
    assert snap["solar_power"] == 150        # solarInputPower → Marstek key


async def test_read_telemetry_returns_raw_centi_units_for_coordinator_scaling():
    # Driver returns raw device values under the reused Marstek keys; the
    # coordinator applies the ×0.01 scale from the entity definition (same path
    # as Marstek register sensors). Scaling in the driver would double it.
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["internal_temperature"] == 3035  # hyperTmp raw (→30.35 °C scaled)
    assert snap["battery_voltage"] == 5010        # BatVolt raw (→50.10 V scaled)


def test_centi_scaled_keys_carry_scale_for_coordinator():
    by_key = {d["key"]: d for d in _driver().sensor_definitions}
    for k in ("internal_temperature", "battery_voltage",
              "max_cell_voltage", "min_cell_voltage"):
        assert by_key[k]["scale"] == 0.01


async def test_read_telemetry_maps_grid_off_mode():
    # Off-grid port mode enum passes through unscaled (no "scale" on the select def);
    # the select entity matches the raw value back to its option.
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["grid_off_mode"] == 1


async def test_read_telemetry_maps_mppt_rssi_and_offgrid():
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["mppt1_power"] == 100
    assert snap["mppt2_power"] == 50
    assert snap["mppt3_power"] == 0
    assert snap["mppt4_power"] == 0
    assert snap["wifi_signal_strength"] == -58  # rssi (dBm, as-is)
    assert snap["ac_offgrid_power"] == 0        # gridOffPower


async def test_read_telemetry_cell_voltages_from_packdata():
    # Device-level extremes across packs, raw centi-volt (max of maxVol, min of
    # minVol); coordinator applies the ×0.01 scale.
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["max_cell_voltage"] == 334  # max(334, 330) → 3.34 V scaled
    assert snap["min_cell_voltage"] == 320  # min(333, 320) → 3.20 V scaled


async def test_read_telemetry_remain_time_sentinel_is_none():
    data = {"sn": "ZB1", "properties": {"remainOutTime": 59940}}
    snap = await _driver(session=_session(get_data=data)).read_telemetry()
    assert snap["remain_discharge_time"] is None


async def test_read_telemetry_remain_time_real_value_passes_through():
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["remain_discharge_time"] == 120


async def test_read_telemetry_synthesises_battery_power_charging():
    data = {"sn": "ZB1", "properties": {"packInputPower": 0, "outputPackPower": 300}}
    snap = await _driver(session=_session(get_data=data)).read_telemetry(["battery_power"])
    assert snap["battery_power"] == 300   # +charge


async def test_read_telemetry_synthesises_battery_power_discharging():
    data = {"sn": "ZB1", "properties": {"packInputPower": 450, "outputPackPower": 0}}
    snap = await _driver(session=_session(get_data=data)).read_telemetry(["battery_power"])
    assert snap["battery_power"] == -450  # −discharge


async def test_read_telemetry_converts_soc_set_min_soc_from_deci_percent():
    # _REPORT has socSet=100, minSoc=10 (deci-percent) → 10 %, 1 %.
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["soc_set"] == 10
    assert snap["min_soc"] == 1


async def test_read_telemetry_key_filter():
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry(["battery_soc", "battery_power"])
    # Requested keys are returned. Per-pack keys (like max_charge_power) ride
    # through the filter regardless so the platform can size pack sensors.
    assert {"battery_soc", "battery_power"} <= set(snap)
    extras = set(snap) - {"battery_soc", "battery_power"}
    assert all(re.match(r"pack\d+_", k) for k in extras)


async def test_read_telemetry_emits_per_pack_keys():
    data = {
        "sn": "ZB1",
        "properties": {"electricLevel": 77, "packNum": 1},
        "packData": [
            {"socLevel": 76, "totalVol": 5005, "maxVol": 334, "minVol": 333,
             "maxTemp": 3011, "power": 120, "sn": "PK1", "packType": 500, "state": 0},
        ],
    }
    snap = await _driver(session=_session(get_data=data)).read_telemetry()
    assert snap["pack1_soc"] == 76
    assert snap["pack1_voltage"] == 50.05          # totalVol / 100
    assert snap["pack1_max_cell_voltage"] == 3.34  # maxVol / 100
    assert snap["pack1_min_cell_voltage"] == 3.33
    assert snap["pack1_temperature"] == 30.11      # maxTemp / 100
    assert snap["pack1_power"] == 120
    assert snap["pack1_sn"] == "PK1"
    assert snap["pack1_model"] == 500              # packType
    assert snap["pack1_state"] == 0


async def test_model_label_from_report_product():
    drv = _driver(session=_session(get_data=_REPORT), sn=None)
    assert drv.model_label is None        # nothing read yet
    await drv.read_telemetry()
    assert drv.model_label == "Solarflow 2400 AC"


async def test_read_telemetry_keeps_max_charge_power_through_filter():
    # chargeMaxLimit → max_charge_power is a control attribute (drives PD
    # allocation), so it must survive the key filter even when not requested.
    data = {"sn": "ZB1", "properties": {"electricLevel": 50, "chargeMaxLimit": 800}}
    snap = await _driver(session=_session(get_data=data)).read_telemetry(["battery_soc"])
    assert snap["max_charge_power"] == 800


async def test_read_telemetry_http_failure_returns_empty():
    assert await _driver(session=_session(get_status=503)).read_telemetry() == {}


async def test_read_telemetry_populates_sn():
    drv = _driver(session=_session(get_data=_REPORT), sn=None)
    await drv.read_telemetry()
    assert drv._sn == "ZB123456"


# ---------------------------------------------------------------------------
# apply_setpoint
# ---------------------------------------------------------------------------

async def test_apply_setpoint_charge_posts_ac_mode_1():
    sess = _session(get_data=_REPORT)
    res = await _driver(session=sess).apply_setpoint(600, read_back=False)

    assert res.ok is True
    assert res.net_power_w == 600
    assert res.confirmed is False
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["acMode"] == 1
    assert props["inputLimit"] == 600
    assert props["smartMode"] == 1  # RAM write (off flash); obeys acMode with HEMS off
    assert "outputLimit" not in props


async def test_apply_setpoint_discharge_posts_ac_mode_2():
    sess = _session(get_data=_REPORT)
    res = await _driver(session=sess).apply_setpoint(-450, read_back=False)

    assert res.ok is True
    assert res.net_power_w == -450
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["acMode"] == 2
    assert props["outputLimit"] == 450
    assert props["smartMode"] == 1  # RAM write (off flash); obeys acMode with HEMS off
    assert "inputLimit" not in props


async def test_apply_setpoint_zero_posts_output_limit_0():
    sess = _session(get_data=_REPORT)
    res = await _driver(session=sess).apply_setpoint(0, read_back=False)

    assert res.ok is True
    assert res.net_power_w == 0
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["acMode"] == 2
    assert props["outputLimit"] == 0
    assert props["smartMode"] == 1  # RAM write (off flash); obeys acMode with HEMS off


async def test_apply_setpoint_clamps_charge_to_max():
    res = await _driver(max_charge=800).apply_setpoint(5000, read_back=False)
    assert res.net_power_w == 800


async def test_apply_setpoint_clamps_discharge_to_max():
    res = await _driver(max_discharge=600).apply_setpoint(-5000, read_back=False)
    assert res.net_power_w == -600


async def test_apply_setpoint_http_failure_returns_not_ok():
    res = await _driver(session=_session(post_status=500)).apply_setpoint(300, read_back=False)
    assert res.ok is False
    assert res.failure_reason == "http_write_failed"


async def test_apply_setpoint_confirmed_on_matching_readback():
    readback = {
        "sn": "ZB123456",
        "properties": {
            "acMode": 1, "inputLimit": 600,
            "packInputPower": 0, "outputPackPower": 580,
        },
    }
    sess = MagicMock()
    sess.closed = False
    sess.post = MagicMock(return_value=_cm(_resp(200)))
    sess.get = MagicMock(return_value=_cm(_resp(200, readback)))

    res = await _driver(session=sess).apply_setpoint(600, read_back=True)

    assert res.ok is True
    assert res.confirmed is True
    assert res.battery_power_w == 580


async def test_apply_setpoint_unconfirmed_on_mismatched_readback():
    readback = {
        "sn": "ZB123456",
        "properties": {
            "acMode": 1, "inputLimit": 500,  # commanded 600, readback shows 500
            "packInputPower": 0, "outputPackPower": 480,
        },
    }
    sess = MagicMock()
    sess.closed = False
    sess.post = MagicMock(return_value=_cm(_resp(200)))
    sess.get = MagicMock(return_value=_cm(_resp(200, readback)))

    res = await _driver(session=sess).apply_setpoint(600, read_back=True)

    assert res.ok is True
    assert res.confirmed is False


async def test_apply_setpoint_confirmed_when_charge_clamped_to_device_cap():
    # Device clamps inputLimit to chargeMaxLimit below the commanded power.
    # Confirmation must accept the clamped value, not flag ack_mismatch.
    readback = {
        "sn": "ZB123456",
        "properties": {
            "acMode": 1, "inputLimit": 800, "chargeMaxLimit": 800,
            "packInputPower": 0, "outputPackPower": 790,
        },
    }
    sess = MagicMock()
    sess.closed = False
    sess.post = MagicMock(return_value=_cm(_resp(200)))
    sess.get = MagicMock(return_value=_cm(_resp(200, readback)))

    res = await _driver(session=sess).apply_setpoint(1500, read_back=True)

    assert res.confirmed is True


async def test_apply_setpoint_confirmed_when_discharge_clamped_to_device_cap():
    readback = {
        "sn": "ZB123456",
        "properties": {
            "acMode": 2, "outputLimit": 800, "inverseMaxPower": 800,
            "packInputPower": 790, "outputPackPower": 0,
        },
    }
    sess = MagicMock()
    sess.closed = False
    sess.post = MagicMock(return_value=_cm(_resp(200)))
    sess.get = MagicMock(return_value=_cm(_resp(200, readback)))

    res = await _driver(session=sess).apply_setpoint(-1500, read_back=True)

    assert res.confirmed is True


async def test_apply_setpoint_feedback_timeout_when_readback_fails():
    sess = MagicMock()
    sess.closed = False
    sess.post = MagicMock(return_value=_cm(_resp(200)))
    sess.get = MagicMock(return_value=_cm(_resp(503)))

    res = await _driver(session=sess).apply_setpoint(300, read_back=True)

    assert res.ok is True
    assert res.confirmed is False
    assert res.failure_reason == "feedback_timeout"


# ---------------------------------------------------------------------------
# write_control
# ---------------------------------------------------------------------------

async def test_write_control_maps_key_to_property():
    sess = _session()
    ok = await _driver(session=sess).write_control("soc_set", 90)

    assert ok is True
    # config write: smartMode=0 forces a flash write so the value survives a
    # reboot. smartMode is sticky and the power loop holds it at 1 (RAM), so
    # omitting it would land the config in RAM. soc_set is deci-percent → 90 % → 900.
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props == {"socSet": 900, "smartMode": 0}


async def test_write_control_grid_off_mode_posts_raw_enum():
    sess = _session()
    ok = await _driver(session=sess).write_control("grid_off_mode", 2)

    assert ok is True
    # Raw enum value, no deci-percent scaling, and smartMode=0 so the off-grid
    # port mode persists to flash across reboots.
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props == {"gridOffMode": 2, "smartMode": 0}


async def test_write_control_unknown_key_returns_false():
    sess = _session()
    ok = await _driver(session=sess).write_control("not_a_real_key", 1)

    assert ok is False
    sess.post.assert_not_called()


async def test_write_control_http_failure_returns_false():
    assert await _driver(session=_session(post_status=500)).write_control("min_soc", 10) is False


# ---------------------------------------------------------------------------
# apply_config
# ---------------------------------------------------------------------------

async def test_apply_config_writes_soc_set_and_min_soc():
    sess = _session()
    ok = await _driver(session=sess).apply_config(
        max_soc_pct=90, min_soc_pct=20,
        max_charge_power_w=2400, max_discharge_power_w=2400,
    )

    assert ok is True
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["socSet"] == 900   # 90 % in deci-percent
    assert props["minSoc"] == 200   # 20 % in deci-percent
    assert props["smartMode"] == 0  # flash write so config persists across reboots


@pytest.mark.parametrize("raw,expected", [
    (110, 1000),  # clamped to max 100 % → 1000 deci-percent
    (60,  700),   # clamped to min 70 % → 700
    (85,  850),   # in range → 850
])
async def test_apply_config_clamps_soc_set(raw, expected):
    sess = _session()
    await _driver(session=sess).apply_config(
        max_soc_pct=raw, min_soc_pct=10,
        max_charge_power_w=2400, max_discharge_power_w=2400,
    )
    assert sess.post.call_args.kwargs["json"]["properties"]["socSet"] == expected


@pytest.mark.parametrize("raw,expected", [
    (-5, 0),    # clamped to min 0 % → 0
    (60, 500),  # clamped to max 50 % → 500
    (30, 300),  # in range → 300
])
async def test_apply_config_clamps_min_soc(raw, expected):
    sess = _session()
    await _driver(session=sess).apply_config(
        max_soc_pct=100, min_soc_pct=raw,
        max_charge_power_w=2400, max_discharge_power_w=2400,
    )
    assert sess.post.call_args.kwargs["json"]["properties"]["minSoc"] == expected


async def test_apply_config_http_failure_returns_false():
    ok = await _driver(session=_session(post_status=500)).apply_config(
        max_soc_pct=90, min_soc_pct=20,
        max_charge_power_w=2400, max_discharge_power_w=2400,
    )
    assert ok is False


# ---------------------------------------------------------------------------
# standby
# ---------------------------------------------------------------------------

async def test_standby_posts_output_limit_0_with_smart_mode():
    sess = _session()
    ok = await _driver(session=sess).standby()

    assert ok is True
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["acMode"] == 2
    assert props["outputLimit"] == 0
    assert props["smartMode"] == 1  # transient; must not wear flash


async def test_standby_http_failure_returns_false():
    assert await _driver(session=_session(post_status=500)).standby() is False


# ---------------------------------------------------------------------------
# set_rs485_control
# ---------------------------------------------------------------------------

async def test_set_rs485_control_always_returns_false_with_no_http_call():
    sess = _session()
    drv = _driver(session=sess)

    assert await drv.set_rs485_control(True) is False
    assert await drv.set_rs485_control(False) is False
    sess.post.assert_not_called()


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def _probe_session(status: int = 200, data: dict | None = None) -> MagicMock:
    """Build a fake aiohttp.ClientSession suitable for probe() (used as async CM)."""
    sess = MagicMock()
    sess.__aenter__ = AsyncMock(return_value=sess)
    sess.__aexit__ = AsyncMock(return_value=False)
    sess.get = MagicMock(return_value=_cm(_resp(status, data)))
    return sess


async def test_probe_returns_true_when_properties_present(monkeypatch):
    fake = _probe_session(200, {"properties": {"electricLevel": 80}})
    monkeypatch.setattr(
        "custom_components.marstek_venus_energy_manager.drivers.zendure.aiohttp.ClientSession",
        MagicMock(return_value=fake),
    )
    assert await ZendureLocalDriver.probe("192.168.1.100") is True


async def test_probe_returns_false_on_http_error(monkeypatch):
    fake = _probe_session(404)
    monkeypatch.setattr(
        "custom_components.marstek_venus_energy_manager.drivers.zendure.aiohttp.ClientSession",
        MagicMock(return_value=fake),
    )
    assert await ZendureLocalDriver.probe("192.168.1.100") is False


async def test_probe_returns_false_when_properties_key_missing(monkeypatch):
    fake = _probe_session(200, {"sn": "ZB1", "status": "ok"})
    monkeypatch.setattr(
        "custom_components.marstek_venus_energy_manager.drivers.zendure.aiohttp.ClientSession",
        MagicMock(return_value=fake),
    )
    assert await ZendureLocalDriver.probe("192.168.1.100") is False


async def test_probe_returns_false_on_exception(monkeypatch):
    import asyncio

    fake = MagicMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    fake.get = MagicMock(side_effect=asyncio.TimeoutError)
    monkeypatch.setattr(
        "custom_components.marstek_venus_energy_manager.drivers.zendure.aiohttp.ClientSession",
        MagicMock(return_value=fake),
    )
    assert await ZendureLocalDriver.probe("192.168.1.100") is False
