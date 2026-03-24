"""The Marstek Venus Energy Manager integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from pymodbus.exceptions import ConnectionException

from .const import (
    DOMAIN,
    CONF_ENABLE_PREDICTIVE_CHARGING,
    CONF_CHARGING_TIME_SLOT,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    DEFAULT_BASE_CONSUMPTION_KWH,
    SOC_REEVALUATION_THRESHOLD,
    CONF_ENABLE_WEEKLY_FULL_CHARGE,
    CONF_WEEKLY_FULL_CHARGE_DAY,
    CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY,
    CONF_ENABLE_CHARGE_DELAY,
    CONF_DELAY_SAFETY_MARGIN_MIN,
    DEFAULT_DELAY_SAFETY_MARGIN_MIN,
    WEEKDAY_MAP,
    CHARGE_EFFICIENCY,
    DELAY_SAFETY_FACTOR,
    LOW_FORECAST_THRESHOLD_FACTOR,

    T_START_FALLBACK_HOUR,
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
    CONF_PD_MIN_CHARGE_POWER,
    CONF_PD_MIN_DISCHARGE_POWER,
    DEFAULT_PD_MIN_CHARGE_POWER,
    DEFAULT_PD_MIN_DISCHARGE_POWER,
    DEFAULT_SLOT_TARGET_GRID_POWER,
    CONF_CAPACITY_PROTECTION_ENABLED,
    CONF_CAPACITY_PROTECTION_SOC_THRESHOLD,
    CONF_CAPACITY_PROTECTION_LIMIT,
    DEFAULT_CAPACITY_PROTECTION_SOC,
    DEFAULT_CAPACITY_PROTECTION_LIMIT,
    CONF_MANUAL_MODE_ENABLED,
    CONF_PREDICTIVE_CHARGING_OVERRIDDEN,
)
from .coordinator import MarstekVenusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# List of platforms to support.
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


class ChargeDischargeController:
    """Controller to manage charge/discharge logic for all batteries."""

    def __init__(self, hass: HomeAssistant, coordinators: list[MarstekVenusDataUpdateCoordinator], consumption_sensor: str, config_entry: ConfigEntry):
        """Initialize the controller."""
        self.hass = hass
        self.coordinators = coordinators
        self.consumption_sensor = consumption_sensor
        self.config_entry = config_entry
        
        # State tracking
        self.previous_sensor = None
        self.previous_power = 0
        self.first_execution = True

        # Load PD controller parameters from config (with backward-compatible defaults)
        self.deadband = config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        self.kp = config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP)
        self.kd = config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD)
        self.max_power_change_per_cycle = config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        self.direction_hysteresis = config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        self.min_charge_power = config_entry.data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        self.min_discharge_power = config_entry.data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)

        # Sensor filtering to avoid reacting to instantaneous spikes
        self.sensor_history = []  # Keep last 3 readings for faster response
        self.sensor_history_size = 2

        # PID controller state variables (Ki currently disabled)
        self.ki = 0.0          # Integral gain (DISABLED - using pure PD control)
        self.error_integral = 0.0      # Accumulated error
        self.previous_error = 0.0      # Previous error for derivative
        self.dt = 2.0                  # Control loop time in seconds
        self.integral_decay = 0.90     # Leaky integrator: 10% decay per cycle

        # Oscillation detection for auto-reset
        self.sign_changes = 0           # Count of consecutive sign changes in error
        self.last_error_sign = 0        # Track sign of previous error (1, -1, or 0)
        self.oscillation_threshold = 3  # Reset PID after 3 sign changes

        # Last output sign for directional hysteresis
        self.last_output_sign = 0        # Track last output direction (1=charge, -1=discharge, 0=idle)

        # Stale sensor detection
        self._last_sensor_update_time = None    # datetime of last real sensor change (HA last_updated)
        self._stale_cycles = 0                  # consecutive cycles without sensor change
        self._max_stale_cycles = 15             # safety valve: ~30s before forcing recalculation
        
        # Calculate dynamic anti-windup limits based on total system capacity
        self.max_charge_capacity = sum(c.max_charge_power for c in coordinators)
        self.max_discharge_capacity = sum(c.max_discharge_power for c in coordinators)

        # Load sharing state: track which batteries were active last cycle
        self._active_discharge_batteries = []
        self._active_charge_batteries = []

        # Non-responsive battery tracking: excludes batteries that ACK commands but don't deliver power
        # Format: coordinator -> {"fail_count": int, "excluded_at": datetime|None, "cooldown_minutes": int}
        self._non_responsive_batteries: dict = {}
        
        # Predictive Grid Charging state
        self.predictive_charging_enabled = config_entry.data.get(CONF_ENABLE_PREDICTIVE_CHARGING, False)
        self.charging_time_slot = config_entry.data.get(CONF_CHARGING_TIME_SLOT, None)
        self.solar_forecast_sensor = config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR, None)
        self.max_contracted_power = config_entry.data.get(CONF_MAX_CONTRACTED_POWER, 7000)
        
        # State tracking for predictive charging
        self.grid_charging_active = False  # True when mode is active
        self.last_evaluation_soc = None    # SOC at last check
        self.predictive_charging_overridden = config_entry.data.get(CONF_PREDICTIVE_CHARGING_OVERRIDDEN, False)
        self._grid_charging_initialized = False  # Flag for initialization
        self._last_decision_data = None  # Store last decision for diagnostics
        # Consumption history for dynamic base consumption (7-day rolling average)
        self._daily_consumption_history = []  # List of (date, consumption_kwh)
        # Persistent store for consumption history (survives restarts AND reloads)
        self._consumption_store = Store(hass, 1, f"{DOMAIN}_consumption_history")

        # Manual mode state
        self.manual_mode_enabled = config_entry.data.get(CONF_MANUAL_MODE_ENABLED, False)

        # Capacity Protection Mode state
        self.capacity_protection_enabled = config_entry.data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)
        self.capacity_protection_soc_threshold = config_entry.data.get(CONF_CAPACITY_PROTECTION_SOC_THRESHOLD, DEFAULT_CAPACITY_PROTECTION_SOC)
        self.capacity_protection_limit = config_entry.data.get(CONF_CAPACITY_PROTECTION_LIMIT, DEFAULT_CAPACITY_PROTECTION_LIMIT)
        self._capacity_protection_active = False  # True when SOC < threshold (protection is intervening)
        self._capacity_protection_status = {
            "active": False,
            "avg_soc": None,
            "soc_threshold": self.capacity_protection_soc_threshold,
            "peak_limit": self.capacity_protection_limit,
            "estimated_house_load": None,
            "action": "idle",  # idle, shaving, conserving
            "original_target": None,
            "adjusted_target": None,
        }

        # Weekly Full Charge state
        self.weekly_full_charge_enabled = config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False)
        self.weekly_full_charge_day = config_entry.data.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")
        self.weekly_full_charge_complete = False  # True when ALL batteries reach 100%
        self.last_checked_weekday = None  # Track day transitions for reset logic
        self.weekly_full_charge_registers_written = False  # True when register 44000 set to 100%

        # Unified Charge Delay state
        # Backward compat: new key takes priority, fallback to old keys
        self.charge_delay_enabled = config_entry.data.get(
            CONF_ENABLE_CHARGE_DELAY,
            config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        )
        self._delay_safety_margin_h = config_entry.data.get(CONF_DELAY_SAFETY_MARGIN_MIN, DEFAULT_DELAY_SAFETY_MARGIN_MIN) / 60.0
        self._stored_solar_forecast_kwh = None
        self._stored_solar_forecast_kwh_raw = None
        self._stored_solar_forecast_date = None
        self._charge_delay_unlocked = False     # True when delay has been unlocked today
        self._charge_delay_last_date = None     # For daily reset
        self._solar_t_start = None
        self._delay_last_log_time = 0           # Throttle logging to every 5 minutes
        self._force_full_charge = False         # Manual trigger via button, resets on day change

        # Unified status dict for the ChargeDelaySensor (read-only by sensor)
        self._charge_delay_status = {
            "state": "Disabled" if not self.charge_delay_enabled else "Idle",
            "target_soc": None,
            "forecast_kwh": None,
            "solar_t_start": None,
            "solar_t_end": None,
            "energy_needed_kwh": None,
            "remaining_solar_kwh": None,
            "remaining_consumption_kwh": None,
            "net_solar_kwh": None,
            "charge_time_h": None,
            "estimated_unlock_time": None,
            "unlock_reason": None,
            "safety_margin_min": int(self._delay_safety_margin_h * 60),
        }

        # Minimal status dict for WeeklyFullChargeSensor (charge state only, not delay)
        self._weekly_charge_status = {
            "state": "Disabled" if not self.weekly_full_charge_enabled else "Idle",
        }

        # Persistent storage for weekly charge completion state
        self._store = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.weekly_charge_state")
        # Persistent storage for solar T_start (survives HA restarts within the same day)
        self._solar_t_start_store = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.solar_t_start")

        _LOGGER.info("PD Controller initialized (user-configurable): Kp=%.2f, Ki=%.2f, Kd=%.2f, "
                     "Deadband=±%dW, Filter=%d samples, Hysteresis=%dW, MaxChange=%dW/cycle, Limits: ±%dW",
                     self.kp, self.ki, self.kd,
                     self.deadband, self.sensor_history_size, self.direction_hysteresis,
                     self.max_power_change_per_cycle, self.max_discharge_capacity)

        _LOGGER.info("Predictive Grid Charging: %s (ICP limit: %dW)",
                     "ENABLED" if self.predictive_charging_enabled else "DISABLED",
                     self.max_contracted_power if self.predictive_charging_enabled else 0)

        _LOGGER.info("Weekly Full Charge: %s (day: %s)",
                     "ENABLED" if self.weekly_full_charge_enabled else "DISABLED",
                     self.weekly_full_charge_day.upper() if self.weekly_full_charge_enabled else "N/A")

        _LOGGER.info("Charge Delay: %s (safety margin: %d min)",
                     "ENABLED" if self.charge_delay_enabled else "DISABLED",
                     int(self._delay_safety_margin_h * 60))

        _LOGGER.info("Capacity Protection: %s (SOC threshold: %d%%, peak limit: %dW)",
                     "ENABLED" if self.capacity_protection_enabled else "DISABLED",
                     self.capacity_protection_soc_threshold,
                     self.capacity_protection_limit)

    def update_pd_parameters(self):
        """Re-read PD controller parameters from config_entry.data (hot-reload)."""
        self.deadband = self.config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        self.kp = self.config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP)
        self.kd = self.config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD)
        self.max_power_change_per_cycle = self.config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        self.direction_hysteresis = self.config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        self.min_charge_power = self.config_entry.data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        self.min_discharge_power = self.config_entry.data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)
        self.max_contracted_power = self.config_entry.data.get(CONF_MAX_CONTRACTED_POWER, 7000)
        self._delay_safety_margin_h = self.config_entry.data.get(CONF_DELAY_SAFETY_MARGIN_MIN, DEFAULT_DELAY_SAFETY_MARGIN_MIN) / 60.0
        self._charge_delay_status["safety_margin_min"] = int(self._delay_safety_margin_h * 60)
        self.charge_delay_enabled = self.config_entry.data.get(
            CONF_ENABLE_CHARGE_DELAY,
            self.config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        )
        self.solar_forecast_sensor = self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR, None)
        self.capacity_protection_enabled = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)
        self.capacity_protection_soc_threshold = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_SOC_THRESHOLD, DEFAULT_CAPACITY_PROTECTION_SOC)
        self.capacity_protection_limit = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_LIMIT, DEFAULT_CAPACITY_PROTECTION_LIMIT)
        _LOGGER.info("PD parameters hot-reloaded: Kp=%.2f, Kd=%.2f, deadband=%d, max_change=%d, hysteresis=%d, min_charge=%d, min_discharge=%d",
                     self.kp, self.kd, self.deadband, self.max_power_change_per_cycle, self.direction_hysteresis, self.min_charge_power, self.min_discharge_power)

    def _is_operation_allowed(self, is_charging: bool) -> bool:
        """Check if charging or discharging is allowed based on time slots.

        Logic:
        - If no time slots configured: Always allowed
        - If time slots configured for DISCHARGE only:
          - Discharge only allowed DURING slots
          - Charging always allowed (not restricted)
        - If time slots configured WITH apply_to_charge=True:
          - Those specific slots also restrict charging
          - Charging only allowed during slots marked with apply_to_charge
        - Charge delay: if enabled, charging is blocked until solar conditions
          indicate it's time to charge (unified delay for daily and weekly)
        """
        from datetime import datetime, time as dt_time

        # Unified charge delay: block charging if delay is active
        if is_charging and self._is_charge_delayed():
            return False

        # Read time slots from config entry (allows live updates from options flow)
        all_time_slots = self.config_entry.data.get("no_discharge_time_slots", [])
        # Filter out disabled slots - treat as if they don't exist
        time_slots = [s for s in all_time_slots if s.get("enabled", True)]

        if not time_slots:
            _LOGGER.debug("No active time slots configured - operation always allowed")
            return True
        
        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        
        operation_type = "charging" if is_charging else "discharging"
        
        # Special case: if charging and NO slot has apply_to_charge=True, charging is always allowed
        if is_charging:
            has_charge_restriction = any(slot.get("apply_to_charge", False) for slot in time_slots)
            if not has_charge_restriction:
                _LOGGER.debug("Charging always allowed - no slots restrict charging")
                return True
        
        _LOGGER.debug("Checking time slots for %s: current_time=%s, current_day=%s, slots=%s", 
                     operation_type, current_time.strftime("%H:%M:%S"), current_day, time_slots)
        
        for i, slot in enumerate(time_slots):
            # Check if this slot applies to the current operation (charge/discharge)
            apply_to_charge = slot.get("apply_to_charge", False)

            # Skip slot if it's charging and this slot doesn't restrict charging
            if is_charging and not apply_to_charge:
                _LOGGER.debug("Slot %d: Skipping for charging (apply_to_charge=False)", i+1)
                continue
            # For discharge, all slots apply
            
            _LOGGER.debug("Checking slot %d: start=%s, end=%s, days=%s, apply_to_charge=%s", 
                         i+1, slot.get("start_time"), slot.get("end_time"), slot.get("days"), apply_to_charge)
            
            # Check if current day is in the slot's days
            if current_day not in slot["days"]:
                _LOGGER.debug("Slot %d: Current day %s not in slot days %s", i+1, current_day, slot["days"])
                continue
            
            # Parse start and end times from the slot
            try:
                start_time = dt_time.fromisoformat(slot["start_time"])
                end_time = dt_time.fromisoformat(slot["end_time"])
            except Exception as e:
                _LOGGER.error("Error parsing time slot %d: %s", i+1, e)
                continue
            
            _LOGGER.debug("Slot %d: Checking if %s is between %s and %s", 
                         i+1, current_time.strftime("%H:%M:%S"), 
                         start_time.strftime("%H:%M:%S"), end_time.strftime("%H:%M:%S"))
            
            # Check if current time is within the slot
            if start_time <= current_time <= end_time:
                _LOGGER.info("MATCH! Slot %d: %s IS ALLOWED - time %s within %s - %s (day: %s)",
                            i+1, operation_type.upper(), current_time.strftime("%H:%M:%S"),
                            start_time.strftime("%H:%M:%S"), end_time.strftime("%H:%M:%S"), current_day)
                return True
        
        _LOGGER.info("No matching time slot found - %s NOT ALLOWED (slots configured but none match)", operation_type.upper())
        return False

    def _get_active_slot(self) -> dict | None:
        """Get the currently active time slot, or None if no slot is active.

        Returns the full slot dict so callers can extract target_grid_power,
        min_charge_power, min_discharge_power, etc.
        """
        from datetime import datetime, time as dt_time

        time_slots = self.config_entry.data.get("no_discharge_time_slots", [])
        if not time_slots:
            return None

        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]

        for slot in time_slots:
            # Skip disabled slots
            if not slot.get("enabled", True):
                continue
            if current_day not in slot.get("days", []):
                continue
            try:
                start_time = dt_time.fromisoformat(slot["start_time"])
                end_time = dt_time.fromisoformat(slot["end_time"])
            except Exception:
                continue

            if start_time <= current_time <= end_time:
                return slot

        return None

    def _get_available_batteries(self, is_charging: bool) -> list:
        """Get list of available batteries for the current operation.
        
        For charging with hysteresis:
          1. Battery charges normally until reaching max_soc
          2. Once max_soc is reached, hysteresis activates
          3. Battery won't charge again until SOC drops below (max_soc - hysteresis_percent)
          4. When SOC drops below threshold, hysteresis deactivates and charging resumes
        
        For discharging: only checks min_soc
        """
        available_batteries = []
        for coordinator in self.coordinators:
            if coordinator.data is None:
                continue

            # Skip batteries that are unreachable
            if not coordinator.is_available:
                _LOGGER.debug("%s: Skipping - battery unreachable (failures: %d)",
                             coordinator.name, coordinator._consecutive_failures)
                continue

            # Skip batteries excluded due to non-responsive behavior
            if self._is_battery_excluded(coordinator):
                _LOGGER.debug("%s: Skipping - excluded due to non-responsive behavior", coordinator.name)
                continue
                
            current_soc = coordinator.data.get("battery_soc", 0)
            
            if is_charging:
                # Check if weekly full charge is active AND 100% is actually unlocked
                weekly_charge_active = self._is_weekly_full_charge_active()
                weekly_100_unlocked = weekly_charge_active and (
                    not self.charge_delay_enabled or self._charge_delay_unlocked
                )

                # Update hysteresis state if enabled
                if coordinator.enable_charge_hysteresis:
                    # Only override hysteresis when 100% is actually unlocked
                    if weekly_100_unlocked:
                        # Force-disable hysteresis during weekly charge
                        if coordinator._hysteresis_active:
                            _LOGGER.debug("%s: Overriding hysteresis for weekly full charge", coordinator.name)
                        coordinator._hysteresis_active = False
                    else:
                        # Normal hysteresis logic
                        if current_soc >= coordinator.max_soc:
                            coordinator._hysteresis_active = True

                        charge_threshold = coordinator.max_soc - coordinator.charge_hysteresis_percent
                        if current_soc < charge_threshold:
                            coordinator._hysteresis_active = False

                        if coordinator._hysteresis_active:
                            _LOGGER.debug("%s: Skipping charge - Hysteresis active (SOC %.1f%%, threshold: %.1f%%)",
                                         coordinator.name, current_soc, charge_threshold)
                            continue

                # Determine effective max SOC
                if weekly_100_unlocked:
                    effective_max_soc = 100
                    _LOGGER.debug("%s: Weekly Full Charge active - effective_max_soc=100%% (configured: %d%%)",
                                 coordinator.name, coordinator.max_soc)
                else:
                    effective_max_soc = coordinator.max_soc

                # Only charge if below effective max SOC
                if current_soc < effective_max_soc:
                    available_batteries.append(coordinator)
            else:  # discharging
                if current_soc > coordinator.min_soc:
                    available_batteries.append(coordinator)
        
        return available_batteries

    # -------------------------------------------------------------------------
    # Non-responsive battery detection helpers
    # -------------------------------------------------------------------------

    def _is_battery_excluded(self, coordinator) -> bool:
        """Return True if the battery is currently in non-responsive cooldown.

        When the cooldown expires, the battery is allowed one retry window:
        fail_count is reset and the next cooldown duration is doubled (capped at 30 min).
        """
        info = self._non_responsive_batteries.get(coordinator)
        if not info or info["excluded_at"] is None:
            return False
        elapsed_min = (dt_util.utcnow() - info["excluded_at"]).total_seconds() / 60
        if elapsed_min >= info["cooldown_minutes"]:
            _LOGGER.info(
                "[%s] Non-responsive cooldown expired (%d min) - retrying battery",
                coordinator.name, info["cooldown_minutes"],
            )
            info["excluded_at"] = None
            info["fail_count"] = 0
            info["cooldown_minutes"] = min(info["cooldown_minutes"] * 2, 30)
            return False
        return True

    def _record_non_responsive(self, coordinator, commanded: float, actual: float) -> None:
        """Record a non-delivery cycle for a battery and exclude it after 3 consecutive fails."""
        info = self._non_responsive_batteries.setdefault(
            coordinator,
            {"fail_count": 0, "excluded_at": None, "cooldown_minutes": 5},
        )
        info["fail_count"] += 1
        _LOGGER.debug(
            "[%s] Not delivering power: commanded=%dW, actual=%dW (fail %d/3)",
            coordinator.name, int(commanded), int(actual), info["fail_count"],
        )
        if info["fail_count"] >= 3 and info["excluded_at"] is None:
            info["excluded_at"] = dt_util.utcnow()
            _LOGGER.warning(
                "[%s] Battery is not delivering power after 3 consecutive cycles "
                "(commanded=%dW, actual=%dW). Excluding from pool for %d minutes.",
                coordinator.name, int(commanded), int(actual), info["cooldown_minutes"],
            )

    def _clear_non_responsive(self, coordinator) -> None:
        """Mark a battery as healthy (delivering power) and reset its exclusion state."""
        info = self._non_responsive_batteries.get(coordinator)
        if info:
            was_excluded = info["excluded_at"] is not None
            info["fail_count"] = 0
            info["excluded_at"] = None
            info["cooldown_minutes"] = 5  # reset backoff after successful delivery
            if was_excluded:
                _LOGGER.info(
                    "[%s] Battery is delivering power again - returned to pool",
                    coordinator.name,
                )

    @property
    def non_responsive_battery_names(self) -> list[str]:
        """Return names of batteries currently excluded due to non-responsive behavior."""
        now = dt_util.utcnow()
        return [
            c.name
            for c, info in self._non_responsive_batteries.items()
            if info.get("excluded_at") is not None
            and (now - info["excluded_at"]).total_seconds() / 60 < info["cooldown_minutes"]
        ]

    # -------------------------------------------------------------------------

    def _is_weekly_full_charge_active(self) -> bool:
        """Check if weekly full charge is currently active.

        Returns True if:
        - Feature is enabled
        - Today is the selected day
        - NOT all batteries have reached 100% yet

        Also handles day boundary transitions to reset the flag.
        """
        if not self.weekly_full_charge_enabled:
            return False

        from datetime import datetime

        now = datetime.now()
        current_weekday = now.weekday()
        target_weekday = WEEKDAY_MAP[self.weekly_full_charge_day]

        # Handle day boundary transitions
        if self.last_checked_weekday is not None and self.last_checked_weekday != current_weekday:
            # Day changed - check if we're exiting the target day
            if self.last_checked_weekday == target_weekday and current_weekday != target_weekday:
                # Just exited the target day - reset flags for next week
                _LOGGER.info("Weekly Full Charge: Exited %s, resetting flags for next week",
                            self.weekly_full_charge_day.upper())
                self.weekly_full_charge_complete = False
                self.weekly_full_charge_registers_written = False
                self._force_full_charge = False
                self._weekly_charge_status["state"] = "Idle"
                # Save the cleared state asynchronously (don't await to avoid blocking)
                asyncio.create_task(self._save_weekly_charge_state())

        self.last_checked_weekday = current_weekday

        # Check if we're on the target day and haven't completed yet
        is_target_day = current_weekday == target_weekday

        # Force full charge button overrides the day check
        if self._force_full_charge:
            if self.weekly_full_charge_complete:
                return False
            return True

        if not is_target_day:
            return False

        if self.weekly_full_charge_complete:
            _LOGGER.debug("Weekly Full Charge: On target day but already completed - using normal max_soc")
            return False

        # Active: on target day and not yet complete
        return True

    async def _load_weekly_charge_state(self) -> None:
        """Load persisted weekly charge completion state from storage.

        This ensures that if Home Assistant is reloaded after the weekly charge
        completes, the system remembers not to restart the charging process.
        """
        if not self.weekly_full_charge_enabled:
            return

        try:
            data = await self._store.async_load()
            if data is None:
                _LOGGER.debug("Weekly Full Charge: No persisted state found")
                return

            from datetime import datetime

            now = datetime.now()
            current_weekday = now.weekday()
            target_weekday = WEEKDAY_MAP[self.weekly_full_charge_day]

            # Only restore state if we're still on the completion day
            stored_completion_day = data.get("completion_weekday")
            if stored_completion_day == current_weekday == target_weekday:
                self.weekly_full_charge_complete = data.get("complete", False)
                self.weekly_full_charge_registers_written = data.get("registers_written", False)
                # Restore delay state
                self._charge_delay_unlocked = data.get("delay_unlocked", False)
                self._solar_t_start = data.get("solar_t_start")
                _LOGGER.info("Weekly Full Charge: Restored state - complete=%s, registers_written=%s, delay_unlocked=%s",
                            self.weekly_full_charge_complete, self.weekly_full_charge_registers_written,
                            self._charge_delay_unlocked)
            else:
                _LOGGER.debug("Weekly Full Charge: Stored state is for different day - ignoring")

            # Always restore forecast data (captured night before, independent of day)
            stored_forecast = data.get("stored_forecast_kwh")
            stored_forecast_date = data.get("stored_forecast_date")
            if stored_forecast is not None and stored_forecast_date is not None:
                from datetime import date
                self._stored_solar_forecast_kwh = stored_forecast
                self._stored_solar_forecast_date = date.fromisoformat(stored_forecast_date)
                _LOGGER.debug("Weekly Full Charge: Restored forecast=%.2f kWh (date=%s)",
                             stored_forecast, stored_forecast_date)

        except Exception as e:
            _LOGGER.error("Weekly Full Charge: Failed to load persisted state: %s", e)

    async def _save_weekly_charge_state(self) -> None:
        """Save weekly charge completion state to persistent storage."""
        if not self.weekly_full_charge_enabled:
            return

        try:
            from datetime import datetime
            now = datetime.now()

            data = {
                "complete": self.weekly_full_charge_complete,
                "registers_written": self.weekly_full_charge_registers_written,
                "completion_weekday": now.weekday(),
                "timestamp": now.isoformat(),
                # Delay state
                "stored_forecast_kwh": self._stored_solar_forecast_kwh,
                "stored_forecast_date": self._stored_solar_forecast_date.isoformat() if self._stored_solar_forecast_date else None,
                "delay_unlocked": self._charge_delay_unlocked,
                "solar_t_start": self._solar_t_start,
            }

            await self._store.async_save(data)
            _LOGGER.debug("Weekly Full Charge: Saved state to storage")
        except Exception as e:
            _LOGGER.error("Weekly Full Charge: Failed to save state: %s", e)

    def _save_solar_t_start(self) -> None:
        """Fire-and-forget: persist solar_t_start alongside today's date."""
        from datetime import date
        asyncio.create_task(self._solar_t_start_store.async_save({
            "date": date.today().isoformat(),
            "t_start": self._solar_t_start,
        }))

    async def _load_solar_t_start(self) -> None:
        """Restore solar_t_start from storage if it was captured today."""
        try:
            data = await self._solar_t_start_store.async_load()
            if not data:
                return
            from datetime import date
            if data.get("date") == date.today().isoformat() and data.get("t_start") is not None:
                self._solar_t_start = data["t_start"]
                _LOGGER.info(
                    "Charge Delay: Restored solar T_start=%.2fh from storage (HA restart)",
                    self._solar_t_start,
                )
        except Exception as e:
            _LOGGER.error("Charge Delay: Failed to load solar T_start from storage: %s", e)

    # ---- Weekly Full Charge Delay Methods ----

    def _calculate_solar_noon(self) -> float:
        """Calculate local solar noon from HA longitude and timezone.

        Returns solar noon as a float hour (e.g. 13.25 = 13:15).
        Cached per day (recalculated when date changes to handle DST transitions).
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now().date()
        cache_attr = "_solar_noon_cache"
        cached = getattr(self, cache_attr, None)
        if cached is not None and cached[0] == today:
            return cached[1]

        tz = ZoneInfo(self.hass.config.time_zone)
        utc_offset = datetime.now(tz).utcoffset().total_seconds() / 3600
        solar_noon = 12.0 - (self.hass.config.longitude / 15.0) + utc_offset
        setattr(self, cache_attr, (today, solar_noon))
        _LOGGER.info(
            "Weekly Full Charge Delay: Solar noon calculated at %.2fh (longitude=%.2f, UTC offset=%.1f)",
            solar_noon, self.hass.config.longitude, utc_offset
        )
        return solar_noon

    def _calculate_sunrise(self) -> float | None:
        """Estimate local sunrise time from HA latitude/longitude and day of year.

        Uses the standard solar declination + hour-angle formula.
        Returns sunrise as a float hour (e.g. 7.5 = 07:30), or None if the
        sun never rises today (polar night) or if HA location is not configured.
        """
        import math
        from datetime import datetime

        try:
            latitude = self.hass.config.latitude
            if latitude is None:
                return None

            day_of_year = datetime.now().timetuple().tm_yday
            lat_rad = math.radians(latitude)

            # Solar declination (degrees → radians)
            declination_rad = math.radians(
                -23.45 * math.cos(math.radians(360 / 365 * (day_of_year + 10)))
            )

            # Hour angle at sunrise: cos(H) = -tan(lat) * tan(dec)
            cos_h = -math.tan(lat_rad) * math.tan(declination_rad)
            if cos_h < -1 or cos_h > 1:
                return None  # Polar day / polar night

            hour_angle_deg = math.degrees(math.acos(cos_h))
            solar_noon = self._calculate_solar_noon()
            return solar_noon - hour_angle_deg / 15.0
        except Exception:  # noqa: BLE001
            return None

    def _detect_solar_t_start(self) -> None:
        """Detect start of solar production via grid sensor and battery state.

        Primary: sets self._solar_t_start when grid_power <= 0 while batteries
        are not discharging, indicating solar is covering the full house load.

        Fallback: if the primary condition hasn't fired within 30 min after the
        astronomically estimated sunrise (high-consumption day where grid power
        never reaches zero), uses the estimated sunrise as t_start so the
        sinusoidal energy model can still run.

        Only checks after 7:00 to avoid false triggers from overnight grid charging.
        """
        if self._solar_t_start is not None:
            return  # Already detected today

        from datetime import datetime

        now = datetime.now()
        if now.hour < 7:
            return  # Too early, any export is likely from nocturnal grid charging

        now_h = now.hour + now.minute / 60.0

        # --- Primary: grid ≤ 0 and batteries not discharging ---
        grid_state = self.hass.states.get(self.consumption_sensor)
        if grid_state and grid_state.state not in ("unknown", "unavailable"):
            try:
                grid_power = float(grid_state.state)
                if grid_power <= 0:
                    total_battery_power = sum(
                        (c.data.get("battery_power", 0) or 0)
                        for c in self.coordinators if c.data
                    )
                    if total_battery_power <= 0:
                        self._solar_t_start = now_h
                        self._save_solar_t_start()
                        t_end = self._estimate_t_end()
                        _LOGGER.info(
                            "Charge Delay: Solar T_start detected via grid=%.0fW, battery=%.0fW "
                            "at %.2fh, estimated T_end=%.2fh",
                            grid_power, total_battery_power, self._solar_t_start, t_end
                        )
                        return
            except (ValueError, TypeError):
                pass

        # --- Fallback: astronomical sunrise + 30 min buffer ---
        estimated_sunrise = self._calculate_sunrise()
        if estimated_sunrise is not None and now_h >= estimated_sunrise + 0.5:
            self._solar_t_start = estimated_sunrise
            self._save_solar_t_start()
            t_end = self._estimate_t_end()
            _LOGGER.info(
                "Charge Delay: Solar T_start set via astronomical sunrise fallback "
                "(estimated=%.2fh, now=%.2fh, T_end=%.2fh)",
                estimated_sunrise, now_h, t_end
            )

    def _estimate_t_end(self) -> float:
        """Estimate end of solar production by symmetry around solar noon.

        Returns T_end as a float hour. Dynamically extends if batteries
        are still charging beyond the estimated T_end.
        """
        from datetime import datetime

        solar_noon = self._calculate_solar_noon()
        t_end = 2 * solar_noon - self._solar_t_start

        # Dynamic extension: if current time is past T_end but batteries still charging
        now = datetime.now()
        now_h = now.hour + now.minute / 60.0
        if now_h > t_end:
            any_charging = any(
                (c.data.get("battery_power", 0) or 0) > 0
                for c in self.coordinators if c.data
            )
            if any_charging:
                extended_t_end = now_h + 1.0
                _LOGGER.debug(
                    "Weekly Full Charge Delay: Extended T_end from %.2fh to %.2fh (active production)",
                    t_end, extended_t_end
                )
                return extended_t_end

        return t_end

    @staticmethod
    def _h_to_hhmm(h: float | None) -> str | None:
        """Convert decimal hours to HH:MM string."""
        if h is None:
            return None
        hours = int(h)
        minutes = int((h - hours) * 60)
        return f"{hours:02d}:{minutes:02d}"

    @staticmethod
    def _get_solar_fraction_done(now_h: float, t_start: float, t_end: float) -> float:
        """Calculate cumulative fraction of daily solar energy produced by now.

        Uses sinusoidal model: F(t) = [1 - cos(π × (t - t_start) / (t_end - t_start))] / 2
        Returns value clamped to [0, 1].
        """
        import math

        if t_end <= t_start:
            return 1.0  # Invalid window, assume all produced

        if now_h <= t_start:
            return 0.0
        if now_h >= t_end:
            return 1.0

        progress = (now_h - t_start) / (t_end - t_start)
        fraction = (1.0 - math.cos(math.pi * progress)) / 2.0
        return max(0.0, min(1.0, fraction))

    def _get_today_target_soc(self) -> int:
        """Get today's charge target SOC.

        On weekly full charge day → 100.
        Otherwise → average max_soc across batteries.
        """
        if self._is_weekly_full_charge_active():
            return 100

        if self.coordinators:
            return round(sum(c.max_soc for c in self.coordinators) / len(self.coordinators))
        return 100

    def _is_charge_delayed(self) -> bool:
        """Unified gate: check if charging should be delayed based on solar forecast.

        Returns True if charging should be blocked, False if allowed.
        Called from _is_operation_allowed() for every charge attempt.
        """
        if not self.charge_delay_enabled:
            self._charge_delay_status["state"] = "Disabled"
            return False

        # Already unlocked today?
        if self._charge_delay_unlocked:
            self._charge_delay_status["state"] = "Charging allowed"
            return False

        target_soc = self._get_today_target_soc()
        self._charge_delay_status["target_soc"] = target_soc

        # Evaluate delay conditions
        if self._should_delay_charge(target_soc):
            return True  # Keep delay active (block charging)

        # Delay conditions no longer met - unlock permanently for today
        self._charge_delay_unlocked = True
        _LOGGER.info("Charge Delay: Unlocked (target_soc=%d%%) - charging now allowed", target_soc)
        # Persist unlock state if on weekly charge day
        if self._is_weekly_full_charge_active():
            asyncio.create_task(self._save_weekly_charge_state())
        return False

    def _should_delay_charge(self, target_soc: int) -> bool:
        """Determine if charging should be delayed based on solar forecast.

        Unified method for both daily (max_soc) and weekly (100%) charge delay.
        Uses stored forecast from the night before (captured at 23:00).

        Returns True to keep delay active (block charging),
        False to unlock charging.

        Fail-safe: any failure → unlock (allow charging).

        Decision flow:
        1. No valid stored forecast → unlock immediately
        2. Low forecast (<1.5× capacity) → unlock (bad solar day)
        3. No T_start detected and past fallback hour → unlock
        4. Past T_end with no active production → unlock
        5. Batteries already at target → unlock
        6. Insufficient remaining solar energy → unlock
        7. Insufficient time before T_end → unlock
        8. Otherwise → keep delay active
        """
        from datetime import datetime
        from time import monotonic

        now = datetime.now()
        now_h = now.hour + now.minute / 60.0
        status = self._charge_delay_status
        _h_to_hhmm = self._h_to_hhmm

        def _unlock(reason):
            """Set status and return False (unlock)."""
            status["unlock_reason"] = reason
            status["state"] = f"Unlocking ({reason})"
            return False

        # Update common status fields
        status["forecast_kwh"] = self._stored_solar_forecast_kwh_raw
        status["solar_t_start"] = _h_to_hhmm(self._solar_t_start)

        # --- Exception 1: No valid stored forecast ---
        if self._stored_solar_forecast_kwh is None or self._stored_solar_forecast_date is None:
            _LOGGER.info("Charge Delay: No stored forecast - unlocking (reason: no_forecast)")
            return _unlock("no_forecast")

        # Validate forecast date is from yesterday (captured night before)
        today = now.date()
        from datetime import timedelta as td
        yesterday = today - td(days=1)
        if self._stored_solar_forecast_date != yesterday:
            _LOGGER.info(
                "Charge Delay: Forecast date mismatch (stored=%s, expected=%s) - unlocking",
                self._stored_solar_forecast_date, yesterday
            )
            return _unlock("no_forecast")

        forecast_today = self._stored_solar_forecast_kwh

        # --- Exception 2: Low forecast (bad solar day) ---
        total_capacity_kwh = sum(
            c.data.get("battery_total_energy", 0) for c in self.coordinators if c.data
        )
        if total_capacity_kwh <= 0:
            _LOGGER.info("Charge Delay: Invalid battery capacity - unlocking")
            return _unlock("no_forecast")

        if forecast_today < LOW_FORECAST_THRESHOLD_FACTOR * total_capacity_kwh:
            _LOGGER.info(
                "Charge Delay: Low forecast (%.1f kWh < %.1f × %.1f kWh) - unlocking (reason: low_forecast)",
                forecast_today, LOW_FORECAST_THRESHOLD_FACTOR, total_capacity_kwh
            )
            return _unlock("low_forecast")

        # --- Exception 3: No T_start detected ---
        if self._solar_t_start is None:
            if now_h > T_START_FALLBACK_HOUR:
                _LOGGER.info(
                    "Charge Delay: No solar production by %.0f:00 - unlocking (reason: no_t_start)",
                    T_START_FALLBACK_HOUR
                )
                return _unlock("no_t_start")
            # Still waiting for solar production
            status["state"] = "Waiting for solar"
            return True

        # --- Get T_end ---
        t_end = self._estimate_t_end()
        status["solar_t_end"] = _h_to_hhmm(t_end)

        # --- Exception 4: Past T_end with no active production ---
        if now_h >= t_end:
            any_charging = any(
                (c.data.get("battery_power", 0) or 0) > 0
                for c in self.coordinators if c.data
            )
            if not any_charging:
                _LOGGER.info("Charge Delay: Past T_end (%.2fh) with no production - unlocking", t_end)
                return _unlock("past_t_end")

        # --- Calculate energy balance ---
        # Energy needed to reach target_soc
        energy_needed_kwh = sum(
            (target_soc - c.data.get("battery_soc", 100)) / 100.0 * c.data.get("battery_total_energy", 0)
            for c in self.coordinators if c.data
        )

        if energy_needed_kwh <= 0:
            return _unlock("batteries_full")

        # Charge time estimate
        max_charge_power_kw = sum(c.max_charge_power for c in self.coordinators) / 1000.0
        if max_charge_power_kw <= 0:
            return _unlock("no_charge_power")
        charge_time_h = energy_needed_kwh / (max_charge_power_kw * CHARGE_EFFICIENCY)

        # Remaining solar and consumption
        solar_fraction_done = self._get_solar_fraction_done(now_h, self._solar_t_start, t_end)
        remaining_solar_kwh = forecast_today * (1.0 - solar_fraction_done)

        hours_to_t_end = max(0, t_end - now_h)
        daylight_hours = t_end - self._solar_t_start
        if daylight_hours > 0:
            avg_consumption = self._get_avg_daily_consumption()
            remaining_consumption_kwh = (avg_consumption / daylight_hours) * hours_to_t_end
        else:
            remaining_consumption_kwh = 0

        net_solar_for_battery = remaining_solar_kwh - remaining_consumption_kwh

        # Time backup check
        safety_margin_h = self._delay_safety_margin_h
        time_limit_reached = (now_h + charge_time_h + safety_margin_h) >= t_end
        energy_insufficient = net_solar_for_battery < (energy_needed_kwh * DELAY_SAFETY_FACTOR)

        # Update status with calculation details
        status["energy_needed_kwh"] = round(energy_needed_kwh, 2)
        status["remaining_solar_kwh"] = round(remaining_solar_kwh, 2)
        status["remaining_consumption_kwh"] = round(remaining_consumption_kwh, 2)
        status["net_solar_kwh"] = round(net_solar_for_battery, 2)
        status["charge_time_h"] = round(charge_time_h, 2)

        # Estimate unlock time: earliest of time-backup and energy-balance triggers
        time_backup_unlock_h = t_end - charge_time_h - safety_margin_h
        energy_balance_unlock_h = self._estimate_energy_balance_unlock_h(
            forecast_today, energy_needed_kwh, self._solar_t_start, t_end, now_h
        )
        if energy_balance_unlock_h is not None:
            est_unlock_h = min(time_backup_unlock_h, energy_balance_unlock_h)
        else:
            est_unlock_h = time_backup_unlock_h
        status["estimated_unlock_time"] = _h_to_hhmm(max(now_h, est_unlock_h))

        # Throttled logging (every 5 minutes)
        current_time = monotonic()
        if current_time - self._delay_last_log_time >= 300:
            self._delay_last_log_time = current_time
            _LOGGER.info(
                "Charge Delay (target=%d%%): Solar remaining=%.1f kWh, Consumption remaining=%.1f kWh, "
                "Net for battery=%.1f kWh, Needed=%.1f kWh (×%.1f=%.1f), "
                "Charge time=%.1fh, Hours to T_end=%.1fh → %s",
                target_soc, remaining_solar_kwh, remaining_consumption_kwh,
                net_solar_for_battery, energy_needed_kwh,
                DELAY_SAFETY_FACTOR, energy_needed_kwh * DELAY_SAFETY_FACTOR,
                charge_time_h, hours_to_t_end,
                "KEEP DELAY" if not energy_insufficient and not time_limit_reached else "UNLOCK"
            )

        if energy_insufficient:
            _LOGGER.info(
                "Charge Delay: Insufficient solar (net=%.1f < needed=%.1f) - unlocking (reason: energy_balance)",
                net_solar_for_battery, energy_needed_kwh * DELAY_SAFETY_FACTOR
            )
            return _unlock("energy_balance")

        if time_limit_reached:
            _LOGGER.info(
                "Charge Delay: Time limit (%.2f + %.2f + %.2f = %.2f >= T_end %.2f) - unlocking (reason: time_backup)",
                now_h, charge_time_h, safety_margin_h,
                now_h + charge_time_h + safety_margin_h, t_end
            )
            return _unlock("time_backup")

        # All checks passed - keep delay active
        status["state"] = f"Delayed ({status['estimated_unlock_time']} est.)"
        return True

    def _get_avg_daily_consumption(self) -> float:
        """Get average daily consumption from history, with fallback."""
        if self._daily_consumption_history:
            total = sum(c for _, c in self._daily_consumption_history)
            return total / len(self._daily_consumption_history)
        return DEFAULT_BASE_CONSUMPTION_KWH

    def _estimate_energy_balance_unlock_h(
        self,
        forecast_kwh: float,
        energy_needed_kwh: float,
        t_start: float,
        t_end: float,
        now_h: float,
    ) -> float | None:
        """Estimate when the energy balance condition will trigger the delay unlock.

        Binary-searches for the earliest time t >= now_h where:
          remaining_solar(t) - remaining_consumption(t) < energy_needed × DELAY_SAFETY_FACTOR

        Returns the estimated hour as float, or None if it cannot be estimated.
        """
        import math

        daylight_hours = t_end - t_start
        if daylight_hours <= 0:
            return None

        avg_consumption = self._get_avg_daily_consumption()
        k = avg_consumption / daylight_hours  # kWh consumed per hour
        threshold = energy_needed_kwh * DELAY_SAFETY_FACTOR

        def net_solar_at(t: float) -> float:
            """Net solar available for battery at time t."""
            progress = max(0.0, min(1.0, (t - t_start) / daylight_hours))
            fraction_done = (1.0 - math.cos(math.pi * progress)) / 2.0
            remaining_solar = forecast_kwh * (1.0 - fraction_done)
            remaining_consumption = k * max(0.0, t_end - t)
            return remaining_solar - remaining_consumption

        # If already below threshold now, return now_h
        if net_solar_at(now_h) < threshold:
            return now_h

        # If still above threshold at t_end, no energy-balance unlock expected
        if net_solar_at(t_end) >= threshold:
            return None

        # Binary search for crossing point
        lo, hi = now_h, t_end
        for _ in range(40):  # 40 iterations → precision < 1 second
            mid = (lo + hi) / 2.0
            if net_solar_at(mid) >= threshold:
                lo = mid
            else:
                hi = mid

        return (lo + hi) / 2.0

    async def _capture_solar_forecast(self, _now=None) -> None:
        """Capture solar forecast every night at 23:00 for next day's charge delay.

        The forecast sensor shows tomorrow's value at this hour (before midnight reset).
        Stored forecast is used by _should_delay_charge() the next morning.
        """
        from datetime import datetime

        if not self.solar_forecast_sensor:
            _LOGGER.warning("Charge Delay: No solar forecast sensor configured - delay won't work")
            return

        forecast_state = self.hass.states.get(self.solar_forecast_sensor)
        if forecast_state is None:
            _LOGGER.warning("Charge Delay: Solar forecast sensor '%s' not found", self.solar_forecast_sensor)
            return

        try:
            forecast_value = float(forecast_state.state)
        except (ValueError, TypeError):
            _LOGGER.error("Charge Delay: Invalid forecast value '%s'", forecast_state.state)
            return

        now = datetime.now()
        self._stored_solar_forecast_kwh_raw = forecast_value
        self._stored_solar_forecast_kwh = forecast_value * 0.85  # 15% conservative correction
        self._stored_solar_forecast_date = now.date()
        _LOGGER.info(
            "Charge Delay: Captured solar forecast: %.2f kWh (raw=%.2f kWh, -15%% correction) for tomorrow",
            self._stored_solar_forecast_kwh, forecast_value
        )

        # Persist to store
        await self._save_weekly_charge_state()

    async def _handle_weekly_full_charge_registers(self) -> None:
        """
        Manage weekly full charge register writes and completion detection.

        This runs independently of control mode (predictive/normal) to ensure
        hardware registers are properly configured when weekly charge is active.

        Responsibilities:
        - Write register 44000 to 100% on first activation (v2 only)
        - Detect completion (all batteries at 100%)
        - Restore register 44000 to configured max_soc when complete
        - Re-enable hysteresis after completion
        """
        if not self.weekly_full_charge_enabled and not self._force_full_charge:
            return
        if not self._is_weekly_full_charge_active():
            return

        # Check if unified charge delay is active - if so, don't write registers yet
        # Skip delay logic when force button was pressed
        if self.charge_delay_enabled and not self._charge_delay_unlocked and not self._force_full_charge:
            return  # Delay is handled by _is_charge_delayed() in _is_operation_allowed()

        # Write register 44000 to 100% on first activation (v2 only - v3 uses software enforcement)
        if not self.weekly_full_charge_registers_written:
            _LOGGER.info("Weekly Full Charge: Activating for compatible batteries")
            for coordinator in self.coordinators:
                cutoff_reg = coordinator.get_register("charging_cutoff_capacity")

                if cutoff_reg is None:
                    _LOGGER.warning(
                        "%s: Weekly full charge - no hardware cutoff register (v3 battery). "
                        "Using software enforcement to 100%%.",
                        coordinator.name
                    )
                    # v3 batteries: software enforcement will allow charging to 100%
                    # since effective_max_soc is set to 100 when weekly charge is active
                    continue

                # v2 batteries: write hardware register
                try:
                    # Write 1000 to register 44000 (100% = 1000 in register scale)
                    await coordinator.write_register(cutoff_reg, 1000, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.debug("%s: Set hardware charging cutoff to 100%%", coordinator.name)
                except Exception as e:
                    _LOGGER.error("%s: Failed to write charging cutoff register: %s", coordinator.name, e)

            self.weekly_full_charge_registers_written = True
            self._weekly_charge_status["state"] = "Charging to 100%"

        # Check if all batteries reached 100%
        all_batteries_full = all(
            c.data.get("battery_soc", 0) >= 100
            for c in self.coordinators if c.data
        )

        if all_batteries_full and not self.weekly_full_charge_complete:
            # All batteries just reached 100% - mark as complete
            _LOGGER.info("Weekly Full Charge: Complete - reverting to configured limits")
            self.weekly_full_charge_complete = True
            self._weekly_charge_status["state"] = "Complete"

            # Restore register 44000 to original max_soc values (v2 only)
            for coordinator in self.coordinators:
                cutoff_reg = coordinator.get_register("charging_cutoff_capacity")

                if cutoff_reg is None:
                    _LOGGER.debug("%s: No hardware cutoff register to restore (v3 battery)", coordinator.name)
                    # v3: software enforcement automatically reverts to max_soc
                    continue

                # v2: restore hardware register
                try:
                    max_soc_value = int(coordinator.max_soc / 0.1)  # Convert to register value
                    await coordinator.write_register(cutoff_reg, max_soc_value, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.debug("%s: Restored hardware cutoff to %d%% (reg=%d)",
                                coordinator.name, coordinator.max_soc, max_soc_value)
                except Exception as e:
                    _LOGGER.error("%s: Failed to restore charging cutoff register: %s", coordinator.name, e)

            # Re-enable hysteresis for batteries that have it configured
            for coordinator in self.coordinators:
                if coordinator.enable_charge_hysteresis:
                    coordinator._hysteresis_active = True
                    _LOGGER.debug("%s: Re-enabled hysteresis after weekly full charge", coordinator.name)

            # Persist the completion state so it survives HA restarts
            await self._save_weekly_charge_state()

    def _round_to_5w(self, value: float) -> int:
        """Round value to nearest 5W granularity."""
        return round(value / 5) * 5
    
    def reset_pid_state(self):
        """Manually reset PID controller state. Useful when system is unstable."""
        _LOGGER.warning("PID: MANUAL RESET requested - clearing all PID state variables")
        _LOGGER.info("PID: Previous state - integral=%.1fW (%.1f%%), previous_error=%.1fW, sign_changes=%d",
                    self.error_integral, 
                    (abs(self.error_integral) / max(self.max_charge_capacity, self.max_discharge_capacity)) * 100,
                    self.previous_error, self.sign_changes)
        
        self.error_integral = 0.0
        self.previous_error = 0.0
        self.sign_changes = 0
        self.last_error_sign = 0
        self.last_output_sign = 0
        self.previous_power = 0
        self.sensor_history.clear()
        self.first_execution = True  # Force re-initialization on next cycle
        
        _LOGGER.info("PID: State reset complete - system will re-initialize on next control cycle")

    async def _save_consumption_history(self) -> None:
        """Persist consumption history to disk via HA Store."""
        try:
            data = {
                "history": [
                    (d.isoformat(), c) for d, c in self._daily_consumption_history
                ]
            }
            await self._consumption_store.async_save(data)
        except Exception as e:
            _LOGGER.error("Failed to save consumption history: %s", e)

    async def _load_consumption_history(self) -> bool:
        """Load consumption history from HA Store. Returns True if data was loaded."""
        from datetime import date
        try:
            data = await self._consumption_store.async_load()
            if data and "history" in data and data["history"]:
                self._daily_consumption_history = [
                    (date.fromisoformat(date_str), consumption)
                    for date_str, consumption in data["history"]
                ]
                _LOGGER.info(
                    "Loaded consumption history from store: %d days (oldest: %s, newest: %s)",
                    len(self._daily_consumption_history),
                    self._daily_consumption_history[0][0] if self._daily_consumption_history else "N/A",
                    self._daily_consumption_history[-1][0] if self._daily_consumption_history else "N/A"
                )
                return True
            _LOGGER.debug("No consumption history found in store")
            return False
        except Exception as e:
            _LOGGER.warning("Failed to load consumption history from store: %s", e)
            return False

    async def _get_dynamic_base_consumption(self) -> float:
        """Get dynamic base consumption from 7-day average of daily discharge.

        Uses the daily discharging energy sensor which resets every 24 hours.
        Daily values are automatically captured at 23:55 by scheduled task.
        This method performs opportunistic backfill from history if needed.
        """
        from datetime import date, datetime, timedelta

        today = date.today()
        entity_id = "sensor.marstek_venus_system_daily_discharging_energy"

        # OPPORTUNISTIC BACKFILL: Replace default entries with real data from HA history
        # This recovers real data after restarts or when defaults were pre-populated
        real_data_dates = {d for d, c in self._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH}
        if len(real_data_dates) < 7:
            for days_ago in range(1, 8):  # Look back 7 days (excluding today)
                past_date = today - timedelta(days=days_ago)
                if past_date not in real_data_dates:
                    # Try to capture this missing day from history
                    await self._capture_from_history(entity_id, past_date)
                    await asyncio.sleep(0.1)  # Small delay between history queries

        # Calculate average from history
        if len(self._daily_consumption_history) == 0:
            _LOGGER.warning(
                "No consumption history, using fallback: %.1f kWh",
                DEFAULT_BASE_CONSUMPTION_KWH
            )
            return DEFAULT_BASE_CONSUMPTION_KWH

        total = sum(consumption for _, consumption in self._daily_consumption_history)
        average = total / len(self._daily_consumption_history)

        if average <= 0:
            _LOGGER.warning(
                "Average consumption is 0, using fallback: %.1f kWh",
                DEFAULT_BASE_CONSUMPTION_KWH
            )
            return DEFAULT_BASE_CONSUMPTION_KWH

        real_count = sum(1 for _, c in self._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH)
        _LOGGER.info(
            "Dynamic base consumption: %.1f kWh (avg of %d days, %d real + %d defaults)",
            average, len(self._daily_consumption_history),
            real_count, len(self._daily_consumption_history) - real_count
        )

        return average

    async def _capture_from_history(self, entity_id: str, target_date: date) -> None:
        """Capture daily consumption from HA history for a specific date.

        Gets the maximum value from the target date (final reading before reset).

        Args:
            entity_id: Entity ID of the daily sensor
            target_date: Date to capture data for
        """
        from datetime import date, datetime, timedelta
        from homeassistant.util import dt as dt_util

        try:
            from homeassistant.components.recorder import history
        except ImportError:
            _LOGGER.warning("Recorder history module not available for backfill")
            return

        # Define time range for the target date in local timezone
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC
        start_time = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)
        end_time = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=local_tz)

        _LOGGER.debug(
            "Backfill attempt: entity=%s, date=%s, range=%s to %s",
            entity_id, target_date, start_time, end_time
        )

        try:
            # Get history for the entity using the recorder's own executor
            from homeassistant.components.recorder import get_instance
            recorder_instance = get_instance(self.hass)
            states = await recorder_instance.async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                start_time,
                end_time,
                entity_id
            )

            if entity_id not in states or len(states[entity_id]) == 0:
                _LOGGER.debug("No history found for %s on %s", entity_id, target_date)
                return

            # Find the maximum value (final reading before reset)
            max_value = 0.0
            state_count = 0
            for state in states[entity_id]:
                state_count += 1
                if state.state not in ['unknown', 'unavailable']:
                    try:
                        value = float(state.state)
                        max_value = max(max_value, value)
                    except (ValueError, TypeError):
                        continue

            _LOGGER.debug(
                "Backfill query result: %d states found, max_value=%.2f for %s on %s",
                state_count, max_value, entity_id, target_date
            )

            if max_value >= 1.5:
                # Replace existing entry for this date (including defaults) or append
                replaced = False
                for i, (d, c) in enumerate(self._daily_consumption_history):
                    if d == target_date:
                        self._daily_consumption_history[i] = (target_date, max_value)
                        replaced = True
                        break
                if not replaced:
                    self._daily_consumption_history.append((target_date, max_value))

                _LOGGER.info(
                    "Captured daily consumption from history: %.1f kWh for %s (%s, history: %d days)",
                    max_value, target_date,
                    "replaced default" if replaced else "new entry",
                    len(self._daily_consumption_history)
                )

                # Cleanup: keep only last 7 days
                cutoff_date = date.today() - timedelta(days=7)
                self._daily_consumption_history = [
                    (d, c) for d, c in self._daily_consumption_history
                    if d > cutoff_date
                ]
        except Exception as e:
            _LOGGER.error("Failed to capture from history for %s on %s: %s", entity_id, target_date, e)

    async def _startup_backfill_consumption(self) -> None:
        """Run backfill from recorder history shortly after startup.

        Called once after a delay to give the recorder and coordinators time
        to initialize. Replaces default entries with real historical data.
        """
        from datetime import date, timedelta

        if not self.predictive_charging_enabled:
            return

        entity_id = "sensor.marstek_venus_system_daily_discharging_energy"
        today = date.today()

        _LOGGER.info(
            "Startup backfill: attempting to replace defaults with real data "
            "(current history: %d entries, %d real)",
            len(self._daily_consumption_history),
            sum(1 for _, c in self._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH)
        )

        # Also capture today's running total from coordinators if available
        coordinators_with_data = [c for c in self.coordinators if c.data]
        if coordinators_with_data:
            today_value = sum(
                c.data.get("total_daily_discharging_energy", 0)
                for c in coordinators_with_data
            )
            if today_value >= 1.5:
                # Replace today's default with current running total
                for i, (d, c) in enumerate(self._daily_consumption_history):
                    if d == today:
                        if c == DEFAULT_BASE_CONSUMPTION_KWH:
                            self._daily_consumption_history[i] = (today, today_value)
                            _LOGGER.info(
                                "Startup backfill: replaced today's default with current value: %.2f kWh",
                                today_value
                            )
                        break

        # Try to backfill past days from recorder history
        real_data_dates = {d for d, c in self._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH}
        backfill_count = 0
        for days_ago in range(1, 8):
            past_date = today - timedelta(days=days_ago)
            if past_date not in real_data_dates:
                await self._capture_from_history(entity_id, past_date)
                await asyncio.sleep(0.1)
                backfill_count += 1

        real_after = sum(1 for _, c in self._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH)
        _LOGGER.info(
            "Startup backfill complete: attempted %d days, now %d real entries out of %d total",
            backfill_count, real_after, len(self._daily_consumption_history)
        )

        # Persist updated history to disk
        await self._save_consumption_history()

    def _initialize_consumption_history_with_defaults(self) -> None:
        """Initialize consumption history with default values for the past 7 days.

        This provides an immediate 7-day average on first use, using the fallback
        consumption value. Real data will gradually replace these estimates as days pass.

        Only initializes if history is completely empty (first-time setup).
        """
        from datetime import date, timedelta

        # Only initialize if history is empty
        if len(self._daily_consumption_history) > 0:
            return

        _LOGGER.info(
            "Initializing consumption history with default values (%.1f kWh per day)",
            DEFAULT_BASE_CONSUMPTION_KWH
        )

        today = date.today()

        # Pre-populate with 7 days of fallback values (6 days ago through today)
        for days_ago in range(6, -1, -1):
            past_date = today - timedelta(days=days_ago)
            self._daily_consumption_history.append((past_date, DEFAULT_BASE_CONSUMPTION_KWH))

        _LOGGER.info(
            "Pre-populated consumption history with %d days of default values",
            len(self._daily_consumption_history)
        )

    async def _capture_daily_consumption(self, now=None) -> None:
        """Scheduled task to capture daily battery consumption.

        Runs daily at 23:55 to capture the day's accumulated discharge energy
        before the sensor resets at midnight. This ensures we always have
        historical data for predictive charging calculations.

        Reads directly from coordinator data (Modbus registers) to avoid
        dependency on entity_id naming.

        Args:
            now: Timestamp from scheduler (unused, for compatibility)
        """
        from datetime import date, timedelta

        if not self.predictive_charging_enabled:
            return  # Don't capture if predictive charging is disabled

        today = date.today()

        # Read directly from coordinator data (sum across all batteries)
        coordinators_with_data = [c for c in self.coordinators if c.data]
        if not coordinators_with_data:
            _LOGGER.warning("Daily consumption capture: no coordinators with data available")
            return

        try:
            current_value = sum(
                c.data.get("total_daily_discharging_energy", 0)
                for c in coordinators_with_data
            )

            # Only capture if we have meaningful data (>= 1.5 kWh)
            if current_value < 1.5:
                _LOGGER.warning(
                    "Daily consumption capture: value too low (%.2f kWh), skipping",
                    current_value
                )
                return

            # Check if today's data already exists
            has_today = any(d == today for d, _ in self._daily_consumption_history)

            if has_today:
                # Update today's value (replace with latest reading)
                self._daily_consumption_history = [
                    (d, current_value if d == today else c)
                    for d, c in self._daily_consumption_history
                ]
                _LOGGER.info(
                    "Daily consumption capture: UPDATED today's value: %.2f kWh (%d days in history)",
                    current_value, len(self._daily_consumption_history)
                )
            else:
                # Add today's value
                self._daily_consumption_history.append((today, current_value))
                _LOGGER.info(
                    "Daily consumption capture: CAPTURED today's value: %.2f kWh (%d days in history)",
                    current_value, len(self._daily_consumption_history)
                )

                # Cleanup: keep only last 7 days
                cutoff_date = today - timedelta(days=7)
                self._daily_consumption_history = [
                    (d, c) for d, c in self._daily_consumption_history
                    if d > cutoff_date
                ]

            # Persist updated history to disk
            await self._save_consumption_history()

        except (ValueError, TypeError) as e:
            _LOGGER.error("Daily consumption capture: Failed to parse sensor value: %s", e)

    async def _should_activate_grid_charging(self) -> dict:
        """
        Evaluate whether to activate grid charging using energy balance approach.

        Formula: charge if (usable_energy + solar_forecast) < consumption

        Where:
        - usable_energy = stored_energy - cutoff_energy
        - stored_energy = (avg_soc / 100) × total_capacity
        - cutoff_energy = (min_soc / 100) × total_capacity
        - min_reserve = usable_energy (dynamic buffer above hardware cutoff)

        The hardware discharge cutoff is used directly with no safety margin.

        Returns:
            dict with 12 fields:
                "should_charge": bool,
                "solar_forecast_kwh": float | None,
                "stored_energy_kwh": float,
                "usable_energy_kwh": float,
                "min_reserve_kwh": float,
                "cutoff_energy_kwh": float,
                "effective_min_soc": float,
                "avg_soc": float,
                "avg_consumption_kwh": float,
                "total_available_kwh": float,
                "energy_deficit_kwh": float,
                "days_in_history": int,
                "reason": str
        """
        if not self.predictive_charging_enabled:
            return {
                "should_charge": False,
                "solar_forecast_kwh": None,
                "stored_energy_kwh": 0,
                "usable_energy_kwh": 0,
                "min_reserve_kwh": 0,
                "cutoff_energy_kwh": 0,
                "effective_min_soc": 0,
                "avg_soc": 0,
                "avg_consumption_kwh": 0,
                "total_available_kwh": 0,
                "energy_deficit_kwh": 0,
                "days_in_history": 0,
                "reason": "Predictive charging disabled"
            }

        # Guard against empty or invalid coordinators
        coordinators_with_data = [c for c in self.coordinators if c.data]
        if not coordinators_with_data:
            _LOGGER.error("No battery coordinators with valid data for predictive charging evaluation")
            return {
                "should_charge": False,
                "solar_forecast_kwh": None,
                "stored_energy_kwh": 0,
                "usable_energy_kwh": 0,
                "min_reserve_kwh": 0,
                "cutoff_energy_kwh": 0,
                "effective_min_soc": 0,
                "avg_soc": 0,
                "avg_consumption_kwh": 0,
                "total_available_kwh": 0,
                "energy_deficit_kwh": 0,
                "days_in_history": 0,
                "reason": "No battery data available"
            }

        # === STEP 3: Calculate Energy Balance ===
        # Get battery configuration
        total_capacity_kwh = sum(c.data.get("battery_total_energy", 0) for c in coordinators_with_data)
        if total_capacity_kwh <= 0:
            _LOGGER.error(
                "Invalid total battery capacity (%.2f kWh) - cannot evaluate predictive charging",
                total_capacity_kwh
            )
            return {
                "should_charge": False,
                "solar_forecast_kwh": None,
                "stored_energy_kwh": 0,
                "usable_energy_kwh": 0,
                "min_reserve_kwh": 0,
                "cutoff_energy_kwh": 0,
                "effective_min_soc": 0,
                "avg_soc": 0,
                "avg_consumption_kwh": 0,
                "total_available_kwh": 0,
                "energy_deficit_kwh": 0,
                "days_in_history": 0,
                "reason": f"Invalid battery capacity: {total_capacity_kwh:.2f} kWh"
            }
        avg_soc = sum(c.data.get("battery_soc", 0) for c in coordinators_with_data) / len(coordinators_with_data)

        # Get min_soc from coordinators (use max if mixed configs for safety)
        min_soc_values = [c.min_soc for c in self.coordinators]
        min_soc = max(min_soc_values) if min_soc_values else 20  # Default 20% if unavailable

        # Calculate energy components
        stored_energy_kwh = (avg_soc / 100) * total_capacity_kwh
        cutoff_energy_kwh = (min_soc / 100) * total_capacity_kwh
        usable_energy_kwh = max(0, stored_energy_kwh - cutoff_energy_kwh)
        min_reserve_kwh = usable_energy_kwh  # Dynamic buffer: 0 at cutoff, positive above
        effective_min_soc = min_soc  # Actual hardware cutoff, no safety margin

        # Get dynamic consumption forecast
        avg_consumption_kwh = await self._get_dynamic_base_consumption()
        days_in_history = len(self._daily_consumption_history)

        # === STEP 4: Get Solar Forecast ===
        forecast_state = self.hass.states.get(self.solar_forecast_sensor)
        if forecast_state is None or forecast_state.state in ("unknown", "unavailable"):
            # Conservative mode: assume zero solar, compare usable vs consumption
            total_available_kwh = usable_energy_kwh
            energy_deficit_kwh = avg_consumption_kwh - total_available_kwh
            should_charge = energy_deficit_kwh > 0

            _LOGGER.warning(
                "Solar forecast unavailable - using conservative mode:\n"
                "  Battery: %.2f kWh stored (%.1f%% SOC), %.2f kWh usable (cutoff: %.1f%%, locked: %.2f kWh)\n"
                "  Consumption: %.2f kWh expected\n"
                "  → Decision: %s (deficit: %.2f kWh)",
                stored_energy_kwh, avg_soc, usable_energy_kwh, min_soc, cutoff_energy_kwh,
                avg_consumption_kwh,
                "ACTIVATE CHARGING" if should_charge else "NO CHARGING NEEDED",
                energy_deficit_kwh
            )

            return {
                "should_charge": should_charge,
                "solar_forecast_kwh": None,
                "stored_energy_kwh": stored_energy_kwh,
                "usable_energy_kwh": usable_energy_kwh,
                "min_reserve_kwh": min_reserve_kwh,
                "cutoff_energy_kwh": cutoff_energy_kwh,
                "effective_min_soc": effective_min_soc,
                "avg_soc": avg_soc,
                "avg_consumption_kwh": avg_consumption_kwh,
                "total_available_kwh": total_available_kwh,
                "energy_deficit_kwh": energy_deficit_kwh,
                "days_in_history": days_in_history,
                "reason": f"Solar unavailable - conservative mode ({'charge' if should_charge else 'safe'})"
            }

        try:
            solar_forecast_kwh = float(forecast_state.state)
        except (ValueError, TypeError):
            # Treat invalid as unavailable - use same conservative logic
            total_available_kwh = usable_energy_kwh
            energy_deficit_kwh = avg_consumption_kwh - total_available_kwh
            should_charge = energy_deficit_kwh > 0

            _LOGGER.error(
                "Invalid solar forecast value '%s' - using conservative mode:\n"
                "  Battery: %.2f kWh usable\n"
                "  Consumption: %.2f kWh expected\n"
                "  → Decision: %s",
                forecast_state.state,
                usable_energy_kwh,
                avg_consumption_kwh,
                "ACTIVATE CHARGING" if should_charge else "NO CHARGING NEEDED"
            )

            return {
                "should_charge": should_charge,
                "solar_forecast_kwh": None,
                "stored_energy_kwh": stored_energy_kwh,
                "usable_energy_kwh": usable_energy_kwh,
                "min_reserve_kwh": min_reserve_kwh,
                "cutoff_energy_kwh": cutoff_energy_kwh,
                "effective_min_soc": effective_min_soc,
                "avg_soc": avg_soc,
                "avg_consumption_kwh": avg_consumption_kwh,
                "total_available_kwh": total_available_kwh,
                "energy_deficit_kwh": energy_deficit_kwh,
                "days_in_history": days_in_history,
                "reason": "Invalid solar forecast - conservative mode"
            }

        # === STEP 6: Calculate Energy Balance and Decide ===
        total_available_kwh = usable_energy_kwh + solar_forecast_kwh
        energy_deficit_kwh = avg_consumption_kwh - total_available_kwh
        should_charge = energy_deficit_kwh > 0

        _LOGGER.info(
            "Predictive Grid Charging Evaluation (Energy Balance):\n"
            "  Battery Status:\n"
            "    - Total capacity: %.2f kWh\n"
            "    - Current SOC: %.1f%% (%.2f kWh stored)\n"
            "    - Discharge cutoff: %.1f%% (%.2f kWh locked)\n"
            "    - Usable reserve: %.2f kWh (above cutoff)\n"
            "  Energy Balance:\n"
            "    - Solar forecast: %.2f kWh\n"
            "    - Consumption forecast: %.2f kWh (%d-day avg)\n"
            "    - Total available: %.2f kWh (usable + solar)\n"
            "    - Energy deficit: %.2f kWh\n"
            "  → Decision: %s",
            total_capacity_kwh,
            avg_soc, stored_energy_kwh,
            min_soc, cutoff_energy_kwh,
            usable_energy_kwh,
            solar_forecast_kwh,
            avg_consumption_kwh, days_in_history,
            total_available_kwh,
            energy_deficit_kwh,
            "ACTIVATE CHARGING" if should_charge else "NO CHARGING NEEDED"
        )

        # === STEP 7: Return Complete Decision Data ===
        return {
            "should_charge": should_charge,
            "solar_forecast_kwh": solar_forecast_kwh,
            "stored_energy_kwh": stored_energy_kwh,
            "usable_energy_kwh": usable_energy_kwh,
            "min_reserve_kwh": min_reserve_kwh,
            "cutoff_energy_kwh": cutoff_energy_kwh,
            "effective_min_soc": effective_min_soc,
            "avg_soc": avg_soc,
            "avg_consumption_kwh": avg_consumption_kwh,
            "total_available_kwh": total_available_kwh,
            "energy_deficit_kwh": energy_deficit_kwh,
            "days_in_history": days_in_history,
            "reason": (
                f"Energy deficit: {energy_deficit_kwh:.2f} kWh "
                f"(available: {total_available_kwh:.2f} kWh < consumption: {avg_consumption_kwh:.2f} kWh)"
                if should_charge else
                f"Sufficient energy: {total_available_kwh:.2f} kWh available "
                f"≥ {avg_consumption_kwh:.2f} kWh consumption"
            )
        }

    def _check_time_window(self) -> bool:
        """Helper to check if we're in the time window (without override check)."""
        from datetime import datetime, time as dt_time
        
        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        
        # Check day
        if current_day not in self.charging_time_slot["days"]:
            return False
        
        # Check time
        try:
            start_time = dt_time.fromisoformat(self.charging_time_slot["start_time"])
            end_time = dt_time.fromisoformat(self.charging_time_slot["end_time"])
        except Exception as e:
            _LOGGER.error("Error parsing predictive charging time slot: %s", e)
            return False
        
        # Handle overnight slots
        if start_time <= end_time:
            return start_time <= current_time <= end_time
        else:
            return current_time >= start_time or current_time <= end_time
    
    def _is_in_pre_evaluation_window(self) -> bool:
        """Check if we're 1 hour before the charging slot starts (for early evaluation).

        This method checks the NEXT occurrence of the configured start_time (either today or tomorrow)
        and determines if we're currently within the pre-evaluation window (±5 minutes tolerance).

        Returns True if:
        - Current time is within 60±5 minutes before a slot start time
        - The day the slot will start on is in configured days
        """
        from datetime import datetime, time as dt_time, timedelta

        now = datetime.now()

        try:
            start_time = dt_time.fromisoformat(self.charging_time_slot["start_time"])
        except Exception as e:
            _LOGGER.error("Error parsing predictive charging time slot: %s", e)
            return False

        # Check both today's and tomorrow's potential slots
        # This handles all cases including midnight boundary crossings
        for days_ahead in [0, 1]:
            slot_date = now.date() + timedelta(days=days_ahead)
            slot_datetime = datetime.combine(slot_date, start_time)

            # Skip if this slot is in the past
            if slot_datetime <= now:
                continue

            # Calculate pre-eval time (1 hour before slot)
            pre_eval_target = slot_datetime - timedelta(minutes=60)

            # Check if we're within ±5 minutes of pre-eval target (10-minute window)
            time_diff_seconds = abs((now - pre_eval_target).total_seconds())
            time_diff_minutes = time_diff_seconds / 60

            # INFO LOG: Show timing calculation for slots that aren't in the past
            _LOGGER.info(
                "Pre-eval check: now=%s, slot=%s, pre_eval_target=%s, time_diff=%.1f min, threshold=±5 min",
                now.strftime("%a %H:%M"),
                slot_datetime.strftime("%a %H:%M"),
                pre_eval_target.strftime("%a %H:%M"),
                time_diff_minutes
            )

            if time_diff_seconds <= 5 * 60:
                # We're in the pre-eval window for this slot
                # Check if the slot's day is configured
                slot_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][slot_datetime.weekday()]

                # INFO LOG: Show day matching logic
                _LOGGER.info(
                    "Pre-eval WINDOW DETECTED: slot_day=%s, configured_days=%s, match=%s",
                    slot_day.upper(),
                    self.charging_time_slot["days"],
                    slot_day in self.charging_time_slot["days"]
                )

                if slot_day in self.charging_time_slot["days"]:
                    _LOGGER.info(
                        "✓ PRE-EVALUATION WINDOW ACTIVE: slot starts at %s (%s), current time=%s",
                        slot_datetime.strftime("%a %H:%M"),
                        slot_day.upper(),
                        now.strftime("%a %H:%M")
                    )
                    return True
                else:
                    _LOGGER.info(
                        "✗ Pre-eval window detected but slot day %s NOT in configured days - skipping",
                        slot_day.upper()
                    )
                    return False

        # No pre-eval window found
        return False

    def _is_in_predictive_charging_slot(self) -> bool:
        """Check if we're currently within the predictive charging time slot."""
        if not self.predictive_charging_enabled or self.charging_time_slot is None:
            return False
        
        # Check manual override
        if self.predictive_charging_overridden:
            return False
        
        return self._check_time_window()

    async def _handle_predictive_grid_charging(self):
        """
        Handle predictive grid charging mode.

        Target: Keep consumption/export sensor at max_contracted_power.
        If home consumption increases, reduce battery charging to avoid exceeding ICP.
        """
        consumption_state = self.hass.states.get(self.consumption_sensor)
        if consumption_state is None:
            _LOGGER.warning("Consumption sensor unavailable during predictive charging")
            return
        
        try:
            sensor_raw = float(consumption_state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid consumption sensor state: %s", consumption_state.state)
            return
        
        # Apply sensor filtering
        self.sensor_history.append(sensor_raw)
        if len(self.sensor_history) > self.sensor_history_size:
            self.sensor_history.pop(0)
        sensor_filtered = sum(self.sensor_history) / len(self.sensor_history)
        
        # Get available batteries (respecting max_soc)
        available_batteries = self._get_available_batteries(is_charging=True)
        if not available_batteries:
            _LOGGER.info("Predictive charging: No batteries available (all at max_soc)")
            for coordinator in self.coordinators:
                await self._set_battery_power(coordinator, 0, 0)
            return
        
        # Calculate max available charging power from batteries
        max_battery_charge = sum(c.max_charge_power for c in available_batteries)
        
        # TARGET: max_contracted_power (e.g., 7000W)
        # ERROR: target - sensor_actual (INVERTED for predictive mode)
        # Positive error = importing LESS than target → increase charging
        # Negative error = importing MORE than target → reduce charging
        
        target_power = self.max_contracted_power
        error = target_power - sensor_filtered  # INVERTED: target - sensor
        
        # PD Control with modified target
        if not self._grid_charging_initialized:
            # Initialize for grid charging mode (first time entering)
            self.previous_error = error
            self.previous_power = -min(max_battery_charge, target_power)  # Start at max charge
            self._grid_charging_initialized = True
            self.first_execution = False  # Mark as initialized to avoid conflicts
            _LOGGER.info("Initialized predictive charging: target=%dW, initial_charge=%dW",
                        target_power, abs(self.previous_power))
        
        # Calculate derivative
        error_derivative = (error - self.previous_error) / self.dt
        
        # PD terms
        P = self.kp * error
        D = self.kd * error_derivative
        pd_adjustment = P + D
        
        # Calculate new charging power (incremental)
        # If error > 0 (importing too little) -> increase charging (adjustment is positive -> previous_power becomes more negative)
        # If error < 0 (importing too much) -> reduce charging (adjustment is negative -> previous_power becomes less negative)
        new_power_raw = self.previous_power - pd_adjustment
        
        # Apply rate limiter
        power_change = new_power_raw - self.previous_power
        if abs(power_change) > self.max_power_change_per_cycle:
            sign = 1 if power_change > 0 else -1
            new_power = self.previous_power + (sign * self.max_power_change_per_cycle)
            _LOGGER.info("Predictive: Rate limiter active (change: %.1fW → %.1fW)",
                        power_change, new_power - self.previous_power)
        else:
            new_power = new_power_raw
        
        # Clamp to battery limits (negative = charging)
        if new_power < -max_battery_charge:
            _LOGGER.info("Predictive: Clamping charge to max available: %dW", max_battery_charge)
            new_power = -max_battery_charge
        elif new_power > 0:
            # Should never charge positively (discharge) in this mode
            _LOGGER.warning("Predictive: Negative power detected (discharge), clamping to 0W")
            new_power = 0
        
        _LOGGER.info(
            "Predictive Grid Charging: Grid=%.1fW, Target=%dW, Error=%.1fW, P=%.1fW, D=%.1fW, "
            "Adjustment=%.1fW, PrevPower=%.1fW, NewCharge=%dW",
            sensor_filtered, target_power, error, P, D, pd_adjustment, self.previous_power, abs(new_power)
        )

        # Select batteries via load sharing, then distribute power
        selected_batteries = self._select_batteries_for_operation(abs(new_power), available_batteries, is_charging=True)
        power_allocation = self._distribute_power_by_limits(abs(new_power), selected_batteries, is_charging=True)

        total_allocated = sum(power_allocation.values())
        _LOGGER.info("Predictive: Setting charge to %dW total across %d batteries: %s",
                    total_allocated, len(selected_batteries),
                    {c.name: p for c, p in power_allocation.items()})

        # Write to selected batteries
        for coordinator in selected_batteries:
            await self._set_battery_power(coordinator, power_allocation.get(coordinator, 0), 0)

        # Set all other batteries to 0 (non-available + available-but-not-selected)
        for coordinator in self.coordinators:
            if coordinator not in selected_batteries:
                await self._set_battery_power(coordinator, 0, 0)
        
        # Update state
        self.previous_power = new_power
        self.previous_error = error
        self.previous_sensor = sensor_filtered

    def _distribute_power_by_limits(self, total_power: float, available_batteries: list, is_charging: bool) -> dict:
        """Distribute power among batteries proportionally to their individual limits.

        Returns dict mapping coordinator -> power (int, rounded to 5W).
        """
        if not available_batteries:
            return {}

        # Get each battery's individual limit
        limits = {}
        for c in available_batteries:
            limits[c] = c.max_charge_power if is_charging else c.max_discharge_power

        total_capacity = sum(limits.values())
        if total_capacity <= 0:
            return {c: 0 for c in available_batteries}

        # Clamp total request to total capacity
        remaining_power = min(total_power, total_capacity)

        allocation = {}
        remaining_batteries = list(available_batteries)

        # Iterative allocation: distribute proportionally, cap at limits, redistribute excess
        while remaining_power > 0 and remaining_batteries:
            current_capacity = sum(limits[c] for c in remaining_batteries)
            if current_capacity <= 0:
                break

            all_fit = True
            for c in list(remaining_batteries):
                share = remaining_power * (limits[c] / current_capacity)
                if share >= limits[c]:
                    # This battery is at its limit
                    allocation[c] = self._round_to_5w(limits[c])
                    remaining_power -= limits[c]
                    remaining_batteries.remove(c)
                    all_fit = False

            if all_fit:
                # All remaining batteries can handle their proportional share
                for c in remaining_batteries:
                    share = remaining_power * (limits[c] / current_capacity)
                    allocation[c] = self._round_to_5w(share)
                break

        # Ensure all batteries have an entry
        for c in available_batteries:
            if c not in allocation:
                allocation[c] = 0

        return allocation

    def _select_batteries_for_operation(
        self,
        total_power: float,
        available_batteries: list,
        is_charging: bool
    ) -> list:
        """Select minimum batteries needed so total_power <= 60% of combined capacity.

        Prioritizes:
        - Discharge: Highest SOC first (drain fullest battery first)
        - Charge: Lowest SOC first (fill emptiest battery first)

        Hysteresis:
        - SOC: Active batteries get 5% effective SOC advantage to avoid ping-pong
        - Power: Activate at 60%, deactivate at 50% (~100W hysteresis band)
        """
        if len(available_batteries) <= 1:
            return list(available_batteries)

        # No power requested — clear state and return empty
        if total_power <= 0:
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            return list(available_batteries)

        ACTIVATION_THRESHOLD = 0.60
        DEACTIVATION_THRESHOLD = 0.50
        SOC_HYSTERESIS = 5.0
        ENERGY_HYSTERESIS = 2.5  # kWh advantage for active battery in tiebreaker

        previous_active = (
            self._active_charge_batteries if is_charging
            else self._active_discharge_batteries
        )

        def sort_key(coordinator):
            soc = coordinator.data.get("battery_soc", 50) if coordinator.data else 50
            is_active = coordinator in previous_active

            if is_charging:
                # Lowest SOC first; active batteries get -5% to stay selected
                effective_soc = soc - (SOC_HYSTERESIS if is_active else 0)
                energy = coordinator.data.get("total_charging_energy", 0) if coordinator.data else 0
                # Active battery gets -2.5 kWh advantage (lower = selected first)
                effective_energy = energy - (ENERGY_HYSTERESIS if is_active else 0)
                return (effective_soc, effective_energy)
            else:
                # Highest SOC first; active batteries get +5% to stay selected
                effective_soc = soc + (SOC_HYSTERESIS if is_active else 0)
                energy = coordinator.data.get("total_discharging_energy", 0) if coordinator.data else 0
                # Active battery gets -2.5 kWh advantage (lower = selected first)
                effective_energy = energy - (ENERGY_HYSTERESIS if is_active else 0)
                return (-effective_soc, effective_energy)

        sorted_batteries = sorted(available_batteries, key=sort_key)

        # Select minimum batteries needed
        selected = []
        combined_capacity = 0

        for battery in sorted_batteries:
            selected.append(battery)
            limit = battery.max_charge_power if is_charging else battery.max_discharge_power
            combined_capacity += limit

            if total_power <= combined_capacity * ACTIVATION_THRESHOLD:
                break

        # Power hysteresis: can we remove the last battery added?
        if len(selected) > 1 and len(previous_active) > 0:
            last = selected[-1]
            last_limit = last.max_charge_power if is_charging else last.max_discharge_power
            capacity_without_last = combined_capacity - last_limit

            if (total_power <= capacity_without_last * DEACTIVATION_THRESHOLD
                    and last not in previous_active):
                selected.pop()

        # Log when selection changes
        if set(selected) != set(previous_active):
            mode = "charge" if is_charging else "discharge"
            _LOGGER.info(
                "Load sharing [%s]: %d/%d batteries active (%s) for %dW",
                mode, len(selected), len(available_batteries),
                ", ".join(c.name for c in selected), int(total_power)
            )

        # Update tracking state: clear opposite list since charge/discharge are mutually exclusive
        if is_charging:
            self._active_charge_batteries = list(selected)
            self._active_discharge_batteries = []
        else:
            self._active_discharge_batteries = list(selected)
            self._active_charge_batteries = []

        return selected

    async def _set_battery_power(
        self,
        coordinator: MarstekVenusDataUpdateCoordinator,
        charge_power: float,
        discharge_power: float
    ) -> bool:
        """Set charge/discharge power for a single battery with ACK verification.

        Returns True if command was acknowledged, False otherwise.
        """
        # Skip if battery is unreachable
        if not coordinator.is_available:
            _LOGGER.debug(
                "[%s] Skipping power write - battery unreachable (failures: %d)",
                coordinator.name, coordinator._consecutive_failures
            )
            return False

        # Determine expected force mode
        if charge_power > 0:
            expected_force_mode = 1  # Charge
        elif discharge_power > 0:
            expected_force_mode = 2  # Discharge
        else:
            expected_force_mode = 0  # None

        # Attempt atomic write + verify, with one retry on failure
        for attempt in range(2):
            feedback = await coordinator.write_power_atomic(
                int(discharge_power), int(charge_power), expected_force_mode
            )

            if feedback is None:
                if not coordinator._is_shutting_down:
                    _LOGGER.warning(
                        "[%s] Power write/feedback failed (attempt %d/2)",
                        coordinator.name, attempt + 1
                    )
                continue

            # Verify ACK - check if written values match readback
            ack_ok = (
                feedback["force_mode"] == expected_force_mode and
                feedback["set_charge_power"] == int(charge_power) and
                feedback["set_discharge_power"] == int(discharge_power)
            )

            if ack_ok:
                _LOGGER.debug(
                    "[%s] Power command ACK'd: force=%d, charge=%dW, discharge=%dW, actual=%dW",
                    coordinator.name,
                    expected_force_mode,
                    int(charge_power),
                    int(discharge_power),
                    feedback["battery_power"]
                )
                # Detect non-responsive battery: ACK ok but not delivering discharge power
                if discharge_power >= 100 and charge_power == 0:
                    actual_abs = abs(feedback["battery_power"])
                    if actual_abs < 0.10 * discharge_power:
                        self._record_non_responsive(coordinator, discharge_power, actual_abs)
                    else:
                        self._clear_non_responsive(coordinator)
                return True

            if attempt == 0:
                _LOGGER.warning(
                    "[%s] Power command not ACK'd (attempt 1/2), retrying. "
                    "Expected force=%d, got=%d",
                    coordinator.name,
                    expected_force_mode,
                    feedback["force_mode"]
                )

        if not coordinator._is_shutting_down:
            _LOGGER.error(
                "[%s] Power command failed after 2 attempts. "
                "Battery may not have received command.",
                coordinator.name
            )
        return False

    def _calculate_excluded_devices_adjustment(self, current_grid_power: float) -> float:
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
        excluded_devices = self.config_entry.data.get("excluded_devices", [])
        if not excluded_devices:
            return 0.0

        is_charging = self.previous_power >= 0

        total_adjustment = 0.0
        for device in excluded_devices:
            power_sensor = device.get("power_sensor")
            if not power_sensor:
                continue

            state = self.hass.states.get(power_sensor)
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
                            current_grid_power -= device_power
                            _LOGGER.debug("Excluded device %s consuming %.1fW (solar surplus, battery discharging → full exclusion)",
                                        power_sensor, device_power)
                    else:
                        total_adjustment += device_power
                        _LOGGER.debug("Excluded device %s consuming %.1fW (included in consumption, SUBTRACTING)",
                                    power_sensor, device_power)
                else:
                    # Device is NOT in home sensor → ADD (power from battery)
                    total_adjustment -= device_power
                    _LOGGER.debug("Additional device %s consuming %.1fW (NOT in consumption, ADDING)",
                                    power_sensor, device_power)
            except (ValueError, TypeError):
                _LOGGER.warning("Could not parse device sensor %s: %s", power_sensor, state.state)
        
        return total_adjustment

    def _format_predictive_notification_message(
        self,
        decision_data: dict,
        is_pre_evaluation: bool
    ) -> tuple[str, str]:
        """Format notification title and message from decision data.

        Args:
            decision_data: Dict from _should_activate_grid_charging() with energy balance data
            is_pre_evaluation: True if pre-evaluation (1 hour before), False if initial

        Returns:
            tuple: (title, message)
        """
        from datetime import time as dt_time

        # Extract NEW field names from refactored energy balance decision
        should_charge = decision_data["should_charge"]
        solar_forecast = decision_data["solar_forecast_kwh"]
        stored_energy = decision_data["stored_energy_kwh"]
        usable_energy = decision_data["usable_energy_kwh"]
        min_reserve = decision_data["min_reserve_kwh"]
        effective_min_soc = decision_data["effective_min_soc"]
        avg_soc = decision_data["avg_soc"]
        avg_consumption = decision_data["avg_consumption_kwh"]
        total_available = decision_data["total_available_kwh"]
        energy_deficit = decision_data["energy_deficit_kwh"]
        days_in_history = decision_data["days_in_history"]
        reason = decision_data["reason"]

        # Format consumption history info
        if days_in_history == 0:
            consumption_info = f"{avg_consumption:.2f} kWh (default)"
        else:
            consumption_info = f"{avg_consumption:.2f} kWh (7-day avg, {days_in_history} days)"

        # Handle safe mode (forecast unavailable)
        if solar_forecast is None:
            title = "Predictive Charging: NOT activated (safe mode)"
            message = (
                f"⚠ {reason}\n\n"
                f"Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                f"Discharge cutoff: {effective_min_soc:.0f}% | Usable reserve: {min_reserve:.2f} kWh\n"
                f"Consumption: {consumption_info}\n\n"
                f"Decision: No solar forecast available\n"
                f"Conservative mode applied."
            )
            return (title, message)

        # Normal decision with forecast available
        if not should_charge:
            # Sufficient energy available
            surplus = total_available - avg_consumption
            title = "Predictive Charging: NOT required"
            message = (
                f"✓ Sufficient energy available for tomorrow\n\n"
                f"Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                f"Discharge cutoff: {effective_min_soc:.0f}%\n"
                f"Solar tomorrow: {solar_forecast:.2f} kWh\n"
                f"Consumption: {consumption_info}\n\n"
                f"Available: {total_available:.2f} kWh\n"
                f"Needed: {avg_consumption:.2f} kWh\n"
                f"Surplus: {surplus:.2f} kWh ✓\n\n"
                f"Batteries will not charge from grid."
            )
        else:
            # Insufficient energy - charging needed
            # Build title based on evaluation type
            if is_pre_evaluation:
                try:
                    start_time = dt_time.fromisoformat(self.charging_time_slot["start_time"])
                    title = f"Predictive Charging ACTIVATED (start: {start_time.strftime('%H:%M')})"
                except Exception:
                    title = "Predictive Charging ACTIVATED"
            else:
                title = "Predictive Charging STARTED"

            # Build message
            message = (
                f"⚡ Energy balance shows charging needed\n\n"
                f"Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                f"Discharge cutoff: {effective_min_soc:.0f}% | Usable reserve: {min_reserve:.2f} kWh\n"
                f"Solar tomorrow: {solar_forecast:.2f} kWh\n"
                f"Consumption: {consumption_info}\n\n"
                f"Available: {total_available:.2f} kWh\n"
                f"Needed: {avg_consumption:.2f} kWh\n"
                f"Deficit: {energy_deficit:.2f} kWh ✗\n\n"
                f"⚡ Charging will activate to cover shortfall.\n\n"
            )

            # Add footer based on evaluation type
            if is_pre_evaluation:
                try:
                    start_time = dt_time.fromisoformat(self.charging_time_slot["start_time"])
                    end_time = dt_time.fromisoformat(self.charging_time_slot["end_time"])
                    message += f"Charging will start at {start_time.strftime('%H:%M')} (in ~1 hour)\n"
                    message += f"Charging until: {end_time.strftime('%H:%M')}\n"
                except Exception:
                    message += "Charging will start in ~1 hour\n"
            else:
                try:
                    end_time = dt_time.fromisoformat(self.charging_time_slot["end_time"])
                    message += f"Charging now from grid\n"
                    message += f"Charging until: {end_time.strftime('%H:%M')}\n"
                except Exception:
                    message += "Charging now from grid\n"

            message += f"Maximum power: {self.max_contracted_power}W"

        return (title, message)

    async def _send_predictive_charging_notification(
        self,
        is_pre_evaluation: bool,
        decision_data: dict
    ):
        """Send notification about predictive charging evaluation result.

        Args:
            is_pre_evaluation: True if pre-evaluation (1 hour before), False if initial
            decision_data: Dict from _should_activate_grid_charging() with decision factors
        """
        # Format the notification using the helper method
        title, message = self._format_predictive_notification_message(decision_data, is_pre_evaluation)

        # Send the notification
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": "predictive_charging_evaluation",
            },
        )
    
    async def async_update_charge_discharge(self, now=None):
        """Update the charge/discharge power of the batteries."""
        _LOGGER.debug("ChargeDischargeController: async_update_charge_discharge started.")

        # === SHUTDOWN CHECK (absolute priority) ===
        # Skip all operations if any coordinator is shutting down (integration unloading)
        if any(c._is_shutting_down for c in self.coordinators):
            return

        # === MANUAL MODE CHECK (highest priority) ===
        # If manual mode is enabled, skip all automatic control logic
        if self.manual_mode_enabled:
            _LOGGER.debug("Manual Mode active - skipping automatic control")
            # Do not set batteries to 0 - preserve user's manual settings
            # Do not update PD state - freeze controller state
            return

        # === WEEKLY FULL CHARGE REGISTER MANAGEMENT ===
        # Handle register writes and completion detection BEFORE predictive charging
        # This ensures weekly charge works regardless of active control mode
        await self._handle_weekly_full_charge_registers()

        # === CHARGE DELAY: Daily reset and solar detection ===
        if self.charge_delay_enabled:
            from datetime import date
            today = date.today()
            if self._charge_delay_last_date != today:
                self._charge_delay_unlocked = False
                # Only clear T_start on a real day change. On first cycle after an HA
                # restart _charge_delay_last_date is None, but T_start may have been
                # restored from storage — don't wipe it.
                if self._charge_delay_last_date is not None:
                    self._solar_t_start = None
                self._charge_delay_last_date = today
                self._delay_last_log_time = 0
                # Reset status dict for sensor (preserve safety_margin_min)
                saved_margin = self._charge_delay_status.get("safety_margin_min")
                for key in self._charge_delay_status:
                    if key not in ("state", "safety_margin_min"):
                        self._charge_delay_status[key] = None
                self._charge_delay_status["state"] = "Idle"
                if saved_margin is not None:
                    self._charge_delay_status["safety_margin_min"] = saved_margin
                _LOGGER.info("Charge Delay: New day - state reset")
            # Detect solar production start (shared with weekly charge)
            self._detect_solar_t_start()
            # Proactively evaluate delay to keep ChargeDelaySensor populated
            self._is_charge_delayed()

        # === NEW: Predictive Grid Charging Logic ===
        # Check if we're in PRE-EVALUATION window (1 hour before slot)
        if self.predictive_charging_enabled and self.charging_time_slot is not None:
            in_pre_eval_window = self._is_in_pre_evaluation_window()

            # INFO LOG: Show pre-eval gate conditions (only when window is active to avoid spam)
            if in_pre_eval_window:
                _LOGGER.info(
                    "Pre-eval trigger check: window=TRUE, already_evaluated=%s → will_trigger=%s",
                    hasattr(self, '_pre_evaluated'),
                    not hasattr(self, '_pre_evaluated')
                )

            if in_pre_eval_window and not hasattr(self, '_pre_evaluated'):
                # Perform early evaluation 1 hour before slot starts
                current_avg_soc = sum(c.data.get("battery_soc", 0) for c in self.coordinators if c.data) / len(self.coordinators)
                _LOGGER.info("PRE-EVALUATION: 1 hour before charging slot (SOC: %.1f%%)", current_avg_soc)

                decision_data = await self._should_activate_grid_charging()
                self._pre_eval_decision_data = decision_data  # Store decision for slot start
                self._pre_eval_soc = current_avg_soc
                self._last_decision_data = decision_data  # Store for binary sensor
                self._pre_evaluated = True  # Mark as evaluated

                _LOGGER.info("PRE-EVALUATION result: Charging will be %s when slot starts",
                            "ACTIVATED" if decision_data["should_charge"] else "NOT NEEDED")

                # Send notification with evaluation result
                await self._send_predictive_charging_notification(
                    is_pre_evaluation=True,
                    decision_data=decision_data
                )
        else:
            in_pre_eval_window = False
        
        # Check if we're in the actual time slot (ignoring override for this check)
        in_time_window = (
            self.predictive_charging_enabled and
            self.charging_time_slot is not None and
            self._check_time_window()  # Helper without override check
        )
        
        if in_time_window:
            # Check if override is active
            if self.predictive_charging_overridden:
                # Override active - stop charging and block discharge
                _LOGGER.debug("Predictive charging overridden by user - batteries idle")
                for coordinator in self.coordinators:
                    await self._set_battery_power(coordinator, 0, 0)
                return
            
            # Apply pre-evaluation decision if available
            if hasattr(self, '_pre_eval_decision_data'):
                pre_eval_data = self._pre_eval_decision_data
                self.grid_charging_active = pre_eval_data["should_charge"]
                self.last_evaluation_soc = self._pre_eval_soc
                self._last_decision_data = pre_eval_data
                delattr(self, '_pre_eval_decision_data')
                if hasattr(self, '_pre_eval_soc'):
                    delattr(self, '_pre_eval_soc')
                _LOGGER.info(
                    "Applied pre-evaluation decision at slot start: charging=%s (SOC at pre-eval: %.1f%%)",
                    self.grid_charging_active, self.last_evaluation_soc
                )

            # Check if we need to evaluate/re-evaluate charging decision
            current_avg_soc = sum(c.data.get("battery_soc", 0) for c in self.coordinators if c.data) / len(self.coordinators)

            # Evaluate if: first time entering slot (no pre-evaluation) OR significant SOC drop
            should_reevaluate = (
                self.last_evaluation_soc is None or
                abs(current_avg_soc - self.last_evaluation_soc) >= SOC_REEVALUATION_THRESHOLD
            )
            
            if should_reevaluate:
                is_initial_eval = self.last_evaluation_soc is None
                
                if is_initial_eval:
                    # First evaluation (no pre-evaluation occurred)
                    _LOGGER.info("INITIAL evaluation of predictive grid charging (SOC: %.1f%%)", current_avg_soc)
                else:
                    # Re-evaluation due to SOC drop
                    _LOGGER.info("RE-EVALUATING predictive grid charging due to SOC drop (%.1f%% -> %.1f%%)",
                                self.last_evaluation_soc, current_avg_soc)
                
                decision_data = await self._should_activate_grid_charging()
                self.grid_charging_active = decision_data["should_charge"]
                self.last_evaluation_soc = current_avg_soc
                self._last_decision_data = decision_data  # Store for binary sensor

                # Send notification only on initial evaluation (not re-evaluations)
                if is_initial_eval:
                    await self._send_predictive_charging_notification(
                        is_pre_evaluation=False,
                        decision_data=decision_data
                    )
            
            if self.grid_charging_active:
                # PREDICTIVE CHARGING MODE ACTIVE
                _LOGGER.info("Predictive Grid Charging ACTIVE - target power: %dW", 
                            self.max_contracted_power)
                return await self._handle_predictive_grid_charging()
            else:
                # In charging slot but condition not met - block discharge only
                _LOGGER.info("In predictive charging slot but condition NOT met - blocking discharge")
                for coordinator in self.coordinators:
                    await self._set_battery_power(coordinator, 0, 0)
                return
        else:
            # Not in time window - reset state if exiting
            if self.grid_charging_active or self._grid_charging_initialized:
                _LOGGER.info("Exiting predictive grid charging slot - returning to normal mode")
                self.grid_charging_active = False
                self.last_evaluation_soc = None
                self._grid_charging_initialized = False
                # Reset PD state to avoid oscillations
                self.error_integral = 0.0
                self.previous_error = 0.0
                self.sign_changes = 0
                # Clear notification
                await self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": "predictive_charging_evaluation"},
                )
            
            # Reset override flag when leaving time window
            if self.predictive_charging_overridden:
                self.predictive_charging_overridden = False

            # Reset pre-evaluation flag ONLY if we're past the pre-eval window
            # This prevents the flag from being deleted during pre-eval on days not in the slot
            # (e.g., Sunday 23:00 pre-eval for Monday 00:00 slot when Sunday is not configured)
            if hasattr(self, '_pre_evaluated') and not in_pre_eval_window:
                delattr(self, '_pre_evaluated')
                _LOGGER.info("Predictive charging flags reset (exited time window and pre-eval window)")

        # === Continue with normal PD control ===
        consumption_state = self.hass.states.get(self.consumption_sensor)
        if consumption_state is None:
            _LOGGER.warning(f"Consumption sensor {self.consumption_sensor} not found.")
            return

        try:
            sensor_raw = float(consumption_state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(f"Could not parse consumption sensor state: {consumption_state.state}")
            return
        
        # Detect if sensor has actually updated since last cycle
        sensor_update_time = consumption_state.last_updated
        is_stale = (
            self._last_sensor_update_time is not None
            and sensor_update_time == self._last_sensor_update_time
        )
        previous_update_time = self._last_sensor_update_time
        self._last_sensor_update_time = sensor_update_time

        if is_stale:
            self._stale_cycles += 1
            if self._stale_cycles <= self._max_stale_cycles:
                _LOGGER.debug(
                    "ChargeDischargeController: Sensor stale (cycle %d/%d), maintaining last command %.1fW",
                    self._stale_cycles, self._max_stale_cycles, self.previous_power
                )
                return
            else:
                _LOGGER.debug(
                    "ChargeDischargeController: Sensor stale for %d cycles (~%.0fs). Safety recalculation.",
                    self._stale_cycles, self._stale_cycles * 2.0
                )
        else:
            self._stale_cycles = 0
            # Add to sensor history ONLY on real updates
            self.sensor_history.append(sensor_raw)
            if len(self.sensor_history) > self.sensor_history_size:
                self.sensor_history.pop(0)

        # Use moving average to smooth out instantaneous spikes
        sensor_filtered = sum(self.sensor_history) / len(self.sensor_history) if self.sensor_history else sensor_raw

        # Get active time slot parameters (target grid power)
        active_slot = self._get_active_slot()
        active_target = active_slot.get("target_grid_power", DEFAULT_SLOT_TARGET_GRID_POWER) if active_slot else DEFAULT_SLOT_TARGET_GRID_POWER
        min_charge = self.min_charge_power
        min_discharge = self.min_discharge_power

        # CRITICAL: Check deadband on FILTERED sensor (actual grid balance) BEFORE compensation
        # Deadband is centered around the active target grid power
        if abs(sensor_filtered - active_target) < self.deadband:
            _LOGGER.debug("ChargeDischargeController: Filtered sensor %.1fW within deadband ±%dW of target %dW, no action.",
                          sensor_filtered, self.deadband, active_target)
            
            # Reset integral when within deadband to prevent accumulation (only if Ki > 0)
            if self.ki > 0 and self.error_integral != 0.0:
                _LOGGER.info("PD: Resetting integral term (was %.1fW) - system is balanced within deadband", 
                           self.error_integral)
                self.error_integral = 0.0
                self.sign_changes = 0  # Reset oscillation counter
            
            # Update previous_sensor for next cycle
            self.previous_sensor = sensor_filtered
            # NOTE: Do NOT clear load sharing state here. Batteries keep executing
            # their last command during deadband, so the active battery lists must
            # remain accurate for the diagnostic sensor.
            return
        
        # Use filtered sensor directly - it shows the real grid imbalance we need to correct
        sensor_actual = sensor_filtered
        
        if len(self.sensor_history) >= self.sensor_history_size:
            _LOGGER.debug("Sensor ready: raw=%.1fW, filtered=%.1fW", sensor_raw, sensor_filtered)
        
        # Adjust for excluded/additional devices
        # Positive adjustment = reduce battery discharge (excluded devices)
        # Negative adjustment = increase battery discharge (additional devices not in home sensor)
        excluded_adjustment = self._calculate_excluded_devices_adjustment(sensor_actual)
        if excluded_adjustment != 0:
            if excluded_adjustment > 0:
                _LOGGER.info("Reducing battery demand by %.1fW (excluded devices)", excluded_adjustment)
            else:
                _LOGGER.info("Increasing battery demand by %.1fW (additional devices)", abs(excluded_adjustment))
            sensor_actual -= excluded_adjustment

        if len(self.coordinators) == 0:
            _LOGGER.debug("ChargeDischargeController: No batteries configured.")
            return

        _LOGGER.debug("ChargeDischargeController: sensor_actual=%fW, previous_sensor=%s, previous_power=%fW",
                      sensor_actual, self.previous_sensor, self.previous_power)

        # FIRST EXECUTION: Initialize with sensor reading
        if self.first_execution:
            _LOGGER.info("ChargeDischargeController: First execution - initializing with sensor value: %fW (target: %dW)", sensor_actual, active_target)
            self.previous_sensor = sensor_actual
            # Initial power counteracts the difference from target grid power
            self.previous_power = -(sensor_actual - active_target)
            self.first_execution = False

            # Get available batteries and set initial power
            is_charging = self.previous_power > 0

            # Check time slot restrictions BEFORE sending any power to batteries
            operation_allowed = self._is_operation_allowed(is_charging)
            if not operation_allowed:
                if is_charging:
                    _LOGGER.info("ChargeDischargeController: First execution - Charging NOT ALLOWED by time slot, starting at 0W")
                else:
                    _LOGGER.info("ChargeDischargeController: First execution - Discharging NOT ALLOWED by time slot, starting at 0W")
                self.previous_power = 0
                is_charging = False
                # Initialize PD state at 0
                self.error_integral = 0.0
                self.previous_error = -(sensor_actual - active_target)
                self.last_output_sign = 0
                self.sign_changes = 0
                self._active_discharge_batteries = []
                self._active_charge_batteries = []
                # Set all batteries to 0
                for coordinator in self.coordinators:
                    await self._set_battery_power(coordinator, 0, 0)
                return

            available_batteries = self._get_available_batteries(is_charging)

            if not available_batteries:
                _LOGGER.debug("ChargeDischargeController: No available batteries for initial setup.")
                self._active_discharge_batteries = []
                self._active_charge_batteries = []
                return

            # Select batteries via load sharing, then distribute power
            selected_batteries = self._select_batteries_for_operation(abs(self.previous_power), available_batteries, is_charging)
            power_allocation = self._distribute_power_by_limits(abs(self.previous_power), selected_batteries, is_charging)

            total_allocated = sum(power_allocation.values())
            _LOGGER.info("ChargeDischargeController: Setting initial power to %dW across %d batteries: %s",
                        total_allocated, len(selected_batteries),
                        {c.name: p for c, p in power_allocation.items()})

            for coordinator in selected_batteries:
                power = power_allocation.get(coordinator, 0)
                if is_charging:
                    await self._set_battery_power(coordinator, power, 0)
                else:
                    await self._set_battery_power(coordinator, 0, power)

            # Set all other batteries to 0 (non-available + available-but-not-selected)
            for coordinator in self.coordinators:
                if coordinator not in selected_batteries:
                    await self._set_battery_power(coordinator, 0, 0)

            # Reset PD state for clean start (CRITICAL: clear saturated integral)
            self.error_integral = 0.0
            self.previous_error = -(sensor_actual - active_target)
            self.last_output_sign = 1 if self.previous_power > 0 else (-1 if self.previous_power < 0 else 0)
            self.sign_changes = 0
            _LOGGER.info("PD state initialized: previous_error=%.1fW, last_output_sign=%d, integral=0 (cleared)",
                        self.previous_error, self.last_output_sign)

            return

        # SUBSEQUENT EXECUTIONS: Continue with PD control
        # Deadband was already checked on filtered sensor before compensation
        _LOGGER.debug("ChargeDischargeController: sensor_actual=%fW, UPDATING BATTERIES!",
                      sensor_actual)
        
        # CAPACITY PROTECTION MODE: When enabled and SOC is below threshold,
        # only discharge to cover consumption above the peak limit.
        # This conserves battery energy for essential peak shaving.
        if self.capacity_protection_enabled:
            coordinators_with_data = [c for c in self.coordinators if c.data]
            if coordinators_with_data:
                avg_soc = sum(c.data.get("battery_soc", 0) for c in coordinators_with_data) / len(coordinators_with_data)
            else:
                avg_soc = 100  # Assume full if no data, don't activate protection

            original_target = active_target

            if avg_soc < self.capacity_protection_soc_threshold:
                # Estimate house consumption: grid reading minus what the battery is currently doing
                # sensor_actual = grid power (positive=import), previous_power > 0 = charging, < 0 = discharging
                estimated_house_load = sensor_actual - self.previous_power

                if estimated_house_load > self.capacity_protection_limit:
                    # House load exceeds peak limit: discharge only the excess
                    active_target = self.capacity_protection_limit
                    _LOGGER.info("Capacity Protection ACTIVE: SOC=%.1f%% < %d%%, house_load=%.0fW > limit=%dW → target=%dW",
                                avg_soc, self.capacity_protection_soc_threshold,
                                estimated_house_load, self.capacity_protection_limit, active_target)
                    self._capacity_protection_active = True
                    self._capacity_protection_status.update({
                        "active": True, "avg_soc": round(avg_soc, 1),
                        "estimated_house_load": round(estimated_house_load),
                        "action": "shaving",
                        "original_target": original_target, "adjusted_target": active_target,
                    })
                elif estimated_house_load > active_target:
                    # House load is below peak limit but above normal target: set target to house load
                    # This makes the PD controller smoothly ramp discharge to 0W
                    active_target = estimated_house_load
                    _LOGGER.info("Capacity Protection ACTIVE: SOC=%.1f%% < %d%%, house_load=%.0fW ≤ limit=%dW → idle (target=%.0fW)",
                                avg_soc, self.capacity_protection_soc_threshold,
                                estimated_house_load, self.capacity_protection_limit, active_target)
                    self._capacity_protection_active = True
                    self._capacity_protection_status.update({
                        "active": True, "avg_soc": round(avg_soc, 1),
                        "estimated_house_load": round(estimated_house_load),
                        "action": "conserving",
                        "original_target": original_target, "adjusted_target": active_target,
                    })
                else:
                    # Solar surplus: normal charging, but SOC is still below threshold
                    self._capacity_protection_active = True
                    self._capacity_protection_status.update({
                        "active": True, "avg_soc": round(avg_soc, 1),
                        "estimated_house_load": round(estimated_house_load),
                        "action": "charging",
                        "original_target": original_target, "adjusted_target": active_target,
                    })
            else:
                # SOC above threshold: protection not needed
                self._capacity_protection_active = False
                self._capacity_protection_status.update({
                    "active": False, "avg_soc": round(avg_soc, 1),
                    "estimated_house_load": None,
                    "action": "idle",
                    "original_target": original_target, "adjusted_target": active_target,
                })

            # Always keep thresholds up to date
            self._capacity_protection_status["soc_threshold"] = self.capacity_protection_soc_threshold
            self._capacity_protection_status["peak_limit"] = self.capacity_protection_limit
        else:
            self._capacity_protection_active = False
            self._capacity_protection_status["active"] = False
            self._capacity_protection_status["action"] = "disabled"

        # PD CONTROLLER: Calculate adjustment based on grid imbalance relative to target
        # error > 0: grid power above target → need to discharge more / charge less
        # error < 0: grid power below target → need to charge more / discharge less
        # active_target was calculated before deadband check (reuse it here)
        error = sensor_actual - active_target
        
        # Note: Oscillation detection moved to end of method (after checking restrictions)
        # This prevents false positives when controller is paused by time slot restrictions
        
        # Only process integral if Ki > 0 (integral is enabled)
        if self.ki > 0:
            # DIRECTIONAL RESET: If integral is working AGAINST the current error, it's obsolete
            # Example: integral is positive (wants to charge) but error is negative (should discharge)
            # This means the integral accumulated from old conditions and must be cleared
            integral_sign = 1 if self.error_integral > 0 else (-1 if self.error_integral < 0 else 0)
            error_sign = 1 if error > 0 else (-1 if error < 0 else 0)
            
            if integral_sign != 0 and error_sign != 0 and integral_sign != error_sign:
                # Integral and error have opposite signs - integral is working against the error
                _LOGGER.error("PID DIRECTIONAL CONFLICT: Integral=%.1fW (%s) but Error=%.1fW (%s) - RESETTING integral!",
                            self.error_integral, "charge" if integral_sign > 0 else "discharge",
                            error, "charge" if error_sign > 0 else "discharge")
                self.error_integral = 0.0
                self.sign_changes = 0  # Reset oscillation counter too
            
            # LEAKY INTEGRATOR: Apply decay before adding new error
            # This prevents the integral from growing unbounded and helps it "forget" old errors
            self.error_integral *= self.integral_decay
            
            # Calculate potential new integral value
            new_integral = self.error_integral + error * self.dt
            
            # CONDITIONAL INTEGRATION (Anti-windup):
            # Only accumulate integral if we're NOT saturated at the limits
            # This prevents integral windup when output is already at maximum
            is_saturated_positive = new_integral > self.max_charge_capacity
            is_saturated_negative = new_integral < -self.max_discharge_capacity
            
            if is_saturated_positive:
                self.error_integral = self.max_charge_capacity
                _LOGGER.warning("PID anti-windup: Integral SATURATED at max charge capacity +%dW (not accumulating)", 
                              self.max_charge_capacity)
            elif is_saturated_negative:
                self.error_integral = -self.max_discharge_capacity
                _LOGGER.warning("PID anti-windup: Integral SATURATED at max discharge capacity -%dW (not accumulating)", 
                              self.max_discharge_capacity)
            else:
                # Not saturated, safe to accumulate
                self.error_integral = new_integral
                _LOGGER.debug("PID: Integral updated to %.1fW (within limits)", self.error_integral)
        else:
            # Integral disabled - ensure it stays at zero
            self.error_integral = 0.0
        
        # Calculate derivative using real elapsed time between sensor updates
        if self._stale_cycles > self._max_stale_cycles:
            # Safety valve: suppress derivative to avoid spike from stale data
            real_dt = self.dt
            error_derivative = 0.0
        elif previous_update_time is not None:
            real_dt = max(1.0, min((sensor_update_time - previous_update_time).total_seconds(), 30.0))
            error_derivative = (error - self.previous_error) / real_dt
        else:
            real_dt = self.dt
            error_derivative = (error - self.previous_error) / real_dt
        
        # PID terms
        P = self.kp * error
        I = self.ki * self.error_integral
        D = self.kd * error_derivative
        
        # Calculate ADJUSTMENT to apply to current power (incremental control)
        # P term responds to current error
        # D term dampens rapid changes
        pd_adjustment = P + I + D
        
        # Apply adjustment to previous power to get new target
        new_power_raw = self.previous_power - pd_adjustment  # Minus because we're correcting the imbalance
        
        # RATE LIMITER: Prevent abrupt changes that cause overshoot
        power_change = new_power_raw - self.previous_power
        if abs(power_change) > self.max_power_change_per_cycle:
            # Clamp the change to maximum allowed rate
            sign = 1 if power_change > 0 else -1
            new_power = self.previous_power + (sign * self.max_power_change_per_cycle)
            _LOGGER.info("PD: Rate limiter active - requested change %.1fW exceeds limit ±%dW, clamping to %.1fW",
                        power_change, self.max_power_change_per_cycle, new_power - self.previous_power)
        else:
            new_power = new_power_raw
        
        _LOGGER.debug("PD: Adjustment=%.1fW, Previous power=%.1fW, New target=%.1fW",
                     pd_adjustment, self.previous_power, new_power)
        
        # DIRECTIONAL HYSTERESIS: Prevent rapid switching between charge/discharge
        # If we're changing direction, the new power must overcome the hysteresis threshold
        current_output_sign = 1 if new_power > 0 else (-1 if new_power < 0 else 0)
        
        if self.last_output_sign != 0 and current_output_sign != 0:
            if self.last_output_sign != current_output_sign:
                # Direction is changing - check if it overcomes hysteresis
                if abs(new_power) < self.direction_hysteresis:
                    _LOGGER.info("PD: Direction change suppressed by hysteresis - output=%.1fW < threshold=%dW, staying at 0W",
                                new_power, self.direction_hysteresis)
                    new_power = 0
                    current_output_sign = 0
                else:
                    _LOGGER.info("PD: Direction change ALLOWED - output=%.1fW > threshold=%dW",
                                abs(new_power), self.direction_hysteresis)
        
        # Note: last_output_sign and previous_error will be updated at the end of the method
        # This is done conditionally based on whether the operation is restricted by time slots

        # MINIMUM POWER CHECK: Avoid inefficient low-power operation
        # If PD output is below the configured minimum, stay idle instead
        if new_power > 0 and min_charge > 0 and new_power < min_charge:
            _LOGGER.debug("PD: Charge power %.1fW below minimum %dW, setting to idle",
                          new_power, min_charge)
            new_power = 0
        elif new_power < 0 and min_discharge > 0 and abs(new_power) < min_discharge:
            _LOGGER.debug("PD: Discharge power %.1fW below minimum %dW, setting to idle",
                          abs(new_power), min_discharge)
            new_power = 0

        # Log control output
        if self.ki > 0:
            # Calculate integral utilization percentage for monitoring
            if self.error_integral > 0:  # Integral is positive (charging direction)
                integral_percent = (self.error_integral / self.max_charge_capacity) * 100 if self.max_charge_capacity > 0 else 0
            elif self.error_integral < 0:  # Integral is negative (discharging direction)
                integral_percent = (abs(self.error_integral) / self.max_discharge_capacity) * 100 if self.max_discharge_capacity > 0 else 0
            else:
                integral_percent = 0
            
            _LOGGER.debug("ChargeDischargeController: PD Control - Grid=%.1fW, P=%.1fW, I=%.1fW (%.0f%%), D=%.1fW, Adjustment=%.1fW, New=%.1fW",
                          error, P, I, integral_percent, D, pd_adjustment, new_power)
        else:
            # Integral disabled - simpler log
            _LOGGER.debug("ChargeDischargeController: PD Control - Grid=%.1fW, P=%.1fW, D=%.1fW, Adjustment=%.1fW, New=%.1fW",
                          error, P, D, pd_adjustment, new_power)
        
        # Determine if charging or discharging (before applying restrictions)
        is_charging = new_power > 0
        
        # Check if the operation is allowed based on time slots
        operation_restricted = not self._is_operation_allowed(is_charging)
        if operation_restricted:
            if is_charging:
                _LOGGER.info("ChargeDischargeController: Charging NOT ALLOWED by time slot configuration - controller paused")
            else:
                _LOGGER.info("ChargeDischargeController: Discharging NOT ALLOWED by time slot configuration - controller paused")
            new_power = 0
            is_charging = False  # Reset since we're forcing to 0
            self._active_discharge_batteries = []
            self._active_charge_batteries = []

        # Get available batteries (after checking restrictions to determine correct operation mode)
        available_batteries = self._get_available_batteries(is_charging)
        
        # Apply limits: calculate max total power based on AVAILABLE batteries (not all coordinators)
        # This ensures we only compare against batteries that can actually participate
        if available_batteries:
            max_total_discharge = sum(c.max_discharge_power for c in available_batteries)
            max_total_charge = sum(c.max_charge_power for c in available_batteries)
        else:
            # No batteries available, use zero limits
            max_total_discharge = 0
            max_total_charge = 0
        
        # Clamp new_power to realistic limits (only if not already restricted to 0)
        # Convention: new_power > 0 = charging, new_power < 0 = discharging
        if not operation_restricted and new_power != 0:
            if new_power > max_total_charge:
                new_power = max_total_charge
            elif new_power < -max_total_discharge:
                new_power = -max_total_discharge
        
        _LOGGER.debug("ChargeDischargeController: sensor_actual=%fW, previous_power=%fW, new_power=%fW (available: %d batteries)",
                     sensor_actual, self.previous_power, new_power, len(available_batteries))
        
        if not available_batteries:
            _LOGGER.debug("ChargeDischargeController: No available batteries, setting all to 0.")
            for coordinator in self.coordinators:
                await self._set_battery_power(coordinator, 0, 0)
            self.previous_power = 0
            self.previous_sensor = sensor_actual
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            return
        
        # Select batteries via load sharing, then distribute power
        selected_batteries = self._select_batteries_for_operation(abs(new_power), available_batteries, is_charging)
        power_allocation = self._distribute_power_by_limits(abs(new_power), selected_batteries, is_charging)

        total_allocated = sum(power_allocation.values())
        _LOGGER.debug("ChargeDischargeController: Setting power to %dW total across %d batteries: %s",
                      total_allocated, len(selected_batteries),
                      {c.name: p for c, p in power_allocation.items()})

        # Write to selected batteries
        for coordinator in selected_batteries:
            power = power_allocation.get(coordinator, 0)
            if is_charging:
                await self._set_battery_power(coordinator, power, 0)
            else:
                await self._set_battery_power(coordinator, 0, power)

        # Set all other batteries to 0 (non-available + available-but-not-selected)
        for coordinator in self.coordinators:
            if coordinator not in selected_batteries:
                await self._set_battery_power(coordinator, 0, 0)
        
        # Update state for next cycle
        self.previous_power = new_power
        self.previous_sensor = sensor_actual
        
        # CRITICAL: Only update PD controller state if NOT restricted by time slots
        # This prevents false oscillation warnings when controller is paused
        if not operation_restricted:
            # Controller is active - perform oscillation detection and update state
            
            # OSCILLATION DETECTION: Detect if system is oscillating (frequent sign changes)
            # Key principle: Only track oscillations OUTSIDE deadband
            # - Inside deadband: System is stable, fluctuations are acceptable
            # - Outside deadband: Controller is active, sign changes indicate instability
            error_outside_deadband = abs(error) > self.deadband
            
            if error_outside_deadband:
                # Error is outside deadband - controller is actively trying to correct
                current_error_sign = 1 if error > 0 else (-1 if error < 0 else 0)
                
                # Only count sign changes when BOTH current and previous errors were outside deadband
                if current_error_sign != 0 and self.last_error_sign != 0:
                    if current_error_sign != self.last_error_sign:
                        # Sign changed while outside deadband - potential oscillation
                        self.sign_changes += 1
                        
                        # If too many consecutive sign changes, reset PID to stabilize
                        if self.sign_changes >= self.oscillation_threshold:
                            _LOGGER.debug("PID: Oscillation detected (grid swinging ±%.1fW). Resetting PID state.",
                                          abs(error))
                            self.error_integral = 0.0
                            self.previous_error = 0.0
                            self.sign_changes = 0
                            # Don't return, allow proportional control to continue
                    else:
                        # Same sign, reset counter (system is stable in one direction)
                        if self.sign_changes > 0:
                            _LOGGER.debug("PID: Error sign stable outside deadband, resetting oscillation counter (was %d)", 
                                         self.sign_changes)
                            self.sign_changes = 0
                
                # Update last_error_sign only when outside deadband
                self.last_error_sign = current_error_sign
            else:
                # Inside deadband - reset oscillation counter if any
                # This prevents false positives from small fluctuations within tolerance
                if self.sign_changes > 0:
                    _LOGGER.debug("PID: Back inside deadband (error=%.1fW < ±%dW), resetting oscillation counter (was %d)", 
                                 error, self.deadband, self.sign_changes)
                    self.sign_changes = 0
                # Note: last_error_sign is NOT updated when inside deadband
                # This ensures we only track sign changes that matter (outside deadband)
            self.previous_error = error
            self.last_output_sign = current_output_sign
            _LOGGER.debug("ChargeDischargeController: PD state updated - previous_error=%.1fW, error_sign=%d, output_sign=%d",
                         self.previous_error, self.last_error_sign, self.last_output_sign)
        else:
            # Controller is paused by restrictions - DO NOT update error tracking
            # This prevents false oscillation detection from natural load fluctuations
            _LOGGER.debug("ChargeDischargeController: PD state FROZEN (restricted) - error tracking paused to prevent false oscillation warnings")
        
        _LOGGER.debug("ChargeDischargeController: async_update_charge_discharge finished.")


async def _restore_consumption_history(hass: HomeAssistant, entry: ConfigEntry, controller: ChargeDischargeController) -> None:
    """Restore daily consumption history from previous session."""
    from datetime import date
    from homeassistant.util import dt as dt_util
    
    if not controller.predictive_charging_enabled:
        return  # Not using predictive charging, no history needed
    
    # Try to get the predictive charging binary sensor entity
    entity_id = f"binary_sensor.predictive_charging_active"
    state = hass.states.get(entity_id)
    
    if state is None or not state.attributes:
        _LOGGER.debug("No previous predictive charging state found for history restoration")
        return
    
    # Extract history from attributes
    history_data = state.attributes.get("daily_consumption_history", [])
    
    if not history_data:
        _LOGGER.debug("No consumption history found in previous session")
        return
    
    try:
        # Convert stored data back to list of tuples with date objects
        controller._daily_consumption_history = [
            (date.fromisoformat(date_str), consumption)
            for date_str, consumption in history_data
        ]
        
        _LOGGER.info(
            "Restored consumption history: %d days (oldest: %s, newest: %s)",
            len(controller._daily_consumption_history),
            controller._daily_consumption_history[0][0] if controller._daily_consumption_history else "N/A",
            controller._daily_consumption_history[-1][0] if controller._daily_consumption_history else "N/A"
        )
    except Exception as e:
        _LOGGER.warning("Failed to restore consumption history: %s", e)
        controller._daily_consumption_history = []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Venus Energy Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Migration: Add default version for existing installations
    from .const import CONF_BATTERY_VERSION, DEFAULT_VERSION

    for battery_config in entry.data["batteries"]:
        if CONF_BATTERY_VERSION not in battery_config:
            battery_config[CONF_BATTERY_VERSION] = DEFAULT_VERSION
            _LOGGER.info("Migrated %s to %s (default for existing installations)",
                        battery_config[CONF_NAME], DEFAULT_VERSION)

    coordinators = []
    for battery_config in entry.data["batteries"]:
        coordinator = MarstekVenusDataUpdateCoordinator(
            hass,
            name=battery_config[CONF_NAME],
            host=battery_config[CONF_HOST],
            port=battery_config[CONF_PORT],
            consumption_sensor=entry.data["consumption_sensor"],
            battery_version=battery_config.get(CONF_BATTERY_VERSION, DEFAULT_VERSION),
            max_charge_power=battery_config["max_charge_power"],
            max_discharge_power=battery_config["max_discharge_power"],
            max_soc=battery_config["max_soc"],
            min_soc=battery_config["min_soc"],
            enable_charge_hysteresis=battery_config.get("enable_charge_hysteresis", False),
            charge_hysteresis_percent=battery_config.get("charge_hysteresis_percent", 5),
        )
        
        # Connect and fetch initial data
        try:
            connected = await coordinator.connect()
            if not connected:
                # V3 batteries accept only one TCP connection; the slot from unload
                # may not be released yet. Retry once after a brief delay.
                _LOGGER.warning("Initial connection to %s failed, retrying in 1s...", coordinator.host)
                await asyncio.sleep(1.0)
                connected = await coordinator.connect()
            if not connected:
                _LOGGER.warning("Initial connection to %s failed. The integration will keep trying.", coordinator.host)
            else:
                # Enable RS485 Control Mode first (required to apply configuration changes)
                # Only done during integration setup/reload, not repeated during runtime
                _LOGGER.info("Enabling RS485 Control Mode for %s (only on initial setup)", battery_config[CONF_NAME])
                rs485_reg = coordinator.get_register("rs485_control")
                if rs485_reg:
                    await coordinator.write_register(rs485_reg, 21930, do_refresh=False)  # 0x55AA
                    await asyncio.sleep(0.1)

                # Write initial configuration values to the battery
                max_soc_value = int(battery_config["max_soc"] / 0.1)  # Convert to register value
                min_soc_value = int(battery_config["min_soc"] / 0.1)  # Convert to register value
                max_charge_power = int(battery_config["max_charge_power"])
                max_discharge_power = int(battery_config["max_discharge_power"])

                _LOGGER.info("Writing initial configuration for %s (%s): max_soc=%d%%, min_soc=%d%%, max_charge=%dW, max_discharge=%dW",
                           battery_config[CONF_NAME], coordinator.battery_version,
                           battery_config["max_soc"], battery_config["min_soc"],
                           max_charge_power, max_discharge_power)

                # Write cutoff capacities (v2 only - hardware registers)
                cutoff_charge_reg = coordinator.get_register("charging_cutoff_capacity")
                cutoff_discharge_reg = coordinator.get_register("discharging_cutoff_capacity")

                if cutoff_charge_reg is not None:
                    await coordinator.write_register(cutoff_charge_reg, max_soc_value, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.info("%s: Hardware charging cutoff set to %d%% (reg=%d)",
                                coordinator.name, battery_config["max_soc"], max_soc_value)
                else:
                    _LOGGER.info("%s: No hardware charging cutoff register (v3) - using software enforcement",
                                coordinator.name)

                if cutoff_discharge_reg is not None:
                    await coordinator.write_register(cutoff_discharge_reg, min_soc_value, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.info("%s: Hardware discharging cutoff set to %d%% (reg=%d)",
                                coordinator.name, battery_config["min_soc"], min_soc_value)
                else:
                    _LOGGER.info("%s: No hardware discharging cutoff register (v3) - using software enforcement",
                                coordinator.name)

                # Write maximum power limits (available in both versions)
                max_charge_reg = coordinator.get_register("max_charge_power")
                max_discharge_reg = coordinator.get_register("max_discharge_power")

                if max_charge_reg and max_discharge_reg:
                    await coordinator.write_register(max_charge_reg, max_charge_power, do_refresh=False)
                    await asyncio.sleep(0.1)
                    await coordinator.write_register(max_discharge_reg, max_discharge_power, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.info("%s: Max power limits set - charge: %dW, discharge: %dW",
                                coordinator.name, max_charge_power, max_discharge_power)
                
                # Manually trigger first refresh and wait for it
                await coordinator.async_request_refresh()
                # Give a moment for the data to be processed
                await asyncio.sleep(0.5)
        except Exception as e:
            # Disconnect on any setup error
            await coordinator.disconnect()
            raise ConfigEntryNotReady(f"Failed to set up {coordinator.host}: {e}") from e

        coordinators.append(coordinator)

    # Set up the charge/discharge controller BEFORE storing in hass.data
    # This allows the controller to register itself in hass.data[DOMAIN]["pid_controller"]
    controller = ChargeDischargeController(hass, coordinators, entry.data["consumption_sensor"], entry)

    # Restore daily consumption history: try Store first (survives reloads), then binary sensor fallback
    loaded = await controller._load_consumption_history()
    if not loaded:
        await _restore_consumption_history(hass, entry, controller)
        # If restored from binary sensor, migrate to Store for future reloads
        if controller._daily_consumption_history:
            await controller._save_consumption_history()

    # If no history was restored from either source, initialize with default values
    if not controller._daily_consumption_history:
        controller._initialize_consumption_history_with_defaults()
        await controller._save_consumption_history()

    # Restore weekly charge completion state from previous session
    await controller._load_weekly_charge_state()
    # Restore solar T_start if not already restored by weekly charge state (date-based check)
    if controller._solar_t_start is None:
        await controller._load_solar_t_start()

    # Set up periodic timers and store unsub callbacks for manual cancellation during unload
    unsub_control = async_track_time_interval(
        hass, controller.async_update_charge_discharge, timedelta(seconds=2.0)
    )
    entry.async_on_unload(unsub_control)

    # Force coordinator updates every 1.5 seconds with timestamp-based per-sensor polling
    # This ensures all sensors update according to their scan_interval
    async def _force_coordinator_refresh(now):
        """Force coordinator to check and update data based on timestamp thresholds."""
        await asyncio.gather(*[coordinator.async_request_refresh() for coordinator in coordinators])

    _LOGGER.debug("Setting up periodic refresh for all coordinators")

    unsub_refresh = async_track_time_interval(
        hass, _force_coordinator_refresh, timedelta(seconds=1.5)
    )
    entry.async_on_unload(unsub_refresh)

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinators": coordinators,
        "controller": controller,
        "unsub_control": unsub_control,
        "unsub_refresh": unsub_refresh,
    }

    # Listen for config entry updates so config entities refresh their state
    async def _async_update_listener(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        """Handle config entry updates (from Options Flow or config entities)."""
        _LOGGER.debug("Config entry updated, hot-reloading controller parameters")
        if controller:
            controller.update_pd_parameters()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Schedule daily consumption capture at 23:55 local time every day
    # This captures the day's battery discharge energy before the sensor resets at midnight local
    # Also needed for weekly full charge delay (to estimate remaining consumption)
    needs_consumption_capture = (
        controller.predictive_charging_enabled
        or controller.charge_delay_enabled
    )
    if needs_consumption_capture:
        entry.async_on_unload(
            async_track_time_change(
                hass, controller._capture_daily_consumption, hour=23, minute=55, second=0
            )
        )
        _LOGGER.info("Daily consumption capture scheduled at 23:55 local time")

    # Schedule solar forecast capture at 23:00 every night for charge delay
    if controller.charge_delay_enabled:
        entry.async_on_unload(
            async_track_time_change(
                hass, controller._capture_solar_forecast, hour=23, minute=0, second=0
            )
        )
        _LOGGER.info("Charge Delay: Forecast capture scheduled at 23:00 local time")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Replace default consumption data with real recorder data
    # On reload HA is already running, so backfill immediately;
    # on fresh boot, wait for homeassistant_started so the recorder is ready
    if needs_consumption_capture:
        if hass.state == CoreState.running:
            await controller._startup_backfill_consumption()
            _LOGGER.info("Startup consumption backfill executed immediately (reload)")
        else:
            async def _on_homeassistant_started(_event):
                await controller._startup_backfill_consumption()

            entry.async_on_unload(
                hass.bus.async_listen(
                    "homeassistant_started", _on_homeassistant_started
                )
            )
            _LOGGER.info("Startup consumption backfill scheduled for after HA fully started")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    if data := hass.data[DOMAIN].get(entry.entry_id):
        coordinators = data.get("coordinators", [])

        # 1. Cancel periodic timers FIRST to stop control loop and coordinator refresh
        # These run every 2.0s / 1.5s and would write registers on a closing connection
        if unsub := data.get("unsub_control"):
            unsub()
        if unsub := data.get("unsub_refresh"):
            unsub()

        # 2. Set shutdown flag on all coordinators to suppress expected errors
        for coordinator in coordinators:
            coordinator.set_shutting_down(True)

        # 3. Brief delay to let any in-flight control loop iteration complete
        await asyncio.sleep(0.3)

    # 4. Unload platforms (removes entities)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # 5. Write shutdown registers and disconnect (no more interference from timers)
    if data := hass.data[DOMAIN].get(entry.entry_id):
        coordinators = data.get("coordinators", [])

        _LOGGER.info("Shutting down integration - stopping all battery operations")
        for coordinator in coordinators:
            try:
                # Get version-specific registers
                discharge_reg = coordinator.get_register("set_discharge_power")
                charge_reg = coordinator.get_register("set_charge_power")
                force_reg = coordinator.get_register("force_mode")
                rs485_reg = coordinator.get_register("rs485_control")

                # Set all power commands to 0
                _LOGGER.info("Setting %s to standby mode", coordinator.name)
                if discharge_reg:
                    await coordinator.write_register(discharge_reg, 0, do_refresh=False)
                    await asyncio.sleep(0.05)
                if charge_reg:
                    await coordinator.write_register(charge_reg, 0, do_refresh=False)
                    await asyncio.sleep(0.05)
                if force_reg:
                    await coordinator.write_register(force_reg, 0, do_refresh=False)
                    await asyncio.sleep(0.05)

                # Disable RS485 Control Mode (return control to battery's internal logic)
                _LOGGER.info("Disabling RS485 control mode for %s", coordinator.name)
                if rs485_reg:
                    await coordinator.write_register(rs485_reg, 21947, do_refresh=False)  # 0x55BB = disable
                    await asyncio.sleep(0.1)

                _LOGGER.info("%s: Shutdown complete - all control registers reset", coordinator.name)
            except Exception as e:
                _LOGGER.error("Error shutting down battery %s: %s", coordinator.name, e)

        # Disconnect from all coordinators
        await asyncio.gather(*[c.disconnect() for c in coordinators])

        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
