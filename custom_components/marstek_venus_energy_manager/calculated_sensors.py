"""Calculated sensors for the Marstek Venus Energy Manager integration."""
from __future__ import annotations

import time

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EFFICIENCY_SENSOR_DEFINITIONS, STORED_ENERGY_SENSOR_DEFINITIONS, CYCLE_SENSOR_DEFINITIONS
from .coordinator import MarstekVenusDataUpdateCoordinator

# Skip integration across gaps larger than this (stalled coordinator / sensor
# offline) so a resumed update can't dump one giant energy block.
_MAX_INTEGRATION_GAP_S = 600.0

# Only sample the dual-plane efficiency (vA/vD) while PV is not feeding the
# cells: above this MPPT total the AC port no longer equals the battery's own
# conversion leg, so the AC/DC comparison would be contaminated.
_MPPT_ZERO_W = 10.0

# Ignore samples where either plane is near idle: standby self-consumption and
# zero-crossings carry no useful conversion information and would just add noise.
_MIN_POWER_W = 20.0


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


class MarstekVenusEfficiencySensor(CoordinatorEntity, RestoreEntity, SensorEntity):
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
        # On Venus D/A the AC-side hardware energy counters can't see DC-coupled
        # PV charging the cells, so their round-trip ratio runs >100%. For those
        # units measure the real inverter loss directly while PV is idle (MPPT=0):
        # the AC port (ac_power) and the DC battery terminal (battery_power) are
        # two independent planes whose difference is the conversion loss. Each leg
        # is the ratio of two simultaneous power readings, so unlike a cumulative
        # charge/discharge ratio it has no SoC-endpoint dependence and can't blow
        # up on partial cycles. AC-only models keep the accurate hardware counters.
        self._integrate_mode = coordinator.battery_version in ("vA", "vD")
        self._mppt_keys = ["mppt1_power", "mppt2_power", "mppt3_power", "mppt4_power"]
        # Energy on each plane, split by direction (kWh), MPPT=0 windows only.
        self._charge_ac_kwh = 0.0      # AC drawn while charging the cells
        self._charge_dc_kwh = 0.0      # DC stored while charging the cells
        self._discharge_ac_kwh = 0.0   # AC delivered while discharging
        self._discharge_dc_kwh = 0.0   # DC extracted while discharging
        self._last_mono: float | None = None

    def _leg_efficiencies(self):
        """Return (charge_eff, discharge_eff) or (None, None) if not yet sampled."""
        charge_eff = (
            self._charge_dc_kwh / self._charge_ac_kwh
            if self._charge_ac_kwh > 0 else None
        )
        discharge_eff = (
            self._discharge_ac_kwh / self._discharge_dc_kwh
            if self._discharge_dc_kwh > 0 else None
        )
        return charge_eff, discharge_eff

    @property
    def native_value(self):
        """Return round-trip efficiency (%)."""
        if self._integrate_mode:
            charge_eff, discharge_eff = self._leg_efficiencies()
            # A DC-coupled-PV unit (Venus A/D) charges its cells through the
            # MPPT, not the AC port, so the charge leg only samples during the
            # rare AC grid-charge windows — most installs never measure it and
            # round-trip would sit at "unknown" forever. The inverter's AC<->DC
            # conversion is near-symmetric, so when only one leg has been seen
            # estimate the round trip from it; the real product takes over as
            # soon as both legs exist. Per-leg attributes flag which is which.
            if charge_eff is None and discharge_eff is None:
                return None
            charge_eff = charge_eff if charge_eff is not None else discharge_eff
            discharge_eff = discharge_eff if discharge_eff is not None else charge_eff
            return round(min(charge_eff * discharge_eff * 100, 100.0), 2)

        if self.coordinator.data is None:
            return None

        charge_energy = self.coordinator.data.get(self._dependency_keys["charge"], 0)
        discharge_energy = self.coordinator.data.get(self._dependency_keys["discharge"], 0)

        if charge_energy <= 0:
            return None

        return round((discharge_energy / charge_energy) * 100, 2)

    @property
    def extra_state_attributes(self):
        """Expose per-leg efficiency and integrated energy (vA/vD only).

        The energy buckets survive restarts; the leg efficiencies give partial
        visibility before a full round trip (e.g. a unit that only discharges at
        night surfaces its discharge efficiency while round-trip stays None).
        """
        if not self._integrate_mode:
            return None
        charge_eff, discharge_eff = self._leg_efficiencies()
        return {
            "charge_efficiency": round(charge_eff * 100, 2) if charge_eff is not None else None,
            "discharge_efficiency": round(discharge_eff * 100, 2) if discharge_eff is not None else None,
            "charge_ac_kwh": round(self._charge_ac_kwh, 4),
            "charge_dc_kwh": round(self._charge_dc_kwh, 4),
            "discharge_ac_kwh": round(self._discharge_ac_kwh, 4),
            "discharge_dc_kwh": round(self._discharge_dc_kwh, 4),
        }

    async def async_added_to_hass(self) -> None:
        """Restore integrated energy counters on startup."""
        await super().async_added_to_hass()
        if not self._integrate_mode:
            return
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._charge_ac_kwh = float(last.attributes.get("charge_ac_kwh") or 0.0)
                self._charge_dc_kwh = float(last.attributes.get("charge_dc_kwh") or 0.0)
                self._discharge_ac_kwh = float(last.attributes.get("discharge_ac_kwh") or 0.0)
                self._discharge_dc_kwh = float(last.attributes.get("discharge_dc_kwh") or 0.0)
            except (TypeError, ValueError):
                pass

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate terminal power on each coordinator update, then write state."""
        self._accumulate()
        super()._handle_coordinator_update()

    def _accumulate(self) -> None:
        """Integrate AC- and DC-plane energy by direction, while PV is idle."""
        if not self._integrate_mode:
            return
        data = self.coordinator.data
        if not data:
            return
        battery = data.get("battery_power")  # DC terminal, + charge / - discharge
        ac = data.get("ac_power")            # AC port, opposite sign to battery
        if battery is None or ac is None:
            return
        solar = sum(v for k in self._mppt_keys if (v := data.get(k)) is not None)

        now = time.monotonic()
        last = self._last_mono
        self._last_mono = now
        # First sample (fresh start or post-restart): seed the timer, accumulate
        # nothing — monotonic resets across restarts, so this also skips downtime.
        if last is None:
            return
        # PV feeding the cells, or either plane near idle: skip but keep the timer
        # current so the next valid sample doesn't integrate the skipped span.
        if solar > _MPPT_ZERO_W or abs(battery) < _MIN_POWER_W or abs(ac) < _MIN_POWER_W:
            return
        dt = now - last
        if dt <= 0 or dt > _MAX_INTEGRATION_GAP_S:
            return
        hours = dt / 3600.0
        ac_kwh = abs(ac) * hours / 1000.0
        dc_kwh = abs(battery) * hours / 1000.0
        if battery > 0:  # charging the cells: AC drawn in, DC stored
            self._charge_ac_kwh += ac_kwh
            self._charge_dc_kwh += dc_kwh
        else:            # discharging the cells: DC extracted, AC delivered
            self._discharge_ac_kwh += ac_kwh
            self._discharge_dc_kwh += dc_kwh

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
