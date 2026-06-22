"""Tests for the v8 -> v9 entity-registry heal (``async_migrate_entry``).

System-level entities used to key their ``unique_id`` on the config ``entry_id``.
The Omnibattery domain migration creates a NEW entry, so those ids changed and HA
registered duplicates: the old entity became an orphan (stale entry_id prefix, no
device) while the new one was bumped to a ``_2`` entity_id. v9 re-keys them onto
the stable ``marstek_venus_system_`` prefix and removes the orphans.

Needs the real ``hass`` / entity-registry, so it runs only without the suite's
``-p no:homeassistant`` flag (conftest skips it otherwise), e.g.::

    .venv-test/Scripts/python -m pytest tests/test_system_uid_migration.py -o addopts=""
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.omnibattery import async_migrate_entry

DOMAIN = "omnibattery"
# 26-char [A-Z] ULID stand-in for the pre-rebrand (old) config entry_id.
OLD_ULID = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# 32-char lowercase hex (uuid4().hex) — entry_id format of older HA installs.
OLD_HEX = "0123456789abcdef0123456789abcdef"


async def test_v9_heals_system_entity_duplicates(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=8, data={"batteries": []})
    entry.add_to_hass(hass)

    reg = er.async_get(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "marstek_venus_system")},
    )

    # (a) already-migrated duplicate: live `_2` (current entry_id uid, device-bound)
    #     + orphan (old entry_id uid, no device) sitting at the clean entity_id.
    live = reg.async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_manual_mode",
        suggested_object_id="marstek_venus_system_manual_mode_2",
        config_entry=entry, device_id=dev.id,
    )
    reg.async_get_or_create(
        "switch", DOMAIN, f"{OLD_ULID}_manual_mode",
        suggested_object_id="marstek_venus_system_manual_mode",
        config_entry=entry,
    )
    # (b) fresh-migrant: single moved entity, old uid, device-bound, already clean id.
    #     ULID-prefixed (current HA) ...
    reg.async_get_or_create(
        "switch", DOMAIN, f"{OLD_ULID}_charge_delay",
        suggested_object_id="marstek_venus_system_charge_delay",
        config_entry=entry, device_id=dev.id,
    )
    #     ... and 32-hex-prefixed (older 2.0.x install migrating to 3.0.0).
    reg.async_get_or_create(
        "select", DOMAIN, f"{OLD_HEX}_pd_tuning_profile",
        suggested_object_id="marstek_venus_system_pd_tuning_profile",
        config_entry=entry, device_id=dev.id,
    )
    # untouched: aggregate (stable prefix already) + per-battery (host-keyed uid).
    agg = reg.async_get_or_create(
        "sensor", DOMAIN, "marstek_venus_system_soc",
        suggested_object_id="marstek_venus_system_soc",
        config_entry=entry, device_id=dev.id,
    )
    perbat = reg.async_get_or_create(
        "sensor", DOMAIN, "1.2.3.4_502_ac_power",
        suggested_object_id="marstek_venus_1_ac_power",
        config_entry=entry,
    )

    assert live.entity_id == "switch.marstek_venus_system_manual_mode_2"

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 9

    # orphan removed; live re-keyed to the stable uid AND reclaimed the clean id.
    assert reg.async_get_entity_id("switch", DOMAIN, f"{OLD_ULID}_manual_mode") is None
    assert reg.async_get("switch.marstek_venus_system_manual_mode_2") is None
    healed = reg.async_get("switch.marstek_venus_system_manual_mode")
    assert healed is not None
    assert healed.unique_id == "marstek_venus_system_manual_mode"

    # fresh-migrant re-keyed; its (already clean) entity_id is unchanged.
    fresh = reg.async_get("switch.marstek_venus_system_charge_delay")
    assert fresh is not None
    assert fresh.unique_id == "marstek_venus_system_charge_delay"
    assert reg.async_get_entity_id("switch", DOMAIN, f"{OLD_ULID}_charge_delay") is None

    # fresh-migrant with a 32-hex (old-HA) entry_id prefix is healed the same way.
    prof = reg.async_get("select.marstek_venus_system_pd_tuning_profile")
    assert prof is not None
    assert prof.unique_id == "marstek_venus_system_pd_tuning_profile"
    assert reg.async_get_entity_id("select", DOMAIN, f"{OLD_HEX}_pd_tuning_profile") is None

    # untouched entities keep their unique_id.
    assert reg.async_get(agg.entity_id).unique_id == "marstek_venus_system_soc"
    assert reg.async_get(perbat.entity_id).unique_id == "1.2.3.4_502_ac_power"
