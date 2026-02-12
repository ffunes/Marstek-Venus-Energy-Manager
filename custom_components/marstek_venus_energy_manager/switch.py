"""Switch platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SWITCH_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    entities = []

    # Add regular battery switches
    for coordinator in coordinators:
        for definition in SWITCH_DEFINITIONS:
            entities.append(MarstekVenusSwitch(coordinator, definition))

    # Add manual mode switch (system-level, always present)
    if controller:
        entities.append(ManualModeSwitch(hass, entry, controller))

    # Add predictive charging override switch (system-level, not per-battery)
    if controller and controller.predictive_charging_enabled:
        entities.append(PredictiveChargingOverrideSwitch(hass, entry, controller))

    async_add_entities(entities)


class MarstekVenusSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Marstek Venus switch."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = False
        self._command_on = definition["command_on"]
        self._command_off = definition["command_off"]
        self._register = definition["register"]

    @property
    def is_on(self):
        """Return the state of the switch."""
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.definition["key"])
        if value is None:
            return None
        # Check if the value matches command_on (switch is on)
        return value == self._command_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        await self.coordinator.write_register(self._register, self._command_on, do_refresh=True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        await self.coordinator.write_register(self._register, self._command_off, do_refresh=True)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class PredictiveChargingOverrideSwitch(SwitchEntity):
    """Switch to override predictive grid charging for the current slot."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the override switch."""
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_name = "Override Predictive Charging"
        self._attr_unique_id = f"{entry.entry_id}_override_predictive_charging"
        self._attr_icon = "mdi:cancel"
        self._attr_should_poll = False
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        """Return True if override is active."""
        return self.controller.predictive_charging_overridden

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the override to interrupt predictive charging."""
        if self.controller.grid_charging_active:
            self.controller.predictive_charging_overridden = True
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Predictive Charging Override Active",
                    "message": "Predictive grid charging has been manually overridden. Turn off the switch to resume charging.",
                    "notification_id": "predictive_charging_override",
                },
            )
        else:
            self.controller.predictive_charging_overridden = True
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Override Switch Enabled",
                    "message": "Predictive charging override is now enabled. It will block charging when the time slot becomes active.",
                    "notification_id": "predictive_charging_override",
                },
            )
        # Trigger state update
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the override to resume predictive charging."""
        self.controller.predictive_charging_overridden = False
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": "predictive_charging_override"},
        )
        # Trigger state update
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


class ManualModeSwitch(SwitchEntity):
    """Switch to enable manual control mode and pause automatic charge/discharge control."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the manual mode switch."""
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_name = "Manual Mode"
        self._attr_unique_id = f"{entry.entry_id}_manual_mode"
        self._attr_icon = "mdi:hand-back-right"
        self._attr_should_poll = False
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        """Return True if manual mode is active."""
        return self.controller.manual_mode_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable manual mode to pause automatic control."""
        self.controller.manual_mode_enabled = True
        _LOGGER.info("Manual Mode ENABLED - automatic control paused")

        # Set all batteries to 0W (idle state) when entering manual mode
        for coordinator in self.controller.coordinators:
            try:
                # Set charge power to 0
                await coordinator.write_register(42020, 0, do_refresh=False)
                # Set discharge power to 0
                await coordinator.write_register(42021, 0, do_refresh=False)
                # Set force mode to None (0)
                await coordinator.write_register(42010, 0, do_refresh=True)
                _LOGGER.info(f"Set {coordinator.name} to 0W (idle) for manual mode")
            except Exception as e:
                _LOGGER.error(f"Failed to set {coordinator.name} to 0W: {e}")

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Manual Mode Active",
                "message": (
                    "Automatic charge/discharge control is paused. "
                    "All batteries have been set to idle (0W). "
                    "You can now manually control each battery using the "
                    "'Set Forcible Charge/Discharge Power' controls.\n\n"
                    "Turn off Manual Mode to resume automatic control."
                ),
                "notification_id": "manual_mode_active",
            },
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable manual mode to resume automatic control."""
        self.controller.manual_mode_enabled = False

        # Reset PD controller state for clean transition
        self.controller.error_integral = 0.0
        self.controller.previous_error = 0.0
        self.controller.sign_changes = 0

        _LOGGER.info("Manual Mode DISABLED - resuming automatic control")

        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": "manual_mode_active"},
        )
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
