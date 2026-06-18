"""Integration tests for the seamless domain-migration helper.

These mount a fake *old* domain integration with two entities and a user
customization, run ``async_migrate_legacy_domain_entries``, and assert the
migration is seamless: identical ``entity_id`` / ``unique_id``, no ``_2``
suffixes, user customizations preserved, old entry gone, new entry LOADED.

Requires the in-process ``hass`` fixture, so the HA test plugin must be active:
run WITHOUT the suite's default ``-p no:homeassistant`` flag, e.g.::

    .venv-test/Scripts/python -m pytest tests/test_domain_migration.py -o addopts=""

The repo's ``tests/conftest.py`` lifts the socket guard at ``pytest_configure``
so the asyncio self-pipe can be built on a Windows dev box too.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigFlow
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntity,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.marstek_venus_energy_manager.domain_migration import (
    async_migrate_legacy_domain_entries,
)
from custom_components.marstek_venus_energy_manager.migration_flow import (
    LegacyDomainMigrationMixin,
    async_has_legacy_entries,
)

OLD_DOMAIN = "marstek_venus_energy_manager"
NEW_DOMAIN = "omnibattery"

# Hardcoded unique ids + display names that survive the rebrand unchanged. The
# entity_id slug HA derives from each name is what the recorder indexes by.
ENTITIES = [
    ("marstek_venus_system_solar_power", "Marstek Venus System Solar Power"),
    ("marstek_venus_system_battery_power", "Marstek Venus System Battery Power"),
]

ENTRY_DATA = {"host": "1.2.3.4", "port": 502, "battery_version": "v2"}
ENTRY_OPTIONS = {"pd_controller_kp": 0.35}
ENTRY_UNIQUE_ID = "1.2.3.4_502"


class _MockFlow(ConfigFlow):
    """Minimal flow handler so config-entry setup/migrate checks pass.

    VERSION/MINOR_VERSION match the MockConfigEntry defaults (1/1) so
    ``ConfigEntry.async_migrate`` short-circuits to True (no migration needed).
    """

    VERSION = 1
    MINOR_VERSION = 1


@pytest.fixture
def _flow_handlers():
    """Register the flow handler for both domains for the whole test."""
    with mock_config_flow(OLD_DOMAIN, _MockFlow), mock_config_flow(
        NEW_DOMAIN, _MockFlow
    ):
        yield


async def _platform_setup_entry(hass, entry, async_add_entities):
    """Sensor platform that adds the same entities for whichever domain owns it."""
    async_add_entities(
        MockEntity(unique_id=uid, name=name) for uid, name in ENTITIES
    )


def _register_domain(hass: HomeAssistant, domain: str) -> None:
    """Register a fake integration + sensor platform under ``domain``."""

    async def async_setup_entry(hass, entry):
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
        return True

    async def async_unload_entry(hass, entry):
        return await hass.config_entries.async_unload_platforms(
            entry, [Platform.SENSOR]
        )

    mock_integration(
        hass,
        MockModule(
            domain,
            async_setup_entry=async_setup_entry,
            async_unload_entry=async_unload_entry,
        ),
    )
    mock_platform(
        hass,
        f"{domain}.sensor",
        MockPlatform(async_setup_entry=_platform_setup_entry),
    )
    # Config-entry setup imports the config_flow platform (version/migrate check).
    mock_platform(hass, f"{domain}.config_flow", Mock())


async def _setup_old_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Mount the old-domain entry with its two entities live."""
    _register_domain(hass, OLD_DOMAIN)
    _register_domain(hass, NEW_DOMAIN)

    old_entry = MockConfigEntry(
        domain=OLD_DOMAIN,
        title="Marstek Venus",
        unique_id=ENTRY_UNIQUE_ID,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )
    old_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(old_entry.entry_id)
    await hass.async_block_till_done()
    return old_entry


async def test_migration_is_seamless(hass: HomeAssistant, _flow_handlers) -> None:
    """Full recipe: migrate old -> new with zero entity_id/unique_id drift."""
    old_entry = await _setup_old_entry(hass)
    registry = er.async_get(hass)

    reg_entries = er.async_entries_for_config_entry(registry, old_entry.entry_id)
    assert len(reg_entries) == 2

    # --- user customization BEFORE migration: rename one entity_id + assign area.
    area = ar.async_get(hass).async_get_or_create("Living Room")
    target = reg_entries[0]
    registry.async_update_entity(
        target.entity_id,
        new_entity_id="sensor.my_renamed_solar",
        name="My Renamed Solar",
    )
    registry.async_update_entity("sensor.my_renamed_solar", area_id=area.id)
    await hass.async_block_till_done()

    # Snapshot unique_id -> entity_id (post-rename) to prove invariance later.
    pre = er.async_entries_for_config_entry(registry, old_entry.entry_id)
    pre_map = {e.unique_id: e.entity_id for e in pre}
    assert "sensor.my_renamed_solar" in pre_map.values()

    # --- run the migration.
    migrated = await async_migrate_legacy_domain_entries(hass, OLD_DOMAIN, NEW_DOMAIN)
    await hass.async_block_till_done()

    assert len(migrated) == 1
    old_id, new_id = migrated[0]
    assert old_id == old_entry.entry_id

    # --- config entry side: old gone, new present + LOADED, data preserved.
    assert hass.config_entries.async_entries(OLD_DOMAIN) == []
    new_entries = hass.config_entries.async_entries(NEW_DOMAIN)
    assert len(new_entries) == 1
    new_entry = new_entries[0]
    assert new_entry.entry_id == new_id
    assert new_entry.state is ConfigEntryState.LOADED
    assert new_entry.unique_id == ENTRY_UNIQUE_ID
    assert dict(new_entry.data) == ENTRY_DATA
    assert dict(new_entry.options) == ENTRY_OPTIONS

    # --- registry side: same entity_ids + unique_ids, repointed to new platform.
    post = er.async_entries_for_config_entry(registry, new_entry.entry_id)
    post_map = {e.unique_id: e.entity_id for e in post}

    # entity_id identical per unique_id (covers "no _2 suffix").
    assert post_map == pre_map
    assert not any(e.entity_id.endswith("_2") for e in post)
    for e in post:
        assert e.platform == NEW_DOMAIN
        assert e.config_entry_id == new_entry.entry_id

    # --- user customizations survived the migration.
    custom = registry.async_get("sensor.my_renamed_solar")
    assert custom is not None
    assert custom.name == "My Renamed Solar"
    assert custom.area_id == area.id
    # statistic_id == entity_id, and entity_id is unchanged above, so long-term
    # statistics_meta stays attached without simulating the recorder here.


async def test_restored_unavailable_state_blocks_raw_migration(
    hass: HomeAssistant, _flow_handlers
) -> None:
    """Documents the obstacle the helper's state-removal step exists to clear.

    Unloading a config entry (or losing the integration after the rename) does
    not remove the registered entities' states — the entity registry writes a
    restored ``unavailable`` placeholder. ``async_update_entity_platform`` only
    migrates entities with no live state (``None``/``unknown``), so that
    placeholder blocks a naive migration until it is removed.
    """
    old_entry = await _setup_old_entry(hass)
    registry = er.async_get(hass)
    entity_id = er.async_entries_for_config_entry(registry, old_entry.entry_id)[
        0
    ].entity_id

    await hass.config_entries.async_unload(old_entry.entry_id)
    state = hass.states.get(entity_id)
    assert state is not None and state.state == STATE_UNAVAILABLE

    with pytest.raises(ValueError, match="haven't been loaded"):
        registry.async_update_entity_platform(
            entity_id, NEW_DOMAIN, new_config_entry_id="dummy"
        )

    # Removing the placeholder (what the helper does) clears the obstacle.
    hass.states.async_remove(entity_id)
    assert hass.states.get(entity_id) is None


class _SpikeMigrationFlow(LegacyDomainMigrationMixin, ConfigFlow):
    """Stand-in for the real new-domain flow: route to migration when legacy."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if async_has_legacy_entries(self.hass):
            return await self.async_step_migrate_legacy()
        return self.async_abort(reason="no_legacy_entries")


async def test_config_flow_triggers_migration(hass: HomeAssistant) -> None:
    """The trigger: 'Add integration' on the new domain migrates legacy entries.

    This is the only entry point HA always exposes when the new domain has no
    config entries yet (the deadlock that blocks a passive async_setup migration
    after a HACS rename).
    """
    with mock_config_flow(OLD_DOMAIN, _MockFlow), mock_config_flow(
        NEW_DOMAIN, _SpikeMigrationFlow
    ):
        old_entry = await _setup_old_entry(hass)
        registry = er.async_get(hass)
        pre_map = {
            e.unique_id: e.entity_id
            for e in er.async_entries_for_config_entry(registry, old_entry.entry_id)
        }

        # Start "Add Omnibattery" -> detects legacy entries -> confirm form.
        result = await hass.config_entries.flow.async_init(
            NEW_DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "migrate_legacy"
        assert result["description_placeholders"]["count"] == "1"

        # Confirm -> runs the helper -> aborts with success (no entry created here).
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "migration_successful"
        await hass.async_block_till_done()

        # Same seamless outcome as the direct-helper test, via the flow trigger.
        assert hass.config_entries.async_entries(OLD_DOMAIN) == []
        new_entries = hass.config_entries.async_entries(NEW_DOMAIN)
        assert len(new_entries) == 1
        assert new_entries[0].state is ConfigEntryState.LOADED
        post = er.async_entries_for_config_entry(registry, new_entries[0].entry_id)
        assert {e.unique_id: e.entity_id for e in post} == pre_map
        assert all(e.platform == NEW_DOMAIN for e in post)
