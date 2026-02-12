"""Number platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NUMBER_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    for coordinator in coordinators:
        for definition in NUMBER_DEFINITIONS:
            entities.append(MarstekVenusNumber(coordinator, definition))
    async_add_entities(entities)


class MarstekVenusNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Marstek Venus number."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
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
            _LOGGER.info("%s: Updated min_soc %.1f%% → %.1f%% (immediate sync)", 
                         self.coordinator.name, old_min_soc, value)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }
