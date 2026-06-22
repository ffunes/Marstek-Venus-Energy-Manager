"""Unit tests for the language-independent entity_id helper.

These pin the contract that ``entity_id`` slugs are built from the English
``key`` (not the localized display name), so new installs get consistent ids
regardless of the UI language. No hardware, no ``hass`` fixture.
"""
from __future__ import annotations

from custom_components.omnibattery.infra.entity_naming import (
    english_entity_id,
    system_entity_id,
    SYSTEM_OBJECT_ID_PREFIX,
    SYSTEM_UNIQUE_ID_PREFIX,
)


def test_per_battery_slug():
    assert (
        english_entity_id("sensor", "Marstek Venus 1", "ac_power")
        == "sensor.marstek_venus_1_ac_power"
    )


def test_system_slug():
    assert (
        english_entity_id("switch", "Marstek Venus System", "predictive_charging")
        == "switch.marstek_venus_system_predictive_charging"
    )


def test_indexed_key_keeps_index():
    assert (
        english_entity_id("switch", "Marstek Venus System", "time_slot_0_enabled")
        == "switch.marstek_venus_system_time_slot_0_enabled"
    )


def test_deterministic():
    # Same English key in -> same id out, independent of any UI language.
    assert english_entity_id("number", "Marstek Venus 2", "max_soc") == english_entity_id(
        "number", "Marstek Venus 2", "max_soc"
    )


# --- system entity_id (Omnibattery rebrand) -------------------------------
# System entities keep the legacy unique_id prefix (registry identity + history
# link) but suggest an omnibattery_system_* entity_id, so HA's built-in
# "Recreate entity IDs" renames marstek_venus_system_* -> omnibattery_system_*
# while existing installs keep their stored id until they opt in.


def test_system_entity_id_uses_omnibattery_prefix():
    assert (
        system_entity_id("sensor", "home_consumption")
        == "sensor.omnibattery_home_consumption"
    )


def test_system_entity_id_no_double_system_for_system_keys():
    # Keys that already start with "system_" must not produce
    # omnibattery_system_system_*; the prefix is just "omnibattery_".
    assert system_entity_id("sensor", "system_soc") == "sensor.omnibattery_system_soc"
    assert (
        system_entity_id("sensor", "system_battery_cell_power")
        == "sensor.omnibattery_system_battery_cell_power"
    )


def test_system_entity_id_keeps_indexed_suffix():
    assert (
        system_entity_id("switch", "time_slot_0_enabled")
        == "switch.omnibattery_time_slot_0_enabled"
    )


def test_system_entity_id_only_swaps_brand_prefix():
    # The object-id suffix must be identical to the legacy id; only the brand
    # prefix differs. Keeps the id HA's "Recreate entity IDs" produces
    # predictable (and matched against the dashboard by translation_key).
    for domain, key in [
        ("sensor", "home_consumption"),
        ("switch", "predictive_charging"),
        ("select", "pd_tuning_profile"),
        ("sensor", "net_balance"),
    ]:
        legacy = english_entity_id(domain, "Marstek Venus System", key)
        new = system_entity_id(domain, key)
        assert legacy.replace(SYSTEM_UNIQUE_ID_PREFIX, "") == new.replace(
            SYSTEM_OBJECT_ID_PREFIX, ""
        )


def test_system_prefixes_decoupled():
    # unique_id keeps the legacy brand (history link); the suggested object id is
    # rebranded. These must never be the same value.
    assert SYSTEM_UNIQUE_ID_PREFIX == "marstek_venus_system_"
    assert SYSTEM_OBJECT_ID_PREFIX == "omnibattery_"
    assert SYSTEM_UNIQUE_ID_PREFIX != SYSTEM_OBJECT_ID_PREFIX
