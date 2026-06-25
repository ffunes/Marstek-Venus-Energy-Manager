"""Validation tests for the live price-threshold number entities (#408).

Cover the ordering guard in ``MarstekPriceThresholdNumber.async_set_native_value``
(charge ceiling must stay <= discharge floor). Only the *rejecting* paths are
exercised: a valid write reaches ``async_write_ha_state``, which needs the entity
added to a running hass. No HA runtime is required to prove the guard fires.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.omnibattery.number import MarstekPriceThresholdNumber


def _entity(kind, data):
    return MarstekPriceThresholdNumber(SimpleNamespace(), SimpleNamespace(data=data), kind)


def test_discharge_floor_below_charge_ceiling_rejected():
    e = _entity("discharge", {"max_price_threshold": 0.20})
    with pytest.raises(ServiceValidationError):
        asyncio.run(e.async_set_native_value(0.10))


def test_charge_ceiling_above_discharge_floor_rejected():
    e = _entity("charge", {"discharge_price_threshold": 0.30})
    with pytest.raises(ServiceValidationError):
        asyncio.run(e.async_set_native_value(0.40))


def test_no_sibling_threshold_skips_validation():
    # Sibling unset → guard must not trip (it would raise before touching hass,
    # which is a bare SimpleNamespace here). A write attempt that gets past the
    # guard fails on async_update_entry, not on validation.
    e = _entity("discharge", {})  # no max_price_threshold
    with pytest.raises(AttributeError):  # hits hass.config_entries.* , not the guard
        asyncio.run(e.async_set_native_value(0.10))
