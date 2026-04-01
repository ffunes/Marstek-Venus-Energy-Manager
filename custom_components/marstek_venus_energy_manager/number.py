"""Number platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONFIG_NUMBER_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []

    # Add Modbus register numbers (per battery)
    for coordinator in coordinators:
        for definition in coordinator.number_definitions:
            entities.append(MarstekVenusNumber(coordinator, definition))

    # Add config numbers (system-level, PD parameters)
    for definition in CONFIG_NUMBER_DEFINITIONS:
        # Skip conditional entities if their feature has never been configured
        condition = definition.get("condition")
        if condition and condition not in entry.data:
            continue
        entities.append(MarstekConfigNumberEntity(hass, entry, definition))

    async_add_entities(entities)


class MarstekVenusNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Marstek Venus number."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_icon = definition.get("icon")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_native_min_value = definition["min"]
        self._attr_native_max_value = definition["max"]
        self._attr_native_step = definition["step"]
        self._attr_should_poll = False
        self._register = definition["register"]
        self._scale = definition.get("scale", 1.0)  # Scale factor for register conversion

    @property
    def native_value(self):
        """Return the state of the number."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.definition["key"])

    async def async_set_native_value(self, value: float) -> None:
        """Set the value of the number."""
        from logging import getLogger
        _LOGGER = getLogger(__name__)
        
        # Convert value using scale factor if needed
        # For example: 95% with scale=0.1 -> write 950 to register
        register_value = int(value / self._scale)
        
        # Log the conversion for debugging
        if self._scale != 1.0:
            _LOGGER.info("Converting %s: %.1f%s -> register value %d (scale=%.1f)",
                        self.definition['name'], value, self._attr_native_unit_of_measurement or '', 
                        register_value, self._scale)
        
        # Write the converted value to register
        await self.coordinator.write_register(self._register, register_value, do_refresh=True)
        
        # Update coordinator attributes immediately for control loop
        # This ensures changes take effect immediately without waiting for scan_interval
        if self.definition['key'] == 'charging_cutoff_capacity':
            old_max_soc = self.coordinator.max_soc
            self.coordinator.max_soc = value
            self.coordinator.persist_battery_config("max_soc", int(value))

            # RESET HYSTERESIS when max_soc changes
            if self.coordinator.enable_charge_hysteresis:
                # If increasing max_soc and battery is below new limit, clear hysteresis
                current_soc = self.coordinator.data.get("battery_soc", 0) if self.coordinator.data else 0
                if value > old_max_soc and current_soc < value:
                    self.coordinator._hysteresis_active = False
                    _LOGGER.info("%s: Hysteresis reset (max_soc %.1f%% → %.1f%%, SOC=%.1f%%)",
                                self.coordinator.name, old_max_soc, value, current_soc)

            _LOGGER.info("%s: Updated max_soc %.1f%% → %.1f%% (immediate sync)",
                         self.coordinator.name, old_max_soc, value)

        elif self.definition['key'] == 'discharging_cutoff_capacity':
            old_min_soc = self.coordinator.min_soc
            self.coordinator.min_soc = value
            self.coordinator.persist_battery_config("min_soc", int(value))
            _LOGGER.info("%s: Updated min_soc %.1f%% → %.1f%% (immediate sync)",
                         self.coordinator.name, old_min_soc, value)

        elif self.definition['key'] == 'max_charge_power':
            old_value = self.coordinator.max_charge_power
            self.coordinator.max_charge_power = int(value)
            self.coordinator.persist_battery_config("max_charge_power", int(value))
            _LOGGER.info("%s: Updated max_charge_power %dW → %dW (immediate sync)",
                         self.coordinator.name, old_value, int(value))

        elif self.definition['key'] == 'max_discharge_power':
            old_value = self.coordinator.max_discharge_power
            self.coordinator.max_discharge_power = int(value)
            self.coordinator.persist_battery_config("max_discharge_power", int(value))
            _LOGGER.info("%s: Updated max_discharge_power %dW → %dW (immediate sync)",
                         self.coordinator.name, old_value, int(value))

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class MarstekConfigNumberEntity(NumberEntity):
    """Number entity for system-level configuration parameters (PD controller, etc.)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, definition: dict) -> None:
        """Initialize the config number entity."""
        self.hass = hass
        self.entry = entry
        self._definition = definition
        self._key = definition["key"]

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{entry.entry_id}_{definition['key']}"
        self._attr_icon = definition.get("icon")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_native_min_value = definition["min"]
        self._attr_native_max_value = definition["max"]
        self._attr_native_step = definition["step"]
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_should_poll = False
        self._scale = definition.get("scale", 1)

    @property
    def native_value(self):
        """Return the current value from config_entry.data, converted to display units."""
        raw = self.entry.data.get(self._key, self._definition["default"])
        return raw / self._scale

    async def async_set_native_value(self, value: float) -> None:
        """Update the value in config_entry.data and hot-reload controller."""
        new_data = dict(self.entry.data)
        new_data[self._key] = int(value * self._scale) if self._scale != 1 else value
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

        # Hot-reload PD params in the controller without restarting the integration
        controller = self.hass.data[DOMAIN][self.entry.entry_id].get("controller")
        if controller:
            controller.update_pd_parameters()

        _LOGGER.info("Config parameter %s updated to %s", self._key, value)
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
