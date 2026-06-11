"""Excluded-device and EV-charger load management for Marstek Venus.

Owns:
- Net kW correction to the home sensor for excluded-device accounting
- Power adjustment for excluded devices (applied before PD setpoint decisions)
- EV charger no-telemetry state detection and 5-minute battery pause logic

Reads/writes the controller's existing attributes by reference for backward
compatibility with the rest of the control loop:
    previous_power, _excluded_included_adjustment,
    _ev_charging_states, _ev_pause_until.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ExternalLoads:
    """Manages excluded-device and EV-charger load adjustments."""

    def __init__(
        self,
        hass: "HomeAssistant",
        config_entry: "ConfigEntry",
        controller: Any,
    ) -> None:
        self._hass = hass
        self._config_entry = config_entry
        self._controller = controller

    def consumption_delta_kw(self) -> float:
        """Net kW correction to apply to the home sensor for excluded-device accounting.

        Returns a value to ADD to the raw home sensor reading so the accumulator
        reflects only the load the battery is expected to cover:
          - included_in_consumption=True  → device IS in home sensor but battery skips it → subtract
          - included_in_consumption=False → device NOT in home sensor but battery covers it → add
        ev_charger_no_telemetry devices are skipped (no numeric power sensor).
        Unavailable sensors are silently ignored.
        """
        excluded_devices = self._config_entry.data.get("excluded_devices", [])
        if not excluded_devices:
            return 0.0

        delta = 0.0
        for device in excluded_devices:
            if not device.get("enabled", True):
                continue
            if device.get("ev_charger_no_telemetry", False):
                continue
            power_sensor = device.get("power_sensor")
            if not power_sensor:
                continue
            state = self._hass.states.get(power_sensor)
            if state is None or state.state in ("unknown", "unavailable"):
                continue
            try:
                power_w = float(state.state)
            except (ValueError, TypeError):
                continue
            unit = state.attributes.get("unit_of_measurement", "W")
            device_kw = power_w / 1000.0 if unit == "W" else power_w
            if device.get("included_in_consumption", True):
                delta -= device_kw
            else:
                delta += device_kw

        return delta

    def calculate_adjustment(self, current_grid_power: float) -> float:
        """Calculate power adjustment for excluded devices.

        Logic:
        - If device IS included in home consumption sensor (included_in_consumption=True):
          → SUBTRACT its power (battery should NOT power this device)
          → If allow_solar_surplus is True:
            - During DISCHARGE (previous_power < 0): full exclusion (battery won't discharge for device)
            - During CHARGE (previous_power >= 0): no exclusion (PD sees real grid, reduces charging
              to leave solar for the device — avoids feedback loop that causes grid import)
        - If device is NOT included in home consumption sensor (included_in_consumption=False):
          → ADD its power (battery SHOULD power this device, even though home sensor doesn't see it)

        Returns the total adjustment to apply to sensor_actual.
        Positive = reduce battery discharge
        Negative = increase battery discharge
        """
        excluded_devices = self._config_entry.data.get("excluded_devices", [])
        if not excluded_devices:
            self._controller._excluded_included_adjustment = 0.0
            return 0.0

        is_charging = self._controller.previous_power >= 0

        total_adjustment = 0.0
        included_adjustment = 0.0  # Track included_in_consumption portion separately
        for device in excluded_devices:
            if not device.get("enabled", True):
                continue
            # EV chargers in no-telemetry mode expose a state sensor, not a numeric
            # power sensor – their behaviour is handled by _check_ev_charger_state().
            if device.get("ev_charger_no_telemetry", False):
                continue

            power_sensor = device.get("power_sensor")
            if not power_sensor:
                continue

            state = self._hass.states.get(power_sensor)
            if state is None or state.state in ("unknown", "unavailable"):
                _LOGGER.debug("Excluded device sensor %s not available", power_sensor)
                continue

            try:
                device_power = float(state.state)
                included_in_consumption = device.get("included_in_consumption", True)
                allow_solar_surplus = device.get("allow_solar_surplus", False)

                if included_in_consumption:
                    # Device IS in home sensor → SUBTRACT (don't power from battery)
                    if allow_solar_surplus:
                        if is_charging:
                            # Battery is charging: do NOT adjust. PD must see real grid
                            # to reduce charging and leave solar for the device.
                            _LOGGER.debug("Excluded device %s consuming %.1fW (solar surplus, battery charging → no adjustment)",
                                        power_sensor, device_power)
                        else:
                            # Battery is discharging: full exclusion so battery won't
                            # discharge to power this device.
                            total_adjustment += device_power
                            included_adjustment += device_power
                            current_grid_power -= device_power
                            _LOGGER.debug("Excluded device %s consuming %.1fW (solar surplus, battery discharging → full exclusion)",
                                        power_sensor, device_power)
                    else:
                        total_adjustment += device_power
                        included_adjustment += device_power
                        _LOGGER.debug("Excluded device %s consuming %.1fW (included in consumption, SUBTRACTING)",
                                    power_sensor, device_power)
                else:
                    # Device is NOT in home sensor → ADD (power from battery)
                    total_adjustment -= device_power
                    _LOGGER.debug("Additional device %s consuming %.1fW (NOT in consumption, ADDING)",
                                    power_sensor, device_power)
            except (ValueError, TypeError):
                _LOGGER.warning("Could not parse device sensor %s: %s", power_sensor, state.state)

        # Store the included-in-consumption portion for capacity protection
        self._controller._excluded_included_adjustment = included_adjustment
        return total_adjustment

    def check_ev_charger_state(self) -> tuple[bool, bool]:
        """Check state of EV chargers configured with no-telemetry mode.

        Detects a charging state by looking for 'charg' (English) or 'cargand'
        (Spanish) in the sensor state string (case-insensitive).

        On the first cycle a charging state is detected, a 5-minute pause is
        started so the EV can grab as much current from the grid as it needs
        before the battery interferes.  After the pause the battery is allowed
        to charge from solar surplus but must never discharge.

        Returns:
            (pause_active, ev_charging_active):
            - pause_active: True if the 5-min post-detection pause is still running
            - ev_charging_active: True if EV is charging and pause has expired
        """
        excluded_devices = self._config_entry.data.get("excluded_devices", [])
        now = dt_util.utcnow()
        pause_active = False
        ev_charging_active = False

        for device in excluded_devices:
            if not device.get("enabled", True):
                continue
            if not device.get("ev_charger_no_telemetry", False):
                continue

            sensor_id = device.get("power_sensor")
            if not sensor_id:
                continue

            state = self._hass.states.get(sensor_id)
            if state is None or state.state in ("unknown", "unavailable"):
                continue

            state_lower = state.state.lower().strip()
            is_charging = "charg" in state_lower or "cargand" in state_lower

            prev_charging = self._controller._ev_charging_states.get(sensor_id, False)

            if is_charging and not prev_charging:
                # EV just started charging – start 5-minute battery pause
                self._controller._ev_pause_until[sensor_id] = now + timedelta(minutes=5)
                _LOGGER.info(
                    "EV charger %s: charging detected – 5-minute battery pause started",
                    sensor_id,
                )
            elif not is_charging and prev_charging:
                # EV stopped charging – cancel any remaining pause
                self._controller._ev_pause_until.pop(sensor_id, None)
                _LOGGER.info(
                    "EV charger %s: charging stopped – normal battery operation resumed",
                    sensor_id,
                )

            self._controller._ev_charging_states[sensor_id] = is_charging

            pause_until = self._controller._ev_pause_until.get(sensor_id)
            if pause_until is not None:
                if now < pause_until:
                    pause_active = True
                    _LOGGER.debug(
                        "EV charger %s: pause active, %ds remaining",
                        sensor_id,
                        (pause_until - now).total_seconds(),
                    )
                else:
                    # Pause has expired; remove entry and switch to discharge-block mode
                    self._controller._ev_pause_until.pop(sensor_id, None)
                    if is_charging:
                        ev_charging_active = True
            elif is_charging:
                ev_charging_active = True

        return pause_active, ev_charging_active
