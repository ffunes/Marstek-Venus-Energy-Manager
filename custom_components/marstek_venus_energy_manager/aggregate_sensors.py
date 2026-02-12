"""Aggregate sensors for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import logging

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN
from .coordinator import MarstekVenusDataUpdateCoordinator


# Define aggregate sensor definitions
AGGREGATE_SENSOR_DEFINITIONS = [
    {
        "key": "system_soc",
        "name": "System SOC",
        "unit": "%",
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery",
        "precision": 0,
    },
    {
        "key": "system_charge_power",
        "name": "System Charge Power",
        "unit": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-charging",
        "precision": 0,
    },
    {
        "key": "system_discharge_power",
        "name": "System Discharge Power",
        "unit": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-minus",
        "precision": 0,
    },
    {
        "key": "system_total_energy",
        "name": "System Total Energy",
        "unit": "kWh",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": "total",
        "icon": "mdi:battery-heart",
        "precision": 2,
    },
    {
        "key": "system_stored_energy",
        "name": "System Stored Energy",
        "unit": "kWh",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": "total",
        "icon": "mdi:battery-high",
        "precision": 3,
    },
    {
        "key": "system_daily_charging_energy",
        "name": "System Daily Charging Energy",
        "unit": "kWh",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:battery-plus",
        "precision": 2,
    },
    {
        "key": "system_daily_discharging_energy",
        "name": "System Daily Discharging Energy",
        "unit": "kWh",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:battery-minus",
        "precision": 2,
    },
]


class MarstekVenusAggregateSensor(SensorEntity):
    """Representation of an aggregate sensor combining all batteries."""

    def __init__(
        self, coordinators: list[MarstekVenusDataUpdateCoordinator], definition: dict, entry: ConfigEntry, hass: HomeAssistant
    ) -> None:
        """Initialize the aggregate sensor."""
        self.coordinators = coordinators
        self.definition = definition
        self.entry = entry
        self.hass = hass

        # Set entity attributes
        self._attr_name = f"Marstek Venus {definition['name']}"
        self._attr_unique_id = f"marstek_venus_system_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = True  # We poll the coordinators

        # Register as listener to all coordinators
        for coordinator in coordinators:
            coordinator.async_add_listener(self._handle_coordinator_update)
    
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from any coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the state of the aggregate sensor."""
        key = self.definition["key"]
        
        if key == "system_soc":
            return self._calculate_average_soc()
        elif key == "system_charge_power":
            return self._calculate_total_charge_power()
        elif key == "system_discharge_power":
            return self._calculate_total_discharge_power()
        elif key == "system_total_energy":
            return self._calculate_total_energy()
        elif key == "system_stored_energy":
            return self._calculate_total_stored_energy()
        elif key == "system_daily_charging_energy":
            return self._calculate_daily_charging_energy()
        elif key == "system_daily_discharging_energy":
            return self._calculate_daily_discharging_energy()

        return None

    def _calculate_average_soc(self) -> float | None:
        """Calculate average SOC across all batteries."""
        soc_values = []
        for coordinator in self.coordinators:
            if coordinator.data:
                soc = coordinator.data.get("battery_soc")
                if soc is not None:
                    soc_values.append(soc)
        
        if not soc_values:
            return None
        
        avg_soc = sum(soc_values) / len(soc_values)
        return round(avg_soc, self.definition.get("precision", 0))

    def _calculate_total_charge_power(self) -> float | None:
        """Calculate total charge power across all batteries.
        
        Charge power is positive in battery_power, so we sum only positive values.
        """
        total_power = 0
        has_data = False
        
        for coordinator in self.coordinators:
            if coordinator.data:
                power = coordinator.data.get("battery_power")
                if power is not None:
                    # Only count positive values (charging)
                    if power > 0:
                        total_power += power
                        has_data = True
        
        if not has_data:
            return 0  # Return 0 instead of None when not charging
        
        return round(total_power, self.definition.get("precision", 0))

    def _calculate_total_discharge_power(self) -> float | None:
        """Calculate total discharge power across all batteries.

        Discharge power is negative in battery_power, so we sum only negative values and return absolute value.
        """
        total_power = 0
        has_data = False
        battery_powers = []  # For debug logging

        for coordinator in self.coordinators:
            if coordinator.data:
                power = coordinator.data.get("battery_power")
                if power is not None:
                    battery_powers.append(f"{coordinator.name}={power}W")
                    # Only count negative values (discharging)
                    if power < 0:
                        total_power += abs(power)
                        has_data = True

        # Debug logging to see what's being summed
        if battery_powers:
            _LOGGER.debug(f"System Discharge Power calculation: {', '.join(battery_powers)} → Total: {total_power}W")

        if not has_data:
            return 0  # Return 0 instead of None when not discharging

        return round(total_power, self.definition.get("precision", 0))

    def _calculate_total_energy(self) -> float | None:
        """Calculate total energy capacity across all batteries (sum of battery_total_energy sensors)."""
        total_energy = 0
        has_data = False
        
        for coordinator in self.coordinators:
            if coordinator.data:
                # Get the battery_total_energy sensor value
                energy = coordinator.data.get("battery_total_energy")
                if energy is not None:
                    total_energy += energy
                    has_data = True
        
        if not has_data:
            return None
        
        return round(total_energy, self.definition.get("precision", 2))

    def _calculate_total_stored_energy(self) -> float | None:
        """Calculate total stored energy across all batteries (calculated from SOC and total_energy)."""
        total_stored = 0
        has_data = False
        
        for coordinator in self.coordinators:
            if coordinator.data:
                soc = coordinator.data.get("battery_soc")
                total_energy = coordinator.data.get("battery_total_energy")
                
                if soc is not None and total_energy is not None:
                    # Stored energy = (SOC / 100) * Total Energy
                    stored_energy = (soc / 100.0) * total_energy
                    total_stored += stored_energy
                    has_data = True
        
        if not has_data:
            return None
        
        return round(total_stored, self.definition.get("precision", 3))
    
    def _calculate_daily_charging_energy(self) -> float | None:
        """Calculate total daily charging energy across all batteries."""
        total_energy = 0
        has_data = False

        for coordinator in self.coordinators:
            if coordinator.data:
                energy = coordinator.data.get("total_daily_charging_energy")
                if energy is not None:
                    total_energy += energy
                    has_data = True

        if not has_data:
            return None

        return round(total_energy, self.definition.get("precision", 2))

    def _calculate_daily_discharging_energy(self) -> float | None:
        """Calculate total daily discharging energy across all batteries."""
        total_energy = 0
        has_data = False

        for coordinator in self.coordinators:
            if coordinator.data:
                energy = coordinator.data.get("total_daily_discharging_energy")
                if energy is not None:
                    total_energy += energy
                    has_data = True

        if not has_data:
            return None

        return round(total_energy, self.definition.get("precision", 2))

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Available if at least one coordinator has data
        return any(coordinator.data is not None for coordinator in self.coordinators)
