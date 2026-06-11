"""Characterization tests for the excluded-device load logic.

These pin the *current* behavior of the two excluded-device methods on
ExternalLoads so the extraction can be proven to change nothing.

No hardware and no real Home Assistant: ExternalLoads is built with a stub
controller (SimpleNamespace) and a fake hass whose ``states.get`` returns
lightweight state stand-ins. Both methods only read ``config_entry.data`` and
``hass.states``, plus ``previous_power`` for the charge/discharge branch.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.marstek_venus_energy_manager.external_loads import ExternalLoads


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------

class _FakeStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


def _state(value, unit="W"):
    """A minimal stand-in for a Home Assistant State object."""
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _controller(excluded_devices, states=None, previous_power=0.0):
    controller_stub = SimpleNamespace(
        previous_power=previous_power,
        _excluded_included_adjustment=None,
        _ev_charging_states={},
        _ev_pause_until={},
    )
    config_entry = SimpleNamespace(data={"excluded_devices": excluded_devices})
    hass = SimpleNamespace(states=_FakeStates(states or {}))
    return ExternalLoads(hass, config_entry, controller_stub)


def _device(**overrides):
    """A telemetry excluded device with sensible defaults; override per test."""
    base = {
        "enabled": True,
        "ev_charger_no_telemetry": False,
        "power_sensor": "sensor.dev",
        "included_in_consumption": True,
        "allow_solar_surplus": False,
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# consumption_delta_kw  (returns kW; W->kW converted)
# ----------------------------------------------------------------------

def test_delta_kw_no_devices_is_zero():
    assert _controller([]).consumption_delta_kw() == 0.0


def test_delta_kw_included_device_is_subtracted():
    loads = _controller([_device(included_in_consumption=True)],
                       {"sensor.dev": _state(500)})
    assert loads.consumption_delta_kw() == pytest.approx(-0.5)


def test_delta_kw_not_included_device_is_added():
    loads = _controller([_device(included_in_consumption=False)],
                       {"sensor.dev": _state(500)})
    assert loads.consumption_delta_kw() == pytest.approx(0.5)


def test_delta_kw_kilowatt_unit_not_reconverted():
    loads = _controller([_device(included_in_consumption=True)],
                       {"sensor.dev": _state(0.5, unit="kW")})
    assert loads.consumption_delta_kw() == pytest.approx(-0.5)


def test_delta_kw_two_devices_net():
    devices = [
        _device(power_sensor="sensor.a", included_in_consumption=True),
        _device(power_sensor="sensor.b", included_in_consumption=False),
    ]
    loads = _controller(devices,
                       {"sensor.a": _state(500), "sensor.b": _state(200)})
    # -0.5 (subtracted) + 0.2 (added)
    assert loads.consumption_delta_kw() == pytest.approx(-0.3)


@pytest.mark.parametrize("device, states", [
    (_device(enabled=False), {"sensor.dev": _state(500)}),
    (_device(ev_charger_no_telemetry=True), {"sensor.dev": _state(500)}),
    (_device(power_sensor=None), {}),
    (_device(), {"sensor.dev": _state("unavailable")}),
    (_device(), {}),  # sensor missing entirely
])
def test_delta_kw_skips_unusable_devices(device, states):
    assert _controller([device], states).consumption_delta_kw() == 0.0


# ----------------------------------------------------------------------
# calculate_adjustment  (returns W; NO unit conversion)
# Positive = reduce battery discharge, negative = increase it.
# ----------------------------------------------------------------------

def test_adjustment_no_devices_is_zero_and_resets_included():
    loads = _controller([])
    assert loads.calculate_adjustment(0.0) == 0.0
    assert loads._controller._excluded_included_adjustment == 0.0


def test_adjustment_included_no_surplus_subtracts():
    loads = _controller([_device(included_in_consumption=True, allow_solar_surplus=False)],
                       {"sensor.dev": _state(500)})
    assert loads.calculate_adjustment(0.0) == pytest.approx(500.0)
    assert loads._controller._excluded_included_adjustment == pytest.approx(500.0)


def test_adjustment_not_included_adds_discharge():
    loads = _controller([_device(included_in_consumption=False)],
                       {"sensor.dev": _state(500)})
    assert loads.calculate_adjustment(0.0) == pytest.approx(-500.0)
    assert loads._controller._excluded_included_adjustment == pytest.approx(0.0)


def test_adjustment_solar_surplus_while_charging_is_neutral():
    # included + allow_solar_surplus + charging (previous_power >= 0) -> no adjustment
    loads = _controller(
        [_device(included_in_consumption=True, allow_solar_surplus=True)],
        {"sensor.dev": _state(500)},
        previous_power=100.0,
    )
    assert loads.calculate_adjustment(0.0) == pytest.approx(0.0)
    assert loads._controller._excluded_included_adjustment == pytest.approx(0.0)


def test_adjustment_solar_surplus_while_discharging_full_exclusion():
    # included + allow_solar_surplus + discharging (previous_power < 0) -> subtract
    loads = _controller(
        [_device(included_in_consumption=True, allow_solar_surplus=True)],
        {"sensor.dev": _state(500)},
        previous_power=-100.0,
    )
    assert loads.calculate_adjustment(0.0) == pytest.approx(500.0)
    assert loads._controller._excluded_included_adjustment == pytest.approx(500.0)


@pytest.mark.parametrize("device", [
    _device(enabled=False),
    _device(ev_charger_no_telemetry=True),
    _device(power_sensor=None),
])
def test_adjustment_skips_unusable_devices(device):
    loads = _controller([device], {"sensor.dev": _state(500)})
    assert loads.calculate_adjustment(0.0) == 0.0


# ----------------------------------------------------------------------
# check_ev_charger_state  (no-telemetry EV: 5-min pause then discharge-block)
# Time-dependent: a frozen clock drives the pause window. Returns
# (pause_active, ev_charging_active).
# ----------------------------------------------------------------------

def _ev_device(**overrides):
    """A no-telemetry EV charger: a state sensor, not a numeric power sensor."""
    base = {
        "enabled": True,
        "ev_charger_no_telemetry": True,
        "power_sensor": "sensor.ev",
    }
    base.update(overrides)
    return base


def test_ev_start_charging_starts_pause():
    loads = _controller([_ev_device()], {"sensor.ev": _state("charging")})
    # First detection: pause begins, not yet discharge-blocking.
    assert loads.check_ev_charger_state() == (True, False)


def test_ev_pause_stays_active_within_5_min():
    loads = _controller([_ev_device()], {"sensor.ev": _state("charging")})
    loads.check_ev_charger_state()                # pause starts (now + 5 min)
    # An immediate re-check is well within the 5-minute window.
    assert loads.check_ev_charger_state() == (True, False)


def test_ev_charging_active_after_pause_expires():
    loads = _controller([_ev_device()], {"sensor.ev": _state("charging")})
    loads.check_ev_charger_state()                # pause starts
    # Simulate the 5-min pause having elapsed by moving the stored deadline into
    # the past. (freezegun can't patch HA's dt_util.utcnow with the HA pytest
    # plugin disabled, so we manipulate the deadline directly instead.)
    loads._controller._ev_pause_until["sensor.ev"] = dt_util.utcnow() - timedelta(minutes=1)
    assert loads.check_ev_charger_state() == (False, True)


def test_ev_stop_charging_cancels_pause():
    states = {"sensor.ev": _state("charging")}
    loads = _controller([_ev_device()], states)
    loads.check_ev_charger_state()                # pause starts
    states["sensor.ev"] = _state("idle")          # EV stops mid-pause
    assert loads.check_ev_charger_state() == (False, False)
    assert loads._controller._ev_pause_until == {}


def test_ev_idle_does_nothing():
    loads = _controller([_ev_device()], {"sensor.ev": _state("idle")})
    assert loads.check_ev_charger_state() == (False, False)


def test_ev_spanish_cargando_detected():
    loads = _controller([_ev_device()], {"sensor.ev": _state("Cargando")})
    assert loads.check_ev_charger_state() == (True, False)


@pytest.mark.parametrize("device", [
    _ev_device(enabled=False),
    _ev_device(power_sensor=None),
    # A numeric excluded device (not a no-telemetry EV) must be ignored here.
    _device(ev_charger_no_telemetry=False, power_sensor="sensor.ev"),
])
def test_ev_skips_non_applicable_devices(device):
    loads = _controller([device], {"sensor.ev": _state("charging")})
    assert loads.check_ev_charger_state() == (False, False)
