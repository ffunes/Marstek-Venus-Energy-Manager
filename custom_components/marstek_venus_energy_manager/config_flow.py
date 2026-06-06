"""Config flow for Marstek Venus Energy Manager integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.config_entries import ConfigFlow, OptionsFlow, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    EntitySelector,
    EntitySelectorConfig,
    TimeSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    CONF_ENABLE_PREDICTIVE_CHARGING,
    CONF_CHARGING_TIME_SLOT,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY,
    CONF_ENABLE_BALANCE_MONITOR,
    CONF_ENABLE_CHARGE_DELAY,
    CONF_DELAY_SAFETY_MARGIN_MIN,
    DEFAULT_DELAY_SAFETY_MARGIN_MIN,
    CONF_DELAY_SOC_SETPOINT_ENABLED,
    DEFAULT_DELAY_SOC_SETPOINT_ENABLED,
    CONF_DELAY_SOC_SETPOINT,
    DEFAULT_DELAY_SOC_SETPOINT,
    CONF_BATTERY_VERSION,
    CONF_SLAVE_ID,
    DEFAULT_SLAVE_ID,
    DEFAULT_VERSION,
    REGISTER_MAP,
    MAX_POWER_BY_VERSION,
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
    DEFAULT_ENABLE_SYSTEM_POWER_LIMITS,
    DEFAULT_SYSTEM_MAX_CHARGE_POWER,
    DEFAULT_SYSTEM_MAX_DISCHARGE_POWER,
    CONF_CAPACITY_PROTECTION_ENABLED,
    CONF_CAPACITY_PROTECTION_SOC_THRESHOLD,
    CONF_CAPACITY_PROTECTION_LIMIT,
    DEFAULT_CAPACITY_PROTECTION_SOC,
    DEFAULT_CAPACITY_PROTECTION_LIMIT,
    CONF_PREDICTIVE_CHARGING_MODE,
    CONF_PRICE_SENSOR,
    CONF_PRICE_INTEGRATION_TYPE,
    CONF_MAX_PRICE_THRESHOLD,
    CONF_AVERAGE_PRICE_SENSOR,
    CONF_DP_PRICE_DISCHARGE_CONTROL,
    CONF_RT_PRICE_DISCHARGE_CONTROL,
    PREDICTIVE_MODE_TIME_SLOT,
    PREDICTIVE_MODE_DYNAMIC_PRICING,
    PREDICTIVE_MODE_REALTIME_PRICE,
    PRICE_INTEGRATION_NORDPOOL,
    PRICE_INTEGRATION_PVPC,
    PRICE_INTEGRATION_CKW,
    PRICE_INTEGRATION_EPEX,
    PRICE_INTEGRATION_ENTSOE,
    CONF_METER_INVERTED,
    CONF_PREDICTIVE_SAFETY_MARGIN_KWH,
    DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH,
    CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT,
    DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT,
    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    SLOT_BATTERY_SCOPE_ALL,
    SLOT_MODE_PD,
    SLOT_MODE_MANUAL,
    DEFAULT_SLOT_ALLOW_CHARGE,
    DEFAULT_SLOT_ALLOW_DISCHARGE,
    DEFAULT_SLOT_SOC_OVERRIDE_ENABLED,
    DEFAULT_SLOT_POWER_OVERRIDE_ENABLED,
    DEFAULT_SLOT_MODE,
    DEFAULT_SLOT_SOC_MIN_FLOOR,
    DEFAULT_SLOT_SOC_MAX_CEILING,
    MAX_TIME_SLOTS,
)
from .modbus_client import MarstekModbusClient

_LOGGER = logging.getLogger(__name__)


def _time_ranges_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Check if two time ranges overlap. Assumes start < end (no midnight crossing)."""
    from datetime import time as dt_time

    s1 = dt_time.fromisoformat(start1)
    e1 = dt_time.fromisoformat(end1)
    s2 = dt_time.fromisoformat(start2)
    e2 = dt_time.fromisoformat(end2)

    return s1 < e2 and s2 < e1


def _slots_overlap(new_slot: dict, existing_slots: list[dict]) -> bool:
    """Check if new_slot overlaps with any existing slot on shared days and scope.

    Two slots only conflict when they would compete for the same battery: either
    they share a concrete battery_scope, or one (or both) targets all batteries.
    """
    new_days = set(new_slot.get("days", []))
    new_scope = new_slot.get("battery_scope", SLOT_BATTERY_SCOPE_ALL)
    for slot in existing_slots:
        if not (new_days & set(slot.get("days", []))):
            continue
        scope = slot.get("battery_scope", SLOT_BATTERY_SCOPE_ALL)
        if scope != SLOT_BATTERY_SCOPE_ALL and new_scope != SLOT_BATTERY_SCOPE_ALL and scope != new_scope:
            continue
        if _time_ranges_overlap(
            new_slot["start_time"], new_slot["end_time"],
            slot["start_time"], slot["end_time"],
        ):
            return True
    return False


def _battery_scope_options(battery_configs: list[dict]) -> list[dict]:
    """Build battery scope selector options as {value, label} dicts.

    The label shows the user-facing battery name (CONF_NAME) when available,
    falling back to "Battery N" if the config dict has no name.
    """
    opts: list[dict] = [{"value": SLOT_BATTERY_SCOPE_ALL, "label": "All batteries"}]
    for i, bcfg in enumerate(battery_configs or []):
        name = bcfg.get(CONF_NAME) or f"Battery {i + 1}"
        opts.append({"value": f"battery_{i + 1}", "label": name})
    return opts


def _scope_value_in_options(scope: str, opts: list[dict]) -> bool:
    return any(o["value"] == scope for o in opts)


def _battery_hardware_max(bcfg: dict) -> int:
    """Return the battery's hardware max power (W) from MAX_POWER_BY_VERSION."""
    version = bcfg.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
    return int(MAX_POWER_BY_VERSION.get(version, 2500))


def _max_system_hardware_power(battery_configs: list[dict]) -> int:
    """Highest hardware power cap across configured batteries (W)."""
    if not battery_configs:
        return 2500
    return max(_battery_hardware_max(b) for b in battery_configs)


def _scoped_battery_index(scope: str) -> int | None:
    """Parse "battery_N" → N-1. Returns None for "all" or invalid scope."""
    if not scope or scope == SLOT_BATTERY_SCOPE_ALL or not scope.startswith("battery_"):
        return None
    try:
        return int(scope.split("_", 1)[1]) - 1
    except (ValueError, IndexError):
        return None


def _scoped_battery_config(scope: str, battery_configs: list[dict]) -> dict:
    """Return the battery dict for `scope` (or {} for 'all' / invalid index)."""
    idx = _scoped_battery_index(scope)
    if idx is None:
        return {}
    if 0 <= idx < len(battery_configs):
        return battery_configs[idx]
    return {}


def _slot_target_indices(scope: str, num_batteries: int) -> list[int]:
    """Battery indices (0-based) covered by `scope`. Empty if scope invalid."""
    if scope == SLOT_BATTERY_SCOPE_ALL:
        return list(range(num_batteries))
    idx = _scoped_battery_index(scope)
    if idx is None or idx < 0 or idx >= num_batteries:
        return []
    return [idx]


def _battery_scope_name_map(battery_configs: list[dict]) -> str:
    """Human-readable list of 'battery_N → name' for description_placeholders."""
    parts = []
    for i, bcfg in enumerate(battery_configs or []):
        parts.append(f"battery_{i + 1} = {bcfg.get(CONF_NAME) or f'Battery {i + 1}'}")
    return ", ".join(parts) if parts else ""


def _clamp(val: int, low: int, high: int) -> int:
    return max(low, min(high, int(val)))


def _slot_field_key(battery_idx: int, field: str) -> str:
    """Step B form key: '<batteryN>__<field>'. Parsed back in _finalize_slot."""
    return f"battery_{battery_idx + 1}__{field}"


def _build_slot_step_a_schema(battery_configs: list[dict], defaults: dict) -> vol.Schema:
    """Step A: time, days, scope, allow ticks, SOC tick, power tick, mode."""
    scope_opts = _battery_scope_options(battery_configs)
    scope_default = defaults.get("battery_scope") or SLOT_BATTERY_SCOPE_ALL
    if not _scope_value_in_options(scope_default, scope_opts):
        scope_default = SLOT_BATTERY_SCOPE_ALL
    return vol.Schema({
        vol.Required("start_time", default=defaults.get("start_time") or "00:00:00"): TimeSelector(),
        vol.Required("end_time", default=defaults.get("end_time") or "00:00:00"): TimeSelector(),
        vol.Required("days", default=defaults.get("days") or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]):
            SelectSelector(SelectSelectorConfig(
                options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                translation_key="weekday",
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )),
        vol.Required("battery_scope", default=scope_default):
            SelectSelector(SelectSelectorConfig(
                options=scope_opts,
                multiple=False,
                mode=SelectSelectorMode.DROPDOWN,
            )),
        vol.Required("allow_charge", default=bool(defaults.get("allow_charge", DEFAULT_SLOT_ALLOW_CHARGE))): bool,
        vol.Required("allow_discharge", default=bool(defaults.get("allow_discharge", DEFAULT_SLOT_ALLOW_DISCHARGE))): bool,
        vol.Required("soc_override_enabled", default=bool(defaults.get("soc_override_enabled", DEFAULT_SLOT_SOC_OVERRIDE_ENABLED))): bool,
        vol.Required("power_override_enabled", default=bool(defaults.get("power_override_enabled", DEFAULT_SLOT_POWER_OVERRIDE_ENABLED))): bool,
        vol.Required("mode", default=defaults.get("mode") or DEFAULT_SLOT_MODE):
            SelectSelector(SelectSelectorConfig(
                options=[SLOT_MODE_PD, SLOT_MODE_MANUAL],
                translation_key="slot_mode",
                multiple=False,
                mode=SelectSelectorMode.LIST,
            )),
    })


def _build_slot_step_b_schema(
    needs_soc: bool,
    needs_power: bool,
    scope: str,
    battery_configs: list[dict],
    defaults: dict,
) -> vol.Schema:
    """Step B: optional SOC and/or power values, rendered per-battery.

    For each battery covered by `scope` (one for `battery_N`, all for `all`),
    render an independent set of fields keyed as `battery_<idx>__<field>`. The
    consumer (`_finalize_slot`) parses these into `slot["battery_limits"]`.

      - SOC sliders always range [12, 100].
      - Power sliders range [100, battery hardware max] per that specific battery.
      - Defaults pull from the slot's previous `battery_limits[battery_N]` if any,
        else from the battery's user-configured `min_soc`/`max_soc`/
        `max_charge_power`/`max_discharge_power`.
    """
    fields: dict = {}
    indices = _slot_target_indices(scope, len(battery_configs))
    prior = defaults.get("battery_limits") or {}
    for idx in indices:
        bcfg = battery_configs[idx]
        b_key = f"battery_{idx + 1}"
        b_prior = prior.get(b_key) or {}
        hw_max = _battery_hardware_max(bcfg)
        if needs_soc:
            soc_min_def = b_prior.get("soc_min") or int(bcfg.get("min_soc") or DEFAULT_SLOT_SOC_MIN_FLOOR)
            soc_max_def = b_prior.get("soc_max") or int(bcfg.get("max_soc") or DEFAULT_SLOT_SOC_MAX_CEILING)
            fields[vol.Required(
                _slot_field_key(idx, "soc_min"),
                default=_clamp(soc_min_def, DEFAULT_SLOT_SOC_MIN_FLOOR, 30),
            )] = NumberSelector(NumberSelectorConfig(
                min=DEFAULT_SLOT_SOC_MIN_FLOOR, max=30,
                step=1, mode=NumberSelectorMode.SLIDER,
            ))
            fields[vol.Required(
                _slot_field_key(idx, "soc_max"),
                default=_clamp(soc_max_def, 80, DEFAULT_SLOT_SOC_MAX_CEILING),
            )] = NumberSelector(NumberSelectorConfig(
                min=80, max=DEFAULT_SLOT_SOC_MAX_CEILING,
                step=1, mode=NumberSelectorMode.SLIDER,
            ))
        if needs_power:
            charge_def = b_prior.get("max_charge_power_w") or int(bcfg.get("max_charge_power") or hw_max)
            discharge_def = b_prior.get("max_discharge_power_w") or int(bcfg.get("max_discharge_power") or hw_max)
            fields[vol.Required(
                _slot_field_key(idx, "max_charge_power_w"),
                default=_clamp(charge_def, 100, hw_max),
            )] = NumberSelector(NumberSelectorConfig(
                min=100, max=hw_max, step=50, unit_of_measurement="W",
                mode=NumberSelectorMode.SLIDER,
            ))
            fields[vol.Required(
                _slot_field_key(idx, "max_discharge_power_w"),
                default=_clamp(discharge_def, 100, hw_max),
            )] = NumberSelector(NumberSelectorConfig(
                min=100, max=hw_max, step=50, unit_of_measurement="W",
                mode=NumberSelectorMode.SLIDER,
            ))
    return vol.Schema(fields)


def _validate_slot_step_a(user_input: dict) -> dict:
    """Cross-field validation for step A. Returns errors dict (empty if valid)."""
    errors: dict = {}
    allow_c = bool(user_input.get("allow_charge"))
    allow_d = bool(user_input.get("allow_discharge"))
    if not (allow_c or allow_d):
        errors["base"] = "slot_does_nothing"
        return errors
    if user_input.get("mode") == SLOT_MODE_MANUAL and not user_input.get("power_override_enabled"):
        errors["base"] = "manual_requires_power"
        return errors
    if user_input["start_time"] >= user_input["end_time"]:
        errors["base"] = "midnight_crossing"
        return errors
    return errors


def _parse_step_b_battery_limits(step_b: dict | None) -> dict[str, dict]:
    """Group step B form fields by battery key.

    Field keys are encoded as `battery_<N>__<field>` (see _slot_field_key). The
    returned dict maps `battery_N` → `{soc_min, soc_max, max_charge_power_w,
    max_discharge_power_w}`, with int values. Missing fields are omitted.
    """
    if not step_b:
        return {}
    out: dict[str, dict] = {}
    for key, val in step_b.items():
        if "__" not in key:
            continue
        b_key, field = key.split("__", 1)
        if not b_key.startswith("battery_"):
            continue
        if val is None:
            continue
        try:
            out.setdefault(b_key, {})[field] = int(val)
        except (TypeError, ValueError):
            continue
    # Swap soc_min/soc_max if user inverted them
    for b_key, limits in out.items():
        if "soc_min" in limits and "soc_max" in limits and limits["soc_min"] > limits["soc_max"]:
            limits["soc_min"], limits["soc_max"] = limits["soc_max"], limits["soc_min"]
    return out


def _finalize_slot(step_a: dict, step_b: dict | None) -> dict:
    """Merge step A and optional step B into the persisted slot shape."""
    soc_on = bool(step_a.get("soc_override_enabled", False))
    power_on = bool(step_a.get("power_override_enabled", False))
    parsed = _parse_step_b_battery_limits(step_b) if (soc_on or power_on) else {}
    # Strip fields that don't correspond to an enabled tick (defensive)
    battery_limits: dict[str, dict] = {}
    for b_key, limits in parsed.items():
        entry: dict = {}
        if soc_on:
            if "soc_min" in limits:
                entry["soc_min"] = limits["soc_min"]
            if "soc_max" in limits:
                entry["soc_max"] = limits["soc_max"]
        if power_on:
            if "max_charge_power_w" in limits:
                entry["max_charge_power_w"] = limits["max_charge_power_w"]
            if "max_discharge_power_w" in limits:
                entry["max_discharge_power_w"] = limits["max_discharge_power_w"]
        if entry:
            battery_limits[b_key] = entry
    return {
        "start_time": step_a["start_time"],
        "end_time": step_a["end_time"],
        "days": step_a["days"],
        "enabled": True,
        "battery_scope": step_a.get("battery_scope", SLOT_BATTERY_SCOPE_ALL),
        "allow_charge": bool(step_a.get("allow_charge", False)),
        "allow_discharge": bool(step_a.get("allow_discharge", True)),
        "soc_override_enabled": soc_on,
        "power_override_enabled": power_on,
        "battery_limits": battery_limits,
        "mode": step_a.get("mode", DEFAULT_SLOT_MODE),
    }


class MarstekVenusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Venus Energy Manager."""

    VERSION = 5

    def __init__(self):
        """Initialize the config flow."""
        self.config_data = {}
        self.battery_configs = []
        self.battery_index = 0
        self.time_slots = []
        self.excluded_devices = []
        self._current_battery_data = {}  # Stores connection data between battery steps
        self._pending_slot_step_a: dict | None = None  # Buffer between slot step A and step B

    async def _test_connection(self, host: str, port: int, version: str = "v2", slave_id: int = DEFAULT_SLAVE_ID) -> bool:
        """Test connection to a Marstek Venus battery using version-specific register."""
        _LOGGER.info("Testing connection to %s:%s (%s) slave %s", host, port, version, slave_id)
        client = MarstekModbusClient(host, port, slave_id=slave_id)
        try:
            connected = await client.async_connect()
            if not connected:
                _LOGGER.error("Failed to connect to %s:%s", host, port)
                return False

            # Test with version-specific SOC register
            soc_register = REGISTER_MAP.get(version, {}).get("battery_soc")
            if soc_register is None:
                _LOGGER.error("Unknown version: %s", version)
                await client.async_close()
                return False

            _LOGGER.info("Connected to %s:%s (%s), attempting to read register %d", host, port, version, soc_register)
            value = await client.async_read_register(soc_register, "uint16")
            await client.async_close()

            if value is not None:
                _LOGGER.info("Successfully read from %s:%s (%s), SOC: %s", host, port, version, value)
                return True
            else:
                _LOGGER.error("Failed to read SOC register %d from %s:%s (%s)", soc_register, host, port, version)
                return False
        except Exception as e:
            _LOGGER.error("Connection test exception %s:%s (%s): %s", host, port, version, e)
            try:
                await client.async_close()
            except Exception:
                pass
            return False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Ask for the consumption sensor and optional solar forecast sensor."""
        errors = {}

        if user_input is not None:
            # Validate solar forecast sensor if provided
            forecast_sensor = user_input.get(CONF_SOLAR_FORECAST_SENSOR)
            if forecast_sensor:
                forecast_state = self.hass.states.get(forecast_sensor)
                if forecast_state is None:
                    errors["solar_forecast_sensor"] = "sensor_not_found"
                else:
                    unit = forecast_state.attributes.get("unit_of_measurement", "")
                    if unit not in ["kWh", "Wh"]:
                        errors["solar_forecast_sensor"] = "invalid_unit"

            # Validate solar production sensor if provided
            solar_sensor = user_input.get(CONF_SOLAR_PRODUCTION_SENSOR)
            if solar_sensor:
                solar_state = self.hass.states.get(solar_sensor)
                if solar_state is None:
                    errors[CONF_SOLAR_PRODUCTION_SENSOR] = "sensor_not_found"
                else:
                    unit = solar_state.attributes.get("unit_of_measurement", "")
                    if unit not in ["W", "kW"]:
                        errors[CONF_SOLAR_PRODUCTION_SENSOR] = "invalid_unit"

            if not errors:
                self.config_data["consumption_sensor"] = user_input["consumption_sensor"]
                self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                self.config_data[CONF_SOLAR_PRODUCTION_SENSOR] = solar_sensor
                self.config_data[CONF_METER_INVERTED] = user_input.get(CONF_METER_INVERTED, False)
                self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                return await self.async_step_batteries()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("consumption_sensor"):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_METER_INVERTED, default=False):
                        BooleanSelector(),
                    vol.Required("max_contracted_power", default=7000):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX
                            )
                        ),
                    vol.Optional(CONF_SOLAR_FORECAST_SENSOR):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_SOLAR_PRODUCTION_SENSOR):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                }
            ),
            errors=errors if errors else None,
        )

    async def async_step_batteries(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Ask for the number of batteries."""
        if user_input is not None:
            self.config_data["num_batteries"] = int(user_input["num_batteries"])
            return await self.async_step_battery_connection()

        return self.async_show_form(
            step_id="batteries",
            data_schema=vol.Schema(
                {
                    vol.Required("num_batteries", default=1):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1, max=6, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                }
            ),
        )

    async def async_step_battery_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3a: Connection details and battery model for each battery."""
        errors = {}
        battery_num = self.battery_index + 1

        if user_input is not None:
            battery_version = user_input.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
            slave_id = user_input.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
            connection_result = await self._test_connection(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                battery_version,
                slave_id,
            )
            if not connection_result:
                errors["base"] = "cannot_connect"
            else:
                self._current_battery_data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: user_input[CONF_PORT],
                    CONF_SLAVE_ID: slave_id,
                    CONF_BATTERY_VERSION: battery_version,
                }
                return await self.async_step_battery_limits()

        return self.async_show_form(
            step_id="battery_connection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=f"Marstek Venus {battery_num}"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=502): int,
                    vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID):
                        vol.All(NumberSelector(NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)), vol.Coerce(int)),
                    vol.Required(CONF_BATTERY_VERSION, default=DEFAULT_VERSION):
                        SelectSelector(SelectSelectorConfig(
                            options=[
                                {"value": "v2", "label": "Ev2"},
                                {"value": "v3", "label": "Ev3"},
                                {"value": "vA", "label": "A"},
                                {"value": "vD", "label": "D"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )),
                }
            ),
            errors=errors,
            description_placeholders={"battery_num": str(battery_num)},
        )

    async def async_step_battery_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3b: Power and SOC limits for the current battery."""
        battery_num = self.battery_index + 1
        battery_version = self._current_battery_data.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
        max_power = MAX_POWER_BY_VERSION.get(battery_version, 2500)

        if user_input is not None:
            merged = dict(self._current_battery_data)
            merged["max_charge_power"] = int(user_input["max_charge_power"])
            merged["max_discharge_power"] = int(user_input["max_discharge_power"])
            merged["max_soc"] = int(user_input["max_soc"])
            merged["min_soc"] = int(user_input["min_soc"])
            merged["enable_charge_hysteresis"] = user_input["enable_charge_hysteresis"]
            merged["charge_hysteresis_percent"] = int(user_input.get("charge_hysteresis_percent", 5))
            merged["backup_offgrid_threshold"] = int(user_input.get("backup_offgrid_threshold", 50))
            merged[CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED] = user_input.get(
                CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
            )
            self.battery_configs.append(merged)
            self.battery_index += 1

            if self.battery_index >= self.config_data["num_batteries"]:
                self.config_data["batteries"] = self.battery_configs
                return await self.async_step_time_slots()
            return await self.async_step_battery_connection()

        return self.async_show_form(
            step_id="battery_limits",
            data_schema=vol.Schema(
                {
                    vol.Required("max_charge_power", default=max_power):
                        NumberSelector(NumberSelectorConfig(min=100, max=max_power, step=50, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
                    vol.Required("max_discharge_power", default=max_power):
                        NumberSelector(NumberSelectorConfig(min=100, max=max_power, step=50, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
                    vol.Required("max_soc", default=100):
                        NumberSelector(NumberSelectorConfig(min=80, max=100, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("min_soc", default=12):
                        NumberSelector(NumberSelectorConfig(min=12, max=30, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("enable_charge_hysteresis", default=False): bool,
                    vol.Optional("charge_hysteresis_percent", default=5):
                        NumberSelector(NumberSelectorConfig(min=5, max=50, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("backup_offgrid_threshold", default=50):
                        NumberSelector(NumberSelectorConfig(min=0, max=500, step=10, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
                    vol.Required(CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED, default=DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED): bool,
                }
            ),
            description_placeholders={"battery_num": str(battery_num)},
        )

    async def async_step_time_slots(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 4: Ask if user wants to configure time slots."""
        if user_input is not None:
            if user_input.get("configure_time_slots", False):
                return await self.async_step_add_time_slot()
            else:
                # No time slots configured, move to excluded devices
                self.config_data["no_discharge_time_slots"] = []
                return await self.async_step_excluded_devices()

        return self.async_show_form(
            step_id="time_slots",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_time_slots", default=False): bool,
                }
            ),
            description_placeholders={
                "description": "Configure time slots where batteries will NOT discharge (but can charge)"
            },
        )

    async def async_step_add_time_slot(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 5A: Configure base attributes of a time slot."""
        slot_num = len(self.time_slots) + 1
        errors: dict = {}

        if user_input is not None:
            errors = _validate_slot_step_a(user_input)
            if not errors:
                if _slots_overlap(
                    {
                        "start_time": user_input["start_time"],
                        "end_time": user_input["end_time"],
                        "days": user_input["days"],
                        "battery_scope": user_input.get("battery_scope", SLOT_BATTERY_SCOPE_ALL),
                    },
                    self.time_slots,
                ):
                    errors["base"] = "overlapping_slots"
            if not errors:
                self._pending_slot_step_a = dict(user_input)
                if user_input.get("soc_override_enabled") or user_input.get("power_override_enabled"):
                    return await self.async_step_add_time_slot_details()
                return await self._finalize_time_slot(step_b=None)

        defaults = self._slot_defaults_from_existing(len(self.time_slots))
        if user_input:
            defaults = {**defaults, **user_input}

        return self.async_show_form(
            step_id="add_time_slot",
            data_schema=_build_slot_step_a_schema(self.battery_configs, defaults),
            errors=errors if errors else None,
            description_placeholders={"slot_num": str(slot_num)},
        )

    async def async_step_add_time_slot_details(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 5B: Optional SOC / power detail fields for the pending slot."""
        if self._pending_slot_step_a is None:
            return await self.async_step_add_time_slot()

        step_a = self._pending_slot_step_a
        scope = step_a.get("battery_scope", SLOT_BATTERY_SCOPE_ALL)
        needs_soc = bool(step_a.get("soc_override_enabled"))
        needs_power = bool(step_a.get("power_override_enabled"))
        slot_num = len(self.time_slots) + 1

        if user_input is not None:
            return await self._finalize_time_slot(step_b=user_input)

        defaults = self._slot_defaults_from_existing(len(self.time_slots))
        return self.async_show_form(
            step_id="add_time_slot_details",
            data_schema=_build_slot_step_b_schema(needs_soc, needs_power, scope, self.battery_configs, defaults),
            description_placeholders={
                "slot_num": str(slot_num),
                "battery_map": _battery_scope_name_map(self.battery_configs),
            },
        )

    async def _finalize_time_slot(self, step_b: dict | None) -> FlowResult:
        """Persist the pending slot and advance the flow."""
        if self._pending_slot_step_a is None:
            return await self.async_step_add_time_slot()
        slot = _finalize_slot(self._pending_slot_step_a, step_b)
        self.time_slots.append(slot)
        self._pending_slot_step_a = None
        if len(self.time_slots) < MAX_TIME_SLOTS:
            return await self.async_step_add_more_slots()
        self.config_data["no_discharge_time_slots"] = self.time_slots
        return await self.async_step_excluded_devices()

    def _slot_defaults_from_existing(self, index: int) -> dict:
        """Return previously-saved slot at `index`, or empty dict if none."""
        existing = self.config_data.get("no_discharge_time_slots", []) or []
        if 0 <= index < len(existing):
            return dict(existing[index])
        return {}

    async def async_step_add_more_slots(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 6: Ask if user wants to add more time slots."""
        if user_input is not None:
            if user_input.get("add_more", False):
                return await self.async_step_add_time_slot()
            else:
                # User finished adding slots, move to excluded devices
                self.config_data["no_discharge_time_slots"] = self.time_slots
                return await self.async_step_excluded_devices()

        return self.async_show_form(
            step_id="add_more_slots",
            data_schema=vol.Schema(
                {
                    vol.Required("add_more", default=False): bool,
                }
            ),
            description_placeholders={
                "current_slots": str(len(self.time_slots)),
                "max_slots": str(MAX_TIME_SLOTS),
            },
        )

    async def async_step_excluded_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 7: Ask if user wants to configure excluded devices."""
        if user_input is not None:
            if user_input.get("configure_excluded_devices", False):
                return await self.async_step_add_excluded_device()
            else:
                # No excluded devices configured, move to predictive charging
                self.config_data["excluded_devices"] = []
                return await self.async_step_predictive_charging()

        return self.async_show_form(
            step_id="excluded_devices",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_excluded_devices", default=False): bool,
                }
            ),
            description_placeholders={
                "description": "Configure devices that should NOT be powered by battery"
            },
        )

    async def async_step_add_excluded_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 8: Add an excluded device configuration."""
        if user_input is not None:
            # Save the excluded device
            excluded_device = {
                "power_sensor": user_input["power_sensor"],
                "included_in_consumption": user_input.get("included_in_consumption", True),
                "allow_solar_surplus": user_input.get("allow_solar_surplus", False),
                "ev_charger_no_telemetry": user_input.get("ev_charger_no_telemetry", False),
            }
            self.excluded_devices.append(excluded_device)

            # Check if user wants to add more devices (max 4)
            if len(self.excluded_devices) < 4:
                return await self.async_step_add_more_excluded_devices()
            else:
                # Max devices reached, move to predictive charging
                self.config_data["excluded_devices"] = self.excluded_devices
                return await self.async_step_predictive_charging()

        device_num = len(self.excluded_devices) + 1
        return self.async_show_form(
            step_id="add_excluded_device",
            data_schema=vol.Schema(
                {
                    vol.Required("power_sensor"):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Required("included_in_consumption", default=True): bool,
                    vol.Optional("allow_solar_surplus", default=False): bool,
                    vol.Optional("ev_charger_no_telemetry", default=False): bool,
                }
            ),
            description_placeholders={
                "device_num": str(device_num),
                "description": f"Configure excluded device {device_num}"
            },
        )

    async def async_step_add_more_excluded_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 9: Ask if user wants to add more excluded devices."""
        if user_input is not None:
            if user_input.get("add_more", False):
                return await self.async_step_add_excluded_device()
            else:
                # User finished adding devices, move to predictive charging
                self.config_data["excluded_devices"] = self.excluded_devices
                return await self.async_step_predictive_charging()

        return self.async_show_form(
            step_id="add_more_excluded_devices",
            data_schema=vol.Schema(
                {
                    vol.Required("add_more", default=False): bool,
                }
            ),
            description_placeholders={
                "current_devices": str(len(self.excluded_devices)),
                "max_devices": "4",
            },
        )

    async def async_step_predictive_charging(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 10: Ask if user wants to configure predictive grid charging."""
        if user_input is not None:
            if user_input.get("configure_predictive_charging", False):
                return await self.async_step_predictive_charging_mode()
            else:
                # Predictive charging disabled - preserve global sensor if set in step 1
                self.config_data["enable_predictive_charging"] = False
                self.config_data["charging_time_slot"] = None
                self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_TIME_SLOT
                if not self.config_data.get(CONF_SOLAR_FORECAST_SENSOR):
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = None
                return await self.async_step_weekly_full_charge()

        return self.async_show_form(
            step_id="predictive_charging",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_predictive_charging", default=False): bool,
                }
            ),
        )

    async def async_step_predictive_charging_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 10b: Select predictive charging mode (Time Slot vs Dynamic Pricing)."""
        if user_input is not None:
            mode = user_input.get(CONF_PREDICTIVE_CHARGING_MODE, PREDICTIVE_MODE_TIME_SLOT)
            self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = mode
            if mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
                return await self.async_step_dynamic_pricing_config()
            elif mode == PREDICTIVE_MODE_REALTIME_PRICE:
                return await self.async_step_realtime_price_config()
            else:
                return await self.async_step_predictive_charging_config()

        return self.async_show_form(
            step_id="predictive_charging_mode",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PREDICTIVE_CHARGING_MODE, default=PREDICTIVE_MODE_TIME_SLOT):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    PREDICTIVE_MODE_TIME_SLOT,
                                    PREDICTIVE_MODE_DYNAMIC_PRICING,
                                    PREDICTIVE_MODE_REALTIME_PRICE,
                                ],
                                translation_key="predictive_charging_mode",
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                }
            ),
        )

    async def async_step_predictive_charging_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 11a: Configure time slot predictive grid charging."""
        errors = {}
        # Check if solar forecast sensor was already configured in step 1
        has_global_sensor = bool(self.config_data.get(CONF_SOLAR_FORECAST_SENSOR))

        if user_input is not None:
                try:
                    if has_global_sensor:
                        forecast_sensor = self.config_data[CONF_SOLAR_FORECAST_SENSOR]
                    else:
                        forecast_sensor = user_input.get("solar_forecast_sensor")
                        if forecast_sensor:
                            forecast_state = self.hass.states.get(forecast_sensor)
                            if forecast_state is None:
                                errors["solar_forecast_sensor"] = "sensor_not_found"
                            else:
                                unit = forecast_state.attributes.get("unit_of_measurement", "")
                                if unit not in ["kWh", "Wh"]:
                                    errors["solar_forecast_sensor"] = "invalid_unit"

                    if not errors:
                        self.config_data["enable_predictive_charging"] = True
                        self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_TIME_SLOT
                        self.config_data["charging_time_slot"] = {
                            "start_time": user_input["start_time"],
                            "end_time": user_input["end_time"],
                            "days": user_input["days"],
                        }
                        self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                        self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                        self.config_data[CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT] = user_input.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)

                        return await self.async_step_weekly_full_charge()
                except Exception as e:
                    _LOGGER.error("Error validating predictive charging config: %s", e)
                    errors["base"] = "unknown"

        schema_dict = {
            vol.Required("start_time"): TimeSelector(),
            vol.Required("end_time"): TimeSelector(),
            vol.Optional("days", default=["mon", "tue", "wed", "thu", "fri", "sat", "sun"]):
                SelectSelector(
                    SelectSelectorConfig(
                        options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        translation_key="weekday",
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
        }
        if not has_global_sensor:
            schema_dict[vol.Optional("solar_forecast_sensor")] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, default=DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)] = NumberSelector(
            NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
        )

        return self.async_show_form(
            step_id="predictive_charging_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_dynamic_pricing_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 11b: Configure dynamic pricing predictive grid charging."""
        errors = {}
        has_global_sensor = bool(self.config_data.get(CONF_SOLAR_FORECAST_SENSOR))

        if user_input is not None:
            try:
                integration_type = user_input[CONF_PRICE_INTEGRATION_TYPE]
                price_sensor = user_input[CONF_PRICE_SENSOR]

                # Validate price sensor has expected attributes
                price_state = self.hass.states.get(price_sensor)
                if price_state is None:
                    errors[CONF_PRICE_SENSOR] = "sensor_not_found"
                else:
                    attrs = price_state.attributes
                    if integration_type == PRICE_INTEGRATION_PVPC:
                        if not any(f"price_{h:02d}h" in attrs for h in range(24)):
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    elif integration_type == PRICE_INTEGRATION_CKW:
                        prices = attrs.get("prices")
                        if not prices or not isinstance(prices, (list, tuple)) or len(prices) == 0:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    elif integration_type == PRICE_INTEGRATION_EPEX:
                        data = attrs.get("data")
                        if not data or not isinstance(data, (list, tuple)) or len(data) == 0:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    elif integration_type == PRICE_INTEGRATION_ENTSOE:
                        prices = attrs.get("prices_today")
                        if not prices or not isinstance(prices, (list, tuple)) or len(prices) == 0:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    else:  # Nordpool
                        if "raw_today" not in attrs:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"

                # Validate solar forecast sensor if not global
                if has_global_sensor:
                    forecast_sensor = self.config_data[CONF_SOLAR_FORECAST_SENSOR]
                else:
                    forecast_sensor = user_input.get("solar_forecast_sensor")
                    if forecast_sensor:
                        forecast_state = self.hass.states.get(forecast_sensor)
                        if forecast_state is None:
                            errors["solar_forecast_sensor"] = "sensor_not_found"
                        else:
                            unit = forecast_state.attributes.get("unit_of_measurement", "")
                            if unit not in ["kWh", "Wh"]:
                                errors["solar_forecast_sensor"] = "invalid_unit"

                if not errors:
                    max_price_raw = user_input.get(CONF_MAX_PRICE_THRESHOLD)
                    max_price = float(str(max_price_raw).replace(",", ".")) if max_price_raw else None

                    self.config_data["enable_predictive_charging"] = True
                    self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_DYNAMIC_PRICING
                    self.config_data[CONF_PRICE_INTEGRATION_TYPE] = integration_type
                    self.config_data[CONF_PRICE_SENSOR] = price_sensor
                    self.config_data[CONF_MAX_PRICE_THRESHOLD] = max_price
                    self.config_data[CONF_DP_PRICE_DISCHARGE_CONTROL] = user_input.get(CONF_DP_PRICE_DISCHARGE_CONTROL, False)
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    self.config_data[CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT] = user_input.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)

                    return await self.async_step_weekly_full_charge()
            except Exception as e:
                _LOGGER.error("Error validating dynamic pricing config: %s", e)
                errors["base"] = "unknown"

        schema_dict: dict = {
            vol.Required(CONF_PRICE_INTEGRATION_TYPE, default=PRICE_INTEGRATION_NORDPOOL):
                SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            PRICE_INTEGRATION_NORDPOOL,
                            PRICE_INTEGRATION_PVPC,
                            PRICE_INTEGRATION_CKW,
                            PRICE_INTEGRATION_EPEX,
                            PRICE_INTEGRATION_ENTSOE,
                        ],
                        translation_key="price_integration_type",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Required(CONF_PRICE_SENSOR):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(CONF_MAX_PRICE_THRESHOLD):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_DP_PRICE_DISCHARGE_CONTROL, default=False): bool,
        }
        if not has_global_sensor:
            schema_dict[vol.Optional("solar_forecast_sensor")] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, default=DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)] = NumberSelector(
            NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
        )

        return self.async_show_form(
            step_id="dynamic_pricing_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_realtime_price_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 11d: Configure real-time price charging mode."""
        errors = {}
        has_global_sensor = bool(self.config_data.get(CONF_SOLAR_FORECAST_SENSOR))

        if user_input is not None:
            try:
                price_sensor = user_input[CONF_PRICE_SENSOR]
                price_state = self.hass.states.get(price_sensor)
                if price_state is None:
                    errors[CONF_PRICE_SENSOR] = "sensor_not_found"

                if has_global_sensor:
                    forecast_sensor = self.config_data[CONF_SOLAR_FORECAST_SENSOR]
                else:
                    forecast_sensor = user_input.get("solar_forecast_sensor")
                    if forecast_sensor:
                        forecast_state = self.hass.states.get(forecast_sensor)
                        if forecast_state is None:
                            errors["solar_forecast_sensor"] = "sensor_not_found"
                        else:
                            unit = forecast_state.attributes.get("unit_of_measurement", "")
                            if unit not in ["kWh", "Wh"]:
                                errors["solar_forecast_sensor"] = "invalid_unit"

                if not errors:
                    max_price_raw = user_input.get(CONF_MAX_PRICE_THRESHOLD)
                    max_price = float(str(max_price_raw).replace(",", ".")) if max_price_raw else None
                    avg_sensor = user_input.get(CONF_AVERAGE_PRICE_SENSOR) or None

                    self.config_data["enable_predictive_charging"] = True
                    self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_REALTIME_PRICE
                    self.config_data[CONF_PRICE_SENSOR] = price_sensor
                    self.config_data[CONF_MAX_PRICE_THRESHOLD] = max_price
                    self.config_data[CONF_AVERAGE_PRICE_SENSOR] = avg_sensor
                    self.config_data[CONF_RT_PRICE_DISCHARGE_CONTROL] = user_input.get(CONF_RT_PRICE_DISCHARGE_CONTROL, False)
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    self.config_data[CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT] = user_input.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)

                    return await self.async_step_weekly_full_charge()
            except Exception as e:
                _LOGGER.error("Error validating real-time price config: %s", e)
                errors["base"] = "unknown"

        schema_dict: dict = {
            vol.Required(CONF_PRICE_SENSOR):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(CONF_MAX_PRICE_THRESHOLD):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Optional(CONF_AVERAGE_PRICE_SENSOR):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Required(CONF_RT_PRICE_DISCHARGE_CONTROL, default=False): bool,
        }
        if not has_global_sensor:
            schema_dict[vol.Optional("solar_forecast_sensor")] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, default=DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)] = NumberSelector(
            NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
        )

        return self.async_show_form(
            step_id="realtime_price_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_weekly_full_charge(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 11: Ask if user wants to enable weekly full battery charge."""
        if user_input is not None:
            if user_input.get("configure_weekly_full_charge", False):
                return await self.async_step_weekly_full_charge_config()
            else:
                # Weekly full charge disabled
                self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = False
                self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = "sun"
                return await self.async_step_charge_delay()

        return self.async_show_form(
            step_id="weekly_full_charge",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_weekly_full_charge", default=False): bool,
                }
            ),
            description_placeholders={
                "description": "Enable weekly full battery charge for cell balancing"
            },
        )

    async def async_step_weekly_full_charge_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 12: Configure weekly full charge day."""
        if user_input is not None:
            self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = True
            self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = user_input["weekly_full_charge_day"]
            self.config_data[CONF_ENABLE_BALANCE_MONITOR] = True
            return await self.async_step_charge_delay()

        return self.async_show_form(
            step_id="weekly_full_charge_config",
            data_schema=vol.Schema(
                {
                    vol.Required("weekly_full_charge_day", default="sun"):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                                translation_key="weekday",
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                }
            ),
        )

    async def async_step_charge_delay(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 13: Ask if user wants to enable solar charge delay."""
        if user_input is not None:
            if user_input.get("configure_charge_delay", False):
                return await self.async_step_charge_delay_config()
            else:
                self.config_data[CONF_ENABLE_CHARGE_DELAY] = False
                return await self.async_step_capacity_protection()

        return self.async_show_form(
            step_id="charge_delay",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_charge_delay", default=False): bool,
                }
            ),
        )

    async def async_step_charge_delay_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 14: Configure charge delay details."""
        errors = {}
        if user_input is not None:
            self.config_data[CONF_ENABLE_CHARGE_DELAY] = True
            self.config_data[CONF_DELAY_SAFETY_MARGIN_MIN] = int(
                user_input.get("delay_safety_margin_h", DEFAULT_DELAY_SAFETY_MARGIN_MIN / 60) * 60
            )
            soc_setpoint_enabled = user_input.get("delay_soc_setpoint_enabled", DEFAULT_DELAY_SOC_SETPOINT_ENABLED)
            self.config_data[CONF_DELAY_SOC_SETPOINT_ENABLED] = soc_setpoint_enabled
            if soc_setpoint_enabled:
                self.config_data[CONF_DELAY_SOC_SETPOINT] = int(
                    user_input.get("delay_soc_setpoint", DEFAULT_DELAY_SOC_SETPOINT)
                )

            # Check if solar forecast sensor already configured
            existing_forecast = self.config_data.get(CONF_SOLAR_FORECAST_SENSOR)
            if not existing_forecast:
                forecast_sensor = user_input.get("solar_forecast_sensor")
                if not forecast_sensor:
                    errors["solar_forecast_sensor"] = "sensor_not_found"
                else:
                    state = self.hass.states.get(forecast_sensor)
                    if state is None:
                        errors["solar_forecast_sensor"] = "sensor_not_found"
                    else:
                        self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor

            if not errors:
                return await self.async_step_capacity_protection()

        has_forecast_sensor = bool(self.config_data.get(CONF_SOLAR_FORECAST_SENSOR))
        schema_dict = {
            vol.Optional("delay_safety_margin_h", default=DEFAULT_DELAY_SAFETY_MARGIN_MIN / 60):
                NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=6, step=0.5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="h",
                    )
                ),
            vol.Optional("delay_soc_setpoint_enabled", default=DEFAULT_DELAY_SOC_SETPOINT_ENABLED): bool,
            vol.Optional("delay_soc_setpoint", default=DEFAULT_DELAY_SOC_SETPOINT):
                NumberSelector(
                    NumberSelectorConfig(
                        min=12, max=90, step=5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
        }
        if not has_forecast_sensor:
            schema_dict[vol.Optional("solar_forecast_sensor")] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )

        return self.async_show_form(
            step_id="charge_delay_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_capacity_protection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to enable capacity protection mode."""
        if user_input is not None:
            if user_input.get("configure_capacity_protection", False):
                return await self.async_step_capacity_protection_config()
            else:
                self.config_data[CONF_CAPACITY_PROTECTION_ENABLED] = False
                return await self.async_step_hourly_balance()

        return self.async_show_form(
            step_id="capacity_protection",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_capacity_protection", default=False): bool,
                }
            ),
        )

    async def async_step_capacity_protection_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure capacity protection parameters."""
        if user_input is not None:
            self.config_data[CONF_CAPACITY_PROTECTION_ENABLED] = True
            self.config_data[CONF_CAPACITY_PROTECTION_SOC_THRESHOLD] = int(user_input["capacity_protection_soc_threshold"])
            self.config_data[CONF_CAPACITY_PROTECTION_LIMIT] = int(user_input["capacity_protection_limit"])
            return await self.async_step_hourly_balance()

        return self.async_show_form(
            step_id="capacity_protection_config",
            data_schema=vol.Schema(
                {
                    vol.Required("capacity_protection_soc_threshold", default=DEFAULT_CAPACITY_PROTECTION_SOC):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=20, max=100, step=1,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="%",
                            )
                        ),
                    vol.Required("capacity_protection_limit", default=DEFAULT_CAPACITY_PROTECTION_LIMIT):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=500, max=10000, step=100,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
        )

    async def async_step_hourly_balance(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to enable hourly net balance control."""
        if user_input is not None:
            if user_input.get("configure_hourly_balance", False):
                return await self.async_step_hourly_balance_config()
            else:
                from .const import (
                    CONF_ENABLE_HOURLY_BALANCE,
                    CONF_HOURLY_BALANCE_TARGET_NET_WH,
                    CONF_HOURLY_BALANCE_MAX_OFFSET_W,
                    CONF_HOURLY_BALANCE_DEADBAND_WH,
                    CONF_HOURLY_BALANCE_HYSTERESIS_W,
                    DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
                    DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
                    DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
                    DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
                )
                self.config_data[CONF_ENABLE_HOURLY_BALANCE] = False
                self.config_data[CONF_HOURLY_BALANCE_TARGET_NET_WH] = DEFAULT_HOURLY_BALANCE_TARGET_NET_WH
                self.config_data[CONF_HOURLY_BALANCE_MAX_OFFSET_W] = DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W
                self.config_data[CONF_HOURLY_BALANCE_DEADBAND_WH] = DEFAULT_HOURLY_BALANCE_DEADBAND_WH
                self.config_data[CONF_HOURLY_BALANCE_HYSTERESIS_W] = DEFAULT_HOURLY_BALANCE_HYSTERESIS_W
                return await self.async_step_pd_advanced()

        return self.async_show_form(
            step_id="hourly_balance",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_hourly_balance", default=False): bool,
                }
            ),
        )

    async def async_step_hourly_balance_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure hourly net balance parameters."""
        from .const import (
            CONF_ENABLE_HOURLY_BALANCE,
            CONF_HOURLY_BALANCE_TARGET_NET_WH,
            CONF_HOURLY_BALANCE_MAX_OFFSET_W,
            CONF_HOURLY_BALANCE_DEADBAND_WH,
            CONF_HOURLY_BALANCE_HYSTERESIS_W,
            DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
            DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
            DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
            DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
        )
        if user_input is not None:
            self.config_data[CONF_ENABLE_HOURLY_BALANCE] = True
            self.config_data[CONF_HOURLY_BALANCE_TARGET_NET_WH] = float(
                user_input.get(CONF_HOURLY_BALANCE_TARGET_NET_WH, DEFAULT_HOURLY_BALANCE_TARGET_NET_WH)
            )
            self.config_data[CONF_HOURLY_BALANCE_MAX_OFFSET_W] = int(
                user_input.get(CONF_HOURLY_BALANCE_MAX_OFFSET_W, DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W)
            )
            self.config_data[CONF_HOURLY_BALANCE_DEADBAND_WH] = float(
                user_input.get(CONF_HOURLY_BALANCE_DEADBAND_WH, DEFAULT_HOURLY_BALANCE_DEADBAND_WH)
            )
            self.config_data[CONF_HOURLY_BALANCE_HYSTERESIS_W] = int(
                user_input.get(CONF_HOURLY_BALANCE_HYSTERESIS_W, DEFAULT_HOURLY_BALANCE_HYSTERESIS_W)
            )
            return await self.async_step_pd_advanced()

        return self.async_show_form(
            step_id="hourly_balance_config",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_HOURLY_BALANCE_TARGET_NET_WH, default=DEFAULT_HOURLY_BALANCE_TARGET_NET_WH):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=-2.0, max=2.0, step=0.1,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="kWh",
                            )
                        ),
                    vol.Optional(CONF_HOURLY_BALANCE_MAX_OFFSET_W, default=DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=100, max=5000, step=50,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional(CONF_HOURLY_BALANCE_DEADBAND_WH, default=DEFAULT_HOURLY_BALANCE_DEADBAND_WH):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=0.5, step=0.1,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="kWh",
                            )
                        ),
                    vol.Optional(CONF_HOURLY_BALANCE_HYSTERESIS_W, default=DEFAULT_HOURLY_BALANCE_HYSTERESIS_W):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=200, step=5,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
        )

    async def async_step_pd_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to configure advanced PD controller parameters."""
        if user_input is not None:
            if user_input.get("configure_pd_advanced", False):
                return await self.async_step_pd_advanced_config()
            else:
                self.config_data[CONF_PD_KP] = DEFAULT_PD_KP
                self.config_data[CONF_PD_KD] = DEFAULT_PD_KD
                self.config_data[CONF_PD_DEADBAND] = DEFAULT_PD_DEADBAND
                self.config_data[CONF_PD_MAX_POWER_CHANGE] = DEFAULT_PD_MAX_POWER_CHANGE
                self.config_data[CONF_PD_DIRECTION_HYSTERESIS] = DEFAULT_PD_DIRECTION_HYSTERESIS
                self.config_data[CONF_PD_MIN_CHARGE_POWER] = DEFAULT_PD_MIN_CHARGE_POWER
                self.config_data[CONF_PD_MIN_DISCHARGE_POWER] = DEFAULT_PD_MIN_DISCHARGE_POWER
                self.config_data[CONF_TARGET_GRID_POWER] = DEFAULT_TARGET_GRID_POWER
                self.config_data[CONF_ENABLE_SYSTEM_POWER_LIMITS] = DEFAULT_ENABLE_SYSTEM_POWER_LIMITS
                self.config_data[CONF_SYSTEM_MAX_CHARGE_POWER] = DEFAULT_SYSTEM_MAX_CHARGE_POWER
                self.config_data[CONF_SYSTEM_MAX_DISCHARGE_POWER] = DEFAULT_SYSTEM_MAX_DISCHARGE_POWER
                self.config_data[CONF_ENABLE_BALANCE_MONITOR] = True
                return self.async_create_entry(
                    title="Marstek Venus Energy Manager", data=self.config_data
                )

        return self.async_show_form(
            step_id="pd_advanced",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_pd_advanced", default=False): bool,
                }
            ),
        )

    async def async_step_pd_advanced_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure PD controller advanced parameters."""
        if user_input is not None:
            self.config_data[CONF_PD_KP] = user_input["pd_kp"]
            self.config_data[CONF_PD_KD] = user_input["pd_kd"]
            self.config_data[CONF_PD_DEADBAND] = user_input["pd_deadband"]
            self.config_data[CONF_PD_MAX_POWER_CHANGE] = user_input["pd_max_power_change"]
            self.config_data[CONF_PD_DIRECTION_HYSTERESIS] = user_input["pd_direction_hysteresis"]
            self.config_data[CONF_PD_MIN_CHARGE_POWER] = user_input["pd_min_charge_power"]
            self.config_data[CONF_PD_MIN_DISCHARGE_POWER] = user_input["pd_min_discharge_power"]
            self.config_data[CONF_TARGET_GRID_POWER] = user_input["pd_target_grid_power"]
            enable_system_limits = user_input.get("enable_system_power_limits", False)
            self.config_data[CONF_ENABLE_SYSTEM_POWER_LIMITS] = enable_system_limits
            self.config_data[CONF_SYSTEM_MAX_CHARGE_POWER] = (
                user_input["system_max_charge_power"] if enable_system_limits
                else DEFAULT_SYSTEM_MAX_CHARGE_POWER
            )
            self.config_data[CONF_SYSTEM_MAX_DISCHARGE_POWER] = (
                user_input["system_max_discharge_power"] if enable_system_limits
                else DEFAULT_SYSTEM_MAX_DISCHARGE_POWER
            )
            self.config_data[CONF_ENABLE_BALANCE_MONITOR] = True
            return self.async_create_entry(
                title="Marstek Venus Energy Manager", data=self.config_data
            )

        return self.async_show_form(
            step_id="pd_advanced_config",
            data_schema=vol.Schema(
                {
                    vol.Required("pd_kp", default=DEFAULT_PD_KP):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0.1, max=2.0, step=0.05, mode=NumberSelectorMode.BOX
                            )
                        ),
                    vol.Required("pd_kd", default=DEFAULT_PD_KD):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0.0, max=2.0, step=0.05, mode=NumberSelectorMode.BOX
                            )
                        ),
                    vol.Required("pd_deadband", default=DEFAULT_PD_DEADBAND):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=200, step=5, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                    vol.Required("pd_max_power_change", default=DEFAULT_PD_MAX_POWER_CHANGE):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=100, max=2000, step=50, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                    vol.Required("pd_direction_hysteresis", default=DEFAULT_PD_DIRECTION_HYSTERESIS):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=200, step=5, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                    vol.Optional("pd_min_charge_power", default=DEFAULT_PD_MIN_CHARGE_POWER):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=2000, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("pd_min_discharge_power", default=DEFAULT_PD_MIN_DISCHARGE_POWER):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=2000, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("pd_target_grid_power", default=DEFAULT_TARGET_GRID_POWER):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=-2500, max=2500, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("enable_system_power_limits", default=DEFAULT_ENABLE_SYSTEM_POWER_LIMITS): bool,
                    vol.Optional("system_max_charge_power", default=DEFAULT_SYSTEM_MAX_CHARGE_POWER):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=15000, step=50,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("system_max_discharge_power", default=DEFAULT_SYSTEM_MAX_DISCHARGE_POWER):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=15000, step=50,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
        )

    def _migrate_battery_registry_ids(
        self,
        entry: ConfigEntry,
        old_host: str,
        old_port: int,
        new_host: str,
        new_port: int,
        old_slave: int = DEFAULT_SLAVE_ID,
        new_slave: int = DEFAULT_SLAVE_ID,
    ) -> None:
        """Rename entity unique_ids and device identifiers when a battery's host/port/slave changes.

        Preserves long-term statistics and history by keeping the same entity_id.
        Battery-level keys follow `coordinator.device_key` (`{host}_{port}` for
        slave 1, `{host}_{port}_{slave}` otherwise); the device identifier is
        `(DOMAIN, device_key)`. Both are rewritten in place.
        """
        def _device_key(host: str, port: int, slave: int) -> str:
            return f"{host}_{port}" if slave == 1 else f"{host}_{port}_{slave}"

        old_device_id = _device_key(old_host, old_port, old_slave)
        new_device_id = _device_key(new_host, new_port, new_slave)
        old_prefix = f"{old_device_id}_"
        new_prefix = f"{new_device_id}_"

        ent_reg = er.async_get(self.hass)
        for ent in list(ent_reg.entities.values()):
            if (
                ent.config_entry_id == entry.entry_id
                and ent.unique_id.startswith(old_prefix)
            ):
                new_uid = new_prefix + ent.unique_id[len(old_prefix):]
                ent_reg.async_update_entity(ent.entity_id, new_unique_id=new_uid)

        dev_reg = dr.async_get(self.hass)
        old_dev = dev_reg.async_get_device(identifiers={(DOMAIN, old_device_id)})
        if old_dev is not None:
            new_identifiers = set(old_dev.identifiers)
            new_identifiers.discard((DOMAIN, old_device_id))
            new_identifiers.add((DOMAIN, new_device_id))
            dev_reg.async_update_device(
                old_dev.id, new_identifiers=new_identifiers
            )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration — update battery connection settings (IP/port)."""
        self.battery_index = 0
        self._reconfigure_batteries: list[dict] = []
        return await self.async_step_reconfigure_battery()

    async def async_step_reconfigure_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update connection settings for each battery during reconfiguration."""
        entry = self._get_reconfigure_entry()
        current_batteries = entry.data.get("batteries", [])
        battery_num = self.battery_index + 1
        errors = {}

        if user_input is not None:
            battery_version = user_input.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
            slave_id = user_input.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
            if not await self._test_connection(
                user_input[CONF_HOST], user_input[CONF_PORT], battery_version, slave_id
            ):
                errors["base"] = "cannot_connect"
            else:
                original = (
                    current_batteries[self.battery_index]
                    if self.battery_index < len(current_batteries)
                    else {}
                )
                old_host = original.get(CONF_HOST)
                old_port = original.get(CONF_PORT)
                old_slave = original.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
                new_host = user_input[CONF_HOST]
                new_port = user_input[CONF_PORT]

                if (
                    old_host
                    and old_port
                    and (old_host != new_host or old_port != new_port or old_slave != slave_id)
                ):
                    self._migrate_battery_registry_ids(
                        entry, old_host, old_port, new_host, new_port, old_slave, slave_id
                    )

                updated = dict(original)
                updated[CONF_NAME] = user_input[CONF_NAME]
                updated[CONF_HOST] = new_host
                updated[CONF_PORT] = new_port
                updated[CONF_SLAVE_ID] = slave_id
                updated[CONF_BATTERY_VERSION] = battery_version
                self._reconfigure_batteries.append(updated)
                self.battery_index += 1

                if self.battery_index >= len(current_batteries):
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={"batteries": self._reconfigure_batteries},
                    )
                return await self.async_step_reconfigure_battery()

        current = (
            current_batteries[self.battery_index]
            if self.battery_index < len(current_batteries)
            else {}
        )
        defaults = {
            CONF_NAME: current.get(CONF_NAME, f"Marstek Venus {battery_num}"),
            CONF_HOST: current.get(CONF_HOST, ""),
            CONF_PORT: current.get(CONF_PORT, 502),
            CONF_SLAVE_ID: current.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID),
            CONF_BATTERY_VERSION: current.get(CONF_BATTERY_VERSION, DEFAULT_VERSION),
        }

        return self.async_show_form(
            step_id="reconfigure_battery",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
                    vol.Required(CONF_SLAVE_ID, default=defaults[CONF_SLAVE_ID]):
                        vol.All(NumberSelector(NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)), vol.Coerce(int)),
                    vol.Required(
                        CONF_BATTERY_VERSION, default=defaults[CONF_BATTERY_VERSION]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "v2", "label": "Ev2"},
                                {"value": "v3", "label": "Ev3"},
                                {"value": "vA", "label": "A"},
                                {"value": "vD", "label": "D"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"battery_num": str(battery_num)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        # NOTE: Do NOT set self.config_entry - it's a read-only property from OptionsFlow base class
        # The config_entry is automatically available as self.config_entry
        self.config_data = {}
        self.battery_configs = []
        self.battery_index = 0
        self.time_slots = []
        self.excluded_devices = []
        self._current_battery_data = {}  # Stores connection data between battery steps
        self._pending_slot_step_a: dict | None = None  # Buffer between slot step A and step B
        _LOGGER.info("OptionsFlowHandler initialized successfully for entry: %s", config_entry.entry_id)

    async def _test_connection(self, host: str, port: int, version: str = "v2", slave_id: int = DEFAULT_SLAVE_ID) -> bool:
        """Test connection to a Marstek Venus battery.

        If a coordinator already holds a connection to this host, temporarily
        close it (under lock) to free the single-connection slot, run the test,
        and reconnect. Marstek firmware only supports one Modbus TCP connection.
        """
        soc_register = REGISTER_MAP.get(version, {}).get("battery_soc")
        if soc_register is None:
            return False

        # Check if there's an active coordinator for this host + slave id
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinators = entry_data.get("coordinators", [])
        existing_coordinator = None
        for coordinator in coordinators:
            if coordinator.host == host and coordinator.slave_id == slave_id:
                existing_coordinator = coordinator
                break

        if existing_coordinator is not None:
            _LOGGER.info(
                "Reusing coordinator for %s (version=%s) - closing connection for test",
                host, existing_coordinator.battery_version
            )
            # Hold the lock so polling and control loop wait (no errors/warnings)
            async with existing_coordinator.lock:
                # Close existing connection to free the single-connection slot
                await existing_coordinator.client.async_close()
                # Give firmware time to release the connection slot
                await asyncio.sleep(0.5)

                # Test with a fresh connection
                test_client = MarstekModbusClient(host, port, slave_id=slave_id)
                try:
                    connected = await test_client.async_connect()
                    if not connected:
                        _LOGGER.warning("Test connection to %s failed after closing coordinator", host)
                        await existing_coordinator.client.async_connect()
                        return False

                    value = await test_client.async_read_register(
                        soc_register, "uint16"
                    )
                    await test_client.async_close()
                    await asyncio.sleep(0.3)

                    # Reconnect the coordinator's connection
                    await existing_coordinator.client.async_connect()

                    _LOGGER.info("Test connection to %s successful (SOC=%s), coordinator reconnected", host, value)
                    return value is not None
                except Exception as e:
                    _LOGGER.warning("Test connection to %s failed with exception: %s", host, e)
                    try:
                        await test_client.async_close()
                    except Exception:
                        pass
                    await asyncio.sleep(0.3)
                    # Always reconnect coordinator, even on error
                    await existing_coordinator.client.async_connect()
                    return False
        else:
            _LOGGER.info("No existing coordinator for %s - opening new connection", host)
            # No existing coordinator for this host - open new connection directly
            client = MarstekModbusClient(host, port, slave_id=slave_id)
            try:
                connected = await client.async_connect()
                if not connected:
                    return False

                value = await client.async_read_register(soc_register, "uint16")
                await client.async_close()
                return value is not None
            except Exception:
                try:
                    await client.async_close()
                except Exception:
                    pass
                return False

    async def _save_and_finish(self) -> FlowResult:
        """Merge config_data into existing entry data, save, and reload."""
        new_data = dict(self.config_entry.data)
        new_data.update(self.config_data)
        new_data[CONF_ENABLE_BALANCE_MONITOR] = True
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data={})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show menu to select which section to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "sensors",
                "batteries",
                "time_slots",
                "excluded_devices",
                "predictive_charging",
                "weekly_full_charge",
                "charge_delay",
                "capacity_protection",
                "hourly_balance",
                "pd_advanced",
            ],
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure consumption sensor and optional solar forecast sensor."""
        errors = {}
        try:
            if user_input is not None:
                # Validate solar forecast sensor if provided
                forecast_sensor = user_input.get(CONF_SOLAR_FORECAST_SENSOR)
                if forecast_sensor:
                    forecast_state = self.hass.states.get(forecast_sensor)
                    if forecast_state is None:
                        errors["solar_forecast_sensor"] = "sensor_not_found"
                    else:
                        unit = forecast_state.attributes.get("unit_of_measurement", "")
                        if unit not in ["kWh", "Wh"]:
                            errors["solar_forecast_sensor"] = "invalid_unit"

                # Validate solar production sensor if provided
                solar_sensor = user_input.get(CONF_SOLAR_PRODUCTION_SENSOR)
                if solar_sensor:
                    solar_state = self.hass.states.get(solar_sensor)
                    if solar_state is None:
                        errors[CONF_SOLAR_PRODUCTION_SENSOR] = "sensor_not_found"
                    else:
                        unit = solar_state.attributes.get("unit_of_measurement", "")
                        if unit not in ["W", "kW"]:
                            errors[CONF_SOLAR_PRODUCTION_SENSOR] = "invalid_unit"

                if not errors:
                    self.config_data["consumption_sensor"] = user_input["consumption_sensor"]
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data[CONF_SOLAR_PRODUCTION_SENSOR] = solar_sensor
                    self.config_data[CONF_METER_INVERTED] = user_input.get(CONF_METER_INVERTED, False)
                    self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                    return await self._save_and_finish()

            # Load current configuration with defensive defaults
            current_sensor = self.config_entry.data.get("consumption_sensor", "")
            current_forecast = self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR, "")
            current_solar = self.config_entry.data.get(CONF_SOLAR_PRODUCTION_SENSOR, "")
            current_inverted = self.config_entry.data.get(CONF_METER_INVERTED, False)
            current_max_power = self.config_entry.data.get("max_contracted_power", 7000)
        except Exception as e:
            _LOGGER.error("Error in options flow sensors: %s", e, exc_info=True)
            return self.async_abort(reason="unknown_error")

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {
                    vol.Required("consumption_sensor", default=current_sensor):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_METER_INVERTED, default=current_inverted):
                        BooleanSelector(),
                    vol.Required("max_contracted_power", default=current_max_power):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX
                            )
                        ),
                    vol.Optional(CONF_SOLAR_FORECAST_SENSOR, description={"suggested_value": current_forecast} if current_forecast else {}):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_SOLAR_PRODUCTION_SENSOR, description={"suggested_value": current_solar} if current_solar else {}):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                }
            ),
            errors=errors if errors else None,
        )

    async def async_step_batteries(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure number of batteries."""
        try:
            if user_input is not None:
                self.config_data["num_batteries"] = int(user_input["num_batteries"])
                return await self.async_step_battery_connection()

            # Load current number of batteries with defensive handling
            batteries = self.config_entry.data.get("batteries", [])
            current_batteries = len(batteries) if batteries else 1
        except Exception as e:
            _LOGGER.error("Error in options flow batteries step: %s", e, exc_info=True)
            return self.async_abort(reason="unknown_error")

        return self.async_show_form(
            step_id="batteries",
            data_schema=vol.Schema(
                {
                    vol.Required("num_batteries", default=current_batteries):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1, max=6, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                }
            ),
        )

    async def async_step_battery_connection(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure connection details and battery model for each battery."""
        errors = {}

        try:
            battery_num = self.battery_index + 1
            current_batteries = self.config_entry.data.get("batteries", [])

            if user_input is not None:
                battery_version = user_input.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
                slave_id = user_input.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
                connection_result = await self._test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    battery_version,
                    slave_id,
                )
                if not connection_result:
                    errors["base"] = "cannot_connect"
                else:
                    self._current_battery_data = {
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_SLAVE_ID: slave_id,
                        CONF_BATTERY_VERSION: battery_version,
                    }
                    return await self.async_step_battery_limits()

            if self.battery_index < len(current_batteries):
                current_battery = current_batteries[self.battery_index]
                defaults = {
                    CONF_NAME: current_battery.get(CONF_NAME, f"Marstek Venus {battery_num}"),
                    CONF_HOST: current_battery.get(CONF_HOST, ""),
                    CONF_PORT: current_battery.get(CONF_PORT, 502),
                    CONF_SLAVE_ID: current_battery.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID),
                    CONF_BATTERY_VERSION: current_battery.get(CONF_BATTERY_VERSION, DEFAULT_VERSION),
                }
            else:
                defaults = {
                    CONF_NAME: f"Marstek Venus {battery_num}",
                    CONF_HOST: "",
                    CONF_PORT: 502,
                    CONF_SLAVE_ID: DEFAULT_SLAVE_ID,
                    CONF_BATTERY_VERSION: DEFAULT_VERSION,
                }
        except Exception as e:
            _LOGGER.error("Error in options flow battery_connection step: %s", e, exc_info=True)
            return self.async_abort(reason="unknown_error")

        return self.async_show_form(
            step_id="battery_connection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
                    vol.Required(CONF_SLAVE_ID, default=defaults[CONF_SLAVE_ID]):
                        vol.All(NumberSelector(NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)), vol.Coerce(int)),
                    vol.Required(CONF_BATTERY_VERSION, default=defaults[CONF_BATTERY_VERSION]):
                        SelectSelector(SelectSelectorConfig(
                            options=[
                                {"value": "v2", "label": "Ev2"},
                                {"value": "v3", "label": "Ev3"},
                                {"value": "vA", "label": "A"},
                                {"value": "vD", "label": "D"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )),
                }
            ),
            errors=errors,
            description_placeholders={"battery_num": str(battery_num)},
        )

    async def async_step_battery_limits(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure power and SOC limits for the current battery."""
        try:
            battery_num = self.battery_index + 1
            battery_version = self._current_battery_data.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
            max_power = MAX_POWER_BY_VERSION.get(battery_version, 2500)
            current_batteries = self.config_entry.data.get("batteries", [])

            if user_input is not None:
                merged = dict(self._current_battery_data)
                merged["max_charge_power"] = int(user_input["max_charge_power"])
                merged["max_discharge_power"] = int(user_input["max_discharge_power"])
                merged["max_soc"] = int(user_input["max_soc"])
                merged["min_soc"] = int(user_input["min_soc"])
                merged["enable_charge_hysteresis"] = user_input["enable_charge_hysteresis"]
                merged["charge_hysteresis_percent"] = int(user_input.get("charge_hysteresis_percent", 5))
                merged["backup_offgrid_threshold"] = int(user_input.get("backup_offgrid_threshold", 50))
                merged[CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED] = user_input.get(
                    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                    DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                )
                self.battery_configs.append(merged)
                self.battery_index += 1

                num_batteries = self.config_data.get("num_batteries", 1)
                if self.battery_index >= num_batteries:
                    self.config_data["batteries"] = self.battery_configs
                    return await self._save_and_finish()
                return await self.async_step_battery_connection()

            if self.battery_index < len(current_batteries):
                current_battery = current_batteries[self.battery_index]
                defaults = {
                    "max_charge_power": min(current_battery.get("max_charge_power", max_power), max_power),
                    "max_discharge_power": min(current_battery.get("max_discharge_power", max_power), max_power),
                    "max_soc": current_battery.get("max_soc", 100),
                    "min_soc": current_battery.get("min_soc", 12),
                    "enable_charge_hysteresis": current_battery.get("enable_charge_hysteresis", False),
                    "charge_hysteresis_percent": current_battery.get("charge_hysteresis_percent", 5),
                    "backup_offgrid_threshold": current_battery.get("backup_offgrid_threshold", 50),
                    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED: current_battery.get(
                        CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                        DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                    ),
                }
            else:
                defaults = {
                    "max_charge_power": max_power,
                    "max_discharge_power": max_power,
                    "max_soc": 100,
                    "min_soc": 12,
                    "enable_charge_hysteresis": False,
                    "charge_hysteresis_percent": 5,
                    "backup_offgrid_threshold": 50,
                    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED: DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                }
        except Exception as e:
            _LOGGER.error("Error in options flow battery_limits step: %s", e, exc_info=True)
            return self.async_abort(reason="unknown_error")

        return self.async_show_form(
            step_id="battery_limits",
            data_schema=vol.Schema(
                {
                    vol.Required("max_charge_power", default=defaults["max_charge_power"]):
                        NumberSelector(NumberSelectorConfig(min=100, max=max_power, step=50, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
                    vol.Required("max_discharge_power", default=defaults["max_discharge_power"]):
                        NumberSelector(NumberSelectorConfig(min=100, max=max_power, step=50, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
                    vol.Required("max_soc", default=defaults["max_soc"]):
                        NumberSelector(NumberSelectorConfig(min=80, max=100, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("min_soc", default=defaults["min_soc"]):
                        NumberSelector(NumberSelectorConfig(min=12, max=30, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("enable_charge_hysteresis", default=defaults["enable_charge_hysteresis"]): bool,
                    vol.Optional("charge_hysteresis_percent", default=defaults["charge_hysteresis_percent"]):
                        NumberSelector(NumberSelectorConfig(min=5, max=50, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("backup_offgrid_threshold", default=defaults["backup_offgrid_threshold"]):
                        NumberSelector(NumberSelectorConfig(min=0, max=500, step=10, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
                    vol.Required(CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED, default=defaults[CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED]): bool,
                }
            ),
            description_placeholders={"battery_num": str(battery_num)},
        )

    async def async_step_time_slots(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask if user wants to configure time slots."""
        if user_input is not None:
            if user_input.get("configure_time_slots", False):
                # Reset time_slots list to start fresh
                self.time_slots = []
                return await self.async_step_add_time_slot()
            else:
                self.config_data["no_discharge_time_slots"] = []
                return await self._save_and_finish()

        # Check if time slots were previously configured
        existing_slots = self.config_entry.data.get("no_discharge_time_slots", [])
        has_existing_slots = len(existing_slots) > 0

        return self.async_show_form(
            step_id="time_slots",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_time_slots", default=has_existing_slots): bool,
                }
            ),
        )

    async def async_step_add_time_slot(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step A: configure base attributes of a time slot."""
        errors: dict = {}
        batteries = self.config_entry.data.get("batteries", [])

        if user_input is not None:
            errors = _validate_slot_step_a(user_input)
            if not errors:
                if _slots_overlap(
                    {
                        "start_time": user_input["start_time"],
                        "end_time": user_input["end_time"],
                        "days": user_input["days"],
                        "battery_scope": user_input.get("battery_scope", SLOT_BATTERY_SCOPE_ALL),
                    },
                    self.time_slots,
                ):
                    errors["base"] = "overlapping_slots"
            if not errors:
                self._pending_slot_step_a = dict(user_input)
                if user_input.get("soc_override_enabled") or user_input.get("power_override_enabled"):
                    return await self.async_step_add_time_slot_details()
                return await self._finalize_time_slot(step_b=None)

        defaults = self._options_slot_defaults(len(self.time_slots))
        if user_input:
            defaults = {**defaults, **user_input}

        slot_num = len(self.time_slots) + 1
        return self.async_show_form(
            step_id="add_time_slot",
            data_schema=_build_slot_step_a_schema(batteries, defaults),
            errors=errors if errors else None,
            description_placeholders={"slot_num": str(slot_num)},
        )

    async def async_step_add_time_slot_details(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step B: optional SOC / power detail fields for the pending slot."""
        if self._pending_slot_step_a is None:
            return await self.async_step_add_time_slot()

        step_a = self._pending_slot_step_a
        batteries = self.config_entry.data.get("batteries", [])
        scope = step_a.get("battery_scope", SLOT_BATTERY_SCOPE_ALL)
        needs_soc = bool(step_a.get("soc_override_enabled"))
        needs_power = bool(step_a.get("power_override_enabled"))
        slot_num = len(self.time_slots) + 1

        if user_input is not None:
            return await self._finalize_time_slot(step_b=user_input)

        defaults = self._options_slot_defaults(len(self.time_slots))
        return self.async_show_form(
            step_id="add_time_slot_details",
            data_schema=_build_slot_step_b_schema(needs_soc, needs_power, scope, batteries, defaults),
            description_placeholders={
                "slot_num": str(slot_num),
                "battery_map": _battery_scope_name_map(batteries),
            },
        )

    async def _finalize_time_slot(self, step_b: dict | None) -> FlowResult:
        """Persist the pending slot and advance the flow."""
        if self._pending_slot_step_a is None:
            return await self.async_step_add_time_slot()
        slot = _finalize_slot(self._pending_slot_step_a, step_b)
        self.time_slots.append(slot)
        self._pending_slot_step_a = None
        if len(self.time_slots) < MAX_TIME_SLOTS:
            return await self.async_step_add_more_slots()
        self.config_data["no_discharge_time_slots"] = self.time_slots
        return await self._save_and_finish()

    def _options_slot_defaults(self, index: int) -> dict:
        """Return previously-saved slot at `index`, or empty dict if none."""
        existing = self.config_entry.data.get("no_discharge_time_slots", []) or []
        if 0 <= index < len(existing):
            return dict(existing[index])
        return {}

    async def async_step_add_more_slots(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask if user wants to add more time slots."""
        if user_input is not None:
            if user_input.get("add_more", False):
                return await self.async_step_add_time_slot()
            else:
                self.config_data["no_discharge_time_slots"] = self.time_slots
                return await self._save_and_finish()

        # Check if there are more existing slots to show
        existing_slots = self.config_entry.data.get("no_discharge_time_slots", [])
        has_more_existing = len(self.time_slots) < len(existing_slots)

        return self.async_show_form(
            step_id="add_more_slots",
            data_schema=vol.Schema(
                {
                    vol.Required("add_more", default=has_more_existing): bool,
                }
            ),
            description_placeholders={
                "current_slots": str(len(self.time_slots)),
                "max_slots": str(MAX_TIME_SLOTS),
            },
        )

    async def async_step_excluded_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to configure excluded devices."""
        if user_input is not None:
            if user_input.get("configure_excluded_devices", False):
                # Reset excluded_devices list to start fresh
                self.excluded_devices = []
                return await self.async_step_add_excluded_device()
            else:
                self.config_data["excluded_devices"] = []
                return await self._save_and_finish()

        # Check if excluded devices were previously configured
        existing_devices = self.config_entry.data.get("excluded_devices", [])
        has_existing_devices = len(existing_devices) > 0

        return self.async_show_form(
            step_id="excluded_devices",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_excluded_devices", default=has_existing_devices): bool,
                }
            ),
            description_placeholders={
                "description": "Configure devices with special management"
            },
        )

    async def async_step_add_excluded_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add an excluded device configuration."""
        if user_input is not None:
            # Save the excluded device
            excluded_device = {
                "power_sensor": user_input["power_sensor"],
                "included_in_consumption": user_input.get("included_in_consumption", True),
                "allow_solar_surplus": user_input.get("allow_solar_surplus", False),
                "ev_charger_no_telemetry": user_input.get("ev_charger_no_telemetry", False),
            }
            self.excluded_devices.append(excluded_device)

            # Check if user wants to add more devices (max 4)
            if len(self.excluded_devices) < 4:
                return await self.async_step_add_more_excluded_devices()
            else:
                self.config_data["excluded_devices"] = self.excluded_devices
                return await self._save_and_finish()

        # Load existing excluded devices if available and not yet added
        current_devices = self.config_entry.data.get("excluded_devices", [])
        device_num = len(self.excluded_devices)

        if device_num < len(current_devices):
            current_device = current_devices[device_num]
            default_sensor = current_device.get("power_sensor", "")
            default_included = current_device.get("included_in_consumption", True)
            default_allow_solar_surplus = current_device.get("allow_solar_surplus", False)
            default_ev_no_telemetry = current_device.get("ev_charger_no_telemetry", False)
        else:
            default_sensor = ""
            default_included = True
            default_allow_solar_surplus = False
            default_ev_no_telemetry = False

        device_num += 1
        return self.async_show_form(
            step_id="add_excluded_device",
            data_schema=vol.Schema(
                {
                    vol.Required("power_sensor", default=default_sensor):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Required("included_in_consumption", default=default_included): bool,
                    vol.Optional("allow_solar_surplus", default=default_allow_solar_surplus): bool,
                    vol.Optional("ev_charger_no_telemetry", default=default_ev_no_telemetry): bool,
                }
            ),
            description_placeholders={
                "device_num": str(device_num),
                "description": f"Configure special device {device_num}"
            },
        )

    async def async_step_add_more_excluded_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to add more excluded devices."""
        if user_input is not None:
            if user_input.get("add_more", False):
                return await self.async_step_add_excluded_device()
            else:
                self.config_data["excluded_devices"] = self.excluded_devices
                return await self._save_and_finish()

        # Check if there are more existing devices to show
        existing_devices = self.config_entry.data.get("excluded_devices", [])
        has_more_existing = len(self.excluded_devices) < len(existing_devices)

        return self.async_show_form(
            step_id="add_more_excluded_devices",
            data_schema=vol.Schema(
                {
                    vol.Required("add_more", default=has_more_existing): bool,
                }
            ),
            description_placeholders={
                "current_devices": str(len(self.excluded_devices)),
                "max_devices": "4",
            },
        )

    async def async_step_predictive_charging(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to configure predictive grid charging in options flow."""
        if user_input is not None:
            if user_input.get("configure_predictive_charging", False):
                return await self.async_step_predictive_charging_mode()
            else:
                self.config_data["enable_predictive_charging"] = False
                self.config_data["charging_time_slot"] = None
                self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_TIME_SLOT
                return await self._save_and_finish()

        is_predictive_enabled = self.config_entry.data.get("enable_predictive_charging", False)

        return self.async_show_form(
            step_id="predictive_charging",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_predictive_charging", default=is_predictive_enabled): bool,
                }
            ),
        )

    async def async_step_predictive_charging_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select predictive charging mode in options flow."""
        existing_mode = self.config_entry.data.get(CONF_PREDICTIVE_CHARGING_MODE, PREDICTIVE_MODE_TIME_SLOT)

        if user_input is not None:
            mode = user_input.get(CONF_PREDICTIVE_CHARGING_MODE, PREDICTIVE_MODE_TIME_SLOT)
            self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = mode
            if mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
                return await self.async_step_dynamic_pricing_config()
            elif mode == PREDICTIVE_MODE_REALTIME_PRICE:
                return await self.async_step_realtime_price_config()
            else:
                return await self.async_step_predictive_charging_config()

        return self.async_show_form(
            step_id="predictive_charging_mode",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PREDICTIVE_CHARGING_MODE, default=existing_mode):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    PREDICTIVE_MODE_TIME_SLOT,
                                    PREDICTIVE_MODE_DYNAMIC_PRICING,
                                    PREDICTIVE_MODE_REALTIME_PRICE,
                                ],
                                translation_key="predictive_charging_mode",
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                }
            ),
        )

    async def async_step_predictive_charging_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure time slot predictive grid charging in options flow."""
        errors = {}

        existing_config = self.config_entry.data
        time_slot_current = existing_config.get("charging_time_slot", {})
        forecast_sensor_current = existing_config.get("solar_forecast_sensor", "")

        has_global_sensor = bool(self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR))

        if user_input is not None:
            try:
                if has_global_sensor:
                    forecast_sensor = self.config_entry.data[CONF_SOLAR_FORECAST_SENSOR]
                else:
                    forecast_sensor = user_input.get("solar_forecast_sensor")
                    if forecast_sensor:
                        forecast_state = self.hass.states.get(forecast_sensor)
                        if forecast_state is None:
                            errors["solar_forecast_sensor"] = "sensor_not_found"
                        else:
                            unit = forecast_state.attributes.get("unit_of_measurement", "")
                            if unit not in ["kWh", "Wh"]:
                                errors["solar_forecast_sensor"] = "invalid_unit"

                if not errors:
                    self.config_data["enable_predictive_charging"] = True
                    self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_TIME_SLOT
                    self.config_data["charging_time_slot"] = {
                        "start_time": user_input["start_time"],
                        "end_time": user_input["end_time"],
                        "days": user_input["days"],
                    }
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    self.config_data[CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT] = user_input.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)
                    return await self._save_and_finish()
            except Exception as e:
                _LOGGER.error("Error validating predictive charging config: %s", e)
                errors["base"] = "unknown"

        if time_slot_current:
            defaults = {
                "start_time": time_slot_current.get("start_time", "01:00:00"),
                "end_time": time_slot_current.get("end_time", "06:00:00"),
                "days": time_slot_current.get("days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
                "sensor": forecast_sensor_current if forecast_sensor_current else "",
                "margin": existing_config.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH),
                "grid_margin": existing_config.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT),
            }
        else:
            defaults = {
                "start_time": "01:00:00",
                "end_time": "06:00:00",
                "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "sensor": "",
                "margin": DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH,
                "grid_margin": DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT,
            }

        schema_dict = {
            vol.Required("start_time", default=defaults["start_time"]): TimeSelector(),
            vol.Required("end_time", default=defaults["end_time"]): TimeSelector(),
            vol.Required("days", default=defaults["days"]):
                SelectSelector(
                    SelectSelectorConfig(
                        options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        translation_key="weekday",
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
        }
        if not has_global_sensor:
            schema_dict[vol.Optional("solar_forecast_sensor", description={"suggested_value": defaults["sensor"]} if defaults["sensor"] else {})] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=defaults["margin"])] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, default=defaults["grid_margin"])] = NumberSelector(
            NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
        )

        return self.async_show_form(
            step_id="predictive_charging_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_dynamic_pricing_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure dynamic pricing predictive grid charging in options flow."""
        errors = {}
        has_global_sensor = bool(self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR))
        existing_config = self.config_entry.data

        if user_input is not None:
            try:
                integration_type = user_input[CONF_PRICE_INTEGRATION_TYPE]
                price_sensor = user_input[CONF_PRICE_SENSOR]

                price_state = self.hass.states.get(price_sensor)
                if price_state is None:
                    errors[CONF_PRICE_SENSOR] = "sensor_not_found"
                else:
                    attrs = price_state.attributes
                    if integration_type == PRICE_INTEGRATION_PVPC:
                        if not any(f"price_{h:02d}h" in attrs for h in range(24)):
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    elif integration_type == PRICE_INTEGRATION_CKW:
                        prices = attrs.get("prices")
                        if not prices or not isinstance(prices, (list, tuple)) or len(prices) == 0:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    elif integration_type == PRICE_INTEGRATION_EPEX:
                        data = attrs.get("data")
                        if not data or not isinstance(data, (list, tuple)) or len(data) == 0:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    elif integration_type == PRICE_INTEGRATION_ENTSOE:
                        prices = attrs.get("prices_today")
                        if not prices or not isinstance(prices, (list, tuple)) or len(prices) == 0:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"
                    else:  # Nordpool
                        if "raw_today" not in attrs:
                            errors[CONF_PRICE_SENSOR] = "no_price_data"

                if has_global_sensor:
                    forecast_sensor = self.config_entry.data[CONF_SOLAR_FORECAST_SENSOR]
                else:
                    forecast_sensor = user_input.get("solar_forecast_sensor")
                    if forecast_sensor:
                        forecast_state = self.hass.states.get(forecast_sensor)
                        if forecast_state is None:
                            errors["solar_forecast_sensor"] = "sensor_not_found"
                        else:
                            unit = forecast_state.attributes.get("unit_of_measurement", "")
                            if unit not in ["kWh", "Wh"]:
                                errors["solar_forecast_sensor"] = "invalid_unit"

                if not errors:
                    max_price_raw = user_input.get(CONF_MAX_PRICE_THRESHOLD)
                    max_price = float(str(max_price_raw).replace(",", ".")) if max_price_raw else None

                    self.config_data["enable_predictive_charging"] = True
                    self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_DYNAMIC_PRICING
                    self.config_data[CONF_PRICE_INTEGRATION_TYPE] = integration_type
                    self.config_data[CONF_PRICE_SENSOR] = price_sensor
                    self.config_data[CONF_MAX_PRICE_THRESHOLD] = max_price
                    self.config_data[CONF_DP_PRICE_DISCHARGE_CONTROL] = user_input.get(CONF_DP_PRICE_DISCHARGE_CONTROL, False)
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    self.config_data[CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT] = user_input.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)
                    return await self._save_and_finish()
            except Exception as e:
                _LOGGER.error("Error validating dynamic pricing config: %s", e)
                errors["base"] = "unknown"

        default_integration = existing_config.get(CONF_PRICE_INTEGRATION_TYPE, PRICE_INTEGRATION_NORDPOOL)
        default_sensor = existing_config.get(CONF_PRICE_SENSOR, "")
        default_max_price = existing_config.get(CONF_MAX_PRICE_THRESHOLD)
        default_forecast = existing_config.get("solar_forecast_sensor", "")
        default_dp_discharge_control = existing_config.get(CONF_DP_PRICE_DISCHARGE_CONTROL, False)
        default_margin = existing_config.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
        default_grid_margin = existing_config.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)

        schema_dict: dict = {
            vol.Required(CONF_PRICE_INTEGRATION_TYPE, default=default_integration):
                SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            PRICE_INTEGRATION_NORDPOOL,
                            PRICE_INTEGRATION_PVPC,
                            PRICE_INTEGRATION_CKW,
                            PRICE_INTEGRATION_EPEX,
                            PRICE_INTEGRATION_ENTSOE,
                        ],
                        translation_key="price_integration_type",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Required(CONF_PRICE_SENSOR, default=default_sensor if default_sensor else vol.UNDEFINED):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_MAX_PRICE_THRESHOLD,
                description={"suggested_value": str(default_max_price)} if default_max_price is not None else {}
            ):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_DP_PRICE_DISCHARGE_CONTROL, default=default_dp_discharge_control): bool,
        }
        if not has_global_sensor:
            schema_dict[vol.Optional(
                "solar_forecast_sensor",
                description={"suggested_value": default_forecast} if default_forecast else {}
            )] = EntitySelector(EntitySelectorConfig(domain="sensor"))
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=default_margin)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, default=default_grid_margin)] = NumberSelector(
            NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
        )

        return self.async_show_form(
            step_id="dynamic_pricing_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_realtime_price_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure real-time price charging mode in options flow."""
        errors = {}
        existing_config = self.config_entry.data
        has_global_sensor = bool(self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR))

        if user_input is not None:
            try:
                price_sensor = user_input[CONF_PRICE_SENSOR]
                price_state = self.hass.states.get(price_sensor)
                if price_state is None:
                    errors[CONF_PRICE_SENSOR] = "sensor_not_found"

                if has_global_sensor:
                    forecast_sensor = self.config_entry.data[CONF_SOLAR_FORECAST_SENSOR]
                else:
                    forecast_sensor = user_input.get("solar_forecast_sensor")
                    if forecast_sensor:
                        forecast_state = self.hass.states.get(forecast_sensor)
                        if forecast_state is None:
                            errors["solar_forecast_sensor"] = "sensor_not_found"
                        else:
                            unit = forecast_state.attributes.get("unit_of_measurement", "")
                            if unit not in ["kWh", "Wh"]:
                                errors["solar_forecast_sensor"] = "invalid_unit"

                if not errors:
                    max_price_raw = user_input.get(CONF_MAX_PRICE_THRESHOLD)
                    max_price = float(str(max_price_raw).replace(",", ".")) if max_price_raw else None
                    avg_sensor = user_input.get(CONF_AVERAGE_PRICE_SENSOR) or None

                    self.config_data["enable_predictive_charging"] = True
                    self.config_data[CONF_PREDICTIVE_CHARGING_MODE] = PREDICTIVE_MODE_REALTIME_PRICE
                    self.config_data[CONF_PRICE_SENSOR] = price_sensor
                    self.config_data[CONF_MAX_PRICE_THRESHOLD] = max_price
                    self.config_data[CONF_AVERAGE_PRICE_SENSOR] = avg_sensor
                    self.config_data[CONF_RT_PRICE_DISCHARGE_CONTROL] = user_input.get(CONF_RT_PRICE_DISCHARGE_CONTROL, False)
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    self.config_data[CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT] = user_input.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)
                    return await self._save_and_finish()
            except Exception as e:
                _LOGGER.error("Error validating real-time price config: %s", e)
                errors["base"] = "unknown"

        default_sensor = existing_config.get(CONF_PRICE_SENSOR, "")
        default_max_price = existing_config.get(CONF_MAX_PRICE_THRESHOLD)
        default_avg_sensor = existing_config.get(CONF_AVERAGE_PRICE_SENSOR, "")
        default_rt_discharge_control = existing_config.get(CONF_RT_PRICE_DISCHARGE_CONTROL, False)
        default_forecast = existing_config.get("solar_forecast_sensor", "")
        default_margin = existing_config.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
        default_grid_margin = existing_config.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)

        schema_dict: dict = {
            vol.Required(CONF_PRICE_SENSOR, default=default_sensor if default_sensor else vol.UNDEFINED):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_MAX_PRICE_THRESHOLD,
                description={"suggested_value": str(default_max_price)} if default_max_price is not None else {}
            ):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Optional(
                CONF_AVERAGE_PRICE_SENSOR,
                description={"suggested_value": default_avg_sensor} if default_avg_sensor else {}
            ):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Required(CONF_RT_PRICE_DISCHARGE_CONTROL, default=default_rt_discharge_control): bool,
        }
        if not has_global_sensor:
            schema_dict[vol.Optional(
                "solar_forecast_sensor",
                description={"suggested_value": default_forecast} if default_forecast else {}
            )] = EntitySelector(EntitySelectorConfig(domain="sensor"))
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=default_margin)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, default=default_grid_margin)] = NumberSelector(
            NumberSelectorConfig(min=0, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
        )

        return self.async_show_form(
            step_id="realtime_price_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_weekly_full_charge(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to enable weekly full battery charge in options flow."""
        if user_input is not None:
            if user_input.get("configure_weekly_full_charge", False):
                return await self.async_step_weekly_full_charge_config()
            else:
                self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = False
                self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = "sun"
                return await self._save_and_finish()

        is_weekly_full_charge_enabled = self.config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False)

        return self.async_show_form(
            step_id="weekly_full_charge",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_weekly_full_charge", default=is_weekly_full_charge_enabled): bool,
                }
            ),
            description_placeholders={
                "description": "Enable weekly full battery charge for cell balancing"
            },
        )

    async def async_step_weekly_full_charge_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure weekly full charge day in options flow."""
        existing_config = self.config_entry.data
        current_day = existing_config.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")
        if user_input is not None:
            self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = True
            self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = user_input["weekly_full_charge_day"]
            self.config_data[CONF_ENABLE_BALANCE_MONITOR] = True
            return await self._save_and_finish()

        return self.async_show_form(
            step_id="weekly_full_charge_config",
            data_schema=vol.Schema(
                {
                    vol.Required("weekly_full_charge_day", default=current_day):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                                translation_key="weekday",
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                }
            ),
        )

    async def async_step_charge_delay(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to enable solar charge delay in options flow."""
        if user_input is not None:
            if user_input.get("configure_charge_delay", False):
                return await self.async_step_charge_delay_config()
            else:
                self.config_data[CONF_ENABLE_CHARGE_DELAY] = False
                return await self._save_and_finish()

        # Backward compat: check old key too
        is_delay_enabled = self.config_entry.data.get(
            CONF_ENABLE_CHARGE_DELAY,
            self.config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        )

        return self.async_show_form(
            step_id="charge_delay",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_charge_delay", default=is_delay_enabled): bool,
                }
            ),
        )

    async def async_step_charge_delay_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure charge delay details in options flow."""
        existing_config = self.config_entry.data
        current_margin = existing_config.get(CONF_DELAY_SAFETY_MARGIN_MIN, DEFAULT_DELAY_SAFETY_MARGIN_MIN)
        current_soc_setpoint_enabled = existing_config.get(CONF_DELAY_SOC_SETPOINT_ENABLED, DEFAULT_DELAY_SOC_SETPOINT_ENABLED)
        current_soc_setpoint = existing_config.get(CONF_DELAY_SOC_SETPOINT, DEFAULT_DELAY_SOC_SETPOINT)
        errors = {}

        if user_input is not None:
            self.config_data[CONF_ENABLE_CHARGE_DELAY] = True
            self.config_data[CONF_DELAY_SAFETY_MARGIN_MIN] = int(
                user_input.get("delay_safety_margin_h", current_margin / 60) * 60
            )
            soc_setpoint_enabled = user_input.get("delay_soc_setpoint_enabled", current_soc_setpoint_enabled)
            self.config_data[CONF_DELAY_SOC_SETPOINT_ENABLED] = soc_setpoint_enabled
            if soc_setpoint_enabled:
                self.config_data[CONF_DELAY_SOC_SETPOINT] = int(
                    user_input.get("delay_soc_setpoint", current_soc_setpoint)
                )

            existing_forecast = self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR)
            if not existing_forecast:
                forecast_sensor = user_input.get("solar_forecast_sensor")
                if not forecast_sensor:
                    errors["solar_forecast_sensor"] = "sensor_not_found"
                else:
                    state = self.hass.states.get(forecast_sensor)
                    if state is None:
                        errors["solar_forecast_sensor"] = "sensor_not_found"
                    else:
                        self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor

            if not errors:
                return await self._save_and_finish()

        has_forecast_sensor = bool(self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR))
        schema_dict = {
            vol.Optional("delay_safety_margin_h", default=current_margin / 60):
                NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=6, step=0.5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="h",
                    )
                ),
            vol.Optional("delay_soc_setpoint_enabled", default=current_soc_setpoint_enabled): bool,
            vol.Optional("delay_soc_setpoint", default=current_soc_setpoint):
                NumberSelector(
                    NumberSelectorConfig(
                        min=12, max=90, step=5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
        }
        if not has_forecast_sensor:
            schema_dict[vol.Optional("solar_forecast_sensor")] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )

        return self.async_show_form(
            step_id="charge_delay_config",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_capacity_protection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to enable capacity protection mode."""
        if user_input is not None:
            if user_input.get("configure_capacity_protection", False):
                return await self.async_step_capacity_protection_config()
            else:
                self.config_data[CONF_CAPACITY_PROTECTION_ENABLED] = False
                return await self._save_and_finish()

        is_enabled = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)

        return self.async_show_form(
            step_id="capacity_protection",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_capacity_protection", default=is_enabled): bool,
                }
            ),
        )

    async def async_step_capacity_protection_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure capacity protection parameters."""
        existing_config = self.config_entry.data
        current_soc = existing_config.get(CONF_CAPACITY_PROTECTION_SOC_THRESHOLD, DEFAULT_CAPACITY_PROTECTION_SOC)
        current_limit = existing_config.get(CONF_CAPACITY_PROTECTION_LIMIT, DEFAULT_CAPACITY_PROTECTION_LIMIT)

        if user_input is not None:
            self.config_data[CONF_CAPACITY_PROTECTION_ENABLED] = True
            self.config_data[CONF_CAPACITY_PROTECTION_SOC_THRESHOLD] = int(user_input["capacity_protection_soc_threshold"])
            self.config_data[CONF_CAPACITY_PROTECTION_LIMIT] = int(user_input["capacity_protection_limit"])
            return await self._save_and_finish()

        return self.async_show_form(
            step_id="capacity_protection_config",
            data_schema=vol.Schema(
                {
                    vol.Required("capacity_protection_soc_threshold", default=current_soc):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=20, max=100, step=1,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="%",
                            )
                        ),
                    vol.Required("capacity_protection_limit", default=current_limit):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=500, max=10000, step=100,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
        )

    async def async_step_hourly_balance(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to enable hourly net balance control in options flow."""
        from .const import (
            CONF_ENABLE_HOURLY_BALANCE,
        )
        if user_input is not None:
            if user_input.get("configure_hourly_balance", False):
                return await self.async_step_hourly_balance_config()
            else:
                from .const import (
                    CONF_HOURLY_BALANCE_TARGET_NET_WH,
                    CONF_HOURLY_BALANCE_MAX_OFFSET_W,
                    CONF_HOURLY_BALANCE_DEADBAND_WH,
                    CONF_HOURLY_BALANCE_HYSTERESIS_W,
                    DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
                    DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
                    DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
                    DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
                )
                self.config_data[CONF_ENABLE_HOURLY_BALANCE] = False
                self.config_data[CONF_HOURLY_BALANCE_TARGET_NET_WH] = DEFAULT_HOURLY_BALANCE_TARGET_NET_WH
                self.config_data[CONF_HOURLY_BALANCE_MAX_OFFSET_W] = DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W
                self.config_data[CONF_HOURLY_BALANCE_DEADBAND_WH] = DEFAULT_HOURLY_BALANCE_DEADBAND_WH
                self.config_data[CONF_HOURLY_BALANCE_HYSTERESIS_W] = DEFAULT_HOURLY_BALANCE_HYSTERESIS_W
                return await self._save_and_finish()

        is_enabled = self.config_entry.data.get(CONF_ENABLE_HOURLY_BALANCE, False)

        return self.async_show_form(
            step_id="hourly_balance",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_hourly_balance", default=is_enabled): bool,
                }
            ),
        )

    async def async_step_hourly_balance_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure hourly net balance parameters in options flow."""
        from .const import (
            CONF_ENABLE_HOURLY_BALANCE,
            CONF_HOURLY_BALANCE_TARGET_NET_WH,
            CONF_HOURLY_BALANCE_MAX_OFFSET_W,
            CONF_HOURLY_BALANCE_DEADBAND_WH,
            CONF_HOURLY_BALANCE_HYSTERESIS_W,
            DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
            DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
            DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
            DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
        )
        existing = self.config_entry.data
        current_target = existing.get(CONF_HOURLY_BALANCE_TARGET_NET_WH, DEFAULT_HOURLY_BALANCE_TARGET_NET_WH)
        current_max_offset = existing.get(CONF_HOURLY_BALANCE_MAX_OFFSET_W, DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W)
        current_deadband = existing.get(CONF_HOURLY_BALANCE_DEADBAND_WH, DEFAULT_HOURLY_BALANCE_DEADBAND_WH)
        current_hysteresis = existing.get(CONF_HOURLY_BALANCE_HYSTERESIS_W, DEFAULT_HOURLY_BALANCE_HYSTERESIS_W)

        # Derive the slider ceiling from the sum of actual battery discharge powers
        coordinators = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {}).get("coordinators", [])
        max_combined_w = max(sum(c.max_discharge_power for c in coordinators), 1000) if coordinators else 5000

        if user_input is not None:
            self.config_data[CONF_ENABLE_HOURLY_BALANCE] = True
            self.config_data[CONF_HOURLY_BALANCE_TARGET_NET_WH] = float(
                user_input.get(CONF_HOURLY_BALANCE_TARGET_NET_WH, current_target)
            )
            self.config_data[CONF_HOURLY_BALANCE_MAX_OFFSET_W] = int(
                user_input.get(CONF_HOURLY_BALANCE_MAX_OFFSET_W, current_max_offset)
            )
            self.config_data[CONF_HOURLY_BALANCE_DEADBAND_WH] = float(
                user_input.get(CONF_HOURLY_BALANCE_DEADBAND_WH, current_deadband)
            )
            self.config_data[CONF_HOURLY_BALANCE_HYSTERESIS_W] = int(
                user_input.get(CONF_HOURLY_BALANCE_HYSTERESIS_W, current_hysteresis)
            )
            return await self._save_and_finish()

        return self.async_show_form(
            step_id="hourly_balance_config",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_HOURLY_BALANCE_TARGET_NET_WH, default=current_target):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=-2.0, max=2.0, step=0.1,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="kWh",
                            )
                        ),
                    vol.Optional(CONF_HOURLY_BALANCE_MAX_OFFSET_W, default=current_max_offset):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=100, max=max_combined_w, step=50,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional(CONF_HOURLY_BALANCE_DEADBAND_WH, default=current_deadband):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=0.5, step=0.1,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="kWh",
                            )
                        ),
                    vol.Optional(CONF_HOURLY_BALANCE_HYSTERESIS_W, default=current_hysteresis):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=200, step=5,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
        )

    async def async_step_pd_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to configure advanced PD controller parameters."""
        if user_input is not None:
            if user_input.get("configure_pd_advanced", False):
                return await self.async_step_pd_advanced_config()
            else:
                self.config_data[CONF_PD_KP] = DEFAULT_PD_KP
                self.config_data[CONF_PD_KD] = DEFAULT_PD_KD
                self.config_data[CONF_PD_DEADBAND] = DEFAULT_PD_DEADBAND
                self.config_data[CONF_PD_MAX_POWER_CHANGE] = DEFAULT_PD_MAX_POWER_CHANGE
                self.config_data[CONF_PD_DIRECTION_HYSTERESIS] = DEFAULT_PD_DIRECTION_HYSTERESIS
                self.config_data[CONF_PD_MIN_CHARGE_POWER] = DEFAULT_PD_MIN_CHARGE_POWER
                self.config_data[CONF_PD_MIN_DISCHARGE_POWER] = DEFAULT_PD_MIN_DISCHARGE_POWER
                self.config_data[CONF_TARGET_GRID_POWER] = self.config_entry.data.get(CONF_TARGET_GRID_POWER, DEFAULT_TARGET_GRID_POWER)
                self.config_data[CONF_ENABLE_SYSTEM_POWER_LIMITS] = self.config_entry.data.get(
                    CONF_ENABLE_SYSTEM_POWER_LIMITS,
                    DEFAULT_ENABLE_SYSTEM_POWER_LIMITS,
                )
                self.config_data[CONF_SYSTEM_MAX_CHARGE_POWER] = (
                    self.config_entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER)
                    if self.config_data[CONF_ENABLE_SYSTEM_POWER_LIMITS]
                    else DEFAULT_SYSTEM_MAX_CHARGE_POWER
                )
                self.config_data[CONF_SYSTEM_MAX_DISCHARGE_POWER] = (
                    self.config_entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER)
                    if self.config_data[CONF_ENABLE_SYSTEM_POWER_LIMITS]
                    else DEFAULT_SYSTEM_MAX_DISCHARGE_POWER
                )
                return await self._save_and_finish()

        # Check if PD parameters were previously configured (non-default values)
        has_custom_pd = (
            self.config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP) != DEFAULT_PD_KP or
            self.config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD) != DEFAULT_PD_KD or
            self.config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND) != DEFAULT_PD_DEADBAND or
            self.config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE) != DEFAULT_PD_MAX_POWER_CHANGE or
            self.config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS) != DEFAULT_PD_DIRECTION_HYSTERESIS or
            self.config_entry.data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER) != DEFAULT_PD_MIN_CHARGE_POWER or
            self.config_entry.data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER) != DEFAULT_PD_MIN_DISCHARGE_POWER or
            self.config_entry.data.get(CONF_TARGET_GRID_POWER, DEFAULT_TARGET_GRID_POWER) != DEFAULT_TARGET_GRID_POWER or
            self.config_entry.data.get(CONF_ENABLE_SYSTEM_POWER_LIMITS, DEFAULT_ENABLE_SYSTEM_POWER_LIMITS) != DEFAULT_ENABLE_SYSTEM_POWER_LIMITS or
            self.config_entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER) != DEFAULT_SYSTEM_MAX_CHARGE_POWER or
            self.config_entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER) != DEFAULT_SYSTEM_MAX_DISCHARGE_POWER
        )

        return self.async_show_form(
            step_id="pd_advanced",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_pd_advanced", default=has_custom_pd): bool,
                }
            ),
            description_placeholders={
                "description": "Configure advanced PD controller parameters for expert tuning of battery charge/discharge behavior. "
                              "Only modify these if you understand PID control theory. Default values work well for most installations."
            },
        )

    async def async_step_pd_advanced_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure PD controller advanced parameters."""
        if user_input is not None:
            # Save PD controller configuration
            self.config_data[CONF_PD_KP] = user_input["pd_kp"]
            self.config_data[CONF_PD_KD] = user_input["pd_kd"]
            self.config_data[CONF_PD_DEADBAND] = user_input["pd_deadband"]
            self.config_data[CONF_PD_MAX_POWER_CHANGE] = user_input["pd_max_power_change"]
            self.config_data[CONF_PD_DIRECTION_HYSTERESIS] = user_input["pd_direction_hysteresis"]
            self.config_data[CONF_PD_MIN_CHARGE_POWER] = user_input["pd_min_charge_power"]
            self.config_data[CONF_PD_MIN_DISCHARGE_POWER] = user_input["pd_min_discharge_power"]
            self.config_data[CONF_TARGET_GRID_POWER] = user_input["pd_target_grid_power"]
            enable_system_limits = user_input.get("enable_system_power_limits", False)
            self.config_data[CONF_ENABLE_SYSTEM_POWER_LIMITS] = enable_system_limits
            self.config_data[CONF_SYSTEM_MAX_CHARGE_POWER] = (
                user_input["system_max_charge_power"] if enable_system_limits
                else DEFAULT_SYSTEM_MAX_CHARGE_POWER
            )
            self.config_data[CONF_SYSTEM_MAX_DISCHARGE_POWER] = (
                user_input["system_max_discharge_power"] if enable_system_limits
                else DEFAULT_SYSTEM_MAX_DISCHARGE_POWER
            )
            return await self._save_and_finish()

        # Load existing configuration with defaults
        existing_config = self.config_entry.data
        current_kp = existing_config.get(CONF_PD_KP, DEFAULT_PD_KP)
        current_kd = existing_config.get(CONF_PD_KD, DEFAULT_PD_KD)
        current_deadband = existing_config.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        current_max_change = existing_config.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        current_hysteresis = existing_config.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        current_min_charge = existing_config.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        current_min_discharge = existing_config.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)
        current_target_grid_power = existing_config.get(CONF_TARGET_GRID_POWER, DEFAULT_TARGET_GRID_POWER)
        current_system_max_charge = existing_config.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER)
        current_system_max_discharge = existing_config.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER)
        current_enable_system_limits = existing_config.get(
            CONF_ENABLE_SYSTEM_POWER_LIMITS,
            (current_system_max_charge or 0) > 0 or (current_system_max_discharge or 0) > 0,
        )

        # Show form
        return self.async_show_form(
            step_id="pd_advanced_config",
            data_schema=vol.Schema(
                {
                    vol.Required("pd_kp", default=current_kp):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0.1, max=2.0, step=0.05, mode=NumberSelectorMode.BOX
                            )
                        ),
                    vol.Required("pd_kd", default=current_kd):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0.0, max=2.0, step=0.05, mode=NumberSelectorMode.BOX
                            )
                        ),
                    vol.Required("pd_deadband", default=current_deadband):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=200, step=5, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                    vol.Required("pd_max_power_change", default=current_max_change):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=100, max=2000, step=50, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                    vol.Required("pd_direction_hysteresis", default=current_hysteresis):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=200, step=5, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                    vol.Optional("pd_min_charge_power", default=current_min_charge):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=2000, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("pd_min_discharge_power", default=current_min_discharge):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=2000, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("pd_target_grid_power", default=current_target_grid_power):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=-2500, max=2500, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("enable_system_power_limits", default=current_enable_system_limits): bool,
                    vol.Optional("system_max_charge_power", default=current_system_max_charge):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=15000, step=50,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                    vol.Optional("system_max_discharge_power", default=current_system_max_discharge):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0, max=15000, step=50,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
            description_placeholders={
                "description": (
                    "**Kp (Proportional Gain)**: Responsiveness to grid imbalance. Higher = faster response but risk of overshoot.\n\n"
                    "**Kd (Derivative Gain)**: Damping to prevent oscillation. Higher = smoother transitions but slower settling.\n\n"
                    "**Deadband**: Grid power tolerance (W) around zero. Prevents micro-adjustments to minor fluctuations.\n\n"
                    "**Max Power Change**: Maximum battery power change per control cycle (W). Prevents abrupt battery commands.\n\n"
                    "**Direction Hysteresis**: Power threshold (W) required to switch between charging and discharging. Prevents rapid direction changes.\n\n"
                    "**Min Charge Power**: Minimum power for charging. Below this, the controller stays idle. 0 = disabled.\n\n"
                    "**Min Discharge Power**: Minimum power for discharging. Below this, the controller stays idle. 0 = disabled.\n\n"
                    "**Target Grid Power**: Grid power setpoint (W) the controller regulates to. Negative = export to grid, positive = import from grid, 0 = net zero.\n\n"
                    "**System Max Charge/Discharge Power**: Optional combined battery power caps. 0 = disabled; per-battery limits still apply."
                )
            },
        )
