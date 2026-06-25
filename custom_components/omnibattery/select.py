"""Select platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_PD_TUNING_PROFILE,
    PD_PROFILE_CUSTOM,
    PD_TUNING_PROFILES,
    PD_TUNING_PROFILE_OPTIONS,
    pd_profile_from_params,
)
from .infra.coordinator import MarstekVenusDataUpdateCoordinator
from .infra.entity_naming import english_entity_id, system_entity_id, SYSTEM_UNIQUE_ID_PREFIX

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []

    # Add Modbus register selects (per battery)
    for coordinator in coordinators:
        for definition in coordinator.select_definitions:
            entities.append(MarstekVenusSelect(coordinator, definition))
        # Drivers without a force_mode register (Zendure) get a software force
        # mode; the controller applies it via apply_setpoint in manual mode.
        if coordinator.needs_software_manual_control:
            entities.append(MarstekManualForceModeSelect(coordinator))

    # Add weekly full charge day select (system-level)
    if entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False):
        entities.append(WeeklyFullChargeDaySelect(hass, entry))

    # Add PD tuning profile select (system-level, always available)
    entities.append(PdTuningProfileSelect(hass, entry))

    async_add_entities(entities)


class MarstekVenusSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Marstek Venus select."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self.entity_id = english_entity_id("select", coordinator.name, definition["key"])
        self._attr_options = list(definition["options"].keys())
        self._attr_entity_registry_enabled_default = definition.get("enabled_by_default", True)
        self._attr_should_poll = False
        self._options_map = definition["options"]

    @property
    def current_option(self):
        """Return the current option."""
        if self.definition.get("use_shadow_state"):
            shadow = self.coordinator.get_shadow_select(self.definition["key"])
            if shadow is not None:
                for option, val in self._options_map.items():
                    if val == shadow:
                        return option
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.definition["key"])
        for option, val in self._options_map.items():
            if val == value:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        value = self._options_map[option]
        await self.coordinator.write_control(self.definition["key"], value, do_refresh=True)
        if self.definition.get("use_shadow_state"):
            self.coordinator.set_shadow_select(self.definition["key"], value)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


WEEKDAY_OPTIONS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# Map full names to internal short codes used in config_entry.data and WEEKDAY_MAP
WEEKDAY_TO_CODE = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
}
CODE_TO_WEEKDAY = {v: k for k, v in WEEKDAY_TO_CODE.items()}


class WeeklyFullChargeDaySelect(SelectEntity):
    """Select entity to choose the day for weekly full charge."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the weekly full charge day select."""
        self.hass = hass
        self.entry = entry

        self._attr_has_entity_name = True
        self._attr_translation_key = "weekly_full_charge_day"
        self._attr_unique_id = f"{SYSTEM_UNIQUE_ID_PREFIX}weekly_full_charge_day"
        self.entity_id = system_entity_id("select", "weekly_full_charge_day")
        self._attr_icon = "mdi:calendar-week"
        self._attr_options = WEEKDAY_OPTIONS
        self._attr_should_poll = False

    @property
    def current_option(self) -> str:
        """Return the currently selected day as full name."""
        code = self.entry.data.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")
        return CODE_TO_WEEKDAY.get(code, "sunday")

    async def async_select_option(self, option: str) -> None:
        """Update the selected day in config_entry.data."""
        code = WEEKDAY_TO_CODE.get(option, option)
        new_data = dict(self.entry.data)
        new_data[CONF_WEEKLY_FULL_CHARGE_DAY] = code
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Weekly full charge day updated to %s (%s)", option, code)
        self.async_write_ha_state()

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Omnibattery System",
            "manufacturer": "Omnibattery",
            "model": "Multi-Battery System",
        }


class PdTuningProfileSelect(SelectEntity):
    """One-click PD tuning presets (system-level).

    Selecting a preset writes its PD gain parameters (Kp, Kd, max power change)
    into config_entry.data; the integration's existing config-entry update listener
    then hot-reloads them. Deadband is intentionally left to the user. The "custom"
    option leaves the sliders for manual fine-tuning. The displayed option is derived
    from the live parameters, so moving a profiled slider by hand falls back to
    "custom" automatically.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the PD tuning profile select."""
        self.hass = hass
        self.entry = entry

        self._attr_has_entity_name = True
        self._attr_translation_key = "pd_tuning_profile"
        self._attr_unique_id = f"{SYSTEM_UNIQUE_ID_PREFIX}pd_tuning_profile"
        self.entity_id = system_entity_id("select", "pd_tuning_profile")
        self._attr_icon = "mdi:tune-variant"
        self._attr_options = list(PD_TUNING_PROFILE_OPTIONS)
        self._attr_should_poll = False

    @property
    def current_option(self) -> str:
        """Return the active profile.

        An explicit "custom" selection sticks; otherwise the option is detected
        from the live parameters so a manual slider change reflects as "custom".
        """
        if self.entry.data.get(CONF_PD_TUNING_PROFILE) == PD_PROFILE_CUSTOM:
            return PD_PROFILE_CUSTOM
        return pd_profile_from_params(self.entry.data)

    async def async_select_option(self, option: str) -> None:
        """Apply a profile (writes its gain params) or switch to manual mode."""
        new_data = dict(self.entry.data)
        new_data[CONF_PD_TUNING_PROFILE] = option
        if option != PD_PROFILE_CUSTOM:
            new_data.update(PD_TUNING_PROFILES[option])
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        # The entry's update listener hot-reloads the controller's PD params.
        _LOGGER.info("PD tuning profile set to %s", option)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Refresh displayed option whenever the config entry changes.

        Manual PD slider moves update config_entry.data via the number entities;
        this keeps the profile select in sync (falling back to "custom").
        """
        self.async_on_remove(self.entry.add_update_listener(self._handle_entry_update))

    async def _handle_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Re-render the current option after a config entry update."""
        self.async_write_ha_state()

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Omnibattery System",
            "manufacturer": "Omnibattery",
            "model": "Multi-Battery System",
        }


# Software force mode: same option strings as the Marstek force_mode register
# select so the existing translations / dashboard label apply unchanged.
MANUAL_FORCE_MODE_OPTIONS = ["None", "Charge", "Discharge"]


class MarstekManualForceModeSelect(CoordinatorEntity, SelectEntity):
    """Software force mode for drivers without a force_mode register (Zendure).

    Stores the choice on the coordinator; while the global Manual Mode switch is
    on, the controller drives the battery to the matching charge/discharge
    setpoint via apply_setpoint (see _apply_software_manual_setpoints). "None"
    leaves the battery idle.
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator) -> None:
        """Initialize the software force-mode select."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "force_mode"
        self._attr_unique_id = f"{coordinator.device_key}_force_mode"
        self.entity_id = english_entity_id("select", coordinator.name, "force_mode")
        self._attr_options = MANUAL_FORCE_MODE_OPTIONS
        self._attr_icon = "mdi:gesture-tap-button"
        self._attr_should_poll = False

    @property
    def current_option(self) -> str:
        """Return the live force mode derived from the commanded power, mirroring
        the Marstek force_mode register (which the controller overwrites)."""
        if self.coordinator.commanded_charge_power > 0:
            return "Charge"
        if self.coordinator.commanded_discharge_power > 0:
            return "Discharge"
        return "None"

    async def async_select_option(self, option: str) -> None:
        """Store the manual force mode and reflect it now.

        The optimistic commanded update (using the stored manual power for the
        chosen direction) keeps the select on the picked option until the next
        control cycle re-asserts it, instead of snapping back.
        """
        self.coordinator.manual_force_mode = option
        if option == "Charge":
            self.coordinator.commanded_charge_power = self.coordinator.manual_set_charge_power
            self.coordinator.commanded_discharge_power = 0
        elif option == "Discharge":
            self.coordinator.commanded_charge_power = 0
            self.coordinator.commanded_discharge_power = self.coordinator.manual_set_discharge_power
        else:
            self.coordinator.commanded_charge_power = 0
            self.coordinator.commanded_discharge_power = 0
        self.coordinator.persist_battery_config("manual_force_mode", option)
        _LOGGER.info("%s: manual_force_mode → %s", self.coordinator.name, option)
        self.async_write_ha_state()

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


