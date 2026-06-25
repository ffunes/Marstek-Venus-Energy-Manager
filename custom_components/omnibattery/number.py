"""Number platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONFIG_NUMBER_DEFINITIONS,
    CONF_ENABLE_SYSTEM_POWER_LIMITS,
    CONF_SYSTEM_MAX_CHARGE_POWER,
    CONF_SYSTEM_MAX_DISCHARGE_POWER,
    CONF_MAX_PRICE_THRESHOLD,
    CONF_DISCHARGE_PRICE_THRESHOLD,
    CONF_PREDICTIVE_CHARGING_MODE,
    CONF_PRICE_INTEGRATION_TYPE,
    PREDICTIVE_MODE_DYNAMIC_PRICING,
    PRICE_INTEGRATION_CKW,
    MIN_CHARGE_HYSTERESIS_PERCENT,
    MAX_CHARGE_HYSTERESIS_PERCENT,
    DOMAIN,
)
from .infra.coordinator import MarstekVenusDataUpdateCoordinator
from .infra.entity_naming import english_entity_id, system_entity_id, SYSTEM_UNIQUE_ID_PREFIX

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []

    # Add Modbus register numbers (per battery)
    for coordinator in coordinators:
        for definition in coordinator.number_definitions:
            entities.append(MarstekVenusNumber(coordinator, definition))
        entities.append(MarstekBackupThresholdNumber(coordinator))

        # For batteries without hardware SOC cutoff registers (v3/vA/vD), expose
        # software-enforced max/min SOC as live-editable entities. The PD controller
        # already enforces these in software; previously they were only changeable
        # through the options flow.
        if not coordinator.capabilities.hardware_soc_cutoff:
            entities.append(MarstekSoftSocLimitNumber(coordinator, "max"))
            entities.append(MarstekSoftSocLimitNumber(coordinator, "min"))

        if coordinator.enable_charge_hysteresis:
            entities.append(MarstekChargeHysteresisNumber(coordinator))

        # Drivers without force_mode/set_*_power registers (Zendure) get
        # software manual-power setpoints; the controller applies them via
        # apply_setpoint while global manual mode is active.
        if coordinator.needs_software_manual_control:
            entities.append(MarstekManualSetPowerNumber(coordinator, "charge"))
            entities.append(MarstekManualSetPowerNumber(coordinator, "discharge"))

        # Drivers whose max_charge_power is a read-only device cap (Zendure) get
        # a software charge-power ceiling instead of the writable register entity.
        if coordinator.needs_software_max_charge:
            entities.append(MarstekSoftMaxChargeNumber(coordinator))

    # Add config numbers (system-level, PD parameters)
    for definition in CONFIG_NUMBER_DEFINITIONS:
        # Skip conditional entities if their feature has never been configured
        condition = definition.get("condition")
        if (
            condition
            and condition not in entry.data
            and condition != CONF_ENABLE_SYSTEM_POWER_LIMITS
        ):
            continue
        condition_enabled = entry.data.get(condition, False)
        if condition == CONF_ENABLE_SYSTEM_POWER_LIMITS and condition not in entry.data:
            condition_enabled = (
                (entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, 0) or 0) > 0
                or (entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, 0) or 0) > 0
            )
        if condition and definition.get("condition_enabled") and not condition_enabled:
            continue
        entities.append(MarstekConfigNumberEntity(hass, entry, definition))

    # Dynamic-pricing charge ceiling / discharge floor as live entities (#408),
    # so automations can rewrite them. Scoped to dynamic-pricing mode (the
    # discharge floor only applies there).
    if (
        entry.data.get("enable_predictive_charging")
        and entry.data.get(CONF_PREDICTIVE_CHARGING_MODE) == PREDICTIVE_MODE_DYNAMIC_PRICING
    ):
        entities.append(MarstekPriceThresholdNumber(hass, entry, "charge"))
        entities.append(MarstekPriceThresholdNumber(hass, entry, "discharge"))

    # Per-excluded-device "exclusion %" sliders (runtime adjustable). EV
    # no-telemetry devices have no numeric power sensor, so the slider would do
    # nothing for them — skip those.
    for index, device in enumerate(entry.data.get("excluded_devices", [])):
        if device.get("ev_charger_no_telemetry", False):
            continue
        entities.append(ExcludedDeviceExclusionPctNumber(hass, entry, index))

    async_add_entities(entities)


class MarstekVenusNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Marstek Venus number."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self.entity_id = english_entity_id("number", coordinator.name, definition["key"])
        self._attr_icon = definition.get("icon")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_native_min_value = definition["min"]
        self._attr_native_max_value = definition["max"]
        self._attr_native_step = definition["step"]
        self._attr_entity_registry_enabled_default = definition.get("enabled_by_default", True)
        self._attr_should_poll = False
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
        
        # Write the converted value via the logical control key
        await self.coordinator.write_control(self.definition["key"], register_value, do_refresh=True)
        
        # Update coordinator attributes immediately for control loop
        # This ensures changes take effect immediately without waiting for scan_interval
        if self.definition['key'] == 'charging_cutoff_capacity':
            old_max_soc = self.coordinator.max_soc
            self.coordinator.max_soc = value
            self.coordinator.persist_battery_config("max_soc", int(value))

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
            self.coordinator.persist_battery_config("min_soc", int(value))
            _LOGGER.info("%s: Updated min_soc %.1f%% → %.1f%% (immediate sync)",
                         self.coordinator.name, old_min_soc, value)

        elif self.definition['key'] == 'max_charge_power':
            old_value = self.coordinator.max_charge_power
            self.coordinator.max_charge_power = int(value)
            self.coordinator.persist_battery_config("max_charge_power", int(value))
            _LOGGER.info("%s: Updated max_charge_power %dW → %dW (immediate sync)",
                         self.coordinator.name, old_value, int(value))

        elif self.definition['key'] == 'max_discharge_power':
            old_value = self.coordinator.max_discharge_power
            self.coordinator.max_discharge_power = int(value)
            self.coordinator.persist_battery_config("max_discharge_power", int(value))
            _LOGGER.info("%s: Updated max_discharge_power %dW → %dW (immediate sync)",
                         self.coordinator.name, old_value, int(value))

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class MarstekConfigNumberEntity(NumberEntity):
    """Number entity for system-level configuration parameters (PD controller, etc.)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, definition: dict) -> None:
        """Initialize the config number entity."""
        self.hass = hass
        self.entry = entry
        self._definition = definition
        self._key = definition["key"]

        self._attr_has_entity_name = True
        self._attr_translation_key = definition["key"]
        self._attr_unique_id = f"{SYSTEM_UNIQUE_ID_PREFIX}{definition['key']}"
        self.entity_id = system_entity_id("number", definition["key"])
        self._attr_icon = definition.get("icon")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_native_min_value = definition["min"]
        self._attr_native_max_value = definition["max"]
        self._attr_native_step = definition["step"]
        self._attr_mode = NumberMode.SLIDER
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_should_poll = False
        self._scale = definition.get("scale", 1)

    async def async_added_to_hass(self) -> None:
        """Refresh the slider when config_entry.data changes.

        Selecting a PD tuning profile rewrites Kp/Kd/deadband/max-change in
        config_entry.data; without this the slider would keep showing its old
        value until HA reloads. Mirrors the profile select's own listener.
        """
        self.async_on_remove(self.entry.add_update_listener(self._handle_entry_update))

    async def _handle_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Re-render the slider value after a config entry update."""
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the current value from config_entry.data, converted to display units."""
        raw = self.entry.data.get(self._key, self._definition["default"])
        return raw / self._scale

    async def async_set_native_value(self, value: float) -> None:
        """Update the value in config_entry.data and hot-reload controller."""
        new_data = dict(self.entry.data)
        new_data[self._key] = int(value * self._scale) if self._scale != 1 else value
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

        # Hot-reload PD params in the controller without restarting the integration
        controller = self.hass.data[DOMAIN][self.entry.entry_id].get("controller")
        if controller:
            controller.update_pd_parameters()

        _LOGGER.info("Config parameter %s updated to %s", self._key, value)
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


class MarstekPriceThresholdNumber(NumberEntity):
    """Live-editable dynamic-pricing charge ceiling / discharge floor (#408).

    Mirrors the optional config-flow value into ``config_entry.data`` so an
    automation can rewrite it via ``number.set_value``. ``update_pd_parameters``
    re-reads both thresholds on every entry update (the same hot-reload hook the
    options flow uses), so changes take effect on the next control cycle. The
    value may be unset (``None`` → ``unknown`` state); the engine then falls back
    (discharge → charge ceiling → daily average).
    """

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -1.0
    _attr_native_max_value = 2.0
    _attr_native_step = 0.001
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, kind: str) -> None:
        """kind = 'charge' (max_price_threshold) or 'discharge' (discharge floor)."""
        self.hass = hass
        self.entry = entry
        self._kind = kind
        key = "max_price_threshold" if kind == "charge" else "discharge_price_threshold"
        self._conf_key = CONF_MAX_PRICE_THRESHOLD if kind == "charge" else CONF_DISCHARGE_PRICE_THRESHOLD
        self._attr_translation_key = key
        # unique_id keeps the legacy prefix (registry identity → preserves history
        # across the Omnibattery rebrand); only the entity_id is rebranded.
        self._attr_unique_id = f"{SYSTEM_UNIQUE_ID_PREFIX}{key}"
        self.entity_id = system_entity_id("number", key)
        self._attr_icon = "mdi:cash-plus" if kind == "charge" else "mdi:cash-minus"
        is_chf = entry.data.get(CONF_PRICE_INTEGRATION_TYPE) == PRICE_INTEGRATION_CKW
        self._attr_native_unit_of_measurement = "CHF/kWh" if is_chf else "€/kWh"

    async def async_added_to_hass(self) -> None:
        """Refresh state when config_entry.data changes (options flow / sibling write)."""
        self.async_on_remove(self.entry.add_update_listener(self._handle_entry_update))

    async def _handle_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Current threshold from config_entry.data (None → unknown)."""
        return self.entry.data.get(self._conf_key)

    async def async_set_native_value(self, value: float) -> None:
        """Persist after enforcing charge ceiling <= discharge floor (#408)."""
        max_price = self.entry.data.get(CONF_MAX_PRICE_THRESHOLD)
        discharge_price = self.entry.data.get(CONF_DISCHARGE_PRICE_THRESHOLD)
        if self._kind == "charge" and discharge_price is not None and value > discharge_price:
            raise ServiceValidationError(
                f"Charge threshold ({value}) cannot exceed the discharge floor ({discharge_price})."
            )
        if self._kind == "discharge" and max_price is not None and value < max_price:
            raise ServiceValidationError(
                f"Discharge floor ({value}) cannot be below the charge threshold ({max_price})."
            )

        new_data = dict(self.entry.data)
        new_data[self._conf_key] = value
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.info("Dynamic pricing %s price threshold updated to %s", self._kind, value)
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


class ExcludedDeviceExclusionPctNumber(NumberEntity):
    """Runtime slider: percentage of an excluded device's demand kept excluded
    from the battery.

    100% (default) = device fully excluded (battery never covers it — original
    behaviour). Lower values let the battery cover the remaining fraction
    (e.g. 60% → battery may cover 40% of the device's demand). Mirrors the
    per-device Solar Surplus switch: stores the value in config_entry.data and
    is read each control cycle by ExternalLoads._exclusion_factor().
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, index: int) -> None:
        """Initialize the exclusion-percentage slider for one excluded device."""
        self.hass = hass
        self.entry = entry
        self._device_index = index

        device = entry.data.get("excluded_devices", [])[index]
        sensor_id = device.get("power_sensor", "")
        friendly = sensor_id.replace("sensor.", "").replace("_", " ").title()

        self._attr_has_entity_name = True
        self._attr_translation_key = "excluded_device_exclusion_pct"
        self._attr_translation_placeholders = {"device": friendly}
        self._attr_unique_id = f"{SYSTEM_UNIQUE_ID_PREFIX}exclusion_pct_{index}"
        self.entity_id = system_entity_id("number", f"exclusion_pct_{index}")
        self._attr_icon = "mdi:battery-charging-50"
        self._attr_native_unit_of_measurement = "%"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 5
        self._attr_mode = NumberMode.SLIDER
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_should_poll = False

    async def async_added_to_hass(self) -> None:
        """Re-render the slider when config_entry.data changes (e.g. reconfigure)."""
        self.async_on_remove(self.entry.add_update_listener(self._handle_entry_update))

    async def _handle_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Return the current exclusion percentage (default 100 = fully excluded)."""
        devices = self.entry.data.get("excluded_devices", [])
        if self._device_index < len(devices):
            return float(devices[self._device_index].get("exclusion_pct", 100))
        return 100.0

    async def async_set_native_value(self, value: float) -> None:
        """Persist the exclusion percentage for this device in config_entry.data."""
        new_data = dict(self.entry.data)
        devices = [dict(d) for d in new_data.get("excluded_devices", [])]
        if self._device_index < len(devices):
            devices[self._device_index]["exclusion_pct"] = int(value)
            new_data["excluded_devices"] = devices
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)
            _LOGGER.info(
                "Exclusion percentage for device %d (%s) → %d%%",
                self._device_index + 1,
                devices[self._device_index].get("power_sensor", ""),
                int(value),
            )
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


class MarstekSoftSocLimitNumber(CoordinatorEntity, NumberEntity):
    """Software-enforced SOC limit for batteries that don't expose hardware cutoff registers (v3/vA/vD).

    Mirrors the UX of the v2 charging/discharging_cutoff_capacity number entities,
    but writes only to coordinator state and config_entry.data — no Modbus write.
    The PD controller reads coordinator.max_soc / coordinator.min_soc each cycle.
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator, kind: str) -> None:
        """Initialize. kind must be 'max' or 'min'."""
        super().__init__(coordinator)
        self._kind = kind
        self._attr_has_entity_name = True
        self._attr_native_unit_of_measurement = "%"
        self._attr_native_step = 1
        self._attr_should_poll = False
        if kind == "max":
            self._attr_translation_key = "charging_cutoff_capacity"
            self._attr_unique_id = f"{coordinator.device_key}_charging_cutoff_capacity"
            self._attr_icon = "mdi:battery-arrow-up"
            self._attr_native_min_value = 50
            self._attr_native_max_value = 100
        else:
            self._attr_translation_key = "discharging_cutoff_capacity"
            self._attr_unique_id = f"{coordinator.device_key}_discharging_cutoff_capacity"
            self._attr_icon = "mdi:battery-arrow-down"
            self._attr_native_min_value = 12
            self._attr_native_max_value = 50
        self.entity_id = english_entity_id("number", coordinator.name, self._attr_translation_key)

    @property
    def native_value(self) -> float:
        """Return the current software limit."""
        if self._kind == "max":
            return float(self.coordinator.max_soc)
        return float(self.coordinator.min_soc)

    async def async_set_native_value(self, value: float) -> None:
        """Update the limit on the coordinator and persist it."""
        new_value = int(value)
        if self._kind == "max":
            old = self.coordinator.max_soc
            self.coordinator.max_soc = new_value
            self.coordinator.persist_battery_config("max_soc", new_value)
            # Mirror v2 hysteresis-reset behavior when raising the limit
            if self.coordinator.enable_charge_hysteresis:
                current_soc = self.coordinator.data.get("battery_soc", 0) if self.coordinator.data else 0
                if new_value > old and current_soc < new_value:
                    self.coordinator._hysteresis_active = False
                    _LOGGER.info("%s: Hysteresis reset (max_soc %d%% → %d%%, SOC=%.1f%%)",
                                 self.coordinator.name, old, new_value, current_soc)
            _LOGGER.info("%s: max_soc %d%% → %d%% (software limit)",
                         self.coordinator.name, old, new_value)
        else:
            old = self.coordinator.min_soc
            self.coordinator.min_soc = new_value
            self.coordinator.persist_battery_config("min_soc", new_value)
            _LOGGER.info("%s: min_soc %d%% → %d%% (software limit)",
                         self.coordinator.name, old, new_value)
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


class MarstekBackupThresholdNumber(CoordinatorEntity, NumberEntity):
    """Number entity for the per-battery backup offgrid load threshold.

    This value has no Modbus register — it is a software-only config parameter
    stored in config_entry.data and read by the PD controller at runtime.
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "backup_offgrid_threshold"
        self._attr_unique_id = f"{coordinator.device_key}_backup_offgrid_threshold"
        self.entity_id = english_entity_id("number", coordinator.name, "backup_offgrid_threshold")
        self._attr_icon = "mdi:transmission-tower-off"
        self._attr_native_unit_of_measurement = "W"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 500
        self._attr_native_step = 10
        self._attr_should_poll = False

    @property
    def native_value(self) -> float:
        """Return the current threshold from the coordinator."""
        return float(self.coordinator.backup_offgrid_threshold)

    async def async_set_native_value(self, value: float) -> None:
        """Update the threshold on the coordinator and persist it."""
        self.coordinator.backup_offgrid_threshold = int(value)
        self.coordinator.persist_battery_config("backup_offgrid_threshold", int(value))
        _LOGGER.info(
            "%s: backup_offgrid_threshold updated to %dW",
            self.coordinator.name, int(value),
        )
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


class MarstekManualSetPowerNumber(CoordinatorEntity, NumberEntity):
    """Manual charge/discharge power setpoint for drivers without force_mode /
    set_*_power registers (Zendure).

    Mirrors the UX of the Marstek set_charge_power/set_discharge_power register
    entities, but writes only to coordinator state. While the global Manual Mode
    switch is on, the controller asserts this value via the driver's
    apply_setpoint each cycle (see _apply_software_manual_setpoints).
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator, kind: str) -> None:
        """Initialize. kind must be 'charge' or 'discharge'."""
        super().__init__(coordinator)
        self._kind = kind
        self._attr_has_entity_name = True
        self._attr_native_unit_of_measurement = "W"
        self._attr_native_min_value = 0
        self._attr_native_step = 10
        self._attr_should_poll = False
        if kind == "charge":
            self._attr_translation_key = "set_charge_power"
            self._attr_unique_id = f"{coordinator.device_key}_set_charge_power"
            self._attr_icon = "mdi:battery-arrow-up-outline"
            self._attr_native_max_value = coordinator.capabilities.max_charge_power_w
        else:
            self._attr_translation_key = "set_discharge_power"
            self._attr_unique_id = f"{coordinator.device_key}_set_discharge_power"
            self._attr_icon = "mdi:battery-arrow-down-outline"
            self._attr_native_max_value = coordinator.capabilities.max_discharge_power_w
        self.entity_id = english_entity_id("number", coordinator.name, self._attr_translation_key)

    @property
    def native_value(self) -> float:
        """Return the live commanded power (mirrors the active setpoint, like the
        Marstek register entity)."""
        if self._kind == "charge":
            return float(self.coordinator.commanded_charge_power)
        return float(self.coordinator.commanded_discharge_power)

    async def async_set_native_value(self, value: float) -> None:
        """Store the manual target (used in manual mode) and reflect it now.

        The optimistic commanded update avoids the slider snapping back to the
        old value before the next control cycle re-asserts it.
        """
        new_value = int(value)
        if self._kind == "charge":
            self.coordinator.manual_set_charge_power = new_value
            self.coordinator.persist_battery_config("manual_set_charge_power", new_value)
            if new_value > 0:
                self.coordinator.commanded_charge_power = new_value
                self.coordinator.commanded_discharge_power = 0
                self.coordinator.manual_set_discharge_power = 0
                self.coordinator.manual_force_mode = "Charge"
                self.coordinator.persist_battery_config("manual_set_discharge_power", 0)
                self.coordinator.persist_battery_config("manual_force_mode", "Charge")
        else:
            self.coordinator.manual_set_discharge_power = new_value
            self.coordinator.persist_battery_config("manual_set_discharge_power", new_value)
            if new_value > 0:
                self.coordinator.commanded_discharge_power = new_value
                self.coordinator.commanded_charge_power = 0
                self.coordinator.manual_set_charge_power = 0
                self.coordinator.manual_force_mode = "Discharge"
                self.coordinator.persist_battery_config("manual_set_charge_power", 0)
                self.coordinator.persist_battery_config("manual_force_mode", "Discharge")
        _LOGGER.info("%s: manual_set_%s_power → %dW", self.coordinator.name, self._kind, new_value)
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


class MarstekSoftMaxChargeNumber(CoordinatorEntity, NumberEntity):
    """Software charge-power ceiling for drivers whose reported max_charge_power
    is a read-only device cap (Zendure chargeMaxLimit).

    Stores a user limit on the coordinator; the poll loop applies
    min(device_cap, user limit) to coordinator.max_charge_power, which the PD
    allocator honours. Uses the same translation_key as the Marstek writable
    register entity so the dashboard renders it as "Máx. carga".
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator) -> None:
        """Initialize the soft max-charge entity."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "max_charge_power"
        self._attr_unique_id = f"{coordinator.device_key}_max_charge_power"
        self.entity_id = english_entity_id("number", coordinator.name, "max_charge_power")
        self._attr_icon = "mdi:battery-arrow-up-outline"
        self._attr_native_unit_of_measurement = "W"
        self._attr_native_min_value = 0
        self._attr_native_max_value = coordinator.capabilities.max_charge_power_w
        self._attr_native_step = 10
        self._attr_should_poll = False

    @property
    def native_value(self) -> float:
        """Return the user-set charge ceiling."""
        return float(self.coordinator.user_max_charge_power)

    async def async_set_native_value(self, value: float) -> None:
        """Store the ceiling, persist it, and apply it against the device cap now."""
        new_value = int(value)
        self.coordinator.user_max_charge_power = new_value
        self.coordinator.persist_battery_config("user_max_charge_power", new_value)
        # Reflect immediately without waiting for the next poll.
        device_cap = None
        if self.coordinator.data is not None:
            device_cap = self.coordinator.data.get("max_charge_power")
        self.coordinator.max_charge_power = (
            min(int(device_cap), new_value) if device_cap is not None else new_value
        )
        _LOGGER.info("%s: user_max_charge_power → %dW", self.coordinator.name, new_value)
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


class MarstekChargeHysteresisNumber(CoordinatorEntity, NumberEntity):
    """Number entity for the per-battery charge hysteresis percentage.

    This value is stored in config_entry.data and read by the PD controller at runtime.
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "charge_hysteresis_percent"
        self._attr_unique_id = f"{coordinator.device_key}_charge_hysteresis_percent"
        self.entity_id = english_entity_id("number", coordinator.name, "charge_hysteresis_percent")
        self._attr_icon = "mdi:battery-sync"
        self._attr_native_unit_of_measurement = "%"
        self._attr_native_min_value = MIN_CHARGE_HYSTERESIS_PERCENT
        self._attr_native_max_value = MAX_CHARGE_HYSTERESIS_PERCENT
        self._attr_native_step = 1
        self._attr_should_poll = False

    @property
    def native_value(self) -> float:
        """Return the current hysteresis percentage from the coordinator."""
        return float(self.coordinator.charge_hysteresis_percent)

    async def async_set_native_value(self, value: float) -> None:
        """Update the hysteresis on the coordinator and persist it."""
        new_value = max(MIN_CHARGE_HYSTERESIS_PERCENT, int(value))
        old = self.coordinator.charge_hysteresis_percent
        self.coordinator.charge_hysteresis_percent = new_value
        self.coordinator.persist_battery_config("charge_hysteresis_percent", new_value)
        _LOGGER.info(
            "%s: charge_hysteresis_percent %d%% → %d%%",
            self.coordinator.name, old, new_value,
        )
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
