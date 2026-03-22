"""Select platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
)
from .coordinator import MarstekVenusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []

    # Add Modbus register selects (per battery)
    for coordinator in coordinators:
        for definition in coordinator.select_definitions:
            entities.append(MarstekVenusSelect(coordinator, definition))

    # Add weekly full charge day select (system-level)
    if entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False):
        entities.append(WeeklyFullChargeDaySelect(hass, entry))

    async_add_entities(entities)


class MarstekVenusSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Marstek Venus select."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_options = list(definition["options"].keys())
        self._attr_should_poll = False
        self._options_map = definition["options"]
        self._register = definition["register"]

    @property
    def current_option(self):
        """Return the current option."""
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.definition["key"])
        for option, val in self._options_map.items():
            if val == value:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        value = self._options_map[option]
        await self.coordinator.write_register(self._register, value, do_refresh=True)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


WEEKDAY_OPTIONS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Map full names to internal short codes used in config_entry.data and WEEKDAY_MAP
WEEKDAY_TO_CODE = {
    "Monday": "mon", "Tuesday": "tue", "Wednesday": "wed", "Thursday": "thu",
    "Friday": "fri", "Saturday": "sat", "Sunday": "sun",
}
CODE_TO_WEEKDAY = {v: k for k, v in WEEKDAY_TO_CODE.items()}


class WeeklyFullChargeDaySelect(SelectEntity):
    """Select entity to choose the day for weekly full charge."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the weekly full charge day select."""
        self.hass = hass
        self.entry = entry

        self._attr_has_entity_name = True
        self._attr_translation_key = "weekly_full_charge_day"
        self._attr_unique_id = f"{entry.entry_id}_weekly_full_charge_day"
        self._attr_icon = "mdi:calendar-week"
        self._attr_options = WEEKDAY_OPTIONS
        self._attr_should_poll = False

    @property
    def current_option(self) -> str:
        """Return the currently selected day as full name."""
        code = self.entry.data.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")
        return CODE_TO_WEEKDAY.get(code, "Sunday")

    async def async_select_option(self, option: str) -> None:
        """Update the selected day in config_entry.data."""
        code = WEEKDAY_TO_CODE.get(option, option)
        new_data = dict(self.entry.data)
        new_data[CONF_WEEKLY_FULL_CHARGE_DAY] = code
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Weekly full charge day updated to %s (%s)", option, code)
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
