"""Hourly net balance sensor entity for Marstek Venus Energy Manager."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_ENABLE_HOURLY_BALANCE
from .hourly_balance import HourlyBalanceManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hourly net balance sensor."""
    if CONF_ENABLE_HOURLY_BALANCE not in entry.data:
        return

    controller = hass.data[DOMAIN][entry.entry_id].get("controller")
    if controller is None or controller._hourly_balance_mgr is None:
        return

    mgr: HourlyBalanceManager = controller._hourly_balance_mgr
    sensor = NetBalanceSensor(entry, mgr)
    mgr.register_sensor(sensor)
    async_add_entities([sensor])


class NetBalanceSensor(SensorEntity):
    """Net grid balance for the current civil hour.

    State  : net kWh (positive = net export to grid, negative = net import).
    Attributes: full status snapshot — offset, breakdown, source.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "balance_neto"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:scale-balance"

    def __init__(self, entry: ConfigEntry, mgr: HourlyBalanceManager) -> None:
        self._entry = entry
        self._mgr = mgr
        self._attr_unique_id = f"{entry.entry_id}_balance_neto"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, "marstek_venus_system")},
            "name": "Marstek Venus System",
            "manufacturer": "Marstek",
            "model": "Venus Multi-Battery System",
        }

    @property
    def native_value(self) -> float | None:
        return self._mgr.get_status_dict()["net_kwh"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._mgr.get_status_dict()
        attrs: dict[str, Any] = {
            "status": self._mgr.get_state_label(),
            "offset_w": s["offset_w"],
            "imp_wh": s["imp_wh"],
            "exp_wh": s["exp_wh"],
            "target_net_wh": s["target_net_wh"],
            "remaining_min": s["remaining_min"],
            "source": s["source"],
            "hour_iso": s["hour_iso"],
        }
        if s["charge_block_reason"]:
            attrs["charge_block_reason"] = s["charge_block_reason"]
        return attrs
