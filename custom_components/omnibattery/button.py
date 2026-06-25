"""Button platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PREDICTIVE_MODE_DYNAMIC_PRICING
from .infra.coordinator import MarstekVenusDataUpdateCoordinator
from .infra.entity_naming import english_entity_id, system_entity_id, SYSTEM_UNIQUE_ID_PREFIX

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

    # System-level button: re-run the dynamic-pricing predictive evaluation on demand.
    if (
        controller
        and controller.predictive_charging_enabled
        and controller.predictive_charging_mode == PREDICTIVE_MODE_DYNAMIC_PRICING
    ):
        entities.append(ReevaluateDynamicPricingButton(controller))

    async_add_entities(entities)


class MarstekVenusButton(ButtonEntity):
    """Representation of a Marstek Venus button."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the button."""
        self.coordinator = coordinator

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self.entity_id = english_entity_id("button", coordinator.name, definition["key"])
        self._attr_icon = definition.get("icon")
        self._attr_device_class = definition.get("device_class")
        self._attr_entity_registry_enabled_default = definition.get("enabled_by_default", True)
        self._attr_should_poll = False
        self._key = definition["key"]
        self._command = definition["command"]

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.write_control(self._key, self._command, do_refresh=True)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class ReevaluateDynamicPricingButton(ButtonEntity):
    """System button to re-run the dynamic-pricing predictive charge evaluation on demand."""

    def __init__(self, controller) -> None:
        """Initialize the re-evaluation button."""
        self.controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "reevaluate_dynamic_pricing"
        self._attr_unique_id = f"{SYSTEM_UNIQUE_ID_PREFIX}reevaluate_dynamic_pricing"
        self.entity_id = system_entity_id("button", "reevaluate_dynamic_pricing")
        self._attr_icon = "mdi:calendar-refresh"
        self._attr_should_poll = False

    async def async_press(self) -> None:
        """Rebuild today's dynamic-pricing schedule now (same path as the 00:05 daily run)."""
        # extended_horizon: pressed mid-day, so look past the already-elapsed slots,
        # matching the startup catch-up evaluation.
        await self.controller._pricing_mgr._evaluate_dynamic_pricing(extended_horizon=True)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Omnibattery System",
            "manufacturer": "Omnibattery",
            "model": "Multi-Battery System",
        }


