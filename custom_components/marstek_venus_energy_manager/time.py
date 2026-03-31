"""Time platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, CONF_PREDICTIVE_CHARGING_MODE, PREDICTIVE_MODE_AUTOMATION_SLOTS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the time platform."""
    if entry.data.get(CONF_PREDICTIVE_CHARGING_MODE) != PREDICTIVE_MODE_AUTOMATION_SLOTS:
        return

    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    if not controller:
        return

    async_add_entities([AutomationChargingEndTimeEntity(entry, controller)])


class AutomationChargingEndTimeEntity(TimeEntity, RestoreEntity):
    """Time entity representing the end time of the automation-driven charging slot.

    Automations (or the included blueprint) write to this entity via time.set_value
    to tell the integration when to stop the current charging slot.
    The value persists across HA restarts via RestoreEntity.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_translation_key = "automation_charging_end_time"
    _attr_icon = "mdi:clock-end"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller) -> None:
        """Initialize the end time entity."""
        self._entry = entry
        self._controller = controller
        self._value: dt_time | None = None
        self._attr_unique_id = f"{entry.entry_id}_automation_charging_end_time"

    async def async_added_to_hass(self) -> None:
        """Restore the last known end time when HA starts."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        try:
            self._value = dt_time.fromisoformat(last_state.state)
            self._controller.automation_slot_end_time = self._value
            _LOGGER.debug(
                "Restored automation charging end time: %s", self._value
            )
        except (ValueError, AttributeError):
            _LOGGER.debug(
                "Could not restore automation charging end time from state: %s",
                last_state.state,
            )

    @property
    def native_value(self) -> dt_time | None:
        """Return the current end time."""
        return self._value

    async def async_set_value(self, value: dt_time) -> None:
        """Set a new end time and update the controller."""
        self._value = value
        self._controller.automation_slot_end_time = value
        _LOGGER.debug("Automation charging end time set to: %s", value)
        self.async_write_ha_state()

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }
