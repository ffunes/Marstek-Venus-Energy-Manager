"""Select platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SELECT_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    for coordinator in coordinators:
        for definition in SELECT_DEFINITIONS:
            entities.append(MarstekVenusSelect(coordinator, definition))
    async_add_entities(entities)


class MarstekVenusSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Marstek Venus select."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
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
