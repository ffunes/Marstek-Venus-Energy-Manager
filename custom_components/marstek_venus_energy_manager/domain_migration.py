"""Seamless migration of config + entity registry between integration domains.

Spike artifact: this is the orchestration that the *new* domain's ``async_setup``
will run once, on first start after the rebrand, to move every config entry and
its entity registry entries from the old domain to the new one **without**
changing any ``entity_id`` or ``unique_id``. Keeping those identical is what
preserves recorder history and long-term statistics (both keyed by ``entity_id``
/ ``statistic_id``), and avoids the ``_2`` suffixes HA would otherwise mint if a
fresh entry re-registered the same unique ids under a new platform.

It is deliberately standalone (not yet wired into ``async_setup``) so it can be
unit-tested in isolation before the rename is committed.

Recipe, per old config entry:
  1. If LOADED, unload it. ``async_update_entity_platform`` refuses to migrate an
     entity that still has a live state, so the entities must be torn down first.
  2. Create a mirror ``ConfigEntry`` on the new domain (same data/options/
     unique_id/source/version) but ``disabled_by`` set, and ``async_add`` it.
     ``async_add`` always calls setup, but a disabled entry returns early and
     loads no platforms — so the new entry exists without grabbing the entities.
  3. Re-point every registry entry of the old entry to the new platform +
     new config entry id, leaving ``entity_id`` and ``unique_id`` untouched.
     This must happen *before* removing the old entry: ``async_remove`` clears
     the registry entries still linked to it.
  4. Remove the old config entry.
  5. Clear ``disabled_by`` on the new entry. That reloads it, and now its
     platforms set up: ``async_get_or_create(new_domain, unique_id)`` re-finds
     the migrated registry entries and reuses their ``entity_id`` verbatim.
"""
from __future__ import annotations

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryDisabler,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def async_migrate_legacy_domain_entries(
    hass: HomeAssistant,
    old_domain: str,
    new_domain: str,
) -> list[tuple[str, str]]:
    """Migrate all config entries from ``old_domain`` to ``new_domain``.

    Returns a list of ``(old_entry_id, new_entry_id)`` pairs for the entries
    that were migrated (empty if there was nothing to do).
    """
    registry = er.async_get(hass)
    migrated: list[tuple[str, str]] = []

    for old in list(hass.config_entries.async_entries(old_domain)):
        # 1. Tear down live entities so the registry entries can be migrated.
        if old.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(old.entry_id)

        # 2. Mirror the entry on the new domain, disabled so it doesn't load yet.
        new_entry = ConfigEntry(
            version=old.version,
            minor_version=old.minor_version,
            domain=new_domain,
            title=old.title,
            data=dict(old.data),
            options=dict(old.options),
            source=old.source,
            unique_id=old.unique_id,
            disabled_by=ConfigEntryDisabler.USER,
            discovery_keys=old.discovery_keys,
        )
        await hass.config_entries.async_add(new_entry)

        # 3. Re-point the registry entries (entity_id + unique_id unchanged).
        for entry in er.async_entries_for_config_entry(registry, old.entry_id):
            # A registered entity whose config entry is unloaded — or whose
            # integration is gone after the rename — gets a restored
            # ``unavailable`` placeholder state from the entity registry.
            # ``async_update_entity_platform`` only migrates entities with no
            # live state (``None`` or ``unknown``), so drop the placeholder
            # first; the new entry recreates a fresh state when it loads.
            if hass.states.get(entry.entity_id) is not None:
                hass.states.async_remove(entry.entity_id)
            registry.async_update_entity_platform(
                entry.entity_id,
                new_domain,
                new_config_entry_id=new_entry.entry_id,
            )

        # 4. Drop the old entry (its registry links are already gone).
        await hass.config_entries.async_remove(old.entry_id)

        # 5. Enable the new entry -> it loads and re-adopts the migrated entities.
        await hass.config_entries.async_set_disabled_by(new_entry.entry_id, None)

        migrated.append((old.entry_id, new_entry.entry_id))

    return migrated
