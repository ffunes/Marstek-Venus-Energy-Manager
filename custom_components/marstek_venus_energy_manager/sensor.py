"""Sensor platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekVenusDataUpdateCoordinator
from .aggregate_sensors import AGGREGATE_SENSOR_DEFINITIONS, MarstekVenusAggregateSensor

_LOGGER = logging.getLogger(__name__)


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

    # Add excluded devices diagnostic sensor
    excluded_devices = entry.data.get("excluded_devices", [])
    if excluded_devices:
        entities.append(ExcludedDevicesConfigSensor(hass, entry))

    # Add discharge window diagnostic sensor (always, even without slots)
    entities.append(DischargeWindowSensor(hass, entry))

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


class ExcludedDevicesConfigSensor(SensorEntity):
    """Read-only sensor showing excluded devices configuration."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the excluded devices config sensor."""
        self.hass = hass
        self.entry = entry

        self._attr_name = "Excluded Devices"
        self._attr_unique_id = f"{entry.entry_id}_config_excluded_devices"
        self._attr_icon = "mdi:devices"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = False

    @property
    def native_value(self) -> int:
        """Return the number of excluded devices."""
        return len(self.entry.data.get("excluded_devices", []))

    @property
    def extra_state_attributes(self) -> dict:
        """Return excluded device details."""
        devices = self.entry.data.get("excluded_devices", [])
        attrs = {"count": len(devices)}
        for i, device in enumerate(devices):
            prefix = f"device_{i + 1}"
            attrs[f"{prefix}_sensor"] = device.get("power_sensor")
            attrs[f"{prefix}_included_in_consumption"] = device.get("included_in_consumption", True)
            attrs[f"{prefix}_allow_solar_surplus"] = device.get("allow_solar_surplus", False)
        return attrs

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


class DischargeWindowSensor(SensorEntity):
    """Diagnostic sensor showing whether we are currently inside an allowed discharge window."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the discharge window sensor."""
        self.hass = hass
        self.entry = entry

        self._attr_name = "Discharge Window"
        self._attr_unique_id = f"{entry.entry_id}_discharge_window"
        self._attr_icon = "mdi:clock-check-outline"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = True

    @property
    def native_value(self) -> str:
        """Return the current discharge window status."""
        from datetime import datetime, time as dt_time

        all_slots = self.entry.data.get("no_discharge_time_slots", [])
        enabled_slots = [s for s in all_slots if s.get("enabled", True)]

        if not enabled_slots:
            return "No slots"

        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]

        for i, slot in enumerate(enabled_slots):
            if current_day not in slot.get("days", []):
                continue
            try:
                start_time = dt_time.fromisoformat(slot["start_time"])
                end_time = dt_time.fromisoformat(slot["end_time"])
            except Exception:
                continue
            if start_time <= current_time <= end_time:
                return f"Active (Slot {i + 1})"

        return "Inactive"

    @property
    def extra_state_attributes(self) -> dict:
        """Return configuration details of all time slots."""
        all_slots = self.entry.data.get("no_discharge_time_slots", [])
        enabled_slots = [s for s in all_slots if s.get("enabled", True)]
        attrs = {
            "slots_configured": len(enabled_slots),
        }

        # Find active slot number
        from datetime import datetime, time as dt_time
        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        active_slot = None

        for i, slot in enumerate(enabled_slots):
            if current_day not in slot.get("days", []):
                continue
            try:
                start_time = dt_time.fromisoformat(slot["start_time"])
                end_time = dt_time.fromisoformat(slot["end_time"])
            except Exception:
                continue
            if start_time <= current_time <= end_time:
                active_slot = i + 1
                break

        attrs["active_slot"] = active_slot

        # Add details for each configured slot (all slots, not just enabled)
        for i, slot in enumerate(all_slots):
            n = i + 1
            days = slot.get("days", [])
            days_str = ", ".join(d.capitalize() for d in days) if days else "None"
            attrs[f"slot_{n}_schedule"] = f"{slot.get('start_time', '??')}-{slot.get('end_time', '??')}"
            attrs[f"slot_{n}_days"] = days_str
            attrs[f"slot_{n}_enabled"] = slot.get("enabled", True)
            attrs[f"slot_{n}_apply_to_charge"] = slot.get("apply_to_charge", False)
            attrs[f"slot_{n}_target_grid_power"] = f"{slot.get('target_grid_power', 0)} W"

        return attrs

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }
