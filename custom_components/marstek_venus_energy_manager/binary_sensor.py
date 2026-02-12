"""Binary sensor platform for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, BINARY_SENSOR_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinators: list[MarstekVenusDataUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    entities = []

    # Add regular battery binary sensors
    for coordinator in coordinators:
        for definition in BINARY_SENSOR_DEFINITIONS:
            entities.append(MarstekVenusBinarySensor(coordinator, definition))

        # Add charge hysteresis sensor for batteries with hysteresis enabled
        if coordinator.enable_charge_hysteresis:
            entities.append(ChargeHysteresisActiveSensor(coordinator))

    # Add predictive charging status sensor (system-level)
    if controller and controller.predictive_charging_enabled:
        entities.append(PredictiveChargingStatusSensor(hass, entry, controller))

    async_add_entities(entities)


class MarstekVenusBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Marstek Venus binary sensor."""

    def __init__(
        self, coordinator: MarstekVenusDataUpdateCoordinator, definition: dict
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.definition = definition
        
        self._attr_name = f"{coordinator.name} {definition['name']}"
        self._attr_unique_id = f"{coordinator.host}_{definition['key']}"
        self._attr_device_class = definition.get("device_class")
        self._attr_icon = definition.get("icon")
        self._attr_should_poll = False

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.definition["key"])

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class ChargeHysteresisActiveSensor(RestoreEntity, BinarySensorEntity):
    """Binary sensor indicating if charge hysteresis is active for a battery.

    This sensor persists its state across reboots using RestoreEntity.
    When hysteresis is active, the battery won't charge until SOC drops
    below (max_soc - hysteresis_percent).
    """

    def __init__(self, coordinator: MarstekVenusDataUpdateCoordinator) -> None:
        """Initialize the hysteresis sensor."""
        self.coordinator = coordinator

        self._attr_name = f"{coordinator.name} Charge Hysteresis Active"
        self._attr_unique_id = f"{coordinator.host}_charge_hysteresis_active"
        self._attr_icon = "mdi:battery-lock"
        self._attr_should_poll = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self) -> None:
        """Restore hysteresis state when entity is added to hass."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is None:
            _LOGGER.debug(
                "[%s] No previous hysteresis state found - starting with hysteresis inactive",
                self.coordinator.name
            )
            return

        # Restore the hysteresis state to the coordinator
        was_active = last_state.state == "on"
        self.coordinator._hysteresis_active = was_active

        _LOGGER.info(
            "[%s] Restored charge hysteresis state: %s",
            self.coordinator.name,
            "ACTIVE" if was_active else "inactive"
        )

    @property
    def is_on(self):
        """Return true if charge hysteresis is active."""
        return self.coordinator._hysteresis_active

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        current_soc = None
        if self.coordinator.data:
            current_soc = self.coordinator.data.get("battery_soc")

        charge_threshold = self.coordinator.max_soc - self.coordinator.charge_hysteresis_percent

        return {
            "max_soc": self.coordinator.max_soc,
            "hysteresis_percent": self.coordinator.charge_hysteresis_percent,
            "charge_resume_threshold": charge_threshold,
            "current_soc": current_soc,
        }

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.host)},
            "name": self.coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


class PredictiveChargingStatusSensor(BinarySensorEntity):
    """Binary sensor indicating if predictive grid charging is currently active."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        """Initialize the status sensor."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        
        self._attr_name = "Predictive Charging Active"
        self._attr_unique_id = f"{entry.entry_id}_predictive_charging_active"
        self._attr_device_class = "running"
        self._attr_icon = "mdi:battery-charging-wireless"
        self._attr_should_poll = True  # Poll to update state
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        """Return true if predictive charging is active."""
        return self.controller.grid_charging_active

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        attrs = {
            "in_charging_slot": self.controller._is_in_predictive_charging_slot(),
            "last_evaluation_soc": self.controller.last_evaluation_soc,
            "overridden": self.controller.predictive_charging_overridden,
        }

        if self.controller.charging_time_slot:
            attrs["time_slot"] = self.controller.charging_time_slot

        if self.controller.solar_forecast_sensor:
            attrs["solar_forecast_sensor"] = self.controller.solar_forecast_sensor

        attrs["max_contracted_power"] = self.controller.max_contracted_power

        # Persist daily consumption history for restoration after restarts
        if hasattr(self.controller, '_daily_consumption_history') and self.controller._daily_consumption_history:
            attrs["daily_consumption_history"] = [
                (d.isoformat(), c) for d, c in self.controller._daily_consumption_history
            ]
            attrs["history_days"] = len(self.controller._daily_consumption_history)

        # Add last decision data if available (for diagnostics)
        if hasattr(self.controller, '_last_decision_data') and self.controller._last_decision_data:
            decision = self.controller._last_decision_data
            attrs.update({
                "stored_energy_kwh": decision.get("stored_energy_kwh"),
                "usable_energy_kwh": decision.get("usable_energy_kwh"),
                "min_reserve_kwh": decision.get("min_reserve_kwh"),
                "cutoff_energy_kwh": decision.get("cutoff_energy_kwh"),
                "effective_min_soc": decision.get("effective_min_soc"),
                "avg_consumption_kwh": decision.get("avg_consumption_kwh"),
                "total_available_kwh": decision.get("total_available_kwh"),
                "energy_deficit_kwh": decision.get("energy_deficit_kwh"),
                "solar_forecast_kwh": decision.get("solar_forecast_kwh"),
                "decision_reason": decision.get("reason"),
            })

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
