"""Characterization tests for PricingManager (module-8 PR3).

These pin the *current* behavior of the runtime pricing engine extracted from
``ChargeDischargeController`` so the move to ``pricing/engine.py`` is proven
cero-cambio-funcional. Runtime state stays on the controller by reference; the
manager reads/writes it via ``self._controller`` (matching the production wiring
where ``sensor.py`` / ``binary_sensor.py`` and the PD control loop also touch it).

No hardware, no running Home Assistant. ``PricingManager.__init__`` only stores
``hass``/``controller`` references, so it is built directly with a SimpleNamespace
hass and a stub controller. Tests cover the pure / early-return branches that need
no ``hass`` and no time mocking.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.omnibattery.const import (
    PRICE_INTEGRATION_CKW,
    PRICE_INTEGRATION_NORDPOOL,
    PREDICTIVE_MODE_DYNAMIC_PRICING,
    PREDICTIVE_MODE_REALTIME_PRICE,
    PREDICTIVE_MODE_TIME_SLOT,
)
from custom_components.omnibattery.pricing import PriceSlot
from custom_components.omnibattery.pricing.engine import PricingManager


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------

def _controller(**overrides):
    """Stub controller exposing only the state/collaborators the manager reads.
    ``_removed`` / ``_set`` record discharge-block calls so tests can assert which
    branch of ``apply_price_discharge_block`` ran."""
    removed: list = []
    set_calls: list = []

    base = dict(
        # discharge-block recorders
        remove_discharge_block=lambda source: removed.append(source),
        set_discharge_block=lambda source, reason, details=None: set_calls.append(
            (source, reason, details)
        ),
        _price_based_discharge_blocked=False,
        # pricing state
        _dynamic_pricing_schedule=None,
        _dynamic_pricing_evaluated_date=None,
        _dp_evening_reevaluated_date=None,
        _dp_daily_avg_price=None,
        # config defaults (DP discharge-control path)
        predictive_charging_mode=PREDICTIVE_MODE_TIME_SLOT,
        dp_price_discharge_control=False,
        rt_price_discharge_control=False,
        price_sensor=None,
        price_integration_type=PRICE_INTEGRATION_NORDPOOL,
        max_price_threshold=None,
        discharge_price_threshold=None,
        average_price_sensor=None,
    )
    base.update(overrides)
    ctrl = SimpleNamespace(**base)
    ctrl._removed = removed
    ctrl._set = set_calls
    return ctrl


def _mgr(ctrl):
    return PricingManager(SimpleNamespace(), ctrl)


def _schedule(slots):
    """Minimal schedule stand-in: only ``selected_slots`` is read here."""
    return SimpleNamespace(selected_slots=slots)


# ----------------------------------------------------------------------
# _get_price_unit
# ----------------------------------------------------------------------

def test_price_unit_ckw_is_chf():
    assert _mgr(_controller(price_integration_type=PRICE_INTEGRATION_CKW))._get_price_unit() == "CHF/kWh"


def test_price_unit_default_is_eur():
    assert _mgr(_controller(price_integration_type=PRICE_INTEGRATION_NORDPOOL))._get_price_unit() == "€/kWh"


# ----------------------------------------------------------------------
# is_in_dynamic_pricing_slot
# ----------------------------------------------------------------------

def test_in_slot_false_when_no_schedule():
    assert _mgr(_controller()).is_in_dynamic_pricing_slot() is False


def test_in_slot_true_when_now_inside_a_slot():
    now = datetime.now()
    slot = PriceSlot(start=now - timedelta(minutes=30), end=now + timedelta(minutes=30), price=0.1)
    ctrl = _controller(_dynamic_pricing_schedule=_schedule([slot]))
    assert _mgr(ctrl).is_in_dynamic_pricing_slot() is True


def test_in_slot_false_when_slot_in_the_past():
    now = datetime.now()
    slot = PriceSlot(start=now - timedelta(hours=2), end=now - timedelta(hours=1), price=0.1)
    ctrl = _controller(_dynamic_pricing_schedule=_schedule([slot]))
    assert _mgr(ctrl).is_in_dynamic_pricing_slot() is False


# ----------------------------------------------------------------------
# evaluation-time guards (deterministic "already done today" branch)
# ----------------------------------------------------------------------

def test_evening_reeval_false_when_already_done_today():
    ctrl = _controller(_dp_evening_reevaluated_date=datetime.now().date())
    assert _mgr(ctrl)._is_evening_reevaluation_time() is False


# ----------------------------------------------------------------------
# _project_remaining_consumption (evening recharge deficit, #409)
# ----------------------------------------------------------------------

def test_remaining_consumption_projects_todays_rate():
    # 18:00, 12 kWh used so far → 0.667 kWh/h × 6h left = 4.0 kWh.
    remaining, rate = PricingManager._project_remaining_consumption(18.0, 12.0, 20.0)
    assert round(rate, 3) == 0.667
    assert round(remaining, 2) == 4.0


def test_remaining_consumption_heavy_day_charges_more_than_light():
    # Same hour: a heavy day so far projects a larger remaining need than a
    # light day — the property "avg − consumed" got backwards.
    heavy, _ = PricingManager._project_remaining_consumption(18.0, 18.0, 17.0)
    light, _ = PricingManager._project_remaining_consumption(18.0, 6.0, 17.0)
    assert heavy > light


def test_remaining_consumption_cold_accumulator_uses_avg_rate():
    # consumed_today = 0 (e.g. just after restart) → fall back to avg/24 rate.
    remaining, rate = PricingManager._project_remaining_consumption(18.0, 0.0, 24.0)
    assert rate == 1.0                  # 24 kWh / 24 h
    assert round(remaining, 2) == 6.0   # 1.0 × 6 h


def test_remaining_consumption_zero_at_midnight():
    remaining, _ = PricingManager._project_remaining_consumption(24.0, 20.0, 20.0)
    assert remaining == 0.0


# ----------------------------------------------------------------------
# apply_price_discharge_block — early-return branches (no hass touched)
# ----------------------------------------------------------------------

def test_discharge_block_removed_when_mode_not_price():
    ctrl = _controller(predictive_charging_mode=PREDICTIVE_MODE_TIME_SLOT)
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]
    assert ctrl._set == []


def test_discharge_block_removed_when_dp_control_disabled():
    ctrl = _controller(
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        dp_price_discharge_control=False,
        price_sensor="sensor.price",
    )
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


def test_discharge_block_removed_when_dp_enabled_but_no_sensor():
    ctrl = _controller(
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        dp_price_discharge_control=True,
        price_sensor=None,
    )
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


def test_discharge_block_removed_when_rt_control_disabled():
    ctrl = _controller(
        predictive_charging_mode=PREDICTIVE_MODE_REALTIME_PRICE,
        rt_price_discharge_control=False,
        price_sensor="sensor.price",
    )
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


# ----------------------------------------------------------------------
# apply_price_discharge_block — separate discharge floor / idle band (#408)
# ----------------------------------------------------------------------

def _mgr_with_price(ctrl, price):
    """PricingManager whose price sensor reads ``price`` (Nordpool float path)."""
    state = SimpleNamespace(state=str(price), attributes={})
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: state))
    return PricingManager(hass, ctrl)


def _dp_band_controller(**overrides):
    base = dict(
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        dp_price_discharge_control=True,
        price_sensor="sensor.price",
        max_price_threshold=0.20,   # charge ceiling
        discharge_price_threshold=0.30,  # discharge floor
    )
    base.update(overrides)
    return _controller(**base)


def test_dp_discharge_floor_blocks_inside_idle_band():
    # price 0.25 sits in the idle band (ceiling 0.20 < 0.25 < floor 0.30):
    # discharge stays blocked. Single-threshold behavior would unblock at 0.21.
    ctrl = _dp_band_controller()
    _mgr_with_price(ctrl, 0.25).apply_price_discharge_block()
    assert ctrl._set and ctrl._set[0][0] == "price_discharge"
    assert ctrl._price_based_discharge_blocked is True


def test_dp_discharge_allowed_above_floor():
    ctrl = _dp_band_controller()
    _mgr_with_price(ctrl, 0.35).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]
    assert ctrl._price_based_discharge_blocked is False


def test_dp_discharge_floor_unset_falls_back_to_charge_ceiling():
    # Back-compat: no floor → reuse max_price_threshold (0.20) for both, so
    # price 0.25 > 0.20 unblocks discharge exactly as before #408.
    ctrl = _dp_band_controller(discharge_price_threshold=None)
    _mgr_with_price(ctrl, 0.25).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]
    assert ctrl._price_based_discharge_blocked is False
