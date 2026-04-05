"""Sensor platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    EFFICIENCY_SENSOR_DEFINITIONS,
    STORED_ENERGY_SENSOR_DEFINITIONS,
    CYCLE_SENSOR_DEFINITIONS,
    CONF_ENABLE_CHARGE_DELAY,
    CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY,
    CONF_ENABLE_PREDICTIVE_CHARGING,
    CONF_CHARGING_TIME_SLOT,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_DELAY_SAFETY_MARGIN_MIN,
    CONF_CAPACITY_PROTECTION_ENABLED,
    CONF_CAPACITY_PROTECTION_SOC_THRESHOLD,
    CONF_CAPACITY_PROTECTION_LIMIT,
    CONF_PD_KP,
    CONF_PD_KD,
    CONF_PD_DEADBAND,
    CONF_PD_MAX_POWER_CHANGE,
    CONF_PD_DIRECTION_HYSTERESIS,
    CONF_PD_MIN_CHARGE_POWER,
    CONF_PD_MIN_DISCHARGE_POWER,
    DEFAULT_PD_KP,
    DEFAULT_PD_KD,
    DEFAULT_PD_DEADBAND,
    DEFAULT_PD_MAX_POWER_CHANGE,
    DEFAULT_PD_DIRECTION_HYSTERESIS,
    DEFAULT_PD_MIN_CHARGE_POWER,
    DEFAULT_PD_MIN_DISCHARGE_POWER,
    CONF_PREDICTIVE_CHARGING_MODE,
    CONF_PRICE_SENSOR,
    CONF_PRICE_INTEGRATION_TYPE,
    CONF_MAX_PRICE_THRESHOLD,
    CONF_AVERAGE_PRICE_SENSOR,
    CONF_DP_PRICE_DISCHARGE_CONTROL,
    CONF_RT_PRICE_DISCHARGE_CONTROL,
    CONF_METER_INVERTED,
)
from .coordinator import MarstekVenusDataUpdateCoordinator
from .aggregate_sensors import AGGREGATE_SENSOR_DEFINITIONS, MarstekVenusAggregateSensor, DailyGridAtMinSocSensor, SystemAlarmSensor
from .calculated_sensors import MarstekVenusEfficiencySensor, MarstekVenusStoredEnergySensor, MarstekVenusCycleSensor

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
            and d not in coordinator.binary_sensor_definitions  # Exclude BINARY_SENSOR_DEFINITIONS
        ]

        for definition in sensor_defs:
            entities.append(MarstekVenusSensor(coordinator, definition))

    # Add aggregate sensors if there are multiple batteries
    if len(coordinators) > 1:
        for definition in AGGREGATE_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusAggregateSensor(coordinators, definition, entry, hass))

    # System alarm sensor — only for v2 batteries (only version with alarm/fault registers)
    v2_coordinators = [c for c in coordinators if c.battery_version == "v2"]
    if v2_coordinators:
        entities.append(SystemAlarmSensor(v2_coordinators))

    # Add calculated sensors (efficiency, stored energy, cycle count) per battery
    for coordinator in coordinators:
        for definition in EFFICIENCY_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusEfficiencySensor(coordinator, definition))
        for definition in STORED_ENERGY_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusStoredEnergySensor(coordinator, definition))
        for definition in CYCLE_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusCycleSensor(coordinator, definition))

    # Add excluded devices diagnostic sensor
    excluded_devices = entry.data.get("excluded_devices", [])
    if excluded_devices:
        entities.append(ExcludedDevicesConfigSensor(hass, entry))

    # Add discharge window diagnostic sensor (always, even without slots)
    entities.append(DischargeWindowSensor(hass, entry))

    # Add active batteries diagnostic sensor (only with multiple batteries)
    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    if controller and len(coordinators) > 1:
        entities.append(ActiveBatteriesSensor(hass, entry, controller, coordinators))

    # Add weekly full charge status sensor (when weekly charge is enabled)
    if controller and controller.weekly_full_charge_enabled:
        entities.append(WeeklyFullChargeSensor(hass, entry, controller))

    # Add charge delay sensor (when charge delay is configured, regardless of enabled state)
    has_charge_delay_config = (
        CONF_ENABLE_CHARGE_DELAY in entry.data
        or CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY in entry.data
    )
    if controller and has_charge_delay_config:
        entities.append(ChargeDelaySensor(hass, entry, controller))

    # Add non-responsive batteries sensor (always, when controller is present)
    if controller:
        entities.append(NonResponsiveBatteriesSensor(hass, entry, controller, coordinators))

    # Add daily grid-at-min-soc energy sensor (feeds into consumption estimation)
    if controller:
        entities.append(DailyGridAtMinSocSensor(controller))

    # Add configuration summary diagnostic sensor (hidden, for support purposes)
    entities.append(ConfigurationSummarySensor(hass, entry))

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
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
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

        self._attr_has_entity_name = True
        self._attr_translation_key = "excluded_devices"
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

        self._attr_has_entity_name = True
        self._attr_translation_key = "discharge_window"
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
            return "no_slots"

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
                return "active"

        return "inactive"

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


class ActiveBatteriesSensor(SensorEntity):
    """Diagnostic sensor showing which batteries are currently active in load sharing."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, controller, coordinators: list
    ) -> None:
        """Initialize the active batteries sensor."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._coordinators = coordinators

        self._attr_has_entity_name = True
        self._attr_translation_key = "active_batteries"
        self._attr_unique_id = f"{entry.entry_id}_active_batteries"
        self._attr_icon = "mdi:battery-sync"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = True

    @property
    def native_value(self) -> str:
        """Return a summary of active batteries."""
        discharge = self.controller._active_discharge_batteries
        charge = self.controller._active_charge_batteries

        if discharge:
            names = ", ".join(c.name for c in discharge)
            return f"Discharging: {names}"
        elif charge:
            names = ", ".join(c.name for c in charge)
            return f"Charging: {names}"
        return "Idle"

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed load sharing state."""
        discharge = self.controller._active_discharge_batteries
        charge = self.controller._active_charge_batteries
        total = len(self._coordinators)

        attrs = {
            "total_batteries": total,
            "discharge_active": len(discharge),
            "discharge_batteries": [c.name for c in discharge],
            "charge_active": len(charge),
            "charge_batteries": [c.name for c in charge],
        }

        # Add per-battery SOC and lifetime energy for context
        for c in self._coordinators:
            if c.data:
                soc = c.data.get("battery_soc", "N/A")
                discharge_kwh = c.data.get("total_discharging_energy", "N/A")
                charge_kwh = c.data.get("total_charging_energy", "N/A")
                attrs[f"{c.name}_soc"] = f"{soc}%"
                attrs[f"{c.name}_total_discharged"] = f"{discharge_kwh} kWh"
                attrs[f"{c.name}_total_charged"] = f"{charge_kwh} kWh"

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


class WeeklyFullChargeSensor(SensorEntity):
    """Diagnostic sensor showing weekly full charge status and delay calculations."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the weekly full charge sensor."""
        self.hass = hass
        self.entry = entry
        self._controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "weekly_full_charge"
        self._attr_unique_id = f"{entry.entry_id}_weekly_full_charge_status"
        self._attr_icon = "mdi:battery-clock"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = True

    @property
    def native_value(self) -> str:
        """Return the current weekly charge status as a translation key."""
        state = self._controller._weekly_charge_status.get("state", "Idle")
        return {
            "Idle": "idle",
            "Disabled": "disabled",
            "Charging to 100%": "charging",
            "Complete": "complete",
        }.get(state, "idle")

    @property
    def extra_state_attributes(self) -> dict:
        """Return weekly charge details as attributes."""
        attrs = {
            "weekly_charge_day": self._controller.weekly_full_charge_day,
            "charge_delay_enabled": self._controller.charge_delay_enabled,
        }
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


class ChargeDelaySensor(SensorEntity):
    """Sensor showing estimated charge start time for the unified charge delay.

    Shows the estimated unlock time as HH:MM or current delay status.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the charge delay sensor."""
        self.hass = hass
        self.entry = entry
        self._controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "charge_delay_status"
        self._attr_unique_id = f"{entry.entry_id}_charge_delay_status"
        self._attr_icon = "mdi:clock-alert-outline"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = True

    @property
    def native_value(self) -> str:
        """Return the charge delay state as a translation key."""
        status = self._controller._charge_delay_status
        state = status.get("state", "Idle")

        if state.startswith("Delayed"):
            return "delayed"

        if state.startswith("Waiting"):
            return "waiting_for_solar"

        if state.startswith("Unlocking") or state == "Charging allowed":
            return "charging_allowed"

        return state.lower()  # "idle", "disabled"

    @property
    def extra_state_attributes(self) -> dict:
        """Return delay calculation details."""
        status = self._controller._charge_delay_status

        attrs = {
            "state": status.get("state", "Idle"),
            "target_soc": status.get("target_soc"),
            "safety_margin_min": status.get("safety_margin_min"),
        }

        for key in (
            "forecast_kwh", "solar_t_start", "solar_t_end",
            "energy_needed_kwh", "remaining_solar_kwh",
            "remaining_consumption_kwh", "net_solar_kwh",
            "charge_time_h", "estimated_unlock_time", "unlock_reason",
        ):
            value = status.get(key)
            if value is not None:
                attrs[key] = value

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


class ConfigurationSummarySensor(SensorEntity):
    """Hidden diagnostic sensor exposing the full integration configuration as attributes.

    Intended for support purposes: share this sensor's state card to give a
    complete picture of how the system is configured.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the configuration summary sensor."""
        self.hass = hass
        self.entry = entry

        self._attr_has_entity_name = True
        self._attr_translation_key = "configuration_summary"
        self._attr_unique_id = f"{entry.entry_id}_configuration_summary"
        self._attr_icon = "mdi:cog-outline"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False
        self._attr_should_poll = False

    @property
    def native_value(self) -> int:
        """Return number of configured batteries as a quick-glance value."""
        return len(self.entry.data.get("batteries", []))

    @property
    def extra_state_attributes(self) -> dict:
        """Return the full integration configuration as attributes."""
        data = self.entry.data
        attrs = {}

        # --- General ---
        attrs["consumption_sensor"] = data.get("consumption_sensor")
        attrs["meter_inverted"] = data.get(CONF_METER_INVERTED, False)
        forecast = data.get(CONF_SOLAR_FORECAST_SENSOR)
        attrs["solar_forecast_sensor"] = forecast if forecast else "not_configured"

        # --- Batteries ---
        batteries = data.get("batteries", [])
        attrs["num_batteries"] = len(batteries)
        for i, bat in enumerate(batteries):
            n = i + 1
            attrs[f"battery_{n}_name"] = bat.get("name")
            attrs[f"battery_{n}_host"] = bat.get("host")
            attrs[f"battery_{n}_port"] = bat.get("port")
            attrs[f"battery_{n}_version"] = bat.get("battery_version")
            attrs[f"battery_{n}_max_charge_power_W"] = bat.get("max_charge_power")
            attrs[f"battery_{n}_max_discharge_power_W"] = bat.get("max_discharge_power")
            attrs[f"battery_{n}_max_soc"] = bat.get("max_soc")
            attrs[f"battery_{n}_min_soc"] = bat.get("min_soc")
            attrs[f"battery_{n}_hysteresis_enabled"] = bat.get("enable_charge_hysteresis", False)
            if bat.get("enable_charge_hysteresis"):
                attrs[f"battery_{n}_hysteresis_percent"] = bat.get("charge_hysteresis_percent")

        # --- Time slots ---
        slots = data.get("no_discharge_time_slots", [])
        attrs["num_time_slots"] = len(slots)
        for i, slot in enumerate(slots):
            n = i + 1
            days = slot.get("days", [])
            days_str = ", ".join(d.capitalize() for d in days) if days else "None"
            attrs[f"slot_{n}_schedule"] = f"{slot.get('start_time')}-{slot.get('end_time')}"
            attrs[f"slot_{n}_days"] = days_str
            attrs[f"slot_{n}_enabled"] = slot.get("enabled", True)
            attrs[f"slot_{n}_apply_to_charge"] = slot.get("apply_to_charge", False)
            attrs[f"slot_{n}_target_grid_power_W"] = slot.get("target_grid_power", 0)

        # --- Predictive charging ---
        predictive_enabled = data.get(CONF_ENABLE_PREDICTIVE_CHARGING, False)
        attrs["predictive_charging_enabled"] = predictive_enabled
        if predictive_enabled:
            attrs["predictive_charging_mode"] = data.get(CONF_PREDICTIVE_CHARGING_MODE)
            time_slot = data.get(CONF_CHARGING_TIME_SLOT)
            if time_slot:
                attrs["predictive_charging_time_slot"] = time_slot
            max_power = data.get(CONF_MAX_CONTRACTED_POWER)
            if max_power is not None:
                attrs["predictive_max_contracted_power_W"] = max_power
            price_sensor = data.get(CONF_PRICE_SENSOR)
            if price_sensor:
                attrs["price_sensor"] = price_sensor
            price_type = data.get(CONF_PRICE_INTEGRATION_TYPE)
            if price_type:
                attrs["price_integration_type"] = price_type
            max_price = data.get(CONF_MAX_PRICE_THRESHOLD)
            if max_price is not None:
                attrs["max_price_threshold"] = max_price
            avg_price_sensor = data.get(CONF_AVERAGE_PRICE_SENSOR)
            if avg_price_sensor:
                attrs["average_price_sensor"] = avg_price_sensor
            dp_discharge = data.get(CONF_DP_PRICE_DISCHARGE_CONTROL)
            if dp_discharge is not None:
                attrs["dp_price_discharge_control"] = dp_discharge
            rt_discharge = data.get(CONF_RT_PRICE_DISCHARGE_CONTROL)
            if rt_discharge is not None:
                attrs["rt_price_discharge_control"] = rt_discharge

        # --- Weekly full charge ---
        weekly_enabled = data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False)
        attrs["weekly_full_charge_enabled"] = weekly_enabled
        if weekly_enabled:
            attrs["weekly_full_charge_day"] = data.get(CONF_WEEKLY_FULL_CHARGE_DAY)

        # --- Charge delay ---
        charge_delay = data.get(CONF_ENABLE_CHARGE_DELAY, False)
        weekly_delay = data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        attrs["charge_delay_enabled"] = charge_delay or weekly_delay
        if charge_delay or weekly_delay:
            attrs["charge_delay_for_weekly_charge"] = weekly_delay
            attrs["charge_delay_safety_margin_min"] = data.get(CONF_DELAY_SAFETY_MARGIN_MIN)

        # --- Capacity protection ---
        cap_enabled = data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)
        attrs["capacity_protection_enabled"] = cap_enabled
        if cap_enabled:
            attrs["capacity_protection_soc_threshold"] = data.get(CONF_CAPACITY_PROTECTION_SOC_THRESHOLD)
            attrs["capacity_protection_limit_W"] = data.get(CONF_CAPACITY_PROTECTION_LIMIT)

        # --- PD controller ---
        attrs["pd_kp"] = data.get(CONF_PD_KP, DEFAULT_PD_KP)
        attrs["pd_kd"] = data.get(CONF_PD_KD, DEFAULT_PD_KD)
        attrs["pd_deadband_W"] = data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        attrs["pd_max_power_change_W"] = data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        attrs["pd_direction_hysteresis_W"] = data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        attrs["pd_min_charge_power_W"] = data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        attrs["pd_min_discharge_power_W"] = data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)

        # --- Excluded devices ---
        excluded = data.get("excluded_devices", [])
        attrs["num_excluded_devices"] = len(excluded)
        for i, dev in enumerate(excluded):
            n = i + 1
            attrs[f"excluded_device_{n}_sensor"] = dev.get("power_sensor")
            attrs[f"excluded_device_{n}_included_in_consumption"] = dev.get("included_in_consumption", True)
            attrs[f"excluded_device_{n}_allow_solar_surplus"] = dev.get("allow_solar_surplus", False)

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


class NonResponsiveBatteriesSensor(SensorEntity):
    """Diagnostic sensor showing batteries excluded due to non-responsive behavior."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, controller, coordinators: list
    ) -> None:
        """Initialize the non-responsive batteries sensor."""
        self.hass = hass
        self.entry = entry
        self._controller = controller
        self._coordinators = coordinators

        self._attr_has_entity_name = True
        self._attr_translation_key = "non_responsive_batteries"
        self._attr_unique_id = f"{entry.entry_id}_non_responsive_batteries"
        self._attr_icon = "mdi:battery-alert"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = True

    @property
    def native_value(self) -> str:
        """Return names of excluded batteries, or 'None' if all are healthy."""
        names = self._controller.non_responsive_battery_names
        return ", ".join(names) if names else "None"

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-battery non-responsive state details."""
        from homeassistant.util import dt as dt_util
        now = dt_util.utcnow()
        attrs = {}
        for coordinator in self._coordinators:
            info = self._controller._non_responsive_batteries.get(coordinator)
            if info and info.get("excluded_at") is not None:
                elapsed_min = (now - info["excluded_at"]).total_seconds() / 60
                remaining_min = max(0.0, info["cooldown_minutes"] - elapsed_min)
                attrs[coordinator.name] = {
                    "excluded": True,
                    "cooldown_minutes": info["cooldown_minutes"],
                    "remaining_minutes": round(remaining_min, 1),
                }
            else:
                attrs[coordinator.name] = {
                    "excluded": False,
                    "fail_count": info["fail_count"] if info else 0,
                }
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
