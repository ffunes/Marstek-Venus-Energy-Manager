"""Button platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MarstekVenusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    entities = []

    # Add regular battery buttons
    for coordinator in coordinators:
        for definition in coordinator.button_definitions:
            entities.append(MarstekVenusButton(coordinator, definition))

    # Add force full charge button (when weekly charge is enabled)
    if controller and controller.weekly_full_charge_enabled:
        entities.append(ForceFullChargeButton(hass, entry, controller))

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


class ForceFullChargeButton(ButtonEntity):
    """Button to force an immediate 100% charge on any day."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the force full charge button."""
        self.hass = hass
        self.entry = entry
        self._controller = controller

        self._attr_name = "Force Full Charge"
        self._attr_unique_id = f"{entry.entry_id}_force_full_charge"
        self._attr_icon = "mdi:battery-arrow-up"
        self._attr_should_poll = False

    async def async_press(self) -> None:
        """Trigger an immediate full charge to 100%."""
        self._controller._force_full_charge = True
        self._controller._weekly_delay_unlocked = True
        self._controller.weekly_full_charge_registers_written = False
        self._controller.weekly_full_charge_complete = False
        self._controller._weekly_charge_status["state"] = "Charging to 100%"
        self._controller._weekly_charge_status["unlock_reason"] = "manual"
        _LOGGER.info("Force Full Charge: Manual 100%% charge triggered via button")

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }
