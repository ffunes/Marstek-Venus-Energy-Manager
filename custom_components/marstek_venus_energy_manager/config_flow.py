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
    CONF_HOUSEHOLD_CONSUMPTION_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY,
    CONF_ENABLE_CHARGE_DELAY,
    CONF_DELAY_SAFETY_MARGIN_MIN,
    DEFAULT_DELAY_SAFETY_MARGIN_MIN,
    CONF_DELAY_SOC_SETPOINT_ENABLED,
    DEFAULT_DELAY_SOC_SETPOINT_ENABLED,
    CONF_DELAY_SOC_SETPOINT,
    DEFAULT_DELAY_SOC_SETPOINT,
    CONF_BATTERY_VERSION,
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
    DEFAULT_PD_KP,
    DEFAULT_PD_KD,
    DEFAULT_PD_DEADBAND,
    DEFAULT_PD_MAX_POWER_CHANGE,
    DEFAULT_PD_DIRECTION_HYSTERESIS,
    DEFAULT_PD_MIN_CHARGE_POWER,
    DEFAULT_PD_MIN_DISCHARGE_POWER,
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
    CONF_METER_INVERTED,
    CONF_PREDICTIVE_SAFETY_MARGIN_KWH,
    DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH,
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
    """Check if new_slot overlaps with any existing slot on shared days."""
    new_days = set(new_slot.get("days", []))
    for slot in existing_slots:
        if not (new_days & set(slot.get("days", []))):
            continue
        if _time_ranges_overlap(
            new_slot["start_time"], new_slot["end_time"],
            slot["start_time"], slot["end_time"],
        ):
            return True
    return False


class MarstekVenusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Venus Energy Manager."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.config_data = {}
        self.battery_configs = []
        self.battery_index = 0
        self.time_slots = []
        self.excluded_devices = []
        self._current_battery_data = {}  # Stores connection data between battery steps

    async def _test_connection(self, host: str, port: int, version: str = "v2") -> bool:
        """Test connection to a Marstek Venus battery using version-specific register."""
        _LOGGER.info("Testing connection to %s:%s (%s)", host, port, version)
        client = MarstekModbusClient(host, port)
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

            # Validate household consumption sensor if provided
            household_sensor = user_input.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR)
            if household_sensor:
                household_state = self.hass.states.get(household_sensor)
                if household_state is None:
                    errors[CONF_HOUSEHOLD_CONSUMPTION_SENSOR] = "sensor_not_found"
                else:
                    unit = household_state.attributes.get("unit_of_measurement", "")
                    if unit not in ["W", "kW"]:
                        errors[CONF_HOUSEHOLD_CONSUMPTION_SENSOR] = "invalid_unit"

            if not errors:
                self.config_data["consumption_sensor"] = user_input["consumption_sensor"]
                self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                self.config_data[CONF_HOUSEHOLD_CONSUMPTION_SENSOR] = household_sensor
                self.config_data[CONF_METER_INVERTED] = user_input.get(CONF_METER_INVERTED, False)
                return await self.async_step_batteries()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("consumption_sensor"):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_METER_INVERTED, default=False):
                        BooleanSelector(),
                    vol.Optional(CONF_SOLAR_FORECAST_SENSOR):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_HOUSEHOLD_CONSUMPTION_SENSOR):
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
            connection_result = await self._test_connection(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                battery_version,
            )
            if not connection_result:
                errors["base"] = "cannot_connect"
            else:
                self._current_battery_data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: user_input[CONF_PORT],
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
                        NumberSelector(NumberSelectorConfig(min=5, max=20, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("backup_offgrid_threshold", default=50):
                        NumberSelector(NumberSelectorConfig(min=0, max=500, step=10, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
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
        """Step 5: Add a time slot configuration."""
        slot_num = len(self.time_slots) + 1
        errors = {}

        if user_input is not None:
            if not errors:
                # Save the time slot
                time_slot = {
                    "start_time": user_input["start_time"],
                    "end_time": user_input["end_time"],
                    "days": user_input["days"],
                    "apply_to_charge": user_input.get("apply_to_charge", False),
                    "target_grid_power": user_input.get("target_grid_power", 0),
                }

                if user_input["start_time"] >= user_input["end_time"]:
                    errors["base"] = "midnight_crossing"
                elif _slots_overlap(time_slot, self.time_slots):
                    errors["base"] = "overlapping_slots"
                else:
                    self.time_slots.append(time_slot)

                    # Check if user wants to add more slots (max 4)
                    if len(self.time_slots) < 4:
                        return await self.async_step_add_more_slots()
                    else:
                        # Max slots reached, move to excluded devices
                        self.config_data["no_discharge_time_slots"] = self.time_slots
                        return await self.async_step_excluded_devices()

        defaults = {
            "start_time": user_input["start_time"] if user_input else None,
            "end_time": user_input["end_time"] if user_input else None,
            "days": user_input["days"] if user_input else ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "apply_to_charge": user_input.get("apply_to_charge", False) if user_input else False,
            "target_grid_power": user_input.get("target_grid_power", 0) if user_input else 0,
        }

        schema_dict = {
            vol.Required("start_time"): TimeSelector(),
            vol.Required("end_time"): TimeSelector(),
            vol.Required("days", default=defaults["days"]):
                SelectSelector(
                    SelectSelectorConfig(
                        options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        translation_key="weekday",
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Required("apply_to_charge", default=defaults["apply_to_charge"]): bool,
            vol.Optional("target_grid_power", default=defaults["target_grid_power"]):
                NumberSelector(
                    NumberSelectorConfig(
                        min=-500, max=500, step=10,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="W",
                    )
                ),
        }

        return self.async_show_form(
            step_id="add_time_slot",
            data_schema=vol.Schema(schema_dict),
            errors=errors if errors else None,
            description_placeholders={
                "slot_num": str(slot_num),
                "description": f"Configure time slot {slot_num} (no discharge period)"
            },
        )

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
                "max_slots": "4",
                "description": f"You have configured {len(self.time_slots)} time slot(s). Add another?"
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
                self.config_data["max_contracted_power"] = 7000
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
                        self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                        self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)

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
        schema_dict[vol.Required("max_contracted_power", default=7000)] = NumberSelector(
            NumberSelectorConfig(
                min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX
            )
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
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
                    self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)

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
                        ],
                        translation_key="price_integration_type",
                        mode=SelectSelectorMode.LIST,
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
        schema_dict[vol.Required("max_contracted_power", default=7000)] = NumberSelector(
            NumberSelectorConfig(min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
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
                    self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)

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
        schema_dict[vol.Required("max_contracted_power", default=7000)] = NumberSelector(
            NumberSelectorConfig(min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
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
                return await self.async_step_pd_advanced()

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
            return await self.async_step_pd_advanced()

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
                                min=2500, max=8000, step=100,
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
                }
            ),
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
        _LOGGER.info("OptionsFlowHandler initialized successfully for entry: %s", config_entry.entry_id)

    async def _test_connection(self, host: str, port: int, version: str = "v2") -> bool:
        """Test connection to a Marstek Venus battery.

        If a coordinator already holds a connection to this host, temporarily
        close it (under lock) to free the single-connection slot, run the test,
        and reconnect. Marstek firmware only supports one Modbus TCP connection.
        """
        soc_register = REGISTER_MAP.get(version, {}).get("battery_soc")
        if soc_register is None:
            return False

        # Check if there's an active coordinator for this host
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinators = entry_data.get("coordinators", [])
        existing_coordinator = None
        for coordinator in coordinators:
            if coordinator.host == host:
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
                test_client = MarstekModbusClient(host, port)
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
            client = MarstekModbusClient(host, port)
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

                # Validate household consumption sensor if provided
                household_sensor = user_input.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR)
                if household_sensor:
                    household_state = self.hass.states.get(household_sensor)
                    if household_state is None:
                        errors[CONF_HOUSEHOLD_CONSUMPTION_SENSOR] = "sensor_not_found"
                    else:
                        unit = household_state.attributes.get("unit_of_measurement", "")
                        if unit not in ["W", "kW"]:
                            errors[CONF_HOUSEHOLD_CONSUMPTION_SENSOR] = "invalid_unit"

                if not errors:
                    self.config_data["consumption_sensor"] = user_input["consumption_sensor"]
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data[CONF_HOUSEHOLD_CONSUMPTION_SENSOR] = household_sensor
                    self.config_data[CONF_METER_INVERTED] = user_input.get(CONF_METER_INVERTED, False)
                    return await self._save_and_finish()

            # Load current configuration with defensive defaults
            current_sensor = self.config_entry.data.get("consumption_sensor", "")
            current_forecast = self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR, "")
            current_household = self.config_entry.data.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR, "")
            current_inverted = self.config_entry.data.get(CONF_METER_INVERTED, False)
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
                    vol.Optional(CONF_SOLAR_FORECAST_SENSOR, description={"suggested_value": current_forecast} if current_forecast else {}):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(CONF_HOUSEHOLD_CONSUMPTION_SENSOR, description={"suggested_value": current_household} if current_household else {}):
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
                connection_result = await self._test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    battery_version,
                )
                if not connection_result:
                    errors["base"] = "cannot_connect"
                else:
                    self._current_battery_data = {
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_BATTERY_VERSION: battery_version,
                    }
                    return await self.async_step_battery_limits()

            if self.battery_index < len(current_batteries):
                current_battery = current_batteries[self.battery_index]
                defaults = {
                    CONF_NAME: current_battery.get(CONF_NAME, f"Marstek Venus {battery_num}"),
                    CONF_HOST: current_battery.get(CONF_HOST, ""),
                    CONF_PORT: current_battery.get(CONF_PORT, 502),
                    CONF_BATTERY_VERSION: current_battery.get(CONF_BATTERY_VERSION, DEFAULT_VERSION),
                }
            else:
                defaults = {
                    CONF_NAME: f"Marstek Venus {battery_num}",
                    CONF_HOST: "",
                    CONF_PORT: 502,
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
                        NumberSelector(NumberSelectorConfig(min=5, max=20, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("backup_offgrid_threshold", default=defaults["backup_offgrid_threshold"]):
                        NumberSelector(NumberSelectorConfig(min=0, max=500, step=10, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)),
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
        """Add a time slot."""
        errors = {}

        if user_input is not None:
            if not errors:
                time_slot = {
                    "start_time": user_input["start_time"],
                    "end_time": user_input["end_time"],
                    "days": user_input["days"],
                    "apply_to_charge": user_input.get("apply_to_charge", False),
                    "target_grid_power": user_input.get("target_grid_power", 0),
                }

                if user_input["start_time"] >= user_input["end_time"]:
                    errors["base"] = "midnight_crossing"
                elif _slots_overlap(time_slot, self.time_slots):
                    errors["base"] = "overlapping_slots"
                else:
                    self.time_slots.append(time_slot)

                    if len(self.time_slots) < 4:
                        return await self.async_step_add_more_slots()
                    else:
                        self.config_data["no_discharge_time_slots"] = self.time_slots
                        return await self._save_and_finish()

        # Load defaults from existing slots or user_input (on error re-show)
        if user_input:
            defaults = {
                "start_time": user_input["start_time"],
                "end_time": user_input["end_time"],
                "days": user_input["days"],
                "apply_to_charge": user_input.get("apply_to_charge", False),
                "target_grid_power": user_input.get("target_grid_power", 0),
            }
        else:
            current_slots = self.config_entry.data.get("no_discharge_time_slots", [])
            slot_num = len(self.time_slots)

            if slot_num < len(current_slots):
                current_slot = current_slots[slot_num]
                defaults = {
                    "start_time": current_slot.get("start_time", "00:00:00"),
                    "end_time": current_slot.get("end_time", "00:00:00"),
                    "days": current_slot.get("days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
                    "apply_to_charge": current_slot.get("apply_to_charge", False),
                    "target_grid_power": current_slot.get("target_grid_power", 0),
                }
            else:
                defaults = {
                    "start_time": "00:00:00",
                    "end_time": "00:00:00",
                    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                    "apply_to_charge": False,
                    "target_grid_power": 0,
                }

        slot_num = len(self.time_slots) + 1
        return self.async_show_form(
            step_id="add_time_slot",
            data_schema=vol.Schema(
                {
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
                    vol.Required("apply_to_charge", default=defaults["apply_to_charge"]): bool,
                    vol.Optional("target_grid_power", default=defaults["target_grid_power"]):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=-500, max=500, step=10,
                                mode=NumberSelectorMode.SLIDER,
                                unit_of_measurement="W",
                            )
                        ),
                }
            ),
            errors=errors if errors else None,
            description_placeholders={"slot_num": str(slot_num)},
        )

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
                "max_slots": "4",
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
                self.config_data["max_contracted_power"] = self.config_entry.data.get("max_contracted_power", 7000)
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
        max_power_current = existing_config.get("max_contracted_power", 7000)

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
                    self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
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
                "power": max_power_current,
                "margin": existing_config.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH),
            }
        else:
            defaults = {
                "start_time": "01:00:00",
                "end_time": "06:00:00",
                "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "sensor": "",
                "power": 7000,
                "margin": DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH,
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
        schema_dict[vol.Required("max_contracted_power", default=defaults["power"])] = NumberSelector(
            NumberSelectorConfig(min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=defaults["margin"])] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
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
                    self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    return await self._save_and_finish()
            except Exception as e:
                _LOGGER.error("Error validating dynamic pricing config: %s", e)
                errors["base"] = "unknown"

        default_integration = existing_config.get(CONF_PRICE_INTEGRATION_TYPE, PRICE_INTEGRATION_NORDPOOL)
        default_sensor = existing_config.get(CONF_PRICE_SENSOR, "")
        default_max_price = existing_config.get(CONF_MAX_PRICE_THRESHOLD)
        default_power = existing_config.get("max_contracted_power", 7000)
        default_forecast = existing_config.get("solar_forecast_sensor", "")
        default_dp_discharge_control = existing_config.get(CONF_DP_PRICE_DISCHARGE_CONTROL, False)
        default_margin = existing_config.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)

        schema_dict: dict = {
            vol.Required(CONF_PRICE_INTEGRATION_TYPE, default=default_integration):
                SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            PRICE_INTEGRATION_NORDPOOL,
                            PRICE_INTEGRATION_PVPC,
                            PRICE_INTEGRATION_CKW,
                        ],
                        translation_key="price_integration_type",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            vol.Required(CONF_PRICE_SENSOR, default=default_sensor if default_sensor else vol.UNDEFINED):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_MAX_PRICE_THRESHOLD,
                default=str(default_max_price) if default_max_price is not None else vol.UNDEFINED
            ):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_DP_PRICE_DISCHARGE_CONTROL, default=default_dp_discharge_control): bool,
        }
        if not has_global_sensor:
            schema_dict[vol.Optional(
                "solar_forecast_sensor",
                description={"suggested_value": default_forecast} if default_forecast else {}
            )] = EntitySelector(EntitySelectorConfig(domain="sensor"))
        schema_dict[vol.Required("max_contracted_power", default=default_power)] = NumberSelector(
            NumberSelectorConfig(min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=default_margin)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
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
                    self.config_data["max_contracted_power"] = user_input["max_contracted_power"]
                    self.config_data[CONF_SOLAR_FORECAST_SENSOR] = forecast_sensor
                    self.config_data["charging_time_slot"] = None
                    self.config_data[CONF_PREDICTIVE_SAFETY_MARGIN_KWH] = user_input.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
                    return await self._save_and_finish()
            except Exception as e:
                _LOGGER.error("Error validating real-time price config: %s", e)
                errors["base"] = "unknown"

        default_sensor = existing_config.get(CONF_PRICE_SENSOR, "")
        default_max_price = existing_config.get(CONF_MAX_PRICE_THRESHOLD)
        default_avg_sensor = existing_config.get(CONF_AVERAGE_PRICE_SENSOR, "")
        default_rt_discharge_control = existing_config.get(CONF_RT_PRICE_DISCHARGE_CONTROL, False)
        default_power = existing_config.get("max_contracted_power", 7000)
        default_forecast = existing_config.get("solar_forecast_sensor", "")
        default_margin = existing_config.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)

        schema_dict: dict = {
            vol.Required(CONF_PRICE_SENSOR, default=default_sensor if default_sensor else vol.UNDEFINED):
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_MAX_PRICE_THRESHOLD,
                default=str(default_max_price) if default_max_price is not None else vol.UNDEFINED
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
        schema_dict[vol.Required("max_contracted_power", default=default_power)] = NumberSelector(
            NumberSelectorConfig(min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX)
        )
        schema_dict[vol.Optional(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, default=default_margin)] = NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
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
                                min=2500, max=8000, step=100,
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
                return await self._save_and_finish()

        # Check if PD parameters were previously configured (non-default values)
        has_custom_pd = (
            self.config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP) != DEFAULT_PD_KP or
            self.config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD) != DEFAULT_PD_KD or
            self.config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND) != DEFAULT_PD_DEADBAND or
            self.config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE) != DEFAULT_PD_MAX_POWER_CHANGE or
            self.config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS) != DEFAULT_PD_DIRECTION_HYSTERESIS or
            self.config_entry.data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER) != DEFAULT_PD_MIN_CHARGE_POWER or
            self.config_entry.data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER) != DEFAULT_PD_MIN_DISCHARGE_POWER
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
                    "**Min Discharge Power**: Minimum power for discharging. Below this, the controller stays idle. 0 = disabled."
                )
            },
        )