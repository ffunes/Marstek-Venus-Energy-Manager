"""Sensor platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EFFICIENCY_SENSOR_DEFINITIONS,
    STORED_ENERGY_SENSOR_DEFINITIONS,
    CYCLE_SENSOR_DEFINITIONS,
    SOLAR_POWER_SENSOR_DEFINITIONS,
    BATTERY_CELL_POWER_SENSOR_DEFINITIONS,
    CONF_ENABLE_CHARGE_DELAY,
    CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY,
    CONF_ENABLE_PREDICTIVE_CHARGING,
    CONF_CHARGING_TIME_SLOT,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_HOUSEHOLD_CONSUMPTION_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_DELAY_SAFETY_MARGIN_MIN,
    CONF_DELAY_SOC_SETPOINT_ENABLED,
    CONF_DELAY_SOC_SETPOINT,
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
    CONF_TARGET_GRID_POWER,
    CONF_ENABLE_SYSTEM_POWER_LIMITS,
    CONF_SYSTEM_MAX_CHARGE_POWER,
    CONF_SYSTEM_MAX_DISCHARGE_POWER,
    DEFAULT_PD_KP,
    DEFAULT_PD_KD,
    DEFAULT_PD_DEADBAND,
    DEFAULT_PD_MAX_POWER_CHANGE,
    DEFAULT_PD_DIRECTION_HYSTERESIS,
    DEFAULT_PD_MIN_CHARGE_POWER,
    DEFAULT_PD_MIN_DISCHARGE_POWER,
    DEFAULT_TARGET_GRID_POWER,
    DEFAULT_SYSTEM_MAX_CHARGE_POWER,
    DEFAULT_SYSTEM_MAX_DISCHARGE_POWER,
    DEFAULT_DELAY_SAFETY_MARGIN_MIN,
    DEFAULT_DELAY_SOC_SETPOINT_ENABLED,
    DEFAULT_DELAY_SOC_SETPOINT,
    DEFAULT_CAPACITY_PROTECTION_SOC,
    DEFAULT_CAPACITY_PROTECTION_LIMIT,
    CONF_PREDICTIVE_CHARGING_MODE,
    CONF_PRICE_SENSOR,
    CONF_PRICE_INTEGRATION_TYPE,
    CONF_MAX_PRICE_THRESHOLD,
    CONF_AVERAGE_PRICE_SENSOR,
    CONF_DP_PRICE_DISCHARGE_CONTROL,
    CONF_RT_PRICE_DISCHARGE_CONTROL,
    CONF_METER_INVERTED,
    CONF_MANUAL_MODE_ENABLED,
    CONF_PREDICTIVE_CHARGING_OVERRIDDEN,
    CONF_PREDICTIVE_SAFETY_MARGIN_KWH,
    DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH,
    CONF_ENABLE_HOURLY_BALANCE,
    CONF_HOURLY_BALANCE_TARGET_NET_WH,
    CONF_HOURLY_BALANCE_MAX_OFFSET_W,
    CONF_HOURLY_BALANCE_DEADBAND_WH,
    CONF_HOURLY_BALANCE_HYSTERESIS_W,
    DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
    DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
    DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
    DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
    SLOT_BATTERY_SCOPE_ALL,
    DEFAULT_SLOT_MODE,
    DEFAULT_SLOT_ALLOW_CHARGE,
    DEFAULT_SLOT_ALLOW_DISCHARGE,
)
from .coordinator import MarstekVenusDataUpdateCoordinator
from .aggregate_sensors import AGGREGATE_SENSOR_DEFINITIONS, MarstekVenusAggregateSensor, DailyGridAtMinSocSensor, SystemAlarmSensor, PdControlQualitySensor
from .calculated_sensors import MarstekVenusEfficiencySensor, MarstekVenusStoredEnergySensor, MarstekVenusCycleSensor, MarstekVenusSolarPowerSensor, MarstekVenusBatteryCellPowerSensor

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

    # Add aggregate sensors. Created even for a single-battery system so the
    # "Marstek Venus System" device never exposes `unavailable` entities — with
    # one battery each aggregate simply mirrors that battery's value.
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
        # DC-coupled PV total + solar-corrected battery power exist only on
        # Venus D/A (units with MPPT registers).
        if coordinator.battery_version in ("vA", "vD"):
            for definition in SOLAR_POWER_SENSOR_DEFINITIONS:
                entities.append(MarstekVenusSolarPowerSensor(coordinator, definition))
            for definition in BATTERY_CELL_POWER_SENSOR_DEFINITIONS:
                entities.append(MarstekVenusBatteryCellPowerSensor(coordinator, definition))

    # Add discharge window diagnostic sensor (always, even without slots)
    entities.append(DischargeWindowSensor(hass, entry))

    # Add active batteries diagnostic sensor. The controller updates its
    # load-sharing tracking even for a single battery (see
    # _select_batteries_for_operation), so this reflects charging/discharging/idle
    # instead of staying unavailable.
    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    if controller:
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

    # Add integration status sensor (always, when controller is present)
    if controller:
        entities.append(IntegrationStatusSensor(hass, entry, controller))

    # Add non-responsive batteries sensor (always, when controller is present)
    if controller:
        entities.append(NonResponsiveBatteriesSensor(hass, entry, controller, coordinators))

    # Add daily grid-at-min-soc energy sensor (feeds into consumption estimation)
    if controller:
        entities.append(DailyGridAtMinSocSensor(controller))

    # Add PD control-quality diagnostic sensor (feeds the tuning-profile feedback)
    if controller:
        entities.append(PdControlQualitySensor(controller))

    # Exact daily energy totals from the real power sensors (panel "Energía hoy").
    # Each is added only when its source sensor is configured.
    if controller and getattr(controller, "solar_production_sensor", None):
        entities.append(DailySolarEnergySensor(controller))
    # Added when a dedicated household sensor OR the (always-present) net grid
    # meter is configured: with no household sensor the daily total is derived
    # from grid + battery AC + solar, matching the power-flow Home Consumption sensor.
    if controller and (
        getattr(controller, "household_consumption_sensor", None)
        or getattr(controller, "consumption_sensor", None)
    ):
        entities.append(DailyHomeEnergySensor(controller))
    # Grid import/export are sign-split from the net consumption meter, which is
    # always configured, so these are always added.
    if controller and getattr(controller, "consumption_sensor", None):
        entities.append(DailyGridImportEnergySensor(controller))
        entities.append(DailyGridExportEnergySensor(controller))



    # Add configuration summary diagnostic sensor (hidden, for support purposes)
    entities.append(ConfigurationSummarySensor(hass, entry))

    async_add_entities(entities)

    # Balance monitor sensors (registered separately so they get their own setup call)
    from . import balance_sensors as _balance_sensors
    await _balance_sensors.async_setup_entry(hass, entry, async_add_entities)

    # Hourly balance sensors
    from . import hourly_balance_sensors as _hourly_balance_sensors
    await _hourly_balance_sensors.async_setup_entry(hass, entry, async_add_entities)


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
        self._attr_unique_id = f"{coordinator.device_key}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_state_class = definition.get("state_class")
        self._attr_native_unit_of_measurement = definition.get("unit")
        self._attr_icon = definition.get("icon")
        self._attr_entity_registry_enabled_default = definition.get("enabled_by_default", True)
        if definition.get("category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if "precision" in definition and (definition.get("unit") or definition.get("state_class")):
            self._attr_suggested_display_precision = definition["precision"]
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
            "identifiers": {(DOMAIN, f"{self.coordinator.device_key}")},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
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
        # Only slots that govern discharge define a discharge window. Charge-only
        # slots (allow_discharge=False) leave discharge unrestricted.
        enabled_slots = [
            s for s in all_slots
            if s.get("enabled", True) and s.get("allow_discharge", DEFAULT_SLOT_ALLOW_DISCHARGE)
        ]

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
        enabled_slots = [
            s for s in all_slots
            if s.get("enabled", True) and s.get("allow_discharge", DEFAULT_SLOT_ALLOW_DISCHARGE)
        ]
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
            attrs[f"slot_{n}_mode"] = slot.get("mode", DEFAULT_SLOT_MODE)
            attrs[f"slot_{n}_battery_scope"] = slot.get("battery_scope", SLOT_BATTERY_SCOPE_ALL)
            attrs[f"slot_{n}_allow_charge"] = slot.get("allow_charge", DEFAULT_SLOT_ALLOW_CHARGE)
            attrs[f"slot_{n}_allow_discharge"] = slot.get("allow_discharge", DEFAULT_SLOT_ALLOW_DISCHARGE)

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
        completion_reason = self._controller._weekly_charge_status.get("completion_reason")
        if completion_reason:
            attrs["completion_reason"] = completion_reason
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


class ChargeDelaySensor(RestoreEntity, SensorEntity):
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

    async def async_added_to_hass(self) -> None:
        """Restore same-day charge-delay latch state after integration reload."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        same_day = (
            dt_util.as_local(last_state.last_updated).date()
            == dt_util.now().date()
        )
        if not same_day:
            return

        if (
            self._controller._delay_soc_setpoint_enabled
            and last_state.state in ("delayed", "waiting_for_solar", "charging_allowed")
        ):
            self._controller._delay_setpoint_reached = True
            _LOGGER.info("Charge Delay: restored SOC setpoint latch from previous state %s", last_state.state)

        if last_state.state == "charging_allowed":
            self._controller._charge_delay_unlocked = True
            _LOGGER.info("Charge Delay: restored same-day unlock state after reload")

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

        if state == "Skipped - Full Charge Day":
            return "skipped_full_charge_day"

        if state == "Charging to setpoint":
            return "charging_to_setpoint"

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
    """Hidden diagnostic sensor exposing support-relevant configuration attributes.

    Intended for support purposes: share this sensor's state card to give a
    concise picture of how the system is configured, without network details.
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

    @staticmethod
    def _entity_or_not_configured(value) -> str:
        """Return an entity ID or a stable placeholder for optional sensors."""
        return value if value else "not_configured"

    @staticmethod
    def _format_days(days: list[str]) -> str:
        """Return a compact day list for issue reports."""
        return ", ".join(day.capitalize() for day in days) if days else "None"

    @staticmethod
    def _battery_versions_summary(batteries: list[dict]) -> str:
        """Return compact counts by battery version."""
        counts: dict[str, int] = {}
        for battery in batteries:
            version = battery.get("battery_version", "unknown")
            counts[version] = counts.get(version, 0) + 1
        return ", ".join(f"{version}: {count}" for version, count in sorted(counts.items())) or "none"

    @property
    def extra_state_attributes(self) -> dict:
        """Return support-relevant integration configuration as attributes."""
        data = self.entry.data
        attrs = {}

        # --- General ---
        attrs["support_summary_version"] = 3
        attrs["grid_sensor"] = data.get("consumption_sensor")
        attrs["meter_inverted"] = data.get(CONF_METER_INVERTED, False)
        attrs["household_consumption_sensor"] = self._entity_or_not_configured(
            data.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR)
        )
        attrs["solar_forecast_sensor"] = self._entity_or_not_configured(
            data.get(CONF_SOLAR_FORECAST_SENSOR)
        )
        attrs["manual_mode_enabled"] = data.get(CONF_MANUAL_MODE_ENABLED, False)

        # --- Batteries ---
        batteries = data.get("batteries", [])
        attrs["num_batteries"] = len(batteries)
        attrs["battery_versions"] = self._battery_versions_summary(batteries)
        total_max_charge_power = sum(
            bat.get("max_charge_power", 0) or 0 for bat in batteries
        )
        total_max_discharge_power = sum(
            bat.get("max_discharge_power", 0) or 0 for bat in batteries
        )
        attrs["total_max_charge_power_W"] = total_max_charge_power
        attrs["total_max_discharge_power_W"] = total_max_discharge_power
        for i, bat in enumerate(batteries):
            n = i + 1
            attrs[f"battery_{n}_name"] = bat.get("name")
            attrs[f"battery_{n}_version"] = bat.get("battery_version")
            attrs[f"battery_{n}_max_charge_power_W"] = bat.get("max_charge_power")
            attrs[f"battery_{n}_max_discharge_power_W"] = bat.get("max_discharge_power")
            attrs[f"battery_{n}_max_soc"] = bat.get("max_soc")
            attrs[f"battery_{n}_min_soc"] = bat.get("min_soc")
            attrs[f"battery_{n}_charge_hysteresis_enabled"] = bat.get(
                "enable_charge_hysteresis", False
            )
            if bat.get("enable_charge_hysteresis"):
                attrs[f"battery_{n}_charge_hysteresis_percent"] = bat.get(
                    "charge_hysteresis_percent"
                )
            attrs[f"battery_{n}_backup_offgrid_threshold_W"] = bat.get(
                "backup_offgrid_threshold"
            )
            attrs[f"battery_{n}_full_charge_voltage_taper_enabled"] = bat.get(
                "full_charge_voltage_taper_enabled", True
            )

        # --- Time slots ---
        slots = data.get("no_discharge_time_slots", [])
        attrs["num_time_slots"] = len(slots)
        attrs["enabled_time_slots"] = sum(1 for slot in slots if slot.get("enabled", True))
        for i, slot in enumerate(slots):
            n = i + 1
            attrs[f"slot_{n}_schedule"] = f"{slot.get('start_time')}-{slot.get('end_time')}"
            attrs[f"slot_{n}_days"] = self._format_days(slot.get("days", []))
            attrs[f"slot_{n}_enabled"] = slot.get("enabled", True)
            attrs[f"slot_{n}_mode"] = slot.get("mode", DEFAULT_SLOT_MODE)
            attrs[f"slot_{n}_battery_scope"] = slot.get("battery_scope", SLOT_BATTERY_SCOPE_ALL)
            attrs[f"slot_{n}_allow_charge"] = slot.get("allow_charge", DEFAULT_SLOT_ALLOW_CHARGE)
            attrs[f"slot_{n}_allow_discharge"] = slot.get("allow_discharge", DEFAULT_SLOT_ALLOW_DISCHARGE)
            attrs[f"slot_{n}_soc_override_enabled"] = slot.get("soc_override_enabled", False)
            attrs[f"slot_{n}_power_override_enabled"] = slot.get("power_override_enabled", False)
            battery_limits = slot.get("battery_limits") or {}
            if battery_limits:
                attrs[f"slot_{n}_battery_limits"] = battery_limits

        # --- Predictive charging ---
        predictive_enabled = data.get(CONF_ENABLE_PREDICTIVE_CHARGING, False)
        attrs["predictive_charging_enabled"] = predictive_enabled
        attrs["predictive_charging_overridden"] = data.get(
            CONF_PREDICTIVE_CHARGING_OVERRIDDEN, False
        )
        attrs["predictive_charging_effective_enabled"] = (
            predictive_enabled
            and not data.get(CONF_PREDICTIVE_CHARGING_OVERRIDDEN, False)
        )
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
            attrs["predictive_safety_margin_kWh"] = data.get(
                CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH
            )

        # --- Weekly full charge ---
        weekly_enabled = data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False)
        attrs["weekly_full_charge_enabled"] = weekly_enabled
        if weekly_enabled:
            attrs["weekly_full_charge_day"] = data.get(CONF_WEEKLY_FULL_CHARGE_DAY)
            attrs["balance_monitor_enabled"] = True

        # --- Charge delay ---
        charge_delay = data.get(CONF_ENABLE_CHARGE_DELAY, False)
        weekly_delay = data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        attrs["charge_delay_enabled"] = charge_delay or weekly_delay
        if charge_delay or weekly_delay:
            attrs["charge_delay_for_weekly_charge"] = weekly_delay
            attrs["charge_delay_safety_margin_min"] = data.get(
                CONF_DELAY_SAFETY_MARGIN_MIN, DEFAULT_DELAY_SAFETY_MARGIN_MIN
            )
            attrs["charge_delay_soc_setpoint_enabled"] = data.get(
                CONF_DELAY_SOC_SETPOINT_ENABLED, DEFAULT_DELAY_SOC_SETPOINT_ENABLED
            )
            if data.get(CONF_DELAY_SOC_SETPOINT_ENABLED, DEFAULT_DELAY_SOC_SETPOINT_ENABLED):
                attrs["charge_delay_soc_setpoint"] = data.get(
                    CONF_DELAY_SOC_SETPOINT, DEFAULT_DELAY_SOC_SETPOINT
                )

        # --- Capacity protection ---
        cap_enabled = data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)
        attrs["capacity_protection_enabled"] = cap_enabled
        if cap_enabled:
            attrs["capacity_protection_soc_threshold"] = data.get(
                CONF_CAPACITY_PROTECTION_SOC_THRESHOLD, DEFAULT_CAPACITY_PROTECTION_SOC
            )
            attrs["capacity_protection_limit_W"] = data.get(
                CONF_CAPACITY_PROTECTION_LIMIT, DEFAULT_CAPACITY_PROTECTION_LIMIT
            )

        # --- Hourly net balance ---
        hourly_balance_configured = CONF_ENABLE_HOURLY_BALANCE in data
        attrs["hourly_balance_configured"] = hourly_balance_configured
        attrs["hourly_balance_enabled"] = data.get(CONF_ENABLE_HOURLY_BALANCE, False)
        if hourly_balance_configured:
            attrs["hourly_balance_target_net_kWh"] = data.get(
                CONF_HOURLY_BALANCE_TARGET_NET_WH,
                DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
            )
            attrs["hourly_balance_max_offset_W"] = data.get(
                CONF_HOURLY_BALANCE_MAX_OFFSET_W,
                DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
            )
            attrs["hourly_balance_deadband_kWh"] = data.get(
                CONF_HOURLY_BALANCE_DEADBAND_WH,
                DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
            )
            attrs["hourly_balance_hysteresis_W"] = data.get(
                CONF_HOURLY_BALANCE_HYSTERESIS_W,
                DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
            )

        # --- PD controller ---
        attrs["pd_target_grid_power_W"] = data.get(
            CONF_TARGET_GRID_POWER, DEFAULT_TARGET_GRID_POWER
        )
        attrs["pd_kp"] = data.get(CONF_PD_KP, DEFAULT_PD_KP)
        attrs["pd_kd"] = data.get(CONF_PD_KD, DEFAULT_PD_KD)
        attrs["pd_deadband_W"] = data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        attrs["pd_max_power_change_W"] = data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        attrs["pd_direction_hysteresis_W"] = data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        attrs["pd_min_charge_power_W"] = data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        attrs["pd_min_discharge_power_W"] = data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)
        system_max_charge_power = data.get(
            CONF_SYSTEM_MAX_CHARGE_POWER,
            DEFAULT_SYSTEM_MAX_CHARGE_POWER,
        )
        system_max_discharge_power = data.get(
            CONF_SYSTEM_MAX_DISCHARGE_POWER,
            DEFAULT_SYSTEM_MAX_DISCHARGE_POWER,
        )
        enable_system_power_limits = data.get(
            CONF_ENABLE_SYSTEM_POWER_LIMITS,
            (system_max_charge_power or 0) > 0 or (system_max_discharge_power or 0) > 0,
        )
        attrs["system_power_limits_enabled"] = enable_system_power_limits
        attrs["system_max_charge_power_W"] = system_max_charge_power
        attrs["system_max_discharge_power_W"] = system_max_discharge_power
        attrs["effective_total_max_charge_power_W"] = (
            min(total_max_charge_power, system_max_charge_power)
            if enable_system_power_limits and system_max_charge_power else total_max_charge_power
        )
        attrs["effective_total_max_discharge_power_W"] = (
            min(total_max_discharge_power, system_max_discharge_power)
            if enable_system_power_limits and system_max_discharge_power else total_max_discharge_power
        )

        # --- Excluded devices ---
        excluded = data.get("excluded_devices", [])
        attrs["num_excluded_devices"] = len(excluded)
        for i, dev in enumerate(excluded):
            n = i + 1
            attrs[f"excluded_device_{n}_sensor"] = dev.get("power_sensor")
            attrs[f"excluded_device_{n}_enabled"] = dev.get("enabled", True)
            attrs[f"excluded_device_{n}_included_in_consumption"] = dev.get("included_in_consumption", True)
            attrs[f"excluded_device_{n}_allow_solar_surplus"] = dev.get("allow_solar_surplus", False)
            attrs[f"excluded_device_{n}_ev_charger_no_telemetry"] = dev.get(
                "ev_charger_no_telemetry", False
            )

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


class IntegrationStatusSensor(SensorEntity):
    """Primary status sensor showing what the integration is currently doing.

    Provides a single at-a-glance state representing the highest-priority
    active mode, from manual override down to normal PD control.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the integration status sensor."""
        self.hass = hass
        self.entry = entry
        self._controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "integration_status"
        self._attr_unique_id = f"{entry.entry_id}_integration_status"
        self._attr_icon = "mdi:home-battery"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = True

    def _time_slot_blocked(self, direction: str) -> bool:
        """Return True when a time-slot whitelist blocks `direction` on every battery.

        Time-slot blockers are stored per-battery (`time_slot_charge` /
        `time_slot_discharge`), so the system-level status only reports the
        restriction when no available battery can act in that direction.
        """
        c = self._controller
        if direction == "discharge":
            getter, key = c.get_discharge_blockers, "time_slot_discharge"
        else:
            getter, key = c.get_charge_blockers, "time_slot_charge"
        coordinators = [
            coordinator
            for coordinator in c.coordinators
            if getattr(coordinator, "is_available", True)
        ]
        if not coordinators:
            return False
        return all(key in getter(coordinator) for coordinator in coordinators)

    def _hourly_balance_state_key(self) -> str | None:
        """Return the integration-status key for hourly net balance activity."""
        c = self._controller
        mgr = getattr(c, "_hourly_balance_mgr", None)
        if mgr is None or not getattr(c, "hourly_balance_enabled", False):
            return None

        return {
            "compensating_import": "hourly_balance_import",
            "compensating_export": "hourly_balance_export",
            "capped": "hourly_balance_capped",
            "compensation_stopped": "hourly_balance_blocked",
        }.get(mgr.get_state_label())

    def _capacity_protection_state_key(self) -> str | None:
        """Return the integration-status key for peak-shaving activity."""
        c = self._controller
        if not getattr(c, "_capacity_protection_active", False):
            return None

        action = c._capacity_protection_status.get("action")
        return {
            "shaving": "peak_shaving",
            "conserving": "capacity_conserving",
            "charging": "capacity_protection_charging",
        }.get(action, "capacity_protection")

    def _ev_charger_state_key(self) -> str | None:
        """Return the integration-status key for no-telemetry EV charger handling."""
        c = self._controller
        charge_blockers = c.get_charge_blockers()
        discharge_blockers = c.get_discharge_blockers()
        if "ev_pause" in charge_blockers or "ev_pause" in discharge_blockers:
            return "ev_charger_pause"
        if "ev_charging" in discharge_blockers:
            return "ev_discharge_blocked"
        return None

    def _balance_hold_batteries(self) -> list[str]:
        """Return batteries currently held by the cell-balance monitor."""
        return [
            coordinator.name
            for coordinator in self._controller.coordinators
            if getattr(coordinator, "balance_hold", False)
        ]

    def _backup_cooldown_batteries(self) -> list[str]:
        """Return batteries temporarily excluded because backup/offgrid load was active."""
        from homeassistant.util import dt as dt_util

        now = dt_util.utcnow()
        return [
            coordinator.name
            for coordinator, cooldown_until in self._controller._backup_cooldown_until.items()
            if cooldown_until and now < cooldown_until
        ]

    @property
    def native_value(self) -> str:
        """Return the current integration status as a translation key."""
        c = self._controller

        # Priority 1: Manual mode overrides everything
        if c.manual_mode_enabled:
            return "manual"

        # Priority 2: Predictive grid charging active
        if c.predictive_charging_enabled and c.grid_charging_active:
            return "grid_charging"

        # Priority 3: Weekly full charge in progress
        if c.weekly_full_charge_enabled:
            if c._weekly_charge_status.get("state") in ("Charging to 100%", "Active balancing"):
                return "weekly_full_charge"

        if any(
            status.get("state") == "active"
            for status in c.get_active_balance_mode_status().values()
        ):
            return "active_balance_mode"

        # Priority 4: Charge delay states
        if c.charge_delay_enabled:
            delay_state = c._charge_delay_status.get("state", "Idle")
            if delay_state.startswith("Delayed"):
                return "charge_delayed"
            if delay_state.startswith("Waiting"):
                return "waiting_for_solar"
            # Skip "charging_to_setpoint" if the controller is actively
            # discharging: _is_charge_delayed() is not called during discharge
            # so this state can be stale.
            if (
                delay_state == "Charging to setpoint"
                and c.previous_power >= 0
                and not getattr(c, "_capacity_protection_active", False)
            ):
                return "charging_to_setpoint"

        # Priority 5: Operational restrictions and feature overrides
        ev_state = self._ev_charger_state_key()
        if ev_state:
            return ev_state

        if self._balance_hold_batteries():
            return "cell_balance_hold"

        capacity_state = self._capacity_protection_state_key()
        if capacity_state:
            return capacity_state

        discharge_blockers = c.get_discharge_blockers()
        if "price_discharge" in discharge_blockers:
            return "price_discharge_blocked"

        hourly_state = self._hourly_balance_state_key()
        if hourly_state:
            return hourly_state

        if self._backup_cooldown_batteries():
            return "backup_mode"

        # Priority 6: Manual time slot forcing batteries off the PD path
        if getattr(c, "_manual_slot_owned", None):
            return "time_slot_manual"

        # Priority 7: Outside all configured operating windows
        if self._time_slot_blocked("discharge"):
            return "no_discharge_slot"
        if self._time_slot_blocked("charge"):
            return "no_charge_slot"

        # Priority 8: PD control state from last command
        if c.first_execution:
            return "initializing"

        prev_power = c.previous_power
        if prev_power > 0:
            return "charging"
        elif prev_power < 0:
            return "discharging"
        return "balanced"

    @property
    def extra_state_attributes(self) -> dict:
        """Return current controller details for diagnostics."""
        c = self._controller
        attrs = {
            "setpoint_active": c.compute_active_target(),
            "previous_power_w": c.previous_power,
            "first_execution": c.first_execution,
            "manual_mode_enabled": c.manual_mode_enabled,
            "grid_charging_active": c.grid_charging_active,
            "price_based_discharge_blocked": c._price_based_discharge_blocked,
            "charge_blocked": c.is_charge_effectively_blocked(),
            "discharge_blocked": c.is_discharge_effectively_blocked(),
        }
        charge_blockers = c.get_charge_blockers()
        if charge_blockers:
            attrs["charge_blockers"] = charge_blockers
        discharge_blockers = c.get_discharge_blockers()
        if discharge_blockers:
            attrs["discharge_blockers"] = discharge_blockers
        battery_charge_blockers = c.get_battery_charge_blockers()
        if battery_charge_blockers:
            attrs["battery_charge_blockers"] = battery_charge_blockers
        battery_discharge_blockers = c.get_battery_discharge_blockers()
        if battery_discharge_blockers:
            attrs["battery_discharge_blockers"] = battery_discharge_blockers
        offsets = dict(c._setpoint_offsets)
        if offsets:
            attrs["setpoint_offsets"] = offsets
        overrides = {k: v[1] for k, v in c._setpoint_overrides.items()}
        if overrides:
            attrs["setpoint_overrides"] = overrides
        attrs["capacity_protection"] = dict(c._capacity_protection_status)

        if c.predictive_charging_enabled:
            attrs["predictive_charging_mode"] = c.predictive_charging_mode
            attrs["predictive_charging_overridden"] = c.predictive_charging_overridden
            attrs["dynamic_price_slot_active"] = c._current_price_slot_active
            attrs["realtime_price_charging"] = c._realtime_price_charging
            attrs["price_data_status"] = c._price_data_status

        mgr = getattr(c, "_hourly_balance_mgr", None)
        if mgr is not None:
            status = mgr.get_status_dict()
            attrs["hourly_balance_status"] = mgr.get_state_label()
            attrs["hourly_balance_offset_w"] = status["offset_w"]
            attrs["hourly_balance_theoretical_offset_w"] = status["theoretical_offset_w"]
            attrs["hourly_balance_net_kwh"] = status["net_kwh"]
            attrs["hourly_balance_remaining_min"] = status["remaining_min"]
            if status["charge_block_reason"]:
                attrs["hourly_balance_charge_block_reason"] = status["charge_block_reason"]

        balance_hold_batteries = self._balance_hold_batteries()
        if balance_hold_batteries:
            attrs["balance_hold_batteries"] = balance_hold_batteries

        backup_cooldown_batteries = self._backup_cooldown_batteries()
        if backup_cooldown_batteries:
            attrs["backup_cooldown_batteries"] = backup_cooldown_batteries

        ev_chargers = [entity_id for entity_id, active in c._ev_charging_states.items() if active]
        if ev_chargers:
            attrs["ev_chargers_active"] = ev_chargers
        if c._ev_pause_until:
            attrs["ev_pause_until"] = {
                entity_id: pause_until.isoformat()
                for entity_id, pause_until in c._ev_pause_until.items()
                if pause_until is not None
            }

        normal_balance = c.get_normal_balance_status()
        if normal_balance:
            attrs["normal_balance_protection"] = normal_balance

        active_balance_mode = c.get_active_balance_mode_status()
        if active_balance_mode:
            attrs["active_balance_mode"] = active_balance_mode

        non_responsive = c.non_responsive_battery_names
        if non_responsive:
            attrs["non_responsive_batteries"] = non_responsive
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
    """Diagnostic sensor showing batteries that are unreachable or non-delivering."""

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
        """Return names of non-responsive batteries, or 'None' if all are healthy."""
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
            unreachable = (
                not coordinator.is_available
                and not getattr(coordinator, "_is_shutting_down", False)
                and getattr(coordinator, "_consecutive_failures", 0) > 0
            )
            if info and info.get("excluded_at") is not None:
                elapsed_min = (now - info["excluded_at"]).total_seconds() / 60
                remaining_min = max(0.0, info["cooldown_minutes"] - elapsed_min)
                attrs[coordinator.name] = {
                    "excluded": True,
                    "unreachable": unreachable,
                    "reason": info.get("reason") or "non_delivery",
                    "retry_attempted": info.get("retry_attempted", False),
                    "wake_attempted": info.get("wake_attempted", False),
                    "cooldown_minutes": info["cooldown_minutes"],
                    "remaining_minutes": round(remaining_min, 1),
                    "consecutive_failures": getattr(coordinator, "_consecutive_failures", 0),
                }
            else:
                attrs[coordinator.name] = {
                    "excluded": unreachable,
                    "unreachable": unreachable,
                    "reason": "connection_unavailable" if unreachable else (info.get("reason") if info else None),
                    "retry_attempted": info.get("retry_attempted", False) if info else False,
                    "wake_attempted": info.get("wake_attempted", False) if info else False,
                    "fail_count": info["fail_count"] if info else 0,
                    "consecutive_failures": getattr(coordinator, "_consecutive_failures", 0),
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


class DailySolarEnergySensor(SensorEntity):
    """Exact daily solar production (kWh), integrated from the real solar power sensor.

    The controller integrates the configured solar_production_sensor at control-loop
    cadence and resets at local midnight (see ConsumptionTracker); this entity just
    surfaces that running total. total_increasing so HA handles the daily reset.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "system_daily_solar_energy"
    _attr_unique_id = "marstek_venus_system_daily_solar_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:solar-power"
    _attr_should_poll = True

    def __init__(self, controller) -> None:
        """Initialize the daily solar energy sensor."""
        self._controller = controller

    @property
    def native_value(self) -> float:
        """Return today's accumulated solar production in kWh."""
        return round(self._controller._daily_solar_energy_kwh, 2)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


class DailyHomeEnergySensor(SensorEntity):
    """Exact daily home consumption (kWh), integrated from the household power.

    Uses the dedicated household_consumption_sensor when configured; otherwise the
    value is derived from grid + battery AC + solar, matching the power-flow Home
    Consumption sensor. Unlike the predictive-charging windowed accumulator, this
    integrates the full 24 h.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "system_daily_home_energy"
    _attr_unique_id = "marstek_venus_system_daily_home_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_should_poll = True

    def __init__(self, controller) -> None:
        """Initialize the daily home energy sensor."""
        self._controller = controller

    @property
    def native_value(self) -> float:
        """Return today's accumulated home consumption in kWh."""
        return round(self._controller._daily_home_energy_kwh, 2)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


class DailyGridImportEnergySensor(SensorEntity):
    """Exact daily grid import (kWh), integrated from the net consumption meter.

    The controller integrates the positive half of the consumption_sensor (power
    drawn FROM the grid) at control-loop cadence and resets at local midnight
    (see ConsumptionTracker); this entity surfaces that running total.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "system_daily_grid_import_energy"
    _attr_unique_id = "marstek_venus_system_daily_grid_import_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:transmission-tower-import"
    _attr_should_poll = True

    def __init__(self, controller) -> None:
        """Initialize the daily grid import energy sensor."""
        self._controller = controller

    @property
    def native_value(self) -> float:
        """Return today's accumulated grid import in kWh."""
        return round(self._controller._daily_grid_import_energy_kwh, 2)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }


class DailyGridExportEnergySensor(SensorEntity):
    """Exact daily grid export (kWh), integrated from the net consumption meter.

    Mirrors DailyGridImportEnergySensor but for the negative half of the
    consumption_sensor (power fed TO the grid).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "system_daily_grid_export_energy"
    _attr_unique_id = "marstek_venus_system_daily_grid_export_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:transmission-tower-export"
    _attr_should_poll = True

    def __init__(self, controller) -> None:
        """Initialize the daily grid export energy sensor."""
        self._controller = controller

    @property
    def native_value(self) -> float:
        """Return today's accumulated grid export in kWh."""
        return round(self._controller._daily_grid_export_energy_kwh, 2)

    @property
    def device_info(self):
        """Return device information for the system."""
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }
