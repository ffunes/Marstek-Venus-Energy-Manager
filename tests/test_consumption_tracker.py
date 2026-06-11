"""Characterization tests for ConsumptionTracker.

These pin the *current* behavior so the planned module refactors can be proven
to change nothing. No Home Assistant entities, no Modbus, no battery: the pure
helpers are called directly, and the one instance test uses the in-process
``hass`` fixture plus a stand-in controller object.
"""
from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace

import pytest

from custom_components.marstek_venus_energy_manager.const import (
    DEFAULT_BASE_CONSUMPTION_KWH,
)
from custom_components.marstek_venus_energy_manager.consumption_tracker import (
    ConsumptionTracker,
)


# ----------------------------------------------------------------------
# Pure solar-energy model: get_solar_fraction_done (static, no HA needed)
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "now_h, t_start, t_end, expected",
    [
        (8.0, 8.0, 16.0, 0.0),    # at sunrise -> nothing produced yet
        (16.0, 8.0, 16.0, 1.0),   # at sunset  -> fully produced
        (12.0, 8.0, 16.0, 0.5),   # midpoint   -> half (sinusoid is symmetric)
        (7.0, 8.0, 16.0, 0.0),    # before window -> clamped to 0
        (17.0, 8.0, 16.0, 1.0),   # after window  -> clamped to 1
        (10.0, 8.0, 16.0, (1.0 - math.cos(math.pi * 0.25)) / 2.0),  # quarter way
    ],
)
def test_solar_fraction_curve(now_h, t_start, t_end, expected):
    result = ConsumptionTracker.get_solar_fraction_done(now_h, t_start, t_end)
    assert result == pytest.approx(expected)


def test_solar_fraction_invalid_window_returns_full():
    # t_end <= t_start is treated as "all produced" rather than dividing by zero.
    assert ConsumptionTracker.get_solar_fraction_done(10.0, 12.0, 12.0) == 1.0
    assert ConsumptionTracker.get_solar_fraction_done(10.0, 12.0, 8.0) == 1.0


# ----------------------------------------------------------------------
# Pure formatting helper: h_to_hhmm (static, no HA needed)
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "hours, expected",
    [
        (13.25, "13:15"),
        (7.5, "07:30"),
        (0.0, "00:00"),
        (9.0, "09:00"),
        (None, None),
    ],
)
def test_h_to_hhmm(hours, expected):
    assert ConsumptionTracker.h_to_hhmm(hours) == expected


# ----------------------------------------------------------------------
# Instance method with a mocked controller: get_avg_daily_consumption
# Proves the controller-by-reference pattern is testable without hardware.
# The tracker is built via __new__ so __init__ (which needs a real hass for
# its Store objects) is skipped: this method only reads one controller attr,
# so isolating it that way keeps the test free of the hass fixture.
# ----------------------------------------------------------------------

def _make_tracker(history):
    """Build a tracker wired to a stand-in controller holding `history`."""
    tracker = ConsumptionTracker.__new__(ConsumptionTracker)
    tracker._controller = SimpleNamespace(_daily_consumption_history=history)
    return tracker


def test_avg_daily_consumption_empty_uses_fallback():
    tracker = _make_tracker([])
    assert tracker.get_avg_daily_consumption() == DEFAULT_BASE_CONSUMPTION_KWH


def test_avg_daily_consumption_averages_history():
    history = [(date(2026, 6, 1), 4.0), (date(2026, 6, 2), 6.0)]
    tracker = _make_tracker(history)
    assert tracker.get_avg_daily_consumption() == pytest.approx(5.0)


def test_avg_daily_consumption_single_day():
    tracker = _make_tracker([(date(2026, 6, 1), 3.0)])
    assert tracker.get_avg_daily_consumption() == pytest.approx(3.0)
