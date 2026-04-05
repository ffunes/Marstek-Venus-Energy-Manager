"""Aggregate sensors for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import logging

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, ALARM_BIT_DESCRIPTIONS, FAULT_BIT_DESCRIPTIONS
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


class DailyGridAtMinSocSensor(SensorEntity):
    """Tracks daily grid energy imported when all batteries are at min SOC during a discharge window.

    This energy represents household demand that the battery could not cover.
    It is accumulated in real-time by the ChargeDischargeController and resets at midnight.
    """

    def __init__(self, controller) -> None:
        """Initialize the sensor."""
        self._controller = controller

        self._attr_has_entity_name = True
        self._attr_unique_id = "marstek_venus_system_daily_grid_at_min_soc_energy"
        self._attr_translation_key = "system_daily_grid_at_min_soc_energy"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_suggested_display_precision = 2
        self._attr_icon = "mdi:transmission-tower-import"
        self._attr_should_poll = False

    async def async_added_to_hass(self) -> None:
        """Register with controller once entity is added to HA."""
        self._controller._grid_at_min_soc_sensor = self

    @property
    def native_value(self) -> float:
        """Return accumulated daily grid import at min SOC."""
        return round(self._controller._daily_grid_at_min_soc_kwh, 2)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


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
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
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
        has_v3 = any(
            getattr(c, "battery_version", "v2") in ("v3", "vA", "vD")
            for c in self.coordinators
        )
        precision = 1 if has_v3 else self.definition.get("precision", 0)
        return round(avg_soc, precision)

    def _calculate_total_charge_power(self) -> float | None:
        """Calculate total charge power across all batteries.

        Charge power is negative in ac_power, so we sum only negative values and return absolute value.
        """
        total_power = 0
        has_data = False

        for coordinator in self.coordinators:
            if coordinator.data:
                power = coordinator.data.get("ac_power")
                if power is not None:
                    # Only count negative values (charging)
                    if power < 0:
                        total_power += abs(power)
                        has_data = True

        if not has_data:
            return 0  # Return 0 instead of None when not charging

        return round(total_power, self.definition.get("precision", 0))

    def _calculate_total_discharge_power(self) -> float | None:
        """Calculate total discharge power across all batteries.

        Discharge power is positive in ac_power, so we sum only positive values.
        """
        total_power = 0
        has_data = False
        ac_powers = []  # For debug logging

        for coordinator in self.coordinators:
            if coordinator.data:
                power = coordinator.data.get("ac_power")
                if power is not None:
                    ac_powers.append(f"{coordinator.name}={power}W")
                    # Only count positive values (discharging)
                    if power > 0:
                        total_power += power
                        has_data = True

        # Debug logging to see what's being summed
        if ac_powers:
            _LOGGER.debug(f"System Discharge Power calculation: {', '.join(ac_powers)} → Total: {total_power}W")

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


class SystemAlarmSensor(SensorEntity):
    """System-level alarm sensor that aggregates fault/alarm status across all batteries.

    State: "OK" when no active alarms or faults.
           "Warning" when one or more alarm bits are set but no fault bits.
           "Fault" when one or more fault bits are set on any battery.

    The extra_state_attributes dict exposes per-battery active alarm/fault labels so
    the user can see which battery is affected and what the condition is.
    """

    _attr_has_entity_name = True
    _attr_unique_id = "marstek_venus_system_alarm_status"
    _attr_translation_key = "system_alarm_status"
    _attr_icon = "mdi:bell-alert"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinators: list[MarstekVenusDataUpdateCoordinator]) -> None:
        """Initialize the system alarm sensor."""
        self.coordinators = coordinators

        for coordinator in coordinators:
            coordinator.async_add_listener(self._handle_coordinator_update)

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @staticmethod
    def _active_labels(value: int, descriptions: dict) -> list[str]:
        return [descriptions[b] for b in range(32) if (value & (1 << b)) and b in descriptions]

    @property
    def native_value(self) -> str:
        """Return overall alarm state across all batteries."""
        any_fault = False
        any_alarm = False
        for coordinator in self.coordinators:
            if not coordinator.data:
                continue
            if coordinator.data.get("fault_status") or 0:
                any_fault = True
            if coordinator.data.get("alarm_status") or 0:
                any_alarm = True
        if any_fault:
            return "Fault"
        if any_alarm:
            return "Warning"
        return "OK"

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-battery active alarm and fault descriptions."""
        attrs: dict = {}
        for coordinator in self.coordinators:
            if not coordinator.data:
                continue
            fault_val: int = coordinator.data.get("fault_status") or 0
            alarm_val: int = coordinator.data.get("alarm_status") or 0
            active: list[str] = []
            if fault_val:
                active += [f"[Fault] {label}" for label in self._active_labels(fault_val, FAULT_BIT_DESCRIPTIONS)]
            if alarm_val:
                active += [f"[Alarm] {label}" for label in self._active_labels(alarm_val, ALARM_BIT_DESCRIPTIONS)]
            if active:
                attrs[coordinator.name] = active
        return attrs

    @property
    def device_info(self):
        """Attach to the system device."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }
