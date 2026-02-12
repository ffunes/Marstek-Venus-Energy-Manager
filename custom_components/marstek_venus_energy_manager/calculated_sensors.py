"""Calculated sensors for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EFFICIENCY_SENSOR_DEFINITIONS, STORED_ENERGY_SENSOR_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calculated sensor platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    for coordinator in coordinators:
        for definition in EFFICIENCY_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusEfficiencySensor(coordinator, definition))
        for definition in STORED_ENERGY_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusStoredEnergySensor(coordinator, definition))
    async_add_entities(entities)


class MarstekVenusEfficiencySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Marstek Venus efficiency sensor."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the efficiency sensor."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = False
        self._dependency_keys = definition["dependency_keys"]

    @property
    def native_value(self):
        """Return the state of the efficiency sensor."""
        if self.coordinator.data is None:
            return None
            
        charge_key = self._dependency_keys["charge"]
        discharge_key = self._dependency_keys["discharge"]
        
        charge_energy = self.coordinator.data.get(charge_key, 0)
        discharge_energy = self.coordinator.data.get(discharge_key, 0)
        
        if charge_energy <= 0:
            return None
            
        efficiency = (discharge_energy / charge_energy) * 100
        return round(efficiency, 2)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class MarstekVenusStoredEnergySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Marstek Venus stored energy sensor."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the stored energy sensor."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = False
        self._dependency_keys = definition["dependency_keys"]

    @property
    def native_value(self):
        """Return the state of the stored energy sensor."""
        if self.coordinator.data is None:
            return None
            
        soc_key = self._dependency_keys["soc"]
        capacity_key = self._dependency_keys["capacity"]
        
        soc = self.coordinator.data.get(soc_key, 0)
        capacity = self.coordinator.data.get(capacity_key, 0)
        
        if capacity <= 0:
            return None
            
        stored_energy = (soc / 100) * capacity
        return round(stored_energy, 3)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }
