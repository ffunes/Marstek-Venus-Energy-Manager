"""Switch platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_CAPACITY_PROTECTION_ENABLED, CONF_ENABLE_CHARGE_DELAY, CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, CONF_MANUAL_MODE_ENABLED, CONF_PREDICTIVE_CHARGING_OVERRIDDEN
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
        for definition in coordinator.switch_definitions:
            entities.append(MarstekVenusSwitch(coordinator, definition))

    # Add manual mode switch (system-level, always present)
    if controller:
        entities.append(ManualModeSwitch(hass, entry, controller))

    # Add predictive charging switch (system-level, not per-battery)
    if controller and controller.predictive_charging_enabled:
        entities.append(PredictiveChargingSwitch(hass, entry, controller))

    # Add capacity protection switch (system-level, when configured, regardless of enabled state)
    if controller and CONF_CAPACITY_PROTECTION_ENABLED in entry.data:
        entities.append(CapacityProtectionSwitch(hass, entry, controller))

    # Add charge delay switch (system-level, when charge delay is configured)
    has_charge_delay_config = (
        CONF_ENABLE_CHARGE_DELAY in entry.data
        or CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY in entry.data
    )
    if controller and has_charge_delay_config:
        entities.append(ChargeDelaySwitch(hass, entry, controller))

    # Add time slot enable/disable switches
    time_slots = entry.data.get("no_discharge_time_slots", [])
    for index in range(len(time_slots)):
        entities.append(TimeSlotSwitch(hass, entry, index))

    # Add per-device enable/disable and solar surplus switches for excluded devices
    excluded_devices = entry.data.get("excluded_devices", [])
    for index in range(len(excluded_devices)):
        entities.append(ExcludedDeviceEnabledSwitch(hass, entry, index))
        entities.append(ExcludedDeviceSolarSurplusSwitch(hass, entry, index))

    async_add_entities(entities)


class MarstekVenusSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Marstek Venus switch."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_icon = definition.get("icon")
        self._attr_entity_registry_enabled_default = definition.get("enabled_by_default", True)
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
        if self.definition["key"] == "rs485_control_mode":
            self.coordinator.set_rs485_user_disabled(False)
        await self.coordinator.write_register(self._register, self._command_on, do_refresh=True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        if self.definition["key"] == "rs485_control_mode":
            self.coordinator.set_rs485_user_disabled(True)
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


class PredictiveChargingSwitch(SwitchEntity):
    """Switch to enable/disable predictive grid charging.

    ON = predictive charging enabled (default when configured).
    OFF = predictive charging paused (overridden).
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the predictive charging switch."""
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "predictive_charging"
        self._attr_unique_id = f"{entry.entry_id}_predictive_charging"
        self._attr_icon = "mdi:solar-power"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if predictive charging is enabled (not overridden)."""
        return not self.controller.predictive_charging_overridden

    async def async_turn_on(self, **kwargs) -> None:
        """Enable predictive charging (remove override)."""
        self.controller.predictive_charging_overridden = False
        new_data = dict(self.entry.data)
        new_data[CONF_PREDICTIVE_CHARGING_OVERRIDDEN] = False
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": "predictive_charging_override"},
        )
        _LOGGER.info("Predictive charging enabled")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable predictive charging (activate override)."""
        self.controller.predictive_charging_overridden = True
        new_data = dict(self.entry.data)
        new_data[CONF_PREDICTIVE_CHARGING_OVERRIDDEN] = True
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        if self.controller.grid_charging_active:
            message = "Predictive grid charging has been paused. Turn the switch back on to resume."
        else:
            message = "Predictive charging is now disabled. It will not activate when the time slot becomes active."
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Predictive Charging Disabled",
                "message": message,
                "notification_id": "predictive_charging_override",
            },
        )
        _LOGGER.info("Predictive charging disabled (overridden)")
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


class TimeSlotSwitch(SwitchEntity):
    """Switch to enable/disable an individual time slot."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, index: int) -> None:
        """Initialize the time slot switch."""
        self.hass = hass
        self.entry = entry
        self._slot_index = index

        self._attr_has_entity_name = True
        self._attr_translation_key = "time_slot"
        self._attr_translation_placeholders = {"slot_number": str(index + 1)}
        self._attr_unique_id = f"{entry.entry_id}_time_slot_{index}_enabled"
        self._attr_icon = "mdi:clock-outline"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if the time slot is enabled."""
        slots = self.entry.data.get("no_discharge_time_slots", [])
        if self._slot_index < len(slots):
            return slots[self._slot_index].get("enabled", True)
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return time slot details as attributes."""
        slots = self.entry.data.get("no_discharge_time_slots", [])
        if self._slot_index >= len(slots):
            return {}
        slot = slots[self._slot_index]
        days = slot.get("days", [])
        days_str = ", ".join(d.capitalize() for d in days) if days else "None"
        return {
            "schedule": f"{slot.get('start_time', '??')}-{slot.get('end_time', '??')}",
            "days": days_str,
            "apply_to_charge": slot.get("apply_to_charge", False),
            "target_grid_power": f"{slot.get('target_grid_power', 0)} W",
        }

    async def _update_slot_enabled(self, enabled: bool) -> None:
        """Update the enabled state of this slot in config_entry.data."""
        new_data = dict(self.entry.data)
        slots = [dict(s) for s in new_data.get("no_discharge_time_slots", [])]
        if self._slot_index < len(slots):
            slots[self._slot_index]["enabled"] = enabled
            new_data["no_discharge_time_slots"] = slots
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)
            state = "enabled" if enabled else "disabled"
            _LOGGER.info("Time slot %d %s", self._slot_index + 1, state)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the time slot."""
        await self._update_slot_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the time slot."""
        await self._update_slot_enabled(False)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


class CapacityProtectionSwitch(SwitchEntity):
    """Switch to enable/disable capacity protection mode at runtime."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the capacity protection switch."""
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "capacity_protection"
        self._attr_unique_id = f"{entry.entry_id}_capacity_protection"
        self._attr_icon = "mdi:battery-lock"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if capacity protection is active."""
        return self.controller.capacity_protection_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable capacity protection mode."""
        self.controller.capacity_protection_enabled = True
        new_data = dict(self.entry.data)
        new_data[CONF_CAPACITY_PROTECTION_ENABLED] = True
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Capacity Protection ENABLED (SOC threshold: %d%%, peak limit: %dW)",
                     self.controller.capacity_protection_soc_threshold,
                     self.controller.capacity_protection_limit)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable capacity protection mode."""
        self.controller.capacity_protection_enabled = False
        new_data = dict(self.entry.data)
        new_data[CONF_CAPACITY_PROTECTION_ENABLED] = False
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Capacity Protection DISABLED")
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


class ChargeDelaySwitch(SwitchEntity):
    """Switch to enable/disable the charge delay feature at runtime."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the charge delay switch."""
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "charge_delay"
        self._attr_unique_id = f"{entry.entry_id}_charge_delay"
        self._attr_icon = "mdi:battery-clock"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if charge delay is enabled."""
        return self.controller.charge_delay_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable charge delay."""
        self.controller.charge_delay_enabled = True
        self.controller._charge_delay_status["state"] = "Idle"
        new_data = dict(self.entry.data)
        new_data[CONF_ENABLE_CHARGE_DELAY] = True
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Charge Delay ENABLED")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable charge delay."""
        self.controller.charge_delay_enabled = False
        self.controller._charge_delay_status["state"] = "Disabled"
        new_data = dict(self.entry.data)
        new_data[CONF_ENABLE_CHARGE_DELAY] = False
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Charge Delay DISABLED")
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


class ExcludedDeviceEnabledSwitch(SwitchEntity):
    """Switch to enable/disable an individual excluded device at runtime.

    ON  = Device is active — its power affects battery charge/discharge calculations.
    OFF = Device is ignored — battery sees raw home sensor power for this device.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, index: int) -> None:
        """Initialize the excluded device enabled switch."""
        self.hass = hass
        self.entry = entry
        self._device_index = index

        device = entry.data.get("excluded_devices", [])[index]
        sensor_id = device.get("power_sensor", "")
        friendly = sensor_id.replace("sensor.", "").replace("_", " ").title()

        self._attr_has_entity_name = True
        self._attr_translation_key = "excluded_device_enabled"
        self._attr_translation_placeholders = {"device": friendly}
        self._attr_unique_id = f"{entry.entry_id}_excluded_device_enabled_{index}"
        self._attr_icon = "mdi:power-plug-off"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if this excluded device is active."""
        devices = self.entry.data.get("excluded_devices", [])
        if self._device_index < len(devices):
            return devices[self._device_index].get("enabled", True)
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return the power sensor entity as an attribute."""
        devices = self.entry.data.get("excluded_devices", [])
        if self._device_index >= len(devices):
            return {}
        device = devices[self._device_index]
        return {
            "power_sensor": device.get("power_sensor", ""),
            "included_in_consumption": device.get("included_in_consumption", True),
        }

    async def _update_enabled(self, enabled: bool) -> None:
        """Update enabled state for this device in config_entry.data."""
        new_data = dict(self.entry.data)
        devices = [dict(d) for d in new_data.get("excluded_devices", [])]
        if self._device_index < len(devices):
            devices[self._device_index]["enabled"] = enabled
            new_data["excluded_devices"] = devices
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)
            state = "enabled" if enabled else "disabled"
            _LOGGER.info(
                "Excluded device %d (%s) %s",
                self._device_index + 1,
                devices[self._device_index].get("power_sensor", ""),
                state,
            )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable this excluded device."""
        await self._update_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable this excluded device."""
        await self._update_enabled(False)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


class ExcludedDeviceSolarSurplusSwitch(SwitchEntity):
    """Switch to toggle solar surplus priority for an excluded device at runtime.

    ON  = Battery does NOT charge with solar surplus while this device is consuming
          (solar goes to the device first — EV/priority mode).
    OFF = Battery charges normally with solar surplus regardless of this device.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, index: int) -> None:
        """Initialize the solar surplus switch."""
        self.hass = hass
        self.entry = entry
        self._device_index = index

        device = entry.data.get("excluded_devices", [])[index]
        sensor_id = device.get("power_sensor", "")
        # Derive a friendly name from the sensor entity ID
        friendly = sensor_id.replace("sensor.", "").replace("_", " ").title()

        self._attr_has_entity_name = True
        self._attr_translation_key = "excluded_device_solar_surplus"
        self._attr_translation_placeholders = {"device": friendly}
        self._attr_unique_id = f"{entry.entry_id}_solar_surplus_{index}"
        self._attr_icon = "mdi:solar-power-variant"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if solar surplus priority is active for this device."""
        devices = self.entry.data.get("excluded_devices", [])
        if self._device_index < len(devices):
            return devices[self._device_index].get("allow_solar_surplus", False)
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return the power sensor entity as an attribute."""
        devices = self.entry.data.get("excluded_devices", [])
        if self._device_index >= len(devices):
            return {}
        device = devices[self._device_index]
        return {
            "power_sensor": device.get("power_sensor", ""),
            "included_in_consumption": device.get("included_in_consumption", True),
        }

    async def _update_solar_surplus(self, enabled: bool) -> None:
        """Update allow_solar_surplus for this device in config_entry.data."""
        new_data = dict(self.entry.data)
        devices = [dict(d) for d in new_data.get("excluded_devices", [])]
        if self._device_index < len(devices):
            devices[self._device_index]["allow_solar_surplus"] = enabled
            new_data["excluded_devices"] = devices
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)
            state = "enabled" if enabled else "disabled"
            _LOGGER.info(
                "Solar surplus priority for device %d (%s) %s",
                self._device_index + 1,
                devices[self._device_index].get("power_sensor", ""),
                state,
            )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable solar surplus priority (battery yields solar to this device)."""
        await self._update_solar_surplus(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable solar surplus priority (battery charges normally)."""
        await self._update_solar_surplus(False)

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

        self._attr_has_entity_name = True
        self._attr_translation_key = "manual_mode"
        self._attr_unique_id = f"{entry.entry_id}_manual_mode"
        self._attr_icon = "mdi:hand-back-right"
        self._attr_should_poll = False

    @property
    def is_on(self) -> bool:
        """Return True if manual mode is active."""
        return self.controller.manual_mode_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable manual mode to pause automatic control."""
        self.controller.manual_mode_enabled = True
        new_data = dict(self.entry.data)
        new_data[CONF_MANUAL_MODE_ENABLED] = True
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Manual Mode ENABLED - automatic control paused")

        # Set all batteries to 0W (idle state) when entering manual mode
        for coordinator in self.controller.coordinators:
            try:
                charge_reg = coordinator.get_register("set_charge_power")
                discharge_reg = coordinator.get_register("set_discharge_power")
                force_reg = coordinator.get_register("force_mode")

                if charge_reg:
                    await coordinator.write_register(charge_reg, 0, do_refresh=False)
                if discharge_reg:
                    await coordinator.write_register(discharge_reg, 0, do_refresh=False)
                if force_reg:
                    await coordinator.write_register(force_reg, 0, do_refresh=False)

                await coordinator.async_request_refresh()
                _LOGGER.info("Set %s to 0W (idle) for manual mode", coordinator.name)
            except Exception as e:
                _LOGGER.error("Failed to set %s to 0W: %s", coordinator.name, e)

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
        new_data = dict(self.entry.data)
        new_data[CONF_MANUAL_MODE_ENABLED] = False
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

        # Reset PD controller state for clean transition
        self.controller.error_integral = 0.0
        self.controller.previous_error = 0.0
        self.controller.sign_changes = 0
        self.controller._active_discharge_batteries = []
        self.controller._active_charge_batteries = []

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


