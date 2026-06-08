"""Calculated sensors for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EFFICIENCY_SENSOR_DEFINITIONS, STORED_ENERGY_SENSOR_DEFINITIONS, CYCLE_SENSOR_DEFINITIONS
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
        for definition in CYCLE_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusCycleSensor(coordinator, definition))
    async_add_entities(entities)


class MarstekVenusEfficiencySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Marstek Venus efficiency sensor."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the efficiency sensor."""
        super().__init__(coordinator)
        self.definition = definition

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
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
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
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

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
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
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class MarstekVenusCycleSensor(CoordinatorEntity, SensorEntity):
    """Calculated battery cycle count: total_discharge / battery_capacity."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the cycle count sensor."""
        super().__init__(coordinator)
        self.definition = definition

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self._attr_state_class = definition.get("state_class")
        self._attr_icon = definition.get("icon")
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = False
        self._dependency_keys = definition["dependency_keys"]

    @property
    def native_value(self):
        """Return calculated cycle count: (discharge + charge) / 2 / capacity."""
        if self.coordinator.data is None:
            return None

        discharge = self.coordinator.data.get(self._dependency_keys["discharge"], 0)
        charge = self.coordinator.data.get(self._dependency_keys["charge"], 0)
        capacity = self.coordinator.data.get(self._dependency_keys["capacity"], 0)

        if not capacity or capacity <= 0:
            return None

        return round((discharge + charge) / 2 / capacity, 1)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class MarstekVenusSolarPowerSensor(CoordinatorEntity, SensorEntity):
    """Total DC-coupled PV power for a Venus D/A unit: sum of its MPPT inputs."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the solar power sensor."""
        super().__init__(coordinator)
        self.definition = definition

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = False
        self._mppt_keys = definition["dependency_keys"]["mppt"]

    @property
    def native_value(self):
        """Return the sum of this unit's MPPT power inputs (W)."""
        if self.coordinator.data is None:
            return None

        total = 0
        for key in self._mppt_keys:
            value = self.coordinator.data.get(key)
            if value is not None:
                total += value
        return round(total)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class MarstekVenusBatteryCellPowerSensor(CoordinatorEntity, SensorEntity):
    """True battery cell power for a Venus D/A unit: battery_power plus DC PV (MPPT).

    The battery_power register mirrors the AC side with inverted sign and excludes
    the DC PV, which charges the cells without crossing the AC port. Adding the
    unit's MPPT recovers the battery's own power. Same sign as battery_power
    (+ charge / - discharge).
    """

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the battery cell power sensor."""
        super().__init__(coordinator)
        self.definition = definition

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = False
        self._battery_key = definition["dependency_keys"]["battery"]
        self._mppt_keys = definition["dependency_keys"]["mppt"]

    @property
    def native_value(self):
        """Return battery_power plus this unit's MPPT total (W)."""
        if self.coordinator.data is None:
            return None

        battery = self.coordinator.data.get(self._battery_key)
        if battery is None:
            return None
        solar = 0
        for key in self._mppt_keys:
            value = self.coordinator.data.get(key)
            if value is not None:
                solar += value
        return round(battery + solar)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }
