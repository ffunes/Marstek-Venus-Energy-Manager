"""Config flow for Marstek Venus Energy Manager integration."""
from __future__ import annotations

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
)

from .const import (
    DOMAIN,
    CONF_ENABLE_PREDICTIVE_CHARGING,
    CONF_CHARGING_TIME_SLOT,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_BATTERY_VERSION,
    DEFAULT_VERSION,
    REGISTER_MAP,
    CONF_PD_KP,
    CONF_PD_KD,
    CONF_PD_DEADBAND,
    CONF_PD_MAX_POWER_CHANGE,
    CONF_PD_DIRECTION_HYSTERESIS,
    DEFAULT_PD_KP,
    DEFAULT_PD_KD,
    DEFAULT_PD_DEADBAND,
    DEFAULT_PD_MAX_POWER_CHANGE,
    DEFAULT_PD_DIRECTION_HYSTERESIS,
)
from .modbus_client import MarstekModbusClient

_LOGGER = logging.getLogger(__name__)


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
        """Step 1: Ask for the consumption sensor."""
        if user_input is not None:
            self.config_data["consumption_sensor"] = user_input["consumption_sensor"]
            return await self.async_step_batteries()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("consumption_sensor"):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                }
            ),
        )

    async def async_step_batteries(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Ask for the number of batteries."""
        if user_input is not None:
            self.config_data["num_batteries"] = int(user_input["num_batteries"])
            return await self.async_step_battery_config()

        return self.async_show_form(
            step_id="batteries",
            data_schema=vol.Schema(
                {
                    vol.Required("num_batteries", default=1):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1, max=4, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                }
            ),
        )

    async def async_step_battery_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: Configure each battery individually."""
        errors = {}

        if user_input is not None:
            # Get version for connection test
            battery_version = user_input.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)

            # Test connection before saving
            connection_result = await self._test_connection(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                battery_version
            )

            if not connection_result:
                errors["base"] = "cannot_connect"
            else:
                # Store version
                user_input[CONF_BATTERY_VERSION] = battery_version
                # Convert power values from string to int
                user_input["max_charge_power"] = int(user_input["max_charge_power"])
                user_input["max_discharge_power"] = int(user_input["max_discharge_power"])
                self.battery_configs.append(user_input)
                self.battery_index += 1

        if not errors and self.battery_index >= self.config_data["num_batteries"]:
            # All batteries configured, move to time slots configuration
            self.config_data["batteries"] = self.battery_configs
            return await self.async_step_time_slots()

        # Show form for the next battery
        battery_num = self.battery_index + 1
        return self.async_show_form(
            step_id="battery_config",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=f"Marstek Venus {battery_num}"):
                        str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=502): int,
                    vol.Required(CONF_BATTERY_VERSION, default=DEFAULT_VERSION):
                        SelectSelector(SelectSelectorConfig(
                            options=[
                                {"value": "v2", "label": "v1/v2"},
                                {"value": "v3", "label": "v3"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )),
                    vol.Required("max_charge_power", default="2500"):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "800", "label": "800W"},
                                    {"value": "2500", "label": "2500W"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    vol.Required("max_discharge_power", default="2500"):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "800", "label": "800W"},
                                    {"value": "2500", "label": "2500W"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    vol.Required("max_soc", default=100):
                        NumberSelector(NumberSelectorConfig(min=80, max=100, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("min_soc", default=12):
                        NumberSelector(NumberSelectorConfig(min=12, max=30, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("enable_charge_hysteresis", default=False): bool,
                    vol.Optional("charge_hysteresis_percent", default=5):
                        NumberSelector(NumberSelectorConfig(min=5, max=20, step=1, mode=NumberSelectorMode.SLIDER)),
                }
            ),
            errors=errors,
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
        if user_input is not None:
            # Save the time slot
            time_slot = {
                "start_time": user_input["start_time"],
                "end_time": user_input["end_time"],
                "days": user_input["days"],
                "apply_to_charge": user_input.get("apply_to_charge", False),
            }
            self.time_slots.append(time_slot)
            
            # Check if user wants to add more slots (max 4)
            if len(self.time_slots) < 4:
                return await self.async_step_add_more_slots()
            else:
                # Max slots reached, move to excluded devices
                self.config_data["no_discharge_time_slots"] = self.time_slots
                return await self.async_step_excluded_devices()

        slot_num = len(self.time_slots) + 1
        return self.async_show_form(
            step_id="add_time_slot",
            data_schema=vol.Schema(
                {
                    vol.Required("start_time"): TimeSelector(),
                    vol.Required("end_time"): TimeSelector(),
                    vol.Required("days", default=["mon", "tue", "wed", "thu", "fri", "sat", "sun"]):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                                translation_key="weekday",
                                multiple=True,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    vol.Required("apply_to_charge", default=False): bool,
                }
            ),
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
                return await self.async_step_predictive_charging_config()
            else:
                # Predictive charging disabled
                self.config_data["enable_predictive_charging"] = False
                self.config_data["charging_time_slot"] = None
                self.config_data["solar_forecast_sensor"] = None
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

    async def async_step_predictive_charging_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 11: Configure predictive grid charging details."""
        errors = {}
        
        if user_input is not None:
                # Validate configuration
                try:
                    # Check solar forecast sensor exists and has valid unit
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
                        # Save predictive charging configuration
                        self.config_data["enable_predictive_charging"] = True
                        self.config_data["charging_time_slot"] = {
                            "start_time": user_input["start_time"],
                            "end_time": user_input["end_time"],
                            "days": user_input["days"],
                        }
                        self.config_data["solar_forecast_sensor"] = user_input["solar_forecast_sensor"]
                        self.config_data["max_contracted_power"] = user_input["max_contracted_power"]

                        return await self.async_step_weekly_full_charge()
                except Exception as e:
                    _LOGGER.error("Error validating predictive charging config: %s", e)
                    errors["base"] = "unknown"
        
        # Show form
        return self.async_show_form(
            step_id="predictive_charging_config",
            data_schema=vol.Schema(
                {
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
                    vol.Required("solar_forecast_sensor"):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Required("max_contracted_power", default=7000):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX
                            )
                        ),
                }
            ),
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
                return self.async_create_entry(
                    title="Marstek Venus Energy Manager", data=self.config_data
                )

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
        """Step 12: Configure weekly full charge details."""
        if user_input is not None:
            # Save weekly full charge configuration
            self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = True
            self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = user_input["weekly_full_charge_day"]

            return self.async_create_entry(
                title="Marstek Venus Energy Manager", data=self.config_data
            )

        # Show form
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
            description_placeholders={
                "description": "Select the day when batteries should charge to 100% for cell balancing. "
                              "After reaching 100%, the system reverts to your configured maximum charge limit."
            },
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
        _LOGGER.info("OptionsFlowHandler initialized successfully for entry: %s", config_entry.entry_id)

    async def _test_connection(self, host: str, port: int, version: str = "v2") -> bool:
        """Test connection to a Marstek Venus battery using version-specific register."""
        client = MarstekModbusClient(host, port)
        try:
            connected = await client.async_connect()
            if not connected:
                return False

            # Test with version-specific SOC register
            soc_register = REGISTER_MAP.get(version, {}).get("battery_soc")
            if soc_register is None:
                await client.async_close()
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

    async def _write_config_to_batteries(self) -> None:
        """Write configuration values to all batteries via Modbus."""
        import asyncio
        from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

        _LOGGER.info("Writing updated configuration to batteries")

        for battery_config in self.config_data["batteries"]:
            battery_version = battery_config.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)
            reg_map = REGISTER_MAP.get(battery_version, REGISTER_MAP[DEFAULT_VERSION])

            client = MarstekModbusClient(battery_config[CONF_HOST], battery_config[CONF_PORT])
            try:
                connected = await client.async_connect()
                if not connected:
                    _LOGGER.warning("Could not connect to %s to update configuration", battery_config[CONF_NAME])
                    continue

                # Convert values
                max_soc_value = int(battery_config["max_soc"] / 0.1)
                min_soc_value = int(battery_config["min_soc"] / 0.1)
                max_charge_power = int(battery_config["max_charge_power"])
                max_discharge_power = int(battery_config["max_discharge_power"])

                _LOGGER.info("Updating %s (%s): max_soc=%d%%, min_soc=%d%%, max_charge=%dW, max_discharge=%dW",
                           battery_config[CONF_NAME], battery_version,
                           battery_config["max_soc"], battery_config["min_soc"],
                           max_charge_power, max_discharge_power)

                # Write cutoff capacities (only if available)
                cutoff_charge_reg = reg_map.get("charging_cutoff_capacity")
                cutoff_discharge_reg = reg_map.get("discharging_cutoff_capacity")

                if cutoff_charge_reg is not None:
                    await client.async_write_register(cutoff_charge_reg, max_soc_value)
                    await asyncio.sleep(0.1)
                    await client.async_write_register(cutoff_discharge_reg, min_soc_value)
                    await asyncio.sleep(0.1)
                    _LOGGER.debug("%s: Hardware cutoff registers updated", battery_config[CONF_NAME])
                else:
                    _LOGGER.info("%s: No hardware cutoff registers (%s) - will use software enforcement",
                               battery_config[CONF_NAME], battery_version)

                # Write maximum power limits (available in both versions)
                max_charge_reg = reg_map.get("max_charge_power")
                max_discharge_reg = reg_map.get("max_discharge_power")

                if max_charge_reg and max_discharge_reg:
                    await client.async_write_register(max_charge_reg, max_charge_power)
                    await asyncio.sleep(0.1)
                    await client.async_write_register(max_discharge_reg, max_discharge_power)
                    await asyncio.sleep(0.1)

                _LOGGER.info("Successfully updated configuration for %s", battery_config[CONF_NAME])
                
            except Exception as e:
                _LOGGER.error("Error updating configuration for %s: %s", battery_config[CONF_NAME], e)
            finally:
                try:
                    await client.async_close()
                except Exception:
                    pass

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Start the options flow - ask for consumption sensor."""
        try:
            if user_input is not None:
                self.config_data["consumption_sensor"] = user_input["consumption_sensor"]
                return await self.async_step_batteries()

            # Load current configuration with defensive defaults
            current_sensor = self.config_entry.data.get("consumption_sensor", "")
        except Exception as e:
            _LOGGER.error("Error in options flow init: %s", e, exc_info=True)
            return self.async_abort(reason="unknown_error")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("consumption_sensor", default=current_sensor):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                }
            ),
        )

    async def async_step_batteries(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure number of batteries."""
        try:
            if user_input is not None:
                self.config_data["num_batteries"] = int(user_input["num_batteries"])
                return await self.async_step_battery_config()

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
                                min=1, max=4, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                }
            ),
        )

    async def async_step_battery_config(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure each battery."""
        errors = {}

        try:
            if user_input is not None:
                # Get version for connection test
                battery_version = user_input.get(CONF_BATTERY_VERSION, DEFAULT_VERSION)

                connection_result = await self._test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    battery_version
                )

                if not connection_result:
                    errors["base"] = "cannot_connect"
                else:
                    # Store version
                    user_input[CONF_BATTERY_VERSION] = battery_version
                    # Convert power values from string to int
                    user_input["max_charge_power"] = int(user_input["max_charge_power"])
                    user_input["max_discharge_power"] = int(user_input["max_discharge_power"])
                    self.battery_configs.append(user_input)
                    self.battery_index += 1

            # Defensive access to config_data
            num_batteries = self.config_data.get("num_batteries", 1)
            if not errors and self.battery_index >= num_batteries:
                self.config_data["batteries"] = self.battery_configs
                return await self.async_step_time_slots()

            # Load current battery config if available with defensive handling
            current_batteries = self.config_entry.data.get("batteries", [])
        except Exception as e:
            _LOGGER.error("Error in options flow battery_config step: %s", e, exc_info=True)
            return self.async_abort(reason="unknown_error")
        battery_num = self.battery_index + 1

        if self.battery_index < len(current_batteries):
            current_battery = current_batteries[self.battery_index]
            defaults = {
                CONF_NAME: current_battery.get(CONF_NAME, f"Marstek Venus {battery_num}"),
                CONF_HOST: current_battery.get(CONF_HOST, ""),
                CONF_PORT: current_battery.get(CONF_PORT, 502),
                CONF_BATTERY_VERSION: current_battery.get(CONF_BATTERY_VERSION, DEFAULT_VERSION),
                "max_charge_power": current_battery.get("max_charge_power", 2500),
                "max_discharge_power": current_battery.get("max_discharge_power", 2500),
                "max_soc": current_battery.get("max_soc", 100),
                "min_soc": current_battery.get("min_soc", 12),
                "enable_charge_hysteresis": current_battery.get("enable_charge_hysteresis", False),
                "charge_hysteresis_percent": current_battery.get("charge_hysteresis_percent", 5),
            }
        else:
            defaults = {
                CONF_NAME: f"Marstek Venus {battery_num}",
                CONF_HOST: "",
                CONF_PORT: 502,
                CONF_BATTERY_VERSION: DEFAULT_VERSION,
                "max_charge_power": 2500,
                "max_discharge_power": 2500,
                "max_soc": 100,
                "min_soc": 12,
                "enable_charge_hysteresis": False,
                "charge_hysteresis_percent": 5,
            }

        return self.async_show_form(
            step_id="battery_config",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
                    vol.Required(CONF_BATTERY_VERSION, default=defaults[CONF_BATTERY_VERSION]):
                        SelectSelector(SelectSelectorConfig(
                            options=[
                                {"value": "v2", "label": "v1/v2"},
                                {"value": "v3", "label": "v3"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )),
                    vol.Required("max_charge_power", default=str(defaults["max_charge_power"])):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "800", "label": "800W"},
                                    {"value": "2500", "label": "2500W"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    vol.Required("max_discharge_power", default=str(defaults["max_discharge_power"])):
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "800", "label": "800W"},
                                    {"value": "2500", "label": "2500W"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    vol.Required("max_soc", default=defaults["max_soc"]):
                        NumberSelector(NumberSelectorConfig(min=80, max=100, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("min_soc", default=defaults["min_soc"]):
                        NumberSelector(NumberSelectorConfig(min=12, max=30, step=1, mode=NumberSelectorMode.SLIDER)),
                    vol.Required("enable_charge_hysteresis", default=defaults["enable_charge_hysteresis"]): bool,
                    vol.Optional("charge_hysteresis_percent", default=defaults["charge_hysteresis_percent"]):
                        NumberSelector(NumberSelectorConfig(min=5, max=20, step=1, mode=NumberSelectorMode.SLIDER)),
                }
            ),
            errors=errors,
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
                return await self.async_step_excluded_devices()

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
        if user_input is not None:
            time_slot = {
                "start_time": user_input["start_time"],
                "end_time": user_input["end_time"],
                "days": user_input["days"],
                "apply_to_charge": user_input.get("apply_to_charge", False),
            }
            self.time_slots.append(time_slot)
            
            if len(self.time_slots) < 4:
                return await self.async_step_add_more_slots()
            else:
                self.config_data["no_discharge_time_slots"] = self.time_slots
                return await self.async_step_excluded_devices()

        # Load existing time slots if available and not yet added
        current_slots = self.config_entry.data.get("no_discharge_time_slots", [])
        slot_num = len(self.time_slots)
        
        if slot_num < len(current_slots):
            current_slot = current_slots[slot_num]
            defaults = {
                "start_time": current_slot.get("start_time", "00:00:00"),
                "end_time": current_slot.get("end_time", "00:00:00"),
                "days": current_slot.get("days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
                "apply_to_charge": current_slot.get("apply_to_charge", False),
            }
        else:
            defaults = {
                "start_time": "00:00:00",
                "end_time": "00:00:00",
                "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "apply_to_charge": False,
            }

        slot_num += 1
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
                }
            ),
            description_placeholders={"slot_num": str(slot_num)},
        )

    async def async_step_add_more_slots(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask if user wants to add more time slots."""
        if user_input is not None:
            if user_input.get("add_more", False):
                return await self.async_step_add_time_slot()
            else:
                self.config_data["no_discharge_time_slots"] = self.time_slots
                return await self.async_step_excluded_devices()

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
                # No excluded devices configured, move to predictive charging
                self.config_data["excluded_devices"] = []
                return await self.async_step_predictive_charging()

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
            }
            self.excluded_devices.append(excluded_device)
            
            # Check if user wants to add more devices (max 4)
            if len(self.excluded_devices) < 4:
                return await self.async_step_add_more_excluded_devices()
            else:
                # Max devices reached, move to predictive charging
                self.config_data["excluded_devices"] = self.excluded_devices
                return await self.async_step_predictive_charging()

        # Load existing excluded devices if available and not yet added
        current_devices = self.config_entry.data.get("excluded_devices", [])
        device_num = len(self.excluded_devices)
        
        if device_num < len(current_devices):
            current_device = current_devices[device_num]
            default_sensor = current_device.get("power_sensor", "")
            default_included = current_device.get("included_in_consumption", True)
        else:
            default_sensor = ""
            default_included = True
        
        device_num += 1
        return self.async_show_form(
            step_id="add_excluded_device",
            data_schema=vol.Schema(
                {
                    vol.Required("power_sensor", default=default_sensor):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Required("included_in_consumption", default=default_included): bool,
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
                # User finished adding devices, move to predictive charging
                self.config_data["excluded_devices"] = self.excluded_devices
                return await self.async_step_predictive_charging()

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
                return await self.async_step_predictive_charging_config()
            else:
                # Predictive charging disabled
                self.config_data["enable_predictive_charging"] = False
                self.config_data["charging_time_slot"] = None
                self.config_data["solar_forecast_sensor"] = None
                self.config_data["max_contracted_power"] = 7000

                return await self.async_step_weekly_full_charge()

        # Check if predictive charging was previously enabled
        is_predictive_enabled = self.config_entry.data.get("enable_predictive_charging", False)

        return self.async_show_form(
            step_id="predictive_charging",
            data_schema=vol.Schema(
                {
                    vol.Required("configure_predictive_charging", default=is_predictive_enabled): bool,
                }
            ),
        )

    async def async_step_predictive_charging_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure predictive grid charging details in options flow."""
        errors = {}
        
        # Load existing configuration
        existing_config = self.config_entry.data
        time_slot_current = existing_config.get("charging_time_slot", {})
        forecast_sensor_current = existing_config.get("solar_forecast_sensor", "")
        max_power_current = existing_config.get("max_contracted_power", 7000)
        
        if user_input is not None:
                # Validate configuration
                try:
                    # Check solar forecast sensor exists and has valid unit
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
                        # Save predictive charging configuration
                        self.config_data["enable_predictive_charging"] = True
                        self.config_data["charging_time_slot"] = {
                            "start_time": user_input["start_time"],
                            "end_time": user_input["end_time"],
                            "days": user_input["days"],
                        }
                        self.config_data["solar_forecast_sensor"] = user_input["solar_forecast_sensor"]
                        self.config_data["max_contracted_power"] = user_input["max_contracted_power"]

                        return await self.async_step_weekly_full_charge()
                except Exception as e:
                    _LOGGER.error("Error validating predictive charging config: %s", e)
                    errors["base"] = "unknown"
        
        # Prepare defaults from existing config
        if time_slot_current:
            defaults = {
                "start_time": time_slot_current.get("start_time", "01:00:00"),
                "end_time": time_slot_current.get("end_time", "06:00:00"),
                "days": time_slot_current.get("days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
                "sensor": forecast_sensor_current if forecast_sensor_current else "",
                "power": max_power_current,
            }
        else:
            defaults = {
                "start_time": "01:00:00",
                "end_time": "06:00:00",
                "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "sensor": "",
                "power": 7000,
            }
        
        # Show form
        return self.async_show_form(
            step_id="predictive_charging_config",
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
                    vol.Required("solar_forecast_sensor", default=defaults["sensor"]):
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Required("max_contracted_power", default=defaults["power"]):
                        NumberSelector(
                            NumberSelectorConfig(
                                min=1000, max=15000, step=100, mode=NumberSelectorMode.BOX
                            )
                        ),
                }
            ),
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
                # Weekly full charge disabled
                self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = False
                self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = "sun"

                # Continue to PD controller advanced settings
                return await self.async_step_pd_advanced()

        # Check if weekly full charge was previously enabled
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
        """Configure weekly full charge details in options flow."""
        # Load existing configuration
        existing_config = self.config_entry.data
        current_day = existing_config.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")

        if user_input is not None:
            # Save weekly full charge configuration
            self.config_data[CONF_ENABLE_WEEKLY_FULL_CHARGE] = True
            self.config_data[CONF_WEEKLY_FULL_CHARGE_DAY] = user_input["weekly_full_charge_day"]

            # Continue to PD controller advanced settings
            return await self.async_step_pd_advanced()

        # Show form
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
            description_placeholders={
                "description": "Select the day when batteries should charge to 100% for cell balancing. "
                              "After reaching 100%, the system reverts to your configured maximum charge limit."
            },
        )

    async def async_step_pd_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to configure advanced PD controller parameters."""
        if user_input is not None:
            if user_input.get("configure_pd_advanced", False):
                return await self.async_step_pd_advanced_config()
            else:
                # Use default PD parameters - set them explicitly for backward compatibility
                self.config_data[CONF_PD_KP] = DEFAULT_PD_KP
                self.config_data[CONF_PD_KD] = DEFAULT_PD_KD
                self.config_data[CONF_PD_DEADBAND] = DEFAULT_PD_DEADBAND
                self.config_data[CONF_PD_MAX_POWER_CHANGE] = DEFAULT_PD_MAX_POWER_CHANGE
                self.config_data[CONF_PD_DIRECTION_HYSTERESIS] = DEFAULT_PD_DIRECTION_HYSTERESIS

                # Final step: Update entry and reload
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=self.config_data
                )
                await self._write_config_to_batteries()
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        # Check if PD parameters were previously configured (non-default values)
        has_custom_pd = (
            self.config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP) != DEFAULT_PD_KP or
            self.config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD) != DEFAULT_PD_KD or
            self.config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND) != DEFAULT_PD_DEADBAND or
            self.config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE) != DEFAULT_PD_MAX_POWER_CHANGE or
            self.config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS) != DEFAULT_PD_DIRECTION_HYSTERESIS
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

            # Final step: Update entry and reload
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self.config_data
            )
            await self._write_config_to_batteries()
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # Load existing configuration with defaults
        existing_config = self.config_entry.data
        current_kp = existing_config.get(CONF_PD_KP, DEFAULT_PD_KP)
        current_kd = existing_config.get(CONF_PD_KD, DEFAULT_PD_KD)
        current_deadband = existing_config.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        current_max_change = existing_config.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        current_hysteresis = existing_config.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)

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
                }
            ),
            description_placeholders={
                "description": (
                    "**Kp (Proportional Gain)**: Responsiveness to grid imbalance. Higher = faster response but risk of overshoot.\n\n"
                    "**Kd (Derivative Gain)**: Damping to prevent oscillation. Higher = smoother transitions but slower settling.\n\n"
                    "**Deadband**: Grid power tolerance (W) around zero. Prevents micro-adjustments to minor fluctuations.\n\n"
                    "**Max Power Change**: Maximum battery power change per control cycle (W). Prevents abrupt battery commands.\n\n"
                    "**Direction Hysteresis**: Power threshold (W) required to switch between charging and discharging. Prevents rapid direction changes."
                )
            },
        )