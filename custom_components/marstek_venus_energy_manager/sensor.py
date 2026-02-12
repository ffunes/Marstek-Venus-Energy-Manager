"""Sensor platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekVenusDataUpdateCoordinator
from .aggregate_sensors import AGGREGATE_SENSOR_DEFINITIONS, MarstekVenusAggregateSensor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    
    # Add individual battery sensors - use version-specific definitions from coordinator
    for coordinator in coordinators:
        # Get sensor definitions from coordinator's version-specific _all_definitions
        # Exclude control entities (number, switch, select) that have their own platforms
        sensor_defs = [
            d for d in coordinator._all_definitions
            if "register" in d
            and "key" in d
            and "min" not in d           # Exclude NUMBER_DEFINITIONS
            and "command_on" not in d    # Exclude SWITCH_DEFINITIONS
            and "options" not in d       # Exclude SELECT_DEFINITIONS
        ]

        for definition in sensor_defs:
            entities.append(MarstekVenusSensor(coordinator, definition))
    
    # Add aggregate sensors if there are multiple batteries
    if len(coordinators) > 1:
        for definition in AGGREGATE_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusAggregateSensor(coordinators, definition, entry, hass))
    
    async_add_entities(entities)


class MarstekVenusSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Marstek Venus sensor."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.definition = definition
        
        # Set entity attributes
        self._attr_name = f"{coordinator.name} {definition['name']}"
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_force_update = definition.get("force_update", False)
        self._attr_should_poll = False

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.definition["key"])
        
        if value is None:
            return None
        
        # Map numeric values to state names if available
        if "states" in self.definition:
            return self.definition["states"].get(value, value)
        
        # For bit-described values, show which bits are active
        if "bit_descriptions" in self.definition:
            active_bits = []
            bit_descriptions = self.definition["bit_descriptions"]
            
            # Check bits based on data type
            max_bits = 64 if self.definition.get("data_type") == "uint64" else 32
            for bit_pos in range(max_bits):
                if value & (1 << bit_pos):
                    if bit_pos in bit_descriptions:
                        active_bits.append(bit_descriptions[bit_pos])
            
            if active_bits:
                return ", ".join(active_bits)
            else:
                return "No active alarms/faults"
        
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }
