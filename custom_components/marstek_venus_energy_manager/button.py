"""Button platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, BUTTON_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []

    # Add regular battery buttons
    for coordinator in coordinators:
        for definition in BUTTON_DEFINITIONS:
            entities.append(MarstekVenusButton(coordinator, definition))

    async_add_entities(entities)


class MarstekVenusButton(ButtonEntity):
    """Representation of a Marstek Venus button."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the button."""
        self.coordinator = coordinator
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_icon = definition.get("icon")
        self._attr_device_class = definition.get("device_class")
        self._attr_should_poll = False
        self._register = definition["register"]
        self._command = definition["command"]

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.write_register(self._register, self._command, do_refresh=True)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }
