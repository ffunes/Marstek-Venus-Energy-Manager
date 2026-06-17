"""Unit tests for the Zendure local HTTP driver.

All HTTP calls are intercepted via an injected aiohttp.ClientSession fake,
so no network access or Home Assistant runtime is required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.marstek_venus_energy_manager.drivers.zendure import (
    NUMBER_DEFINITIONS,
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
    "properties": {
        "electricLevel": 80,
        "outputHomePower": 200,
        "solarInputPower": 0,
        "gridInputPower": 150,
        "packInputPower": 0,
        "outputPackPower": 50,
        "hyperTmp": 35,
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
    },
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


def test_number_definitions_include_soc_and_power_controls():
    keys = {d["key"] for d in _driver().number_definitions}
    assert {"soc_set", "min_soc", "inverse_max_power"} <= keys


def test_select_switch_binary_sensor_button_empty():
    drv = _driver()
    assert drv.select_definitions == []
    assert drv.switch_definitions == []
    assert drv.binary_sensor_definitions == []
    assert drv.button_definitions == []


def test_all_definitions_is_sensor_plus_number():
    assert _driver().all_definitions == SENSOR_DEFINITIONS + NUMBER_DEFINITIONS


# ---------------------------------------------------------------------------
# read_groups
# ---------------------------------------------------------------------------

def test_single_read_group_covers_all_keys():
    drv = _driver()
    groups = drv.read_groups
    assert len(groups) == 1
    assert groups[0].scan_interval == "high"
    assert groups[0].keys == tuple(d["key"] for d in drv.all_definitions)


# ---------------------------------------------------------------------------
# read_telemetry
# ---------------------------------------------------------------------------

async def test_read_telemetry_maps_properties_to_keys():
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry()
    assert snap["battery_soc"] == 80         # electricLevel
    assert snap["output_home_power"] == 200  # outputHomePower
    assert snap["device_temperature"] == 35  # hyperTmp


async def test_read_telemetry_synthesises_battery_power_charging():
    data = {"sn": "ZB1", "properties": {"packInputPower": 0, "outputPackPower": 300}}
    snap = await _driver(session=_session(get_data=data)).read_telemetry(["battery_power"])
    assert snap["battery_power"] == 300   # +charge


async def test_read_telemetry_synthesises_battery_power_discharging():
    data = {"sn": "ZB1", "properties": {"packInputPower": 450, "outputPackPower": 0}}
    snap = await _driver(session=_session(get_data=data)).read_telemetry(["battery_power"])
    assert snap["battery_power"] == -450  # −discharge


async def test_read_telemetry_key_filter():
    snap = await _driver(session=_session(get_data=_REPORT)).read_telemetry(["battery_soc", "battery_power"])
    assert set(snap) == {"battery_soc", "battery_power"}


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
    assert props["smartMode"] == 1
    assert "outputLimit" not in props


async def test_apply_setpoint_discharge_posts_ac_mode_2():
    sess = _session(get_data=_REPORT)
    res = await _driver(session=sess).apply_setpoint(-450, read_back=False)

    assert res.ok is True
    assert res.net_power_w == -450
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["acMode"] == 2
    assert props["outputLimit"] == 450
    assert props["smartMode"] == 1
    assert "inputLimit" not in props


async def test_apply_setpoint_zero_posts_output_limit_0():
    sess = _session(get_data=_REPORT)
    res = await _driver(session=sess).apply_setpoint(0, read_back=False)

    assert res.ok is True
    assert res.net_power_w == 0
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props["acMode"] == 2
    assert props["outputLimit"] == 0


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
    # config write: must NOT include smartMode so the value survives a reboot
    props = sess.post.call_args.kwargs["json"]["properties"]
    assert props == {"socSet": 90}


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
    assert props["socSet"] == 90
    assert props["minSoc"] == 20
    assert "smartMode" not in props  # config write must persist across reboots


@pytest.mark.parametrize("raw,expected", [
    (110, 100),  # clamped to max 100
    (60,  70),   # clamped to min 70
    (85,  85),   # in range
])
async def test_apply_config_clamps_soc_set(raw, expected):
    sess = _session()
    await _driver(session=sess).apply_config(
        max_soc_pct=raw, min_soc_pct=10,
        max_charge_power_w=2400, max_discharge_power_w=2400,
    )
    assert sess.post.call_args.kwargs["json"]["properties"]["socSet"] == expected


@pytest.mark.parametrize("raw,expected", [
    (-5, 0),   # clamped to min 0
    (60, 50),  # clamped to max 50
    (30, 30),  # in range
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
