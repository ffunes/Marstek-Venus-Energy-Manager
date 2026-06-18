"""Config-flow trigger for the legacy-domain migration.

Spike artifact (not wired into production yet).

Why a config flow: after a HACS domain rename, the new domain starts with zero
config entries, so its ``async_setup`` never runs and a passive migration can
never fire. The one entry point HA always exposes regardless of existing entries
is the **config flow** ("Settings → Devices & Services → Add Integration"). So
that is where the rename migration is kicked off: if entries from the legacy
domain are still present in ``.storage`` (HACS only deletes files under
``custom_components/``, never the registries), the flow offers to migrate them.

The heavy lifting — recreating the entries under the new domain and repointing
the entity registry while keeping ``entity_id`` / ``unique_id`` — is the shared
helper in :mod:`.domain_migration`. This module is only the trigger + a small
confirm step. The real new-domain ``ConfigFlow`` will mix
:class:`LegacyDomainMigrationMixin` in and route to it from ``async_step_user``.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .domain_migration import async_migrate_legacy_domain_entries

LEGACY_DOMAIN = "marstek_venus_energy_manager"


def async_has_legacy_entries(
    hass: HomeAssistant, legacy_domain: str = LEGACY_DOMAIN
) -> bool:
    """Return True if any config entry of the legacy domain still exists."""
    return bool(hass.config_entries.async_entries(legacy_domain))


class LegacyDomainMigrationMixin:
    """Adds a ``migrate_legacy`` step to the new domain's ConfigFlow.

    ``async_step_user`` of the real flow should route here when
    :func:`async_has_legacy_entries` is True, e.g.::

        if async_has_legacy_entries(self.hass):
            return await self.async_step_migrate_legacy()
    """

    # Mixed into a ConfigFlow, so these are provided at runtime by FlowHandler.
    hass: HomeAssistant
    handler: str

    _legacy_domain: str = LEGACY_DOMAIN

    async def async_step_migrate_legacy(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm + run the legacy-domain migration, then abort the flow.

        The migration creates the new entries itself (via the helper), so this
        flow does not call ``async_create_entry``; it aborts with a success
        reason once the work is done.
        """
        entries = self.hass.config_entries.async_entries(self._legacy_domain)
        if not entries:
            return self.async_abort(reason="no_legacy_entries")

        if user_input is None:
            return self.async_show_form(
                step_id="migrate_legacy",
                data_schema=vol.Schema({}),
                description_placeholders={"count": str(len(entries))},
            )

        migrated = await async_migrate_legacy_domain_entries(
            self.hass, self._legacy_domain, self.handler
        )
        return self.async_abort(
            reason="migration_successful",
            description_placeholders={"count": str(len(migrated))},
        )
