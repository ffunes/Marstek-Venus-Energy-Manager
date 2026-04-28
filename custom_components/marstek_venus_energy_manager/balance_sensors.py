"""Cell balance sensor entities for Marstek Venus batteries."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .balance_monitor import BalanceMonitor, BalanceSensorGroup
from .const import DOMAIN, CONF_ENABLE_BALANCE_MONITOR


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up balance sensor entities — one group of 5 per battery."""
    if not entry.data.get(CONF_ENABLE_BALANCE_MONITOR, False):
        return

    monitor: BalanceMonitor | None = hass.data[DOMAIN][entry.entry_id].get("balance_monitor")
    if monitor is None:
        return

    coordinators = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities: list[SensorEntity] = []

    for coordinator in coordinators:
        host = coordinator.host
        init = monitor.get_initial_state(host)

        delta = CellDeltaSensor(coordinator, init)
        status = BalanceStatusSensor(coordinator, init)
        trend = DeltaTrendSensor(coordinator, init)
        last_read = LastBalanceReadSensor(coordinator, init)
        avg4w = DeltaAvg4wSensor(coordinator, init)

        group = BalanceSensorGroup()
        for entity in (delta, status, trend, last_read, avg4w):
            group.register(entity)
        monitor.register_sensor_group(host, group)

        entities.extend([delta, status, trend, last_read, avg4w])

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class _BalanceBaseSensor(SensorEntity):
    """Common base for all balance sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Any, init: dict) -> None:
        self._coordinator = coordinator
        self._apply_init(init)

    def _apply_init(self, init: dict) -> None:
        """Override in each subclass to set the specific attribute from init."""

    def on_reading(
        self,
        delta_mv: float,
        status: str,
        trend: str,
        avg_4w: float | None,
        last_ts: str,
    ) -> None:
        """Called by BalanceSensorGroup.push() after each balance reading."""
        self._on_reading(delta_mv, status, trend, avg_4w, last_ts)
        self.async_write_ha_state()

    def _on_reading(self, delta_mv, status, trend, avg_4w, last_ts) -> None:
        """Override in each subclass."""

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f"{self._coordinator.host}_{self._coordinator.port}")},
            "name": self._coordinator.name,
            "manufacturer": "Marstek",
            "model": "Venus",
        }


# ---------------------------------------------------------------------------
# Concrete sensors
# ---------------------------------------------------------------------------

class CellDeltaSensor(_BalanceBaseSensor):
    _attr_translation_key = "cell_delta"
    _attr_native_unit_of_measurement = "mV"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sine-wave"

    def __init__(self, coordinator: Any, init: dict) -> None:
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_cell_delta"
        self._attr_native_value: float | None = None
        super().__init__(coordinator, init)

    def _apply_init(self, init: dict) -> None:
        self._attr_native_value = init.get("delta_mV")

    def _on_reading(self, delta_mv, status, trend, avg_4w, last_ts) -> None:
        self._attr_native_value = round(delta_mv, 1) if delta_mv is not None else None

    @property
    def native_value(self):
        return self._attr_native_value


class BalanceStatusSensor(_BalanceBaseSensor):
    _attr_translation_key = "balance_status"
    _attr_icon = "mdi:battery-heart-variant"

    def __init__(self, coordinator: Any, init: dict) -> None:
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_balance_status"
        self._status: str = "unknown"
        super().__init__(coordinator, init)

    def _apply_init(self, init: dict) -> None:
        self._status = init.get("status", "unknown")

    def _on_reading(self, delta_mv, status, trend, avg_4w, last_ts) -> None:
        self._status = status

    @property
    def native_value(self) -> str:
        return self._status


class DeltaTrendSensor(_BalanceBaseSensor):
    _attr_translation_key = "delta_trend"
    _attr_icon = "mdi:trending-up"

    def __init__(self, coordinator: Any, init: dict) -> None:
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_delta_trend"
        self._trend: str = "unknown"
        super().__init__(coordinator, init)

    def _apply_init(self, init: dict) -> None:
        self._trend = init.get("trend", "unknown")

    def _on_reading(self, delta_mv, status, trend, avg_4w, last_ts) -> None:
        self._trend = trend

    @property
    def native_value(self) -> str:
        return self._trend


class LastBalanceReadSensor(_BalanceBaseSensor):
    _attr_translation_key = "last_balance_read"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: Any, init: dict) -> None:
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_last_balance_read"
        self._ts: datetime | None = None
        super().__init__(coordinator, init)

    def _apply_init(self, init: dict) -> None:
        raw = init.get("last_ts")
        if raw:
            try:
                ts = datetime.fromisoformat(raw)
                self._ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            except ValueError:
                self._ts = None

    def _on_reading(self, delta_mv, status, trend, avg_4w, last_ts) -> None:
        if last_ts:
            try:
                ts = datetime.fromisoformat(last_ts)
                self._ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            except ValueError:
                self._ts = None

    @property
    def native_value(self) -> datetime | None:
        return self._ts


class DeltaAvg4wSensor(_BalanceBaseSensor):
    _attr_translation_key = "delta_avg_4w"
    _attr_native_unit_of_measurement = "mV"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator: Any, init: dict) -> None:
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_delta_avg_4w"
        self._avg: float | None = None
        super().__init__(coordinator, init)

    def _apply_init(self, init: dict) -> None:
        self._avg = init.get("avg_4w")

    def _on_reading(self, delta_mv, status, trend, avg_4w, last_ts) -> None:
        self._avg = avg_4w

    @property
    def native_value(self) -> float | None:
        return self._avg
