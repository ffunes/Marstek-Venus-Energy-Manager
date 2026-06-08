"""The Marstek Venus Energy Manager integration."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_track_time_interval, async_track_time_change, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from pymodbus.exceptions import ConnectionException

from .const import (
    DOMAIN,
    CONF_ENABLE_PREDICTIVE_CHARGING,
    CONF_CHARGING_TIME_SLOT,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_HOUSEHOLD_CONSUMPTION_SENSOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_MAX_CONTRACTED_POWER,
    should_use_household_sensor,
    DEFAULT_BASE_CONSUMPTION_KWH,
    SOC_REEVALUATION_THRESHOLD,
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
    DELAY_SOC_SETPOINT_HYSTERESIS,
    CHARGE_EFFICIENCY,
    DELAY_SAFETY_FACTOR,
    T_START_FALLBACK_HOUR,
    EVENING_REEVAL_HOURS_BEFORE_TEND,
    EVENING_REEVAL_FALLBACK_HOUR,
    EVENING_DEFICIT_THRESHOLD_KWH,
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
    CONF_PD_RELAY_COOLDOWN,
    DEFAULT_PD_RELAY_COOLDOWN,
    RELAY_COOLDOWN_HOLD_POWER,
    CONF_PD_MIN_CYCLE_INTERVAL,
    DEFAULT_PD_MIN_CYCLE_INTERVAL,
    CONF_TARGET_GRID_POWER,
    DEFAULT_TARGET_GRID_POWER,
    CONF_ENABLE_SYSTEM_POWER_LIMITS,
    CONF_SYSTEM_MAX_CHARGE_POWER,
    CONF_SYSTEM_MAX_DISCHARGE_POWER,
    DEFAULT_ENABLE_SYSTEM_POWER_LIMITS,
    DEFAULT_SYSTEM_MAX_CHARGE_POWER,
    DEFAULT_SYSTEM_MAX_DISCHARGE_POWER,
    CONF_CAPACITY_PROTECTION_ENABLED,
    CONF_CAPACITY_PROTECTION_SOC_THRESHOLD,
    CONF_CAPACITY_PROTECTION_LIMIT,
    DEFAULT_CAPACITY_PROTECTION_SOC,
    DEFAULT_CAPACITY_PROTECTION_LIMIT,
    CONF_MANUAL_MODE_ENABLED,
    CONF_PREDICTIVE_CHARGING_OVERRIDDEN,
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
    MULTI_BATTERY_DISCHARGE_CROSSOVER_W,
    MULTI_BATTERY_CHARGE_CROSSOVER_W,
    MULTI_BATTERY_HYSTERESIS_GAP,
    MULTI_BATTERY_MIN_ACTIVATION,
    MULTI_BATTERY_MAX_ACTIVATION,
    MULTI_BATTERY_SELECTION_HOLD_SECONDS,
    CONF_ENABLE_HOURLY_BALANCE,
    CONF_HOURLY_BALANCE_TARGET_NET_WH,
    CONF_HOURLY_BALANCE_MAX_OFFSET_W,
    DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
    DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
    NORMAL_BALANCE_TAPER_CELL_VOLTAGE,
    NORMAL_BALANCE_PAUSE_CELL_VOLTAGE,
    NORMAL_BALANCE_CHARGE_POWER_W,
    NORMAL_BALANCE_MEASURE_WAIT_SECONDS,
    NORMAL_BALANCE_RECAL_SOC_THRESHOLD,
    NORMAL_BALANCE_RECAL_CUTOFF_POWER_W,
    NORMAL_BALANCE_RECAL_CUTOFF_CYCLES,
    NORMAL_BALANCE_RECAL_INVERTER_STANDBY,
    BMS_DISCHARGE_CUTOFF_SOC,
    CONF_ACTIVE_BALANCE_MODE_ENABLED,
    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    DEBUG_CONTROL_LOOP_DETAIL,
)
from .coordinator import MarstekVenusDataUpdateCoordinator
from .hourly_balance import HourlyBalanceManager
from .non_responsive_tracker import NonResponsiveTracker
from .weekly_full_charge import WeeklyFullChargeManager
from .active_balance_mode import ActiveBalanceModeManager

_LOGGER = logging.getLogger(__name__)

# Dynamic pricing data structures
PriceSlot = namedtuple("PriceSlot", ["start", "end", "price"])

# Charge taper is voltage-only. SOC is deliberately ignored near the top because
# some batteries report unstable SOC values while cell voltage remains reliable.
FULL_CHARGE_TAPER_STEPS = ()


@dataclass
class DynamicPricingSchedule:
    """Stores the result of a dynamic pricing evaluation."""
    hours_needed: float
    selected_slots: list  # list[PriceSlot]
    average_price: float
    estimated_cost: float
    total_available_slots: int
    evaluation_time: datetime
    energy_deficit_kwh: float
    charging_needed: bool = True

# List of platforms to support.
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

# Sidebar dashboard panel served with the integration.
PANEL_URL_PATH = "marstek-venus"
PANEL_STATIC_PATH = "/marstek_venus_energy_manager_static"
PANEL_TITLE = "Marstek Venus"
PANEL_ICON = "mdi:home-battery"
_PANEL_REGISTERED_KEY = "_panel_registered"
_STATIC_REGISTERED_KEY = "_panel_static_registered"


async def _async_register_frontend_panel(hass: HomeAssistant, entry: ConfigEntry | None = None) -> None:
    """Register (or refresh) the custom sidebar panel.

    Serves the integration's ``frontend`` directory as a static path (once per
    HA run) and (re)registers the ``marstek-venus-panel`` web component as a
    sidebar panel on every setup, so the module URL and config payload refresh
    when the integration reloads. The configured grid/home power sensors are
    forwarded to the panel so the energy-flow diagram can wire its Grid/Home
    nodes without hardcoding.

    The module URL is cache-busted by the JS file's mtime so any edit to the
    dashboard is picked up by the browser after a reload — without needing an
    integration version bump.
    Non-critical: failures are logged but never block integration setup.
    """
    try:
        from pathlib import Path

        from homeassistant.components import frontend, panel_custom
        from homeassistant.components.http import StaticPathConfig

        frontend_dir = Path(__file__).parent / "frontend"
        domain_data = hass.data.setdefault(DOMAIN, {})

        # Static path can only be registered once per HA run.
        if not domain_data.get(_STATIC_REGISTERED_KEY):
            await hass.http.async_register_static_paths(
                [StaticPathConfig(PANEL_STATIC_PATH, str(frontend_dir), cache_headers=False)]
            )
            domain_data[_STATIC_REGISTERED_KEY] = True

        # Cache-bust by the JS file mtime (changes on every edit/deploy); fall
        # back to the integration version if the file can't be stat'd.
        js_file = frontend_dir / "marstek-panel.js"
        try:
            cache_bust = str(int(js_file.stat().st_mtime))
        except Exception:  # noqa: BLE001
            from homeassistant.loader import async_get_integration

            try:
                cache_bust = (await async_get_integration(hass, DOMAIN)).version or "0"
            except Exception:  # noqa: BLE001
                cache_bust = "0"

        panel_config = {"domain": DOMAIN, "title": PANEL_TITLE}
        if entry is not None:
            from .const import (
                CONF_HOUSEHOLD_CONSUMPTION_SENSOR,
                CONF_SOLAR_FORECAST_SENSOR,
                CONF_SOLAR_PRODUCTION_SENSOR,
            )

            data = entry.data
            # consumption_sensor is the net grid meter (+import / -export) the PD
            # loop regulates — it is the Grid node of the flow diagram.
            if data.get("consumption_sensor"):
                panel_config["grid_entity"] = data["consumption_sensor"]
                # PD convention is +import / -export; if the user's meter is wired
                # the other way the integration negates it (meter_inverted). Forward
                # the flag so the panel applies the same sign to the Grid node and
                # the power-history chart.
                panel_config["grid_inverted"] = bool(data.get(CONF_METER_INVERTED, False))
            if data.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR):
                panel_config["home_entity"] = data[CONF_HOUSEHOLD_CONSUMPTION_SENSOR]
            if data.get(CONF_SOLAR_FORECAST_SENSOR):
                panel_config["solar_forecast_entity"] = data[CONF_SOLAR_FORECAST_SENSOR]
            # Real-time PV production for the Solar node when panels are not wired
            # through the battery MPPT inputs (external inverter).
            if data.get(CONF_SOLAR_PRODUCTION_SENSOR):
                panel_config["solar_entity"] = data[CONF_SOLAR_PRODUCTION_SENSOR]

        # Remove any previous registration so the module URL / config refresh.
        # warn_if_unknown=False: on first setup after restart the panel isn't
        # registered yet, and HA would log "Removing unknown panel marstek-venus".
        try:
            frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        except Exception:  # noqa: BLE001 - not registered yet is fine
            pass

        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name="marstek-venus-panel",
            module_url=f"{PANEL_STATIC_PATH}/marstek-panel.js?v={cache_bust}",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
            config=panel_config,
        )
        domain_data[_PANEL_REGISTERED_KEY] = True
        _LOGGER.info(
            "Registered Marstek Venus sidebar panel at /%s (v=%s)", PANEL_URL_PATH, cache_bust
        )
    except Exception as e:  # noqa: BLE001 - panel is optional, never block setup
        _LOGGER.warning("Could not register Marstek Venus sidebar panel: %s", e)


@callback
def _async_unregister_frontend_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when the last config entry unloads."""
    if not hass.data.get(DOMAIN, {}).get(_PANEL_REGISTERED_KEY):
        return
    try:
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("Error removing Marstek Venus panel: %s", e)
    finally:
        hass.data[DOMAIN][_PANEL_REGISTERED_KEY] = False


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

        # Grid meter options
        self.meter_inverted = config_entry.data.get(CONF_METER_INVERTED, False)

        # Load PD controller parameters from config (with backward-compatible defaults)
        self.deadband = config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        self.kp = config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP)
        self.kd = config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD)
        self.max_power_change_per_cycle = config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        self.direction_hysteresis = config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        self.min_charge_power = config_entry.data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        self.min_discharge_power = config_entry.data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)
        # Relay anti-chatter (minimum-ON dwell). _relay_engage_since is set when the
        # battery transitions idle->active; the dwell blocks the active->idle return.
        self._relay_cooldown_s = config_entry.data.get(CONF_PD_RELAY_COOLDOWN, DEFAULT_PD_RELAY_COOLDOWN)
        self._relay_engage_since = None
        # Event-driven cycle rate limit: drop grid-sensor triggers that arrive
        # closer together than this, so fast meters can't flood the Modbus bridge.
        self._min_cycle_interval_s = config_entry.data.get(CONF_PD_MIN_CYCLE_INTERVAL, DEFAULT_PD_MIN_CYCLE_INTERVAL)
        self._last_cycle_monotonic = 0.0
        self.target_grid_power = config_entry.data.get(CONF_TARGET_GRID_POWER, DEFAULT_TARGET_GRID_POWER)
        self.enable_system_power_limits = config_entry.data.get(
            CONF_ENABLE_SYSTEM_POWER_LIMITS,
            (
                (config_entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER) or 0) > 0
                or (config_entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER) or 0) > 0
            ),
        )
        self.system_max_charge_power = config_entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER)
        self.system_max_discharge_power = config_entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER)

        # Sensor filtering to avoid reacting to instantaneous spikes. Time-constant
        # EMA (alpha = elapsed/(tau+elapsed)) instead of a fixed N-sample average, so
        # the smoothing time stays constant under the variable event-driven cadence.
        self._grid_filter_tau = 2.0     # seconds; larger = smoother but more lag
        self._grid_filter_ema = None    # filtered grid value (W); None until first sample

        # PID controller state variables (Ki currently disabled)
        self.ki = 0.0          # Integral gain (DISABLED - using pure PD control)
        self.error_integral = 0.0      # Accumulated error
        self.previous_error = 0.0      # Previous error for derivative
        self.dt = 2.0                  # Nominal control loop time (s); used to normalize cadence-dependent terms
        self.integral_decay = 0.90     # Leaky integrator: 10% decay per cycle

        # Derivative low-pass filter: smooth the noisy grid derivative so the D term
        # does not inject sensor/PWM/quantization noise into the output. EMA whose
        # alpha is computed per-cycle from real elapsed time (alpha = dt/(tau+dt)).
        self.derivative_tau = 3.0       # seconds; larger = smoother but more lag
        self.derivative_filtered = 0.0  # filtered derivative state

        # Control-quality metrics surfaced via the system_pd_control_quality sensor
        # so the user can see the effect of the PD profile/sliders. Time-constant
        # EMAs (alpha = dt/(tau+dt)) keep the averaging window constant under the
        # variable event-driven cadence, like the rest of the loop.
        self._pd_quality_tau = 60.0      # seconds; metric averaging window
        self._pd_quality_rms_ema = None  # EMA of error^2 (W^2); sqrt -> RMS error
        self._pd_quality_osc_ema = 0.0   # EMA of error-sign changes per minute
        self._pd_quality_last_ts = None  # monotonic ts of last metric update
        # Ignore the tracking transient after any setpoint/target step (hourly
        # balance, capacity protection, user target change, ...) so it doesn't
        # inflate RMS/oscillation. Source-agnostic: keys on active_target moving.
        self._pd_quality_step_grace_s = 10.0  # skip the metric this long after a step
        self._pd_quality_settle_until = 0.0   # monotonic deadline; skip while now < this
        self._pd_quality_prev_target = None   # previous active_target for step detection
        # True when the PD has no headroom to reduce the error (battery full while it
        # would charge, empty while it would discharge, or output pinned at the power
        # rail). Surfaced as the "battery_limited" quality state; not a tuning fault.
        self._pd_limited = False

        # Measured-power anti-windup (back-calculation): re-anchor the incremental
        # base to the battery's real AC output when commanded power is not being
        # delivered (saturation/ramp lag not captured by the capacity clamp).
        self.saturation_backcalc_threshold = 150.0  # W shortfall to count as saturation
        self.saturation_backcalc_cycles = 3          # sustained cycles before re-anchoring
        self._saturation_cycles = 0

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
        self._control_lock = asyncio.Lock()     # serialize control cycle across timer + sensor-event triggers
        self._grid_at_min_soc_last_ts = None     # last accumulation timestamp for grid-at-min-soc kWh integration

        # Normal high-SOC charge protection. These must exist before the first
        # capacity calculation because _battery_power_limit() reads them.
        self._normal_balance_date = dt_util.now().date()
        self._normal_balance_charge_paused: dict[MarstekVenusDataUpdateCoordinator, bool] = {}
        self._normal_balance_voltage_tapered: dict[MarstekVenusDataUpdateCoordinator, bool] = {}
        self._normal_active_balance_phases: dict[MarstekVenusDataUpdateCoordinator, str] = {}
        self._normal_balance_measure_started: dict[MarstekVenusDataUpdateCoordinator, datetime] = {}
        self._normal_balance_last_delta_v: dict[MarstekVenusDataUpdateCoordinator, float] = {}
        self._normal_balance_top_voltage_seen: dict[MarstekVenusDataUpdateCoordinator, bool] = {}
        # SOC recalibration override: keep charging past the tapper pause when the
        # BMS reports a low SOC at the top voltage, until the BMS itself cuts off.
        self._normal_balance_recal_override: dict[MarstekVenusDataUpdateCoordinator, bool] = {}
        self._normal_balance_recal_cutoff_count: dict[MarstekVenusDataUpdateCoordinator, int] = {}
        self._normal_balance_recal_latched: dict[MarstekVenusDataUpdateCoordinator, bool] = {}
        self._active_balance_mgr = ActiveBalanceModeManager(hass, self)
        
        # Calculate dynamic anti-windup limits based on total system capacity
        self.max_charge_capacity = self._effective_system_capacity(coordinators, is_charging=True)
        self.max_discharge_capacity = self._effective_system_capacity(coordinators, is_charging=False)

        # Load sharing state: track which batteries were active last cycle
        self._active_discharge_batteries = []
        self._active_charge_batteries = []
        self._discharge_selection_hold_until = {}
        self._charge_selection_hold_until = {}

        # Non-responsive battery tracking: excludes batteries that ACK commands but don't deliver power
        self._non_responsive = NonResponsiveTracker()
        # Alias to the tracker's internal dict for backward-compat with sensor.py diagnostics
        self._non_responsive_batteries = self._non_responsive.batteries

        # Coordinators currently owned by a manual time-slot this cycle.
        # PD/predictive logic must not touch these — _set_battery_power short-circuits.
        self._manual_slot_owned: set = set()

        # Backup function cooldown: prevents re-entering PD control immediately after offgrid load drops.
        # Format: coordinator -> datetime (UTC) until which the battery stays excluded
        self._backup_cooldown_until: dict = {}

        # EV charger no-telemetry state tracking
        self._ev_charging_states: dict[str, bool] = {}  # sensor_id -> is EV currently charging
        self._ev_pause_until: dict[str, Optional[datetime]] = {}  # sensor_id -> pause end time (UTC)
        
        # Predictive Grid Charging state
        self.predictive_charging_enabled = config_entry.data.get(CONF_ENABLE_PREDICTIVE_CHARGING, False)
        self.charging_time_slot = config_entry.data.get(CONF_CHARGING_TIME_SLOT, None)
        self.solar_forecast_sensor = config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR, None)
        self.household_consumption_sensor = config_entry.data.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR, None)
        self.solar_production_sensor = config_entry.data.get(CONF_SOLAR_PRODUCTION_SENSOR, None)
        self.max_contracted_power = config_entry.data.get(CONF_MAX_CONTRACTED_POWER, 7000)

        # Household consumption accumulator (integration of power sensor over solar+battery window)
        # Owned by ConsumptionTracker (see consumption_tracker.py); these public attrs
        # remain on the controller so binary_sensor.py and aggregate_sensors.py keep reading them.
        self._household_energy_accumulator = 0.0
        self._household_accumulator_date = None  # date when accumulator was last reset

        # Solar production accumulator (house + battery_net - grid, integrated over the day)
        self._solar_production_accumulator = 0.0
        self._solar_accumulator_date = None  # date when solar accumulator was last reset

        # Exact full-day energy totals, integrated from the REAL power sensors
        # (solar_production_sensor / household_consumption_sensor) at control-loop
        # cadence, reset at local midnight, persisted/restored. Surfaced as the
        # system_daily_solar_energy / system_daily_home_energy sensors.
        self._daily_solar_energy_kwh = 0.0
        self._daily_solar_energy_date = None
        self._daily_home_energy_kwh = 0.0
        self._daily_home_energy_date = None
        # Exact daily grid import/export (kWh), sign-split from the net consumption
        # meter (+import / -export). Surfaced as system_daily_grid_import_energy /
        # system_daily_grid_export_energy. Shared reset date (one source sensor).
        self._daily_grid_import_energy_kwh = 0.0
        self._daily_grid_export_energy_kwh = 0.0
        self._daily_grid_energy_date = None

        # State tracking for predictive charging
        self.grid_charging_active = False  # True when mode is active
        self.last_evaluation_soc = None    # SOC at last check
        self.predictive_charging_overridden = config_entry.data.get(CONF_PREDICTIVE_CHARGING_OVERRIDDEN, False)
        self._grid_charging_initialized = False  # Flag for initialization
        self._last_decision_data = None  # Store last decision for diagnostics
        self._slot_entry_time = None  # When we first entered the time slot (for 5-min delay)
        self._predictive_charge_target_soc: Optional[dict] = None  # Per-battery grid-only SOC targets {coordinator: target_%}

        # Real-time Price Mode state
        self.average_price_sensor = config_entry.data.get(CONF_AVERAGE_PRICE_SENSOR, None)
        self._realtime_price_charging: bool = False  # True while actively charging in this mode
        self.rt_price_discharge_control: bool = config_entry.data.get(CONF_RT_PRICE_DISCHARGE_CONTROL, False)

        # Dynamic Pricing Mode state
        self.predictive_charging_mode = config_entry.data.get(CONF_PREDICTIVE_CHARGING_MODE, PREDICTIVE_MODE_TIME_SLOT)
        self.price_sensor = config_entry.data.get(CONF_PRICE_SENSOR, None)
        self.price_integration_type = config_entry.data.get(CONF_PRICE_INTEGRATION_TYPE, PRICE_INTEGRATION_NORDPOOL)
        self.max_price_threshold = config_entry.data.get(CONF_MAX_PRICE_THRESHOLD, None)
        self.dp_price_discharge_control: bool = config_entry.data.get(CONF_DP_PRICE_DISCHARGE_CONTROL, False)
        self._dp_daily_avg_price: Optional[float] = None  # Computed from price slots in _evaluate_dynamic_pricing

        # Price-based discharge control flag (set each cycle by pricing handlers, consumed by PD section)
        self._price_based_discharge_blocked: bool = False
        self._global_charge_blockers: dict[str, dict] = {}
        self._global_discharge_blockers: dict[str, dict] = {}
        self._battery_charge_blockers: dict[MarstekVenusDataUpdateCoordinator, dict[str, dict]] = {}
        self._battery_discharge_blockers: dict[MarstekVenusDataUpdateCoordinator, dict[str, dict]] = {}
        self._dynamic_pricing_schedule: Optional[DynamicPricingSchedule] = None
        self._dynamic_pricing_evaluated_date = None
        self._current_price_slot_active = False
        self._dp_eval_retry_count = 0  # Retry counter if tomorrow prices not available at 23:00
        self._dp_pre_evaluated_slots: dict = {}  # slot.start (datetime) → should_charge (bool)
        self._price_data_status = "not_evaluated"
        self._dp_evening_reevaluated_date = None  # Prevent multiple evening re-evaluations per day

        # Consumption history for dynamic base consumption (7-day rolling average)
        # Owned by ConsumptionTracker; the list lives on the controller so
        # binary_sensor.py can read it as part of predictive_charging_active attrs.
        self._daily_consumption_history = []  # List of (date, consumption_kwh)

        # Grid import accumulator when batteries are at min_soc during discharge window
        self._daily_grid_at_min_soc_kwh = 0.0
        self._grid_at_min_soc_sensor = None  # Reference to HA sensor entity for state push

        # Manual mode state
        self.manual_mode_enabled = config_entry.data.get(CONF_MANUAL_MODE_ENABLED, False)

        # Setpoint offset registry (reference = 0 W grid flow)
        # - Additive offsets: summed to form the base target
        # - Absolute overrides: highest priority wins, replaces additive sum
        self._setpoint_offsets: dict[str, float] = {
            "user_target": self.target_grid_power,  # user's preference from config
        }
        self._setpoint_overrides: dict[str, tuple[int, float]] = {}  # source → (priority, value_w)

        self._rate_limiter_was_active = False
        self._rate_limiter_last_direction = 0
        self._rate_limiter_last_logged_change: float | None = None

        # Capacity Protection Mode state
        self.capacity_protection_enabled = config_entry.data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)
        self.capacity_protection_soc_threshold = config_entry.data.get(CONF_CAPACITY_PROTECTION_SOC_THRESHOLD, DEFAULT_CAPACITY_PROTECTION_SOC)
        self.capacity_protection_limit = config_entry.data.get(CONF_CAPACITY_PROTECTION_LIMIT, DEFAULT_CAPACITY_PROTECTION_LIMIT)
        self._capacity_protection_active = False  # True when SOC < threshold (protection is intervening)
        self._excluded_included_adjustment = 0.0  # Tracks excluded device adjustment for included_in_consumption devices
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
        self._capacity_protection_force_idle = False

        # Weekly Full Charge state
        self.weekly_full_charge_enabled = config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False)
        self.weekly_full_charge_day = config_entry.data.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")
        self.weekly_full_charge_complete = False  # True when the weekly charge to 100% has completed
        self.last_checked_weekday = None  # Track day transitions for reset logic
        self.weekly_full_charge_registers_written = False  # True when register 44000 set to 100%
        self._weekly_charge_needs_restore = False  # True when day changed mid-charge and hardware restore is pending
        self._weekly_charge_saved_max_soc: dict[str, int] = {}  # coordinator.name → original max_soc before writing 100%

        # Unified Charge Delay state
        # Backward compat: new key takes priority, fallback to old keys
        self.charge_delay_enabled = config_entry.data.get(
            CONF_ENABLE_CHARGE_DELAY,
            config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        )
        self._delay_safety_margin_h = config_entry.data.get(CONF_DELAY_SAFETY_MARGIN_MIN, DEFAULT_DELAY_SAFETY_MARGIN_MIN) / 60.0
        self._delay_soc_setpoint_enabled = config_entry.data.get(CONF_DELAY_SOC_SETPOINT_ENABLED, DEFAULT_DELAY_SOC_SETPOINT_ENABLED)
        self._delay_soc_setpoint = config_entry.data.get(CONF_DELAY_SOC_SETPOINT, DEFAULT_DELAY_SOC_SETPOINT)
        self._balance_monitor_enabled = True
        self._predictive_safety_margin_kwh: float = config_entry.data.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
        self._predictive_grid_charge_margin_pct: float = config_entry.data.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)
        self._charge_delay_unlocked = False       # True when delay has been unlocked today
        self._delay_setpoint_reached = False      # True once SOC first reached the setpoint
        self._charge_delay_store: Store = Store(
            hass, 1, f"{DOMAIN}.{config_entry.entry_id}.charge_delay_state"
        )
        self._charge_delay_save_task: asyncio.Task | None = None
        self._balance_monitor = None  # Set from async_setup_entry after monitor is created

        # Hourly Net Balance
        self.hourly_balance_enabled = config_entry.data.get(CONF_ENABLE_HOURLY_BALANCE, False)
        self._hourly_balance_mgr: HourlyBalanceManager | None = (
            HourlyBalanceManager(hass, config_entry, self)
            if CONF_ENABLE_HOURLY_BALANCE in config_entry.data else None
        )
        self._charge_delay_last_date = None       # For daily reset
        self._charge_delay_forecast_cache = None  # Last forecast value used for balance check
        self._charge_delay_balance_needs_charge = True  # Cached balance result (conservative default)
        self._forecast_unavailable_since = None   # monotonic ts when a configured forecast sensor first read unavailable
        self._forecast_grace_s = 300              # hold the delay through forecast blips / HA-startup sensor loading before unlocking
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
            "soc_setpoint": self._delay_soc_setpoint if self._delay_soc_setpoint_enabled else None,
        }

        # Minimal status dict for WeeklyFullChargeSensor (charge state only, not delay)
        self._weekly_charge_status = {
            "state": "Disabled" if not self.weekly_full_charge_enabled else "Idle",
        }

        # Weekly full charge management (owns its own Store internally)
        self._weekly_charge_mgr = WeeklyFullChargeManager(hass, config_entry, self)
        # Backward-compat alias to the manager's underlying Store
        self._store = self._weekly_charge_mgr.store

        # ConsumptionTracker owns its own Stores (consumption history, accumulators,
        # solar T_start). Set from async_setup_entry after the controller exists.
        self._consumption_tracker = None

        _LOGGER.info("PD Controller initialized (user-configurable): Kp=%.2f, Ki=%.2f, Kd=%.2f, "
                     "Deadband=±%dW, Filter τ=%.1fs, Hysteresis=%dW, MaxChange=%dW/cycle, Limits: ±%dW",
                     self.kp, self.ki, self.kd,
                     self.deadband, self._grid_filter_tau, self.direction_hysteresis,
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

        _LOGGER.info("Hourly Net Balance: %s",
                     "ENABLED" if self.hourly_balance_enabled else "DISABLED")

    async def load_charge_delay_state(self) -> None:
        """Restore same-day charge delay latch state from storage."""
        if not self.charge_delay_enabled:
            return

        try:
            data = await self._charge_delay_store.async_load()
            if not data:
                return

            today_iso = dt_util.now().date().isoformat()
            if data.get("date") != today_iso:
                return

            self._charge_delay_unlocked = data.get("delay_unlocked", False)
            self._delay_setpoint_reached = data.get("delay_setpoint_reached", False)
            if data.get("solar_t_start") is not None:
                self._solar_t_start = data.get("solar_t_start")

            _LOGGER.info(
                "Charge Delay: restored state - unlocked=%s, setpoint_reached=%s",
                self._charge_delay_unlocked,
                self._delay_setpoint_reached,
            )
        except Exception as exc:
            _LOGGER.error("Charge Delay: failed to load persisted state: %s", exc)

    def _schedule_charge_delay_state_save(self) -> None:
        """Persist charge delay latch state without blocking the control loop."""
        if not self.charge_delay_enabled:
            return

        if self._charge_delay_save_task and not self._charge_delay_save_task.done():
            self._charge_delay_save_task.cancel()
        self._charge_delay_save_task = asyncio.create_task(
            self._deferred_save_charge_delay_state()
        )

    async def _deferred_save_charge_delay_state(self) -> None:
        """Let the current control-cycle state settle before saving."""
        await asyncio.sleep(0)
        await self._save_charge_delay_state()

    async def _save_charge_delay_state(self) -> None:
        """Save charge delay latch state to persistent storage."""
        try:
            await self._charge_delay_store.async_save({
                "date": dt_util.now().date().isoformat(),
                "delay_unlocked": self._charge_delay_unlocked,
                "delay_setpoint_reached": self._delay_setpoint_reached,
                "solar_t_start": self._solar_t_start,
                "timestamp": dt_util.now().isoformat(),
            })
        except Exception as exc:
            _LOGGER.error("Charge Delay: failed to save persisted state: %s", exc)

    def _configured_system_limit(self, is_charging: bool) -> int:
        """Return the optional system-wide power limit for the direction.

        0 means disabled, preserving the legacy behavior where only per-battery
        limits define total system capacity.
        """
        if not self.enable_system_power_limits:
            return 0

        raw_limit = (
            self.system_max_charge_power if is_charging
            else self.system_max_discharge_power
        )
        try:
            limit = int(raw_limit or 0)
        except (TypeError, ValueError):
            limit = 0
        return max(0, limit)

    def _effective_system_capacity(self, batteries: list, is_charging: bool) -> int:
        """Return available capacity after applying the optional global cap."""
        total_capacity = sum(
            self._battery_power_limit(c, is_charging)
            for c in batteries
        )
        system_limit = self._configured_system_limit(is_charging)
        if system_limit > 0:
            return min(total_capacity, system_limit)
        return total_capacity

    def _refresh_effective_system_capacities(self) -> None:
        """Refresh cached capacities used by PD anti-windup diagnostics."""
        self.max_charge_capacity = self._effective_system_capacity(
            self.coordinators,
            is_charging=True,
        )
        self.max_discharge_capacity = self._effective_system_capacity(
            self.coordinators,
            is_charging=False,
        )

    def _clamp_to_system_capacity(self, power: float, batteries: list, is_charging: bool) -> float:
        """Clamp a positive direction-specific power request to available capacity."""
        return min(power, self._effective_system_capacity(batteries, is_charging))

    def _normal_balance_reset_if_new_day(self) -> None:
        """Reset normal-balance latched state at the local day boundary."""
        today = dt_util.now().date()
        if today == self._normal_balance_date:
            return

        self._normal_balance_date = today
        self._normal_balance_charge_paused.clear()
        self._normal_balance_voltage_tapered.clear()
        self._normal_active_balance_phases.clear()
        self._normal_balance_measure_started.clear()
        self._normal_balance_last_delta_v.clear()
        self._normal_balance_top_voltage_seen.clear()
        self._normal_balance_recal_override.clear()
        self._normal_balance_recal_cutoff_count.clear()
        self._normal_balance_recal_latched.clear()
        for coordinator in self.coordinators:
            self.remove_charge_block("normal_balance_pause", coordinator=coordinator)

    @staticmethod
    def _cell_delta_v(data: dict) -> float | None:
        """Return current max-min cell delta in V when both voltages are known."""
        vmax = data.get("max_cell_voltage")
        vmin = data.get("min_cell_voltage")
        if vmax is None or vmin is None:
            return None
        try:
            return round(float(vmax) - float(vmin), 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _full_charge_voltage_taper_enabled(coordinator) -> bool:
        """Return True when this battery uses full-charge voltage tapering."""
        return bool(
            getattr(
                coordinator,
                CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
            )
        )

    @property
    def use_household_consumption_sensor(self) -> bool:
        """Whether to read the household sensor instead of deriving home power.

        Honoured only when a household sensor is configured AND no solar sensor
        exists; with solar, the derived value (grid + battery AC + solar) is
        preferred. See should_use_household_sensor().
        """
        return should_use_household_sensor(self.config_entry.data)

    def _full_charge_voltage_taper_applies(self, coordinator) -> bool:
        """Return True when the current charge target is 100%, excluding active balance ownership."""
        if not self._full_charge_voltage_taper_enabled(coordinator):
            return False
        if self._is_active_balance_mode_running(coordinator):
            return False
        if getattr(coordinator, "active_balance_mode_enabled", False):
            return False
        if coordinator.max_soc >= 100:
            return True
        if hasattr(self, "_weekly_charge_mgr") and self._weekly_full_charge_unlocked():
            return True
        return False

    def _normal_balance_zone_active(self, coordinator) -> bool:
        """Return True when the battery is in the normal top-balancing zone."""
        if not self._full_charge_voltage_taper_applies(coordinator):
            return False

        data = coordinator.data or {}
        vmax = data.get("max_cell_voltage")
        try:
            if vmax is not None and float(vmax) >= NORMAL_BALANCE_TAPER_CELL_VOLTAGE:
                return True
        except (TypeError, ValueError):
            return False
        return False

    def _compute_recal_override(self, coordinator, vmax_f: float, soc) -> bool:
        """Decide whether to keep charging past the tapper pause to recalibrate SOC.

        Called only when the max cell sits at the pause voltage. A low reported
        SOC at full cell voltage means the BMS coulomb counter has drifted, so
        keep charging (at the tapered power) until the BMS itself cuts off, then
        latch off so the SOC can recalibrate to 100%. The latch clears when the
        battery leaves the top zone (see _refresh_normal_balance_blocks).
        """
        if soc is None or soc >= NORMAL_BALANCE_RECAL_SOC_THRESHOLD:
            self._normal_balance_recal_cutoff_count.pop(coordinator, None)
            return False
        if self._normal_balance_recal_latched.get(coordinator):
            return False

        data = coordinator.data or {}
        power = data.get("battery_power")
        inv = data.get("inverter_state")
        try:
            cutoff = (
                power is not None
                and inv is not None
                and float(power) <= NORMAL_BALANCE_RECAL_CUTOFF_POWER_W
                and int(inv) == NORMAL_BALANCE_RECAL_INVERTER_STANDBY
            )
        except (TypeError, ValueError):
            cutoff = False

        if cutoff:
            count = self._normal_balance_recal_cutoff_count.get(coordinator, 0) + 1
            self._normal_balance_recal_cutoff_count[coordinator] = count
            if count >= NORMAL_BALANCE_RECAL_CUTOFF_CYCLES:
                self._normal_balance_recal_latched[coordinator] = True
                self._normal_balance_recal_cutoff_count.pop(coordinator, None)
                _LOGGER.info(
                    "%s: BMS cutoff during SOC recalibration at vmax=%.3f V, SOC=%s%% — "
                    "holding; SOC should recalibrate to 100%%",
                    coordinator.name, vmax_f, soc,
                )
                return False
        else:
            self._normal_balance_recal_cutoff_count.pop(coordinator, None)
        return True

    def _clear_recal_state(self, coordinator) -> None:
        """Drop all SOC-recalibration state for a battery (session ended)."""
        self._normal_balance_recal_override.pop(coordinator, None)
        self._normal_balance_recal_cutoff_count.pop(coordinator, None)
        self._normal_balance_recal_latched.pop(coordinator, None)

    def _refresh_normal_balance_blocks(self) -> None:
        """Update normal high-SOC charge protection blockers.

        The normal mode does not force charging. It only stops charge while the
        max cell is at the 100% top voltage; SOC hysteresis decides when future
        charging is allowed.
        """
        self._normal_balance_reset_if_new_day()

        for coordinator in self.coordinators:
            data = coordinator.data or {}
            if not self._full_charge_voltage_taper_applies(coordinator):
                self._normal_balance_charge_paused.pop(coordinator, None)
                self._normal_balance_voltage_tapered.pop(coordinator, None)
                self._clear_recal_state(coordinator)
                self.remove_charge_block("normal_balance_pause", coordinator=coordinator)
                continue

            if not data:
                self._normal_balance_charge_paused.pop(coordinator, None)
                self._normal_balance_voltage_tapered.pop(coordinator, None)
                self._normal_balance_recal_override.pop(coordinator, None)
                self.remove_charge_block("normal_balance_pause", coordinator=coordinator)
                continue

            in_zone = self._normal_balance_zone_active(coordinator)
            if not in_zone:
                self._normal_balance_voltage_tapered.pop(coordinator, None)
                # Battery has dropped out of the top zone: end any recal session so
                # a later full charge can recalibrate again.
                self._clear_recal_state(coordinator)

            vmax = data.get("max_cell_voltage")
            paused = False
            if vmax is None:
                paused = False
            else:
                try:
                    vmax_f = float(vmax)
                except (TypeError, ValueError):
                    paused = False
                else:
                    if in_zone and vmax_f >= NORMAL_BALANCE_TAPER_CELL_VOLTAGE:
                        self._normal_balance_voltage_tapered[coordinator] = True
                    if in_zone and vmax_f >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE:
                        self._normal_balance_top_voltage_seen[coordinator] = True
                    if vmax_f >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE:
                        paused = True

            # SOC recalibration: if the pause would trigger but the BMS reports a
            # low SOC at the top voltage, keep charging until the BMS cuts off.
            override = False
            if paused:
                override = self._compute_recal_override(
                    coordinator, vmax_f, data.get("battery_soc")
                )
                if override:
                    paused = False
            self._normal_balance_recal_override[coordinator] = override

            if paused:
                self._normal_balance_charge_paused[coordinator] = True
                self.set_charge_block(
                    "normal_balance_pause",
                    "cell_voltage_pause",
                    {
                        "battery": coordinator.name,
                        "max_cell_voltage": vmax,
                        "delta_V": self._cell_delta_v(data),
                    },
                    coordinator=coordinator,
                )
            else:
                self._normal_balance_charge_paused.pop(coordinator, None)
                self.remove_charge_block("normal_balance_pause", coordinator=coordinator)

    def get_normal_balance_status(self) -> dict:
        """Return normal-balance diagnostics for the integration status sensor."""
        status = {}
        for coordinator in self.coordinators:
            data = coordinator.data or {}
            if not data:
                continue
            status[coordinator.name] = {
                "enabled": self._full_charge_voltage_taper_enabled(coordinator),
                "in_zone": self._normal_balance_zone_active(coordinator),
                "paused": self._normal_balance_charge_paused.get(coordinator, False),
                "max_cell_voltage": data.get("max_cell_voltage"),
                "min_cell_voltage": data.get("min_cell_voltage"),
                "delta_V": self._cell_delta_v(data),
                "voltage_taper_latched": getattr(
                    self, "_normal_balance_voltage_tapered", {}
                ).get(coordinator, False),
                "active_balance_phase": getattr(
                    self, "_normal_active_balance_phases", {}
                ).get(coordinator),
                "soc_recal_active": self._normal_balance_recal_override.get(coordinator, False),
                "soc_recal_bms_cutoff": self._normal_balance_recal_latched.get(coordinator, False),
                "charge_limit_w": self._battery_power_limit(coordinator, True),
            }
        return status

    def _active_balance_charge_resume_target(self, coordinator) -> float:
        return self._active_balance_mgr._active_balance_charge_resume_target(coordinator)

    def _reset_active_balance_charge_resume_target(self, coordinator) -> None:
        self._active_balance_mgr._reset_active_balance_charge_resume_target(coordinator)

    def _lower_active_balance_charge_resume_target(self, coordinator, vmax_f: float) -> float:
        return self._active_balance_mgr._lower_active_balance_charge_resume_target(coordinator, vmax_f)

    def _active_balance_charge_rejected_detected(self, coordinator, phase: str) -> bool:
        return self._active_balance_mgr._active_balance_charge_rejected_detected(coordinator, phase)

    def _pd_house_demand_present(self) -> bool:
        """Return True when the PD input indicates household/grid demand."""
        consumption_state = self.hass.states.get(self.consumption_sensor)
        sensor_raw = self._apply_meter_transform(consumption_state)
        if sensor_raw is None:
            return False
        active_target = self.compute_active_target()
        return sensor_raw > active_target + self.deadband

    async def _handle_normal_max_soc_active_balancing(self) -> bool:
        """Measure cell delta after any 100% target reaches top voltage."""
        active_details = {}
        took_over = False
        active_coordinators: set[MarstekVenusDataUpdateCoordinator] = set()

        for coordinator in self.coordinators:
            if coordinator.data is None or not self._full_charge_voltage_taper_applies(coordinator):
                continue
            if self._is_active_balance_mode_running(coordinator):
                continue
            if self._normal_balance_recal_override.get(coordinator):
                # SOC recalibration in progress: let PD keep charging to the BMS
                # cutoff instead of holding/measuring at the top voltage.
                self._normal_active_balance_phases.pop(coordinator, None)
                self._normal_balance_measure_started.pop(coordinator, None)
                continue
            if coordinator in self._normal_active_balance_phases:
                active_coordinators.add(coordinator)
                continue
            try:
                vmax = float(coordinator.data.get("max_cell_voltage"))
            except (TypeError, ValueError):
                continue
            if vmax >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE:
                self._normal_active_balance_phases[coordinator] = "WAIT_MEASURE"
                self._normal_balance_measure_started[coordinator] = dt_util.utcnow()
                active_coordinators.add(coordinator)

        for coordinator in list(self._normal_active_balance_phases):
            if coordinator not in active_coordinators:
                self._normal_active_balance_phases.pop(coordinator, None)
                self._normal_balance_measure_started.pop(coordinator, None)
                self._reset_active_balance_charge_resume_target(coordinator)

        for coordinator in active_coordinators:
            data = coordinator.data or {}
            try:
                vmax = float(data.get("max_cell_voltage"))
                vmin = float(data.get("min_cell_voltage"))
            except (TypeError, ValueError):
                self._normal_active_balance_phases.pop(coordinator, None)
                self._normal_balance_measure_started.pop(coordinator, None)
                self._reset_active_balance_charge_resume_target(coordinator)
                continue

            phase = self._normal_active_balance_phases.get(coordinator, "WAIT_MEASURE")
            charge_power = 0
            discharge_power = 0
            delta_v = round(vmax - vmin, 4)
            if phase == "WAIT_MEASURE":
                started = self._normal_balance_measure_started.setdefault(
                    coordinator,
                    dt_util.utcnow(),
                )
                if (dt_util.utcnow() - started).total_seconds() >= NORMAL_BALANCE_MEASURE_WAIT_SECONDS:
                    self._normal_balance_last_delta_v[coordinator] = delta_v
                    phase = "MEASURED"
                    self._normal_active_balance_phases[coordinator] = phase
                    if self._balance_monitor is not None:
                        await self._balance_monitor.async_record_top_balance_measurement(
                            coordinator,
                            vmax,
                            vmin,
                            data.get("battery_soc"),
                            phase="top_charge_3_55v",
                        )
                    _LOGGER.info(
                        "%s: normal 100%% balance measurement delta=%.4f V at vmax=%.3f V",
                        coordinator.name,
                        delta_v,
                        vmax,
                    )
            if phase == "MEASURED" and vmax < NORMAL_BALANCE_PAUSE_CELL_VOLTAGE:
                self._normal_active_balance_phases.pop(coordinator, None)
                self._normal_balance_measure_started.pop(coordinator, None)
                self._reset_active_balance_charge_resume_target(coordinator)
                await self._set_battery_power(coordinator, 0, 0)
                continue

            details = {
                "phase": phase.lower(),
                "max_cell_voltage": round(vmax, 3),
                "min_cell_voltage": round(vmin, 3),
                "delta_V": delta_v,
                "charge_w": charge_power,
                "discharge_w": discharge_power,
            }
            active_details[coordinator.name] = details
            took_over = True

            await self._set_battery_power(
                coordinator,
                charge_power,
                discharge_power,
                ignore_charge_blockers={
                    "charge_delay",
                    "time_slot_charge",
                    "max_soc",
                    "charge_hysteresis",
                    "normal_balance_pause",
                },
                ignore_discharge_blockers={
                    "time_slot_discharge",
                    "price_discharge",
                    "min_soc",
                },
            )

        if active_details:
            _LOGGER.debug("Normal max-SOC active balancing: %s", active_details)
        return took_over

    def _persist_battery_runtime_config(self, coordinator, updates: dict) -> None:
        """Persist multiple per-battery runtime values in one config-entry write."""
        if coordinator._config_entry is None:
            return
        new_data = dict(coordinator._config_entry.data)
        batteries = [dict(b) for b in new_data.get("batteries", [])]
        for battery in batteries:
            if (battery.get("host") == coordinator.host and battery.get("port") == coordinator.port
                    and battery.get("slave_id", 1) == coordinator.slave_id):
                battery.update(updates)
                break
        new_data["batteries"] = batteries
        self.hass.config_entries.async_update_entry(coordinator._config_entry, data=new_data)

    def _active_balance_mode_delta_v(self, coordinator) -> float | None:
        return self._active_balance_mgr._active_balance_mode_delta_v(coordinator)

    def _active_balance_mode_cell_values(self, coordinator) -> tuple[float | None, float | None, float | None]:
        return self._active_balance_mgr._active_balance_mode_cell_values(coordinator)

    async def _record_active_balance_mode_measurement(self, coordinator, details: dict) -> None:
        await self._active_balance_mgr._record_active_balance_mode_measurement(coordinator, details)

    def _active_balance_mode_last_recorded_delta_v(self, coordinator) -> tuple[float | None, str]:
        return self._active_balance_mgr._active_balance_mode_last_recorded_delta_v(coordinator)

    def _format_active_balance_value(self, value, unit: str, decimals: int = 1) -> str:
        return self._active_balance_mgr._format_active_balance_value(value, unit, decimals)

    def _active_balance_notification_id(self, coordinator, kind: str, started_ts: str | None = None, reason: str | None = None) -> str:
        return self._active_balance_mgr._active_balance_notification_id(coordinator, kind, started_ts, reason)

    async def _dismiss_persistent_notification(self, notification_id: str) -> None:
        await self._active_balance_mgr._dismiss_persistent_notification(notification_id)

    async def _dismiss_legacy_active_balance_notifications(self, coordinator) -> None:
        await self._active_balance_mgr._dismiss_legacy_active_balance_notifications(coordinator)

    async def _notify_active_balance_mode_started(self, coordinator, started_ts: str) -> None:
        await self._active_balance_mgr._notify_active_balance_mode_started(coordinator, started_ts)

    async def _notify_active_balance_mode_completed(self, coordinator, reason: str, started_ts: str | None, elapsed_h: float | None) -> None:
        await self._active_balance_mgr._notify_active_balance_mode_completed(coordinator, reason, started_ts, elapsed_h)

    def _is_active_balance_mode_running(self, coordinator) -> bool:
        return self._active_balance_mgr._is_active_balance_mode_running(coordinator)

    def _active_balance_mode_started(self, coordinator) -> bool:
        return self._active_balance_mgr._active_balance_mode_started(coordinator)

    def get_active_balance_mode_status(self) -> dict:
        return self._active_balance_mgr.get_active_balance_mode_status()

    async def _apply_active_balance_mode_cutoff(self, coordinator) -> None:
        await self._active_balance_mgr._apply_active_balance_mode_cutoff(coordinator)

    async def _restore_active_balance_mode_cutoff(self, coordinator) -> None:
        await self._active_balance_mgr._restore_active_balance_mode_cutoff(coordinator)

    async def _complete_active_balance_mode(self, coordinator, reason: str, today: str, mark_completed: bool = True) -> None:
        await self._active_balance_mgr._complete_active_balance_mode(coordinator, reason, today, mark_completed)

    async def _handle_active_balance_mode(self) -> None:
        await self._active_balance_mgr._handle_active_balance_mode()
    def _slot_manual_direction_for(self, slot: dict | None, coordinator) -> tuple[str, int] | None:
        """Return (direction, power_w) when `slot` is a valid manual single-direction
        slot for `coordinator`, or None.
        """
        if not slot or slot.get("mode") != "manual":
            return None
        if not slot.get("power_override_enabled"):
            return None
        allow_c = bool(slot.get("allow_charge"))
        allow_d = bool(slot.get("allow_discharge"))
        if allow_c and allow_d:
            return None  # ambiguous: degrade to PD
        limits = self._slot_battery_limits(slot, coordinator)
        if allow_d:
            val = limits.get("max_discharge_power_w")
            if val is None:
                return None
            return ("discharge", int(val))
        if allow_c:
            val = limits.get("max_charge_power_w")
            if val is None:
                return None
            return ("charge", int(val))
        return None

    async def _try_apply_manual_slot(self) -> None:
        """Drive batteries with an active manual time slot directly, bypassing PD.

        Manual slots take a battery off the PD/predictive control path for the
        cycle. Safety blockers (min/max SOC, EV pause, active balance) still
        apply — if a safety block is set, the manual write is skipped.
        """
        self._manual_slot_owned = set()
        for coord in self.coordinators:
            if not coord.is_available:
                continue
            if self._is_active_balance_mode_running(coord):
                continue
            if self._is_backup_function_active(coord):
                continue
            if coord.rs485_user_disabled:
                continue

            slot = self._get_active_slot(coord, "any")
            manual = self._slot_manual_direction_for(slot, coord)
            if manual is None:
                if slot and slot.get("mode") == "manual" \
                   and bool(slot.get("allow_charge")) and bool(slot.get("allow_discharge")):
                    _LOGGER.warning(
                        "[%s] Manual slot has both charge and discharge allowed — falling back to PD",
                        coord.name,
                    )
                continue
            direction, power = manual

            charge_blockers = self.get_charge_blockers(coord)
            discharge_blockers = self.get_discharge_blockers(coord)
            # Time-slot blockers don't apply against the slot that owns the battery.
            charge_safety = {k: v for k, v in charge_blockers.items() if k != "time_slot_charge"}
            discharge_safety = {k: v for k, v in discharge_blockers.items() if k != "time_slot_discharge"}
            if direction == "charge" and charge_safety:
                _LOGGER.debug(
                    "[%s] Manual slot charge skipped — safety blockers: %s",
                    coord.name, ", ".join(charge_safety.keys()),
                )
                continue
            if direction == "discharge" and discharge_safety:
                _LOGGER.debug(
                    "[%s] Manual slot discharge skipped — safety blockers: %s",
                    coord.name, ", ".join(discharge_safety.keys()),
                )
                continue

            if direction == "charge":
                feedback = await coord.write_power_atomic(0, power, 1)
            else:
                feedback = await coord.write_power_atomic(power, 0, 2)

            if feedback is None:
                _LOGGER.warning("[%s] Manual slot write failed", coord.name)
                continue

            self._manual_slot_owned.add(coord)
            _LOGGER.debug(
                "[%s] Manual slot active: direction=%s power=%dW",
                coord.name, direction, power,
            )

    def _is_manual_slot_owned(self, coordinator) -> bool:
        return coordinator in self._manual_slot_owned

    def _apply_slot_power_ceiling(self, coordinator, is_charging: bool, current_limit: int) -> int:
        """Cap the per-battery power limit with the active slot's power override (PD mode only)."""
        slot = self._get_active_slot(coordinator, "charge" if is_charging else "discharge")
        if not slot or not slot.get("power_override_enabled"):
            return current_limit
        if slot.get("mode") == "manual":
            return current_limit
        limits = self._slot_battery_limits(slot, coordinator)
        key = "max_charge_power_w" if is_charging else "max_discharge_power_w"
        val = limits.get(key)
        if val is None:
            return current_limit
        try:
            return min(int(current_limit), int(val))
        except (TypeError, ValueError):
            return current_limit

    def _battery_power_limit(self, coordinator, is_charging: bool) -> int:
        """Return the effective per-battery power limit for the current cycle."""
        if not is_charging:
            return self._apply_slot_power_ceiling(
                coordinator, False, coordinator.max_discharge_power
            )

        limit = coordinator.max_charge_power
        if coordinator.data is None:
            return self._apply_slot_power_ceiling(coordinator, True, limit)
        if not self._full_charge_voltage_taper_applies(coordinator):
            return self._apply_slot_power_ceiling(coordinator, True, limit)

        max_cell_voltage = coordinator.data.get("max_cell_voltage")
        voltage_tapered = getattr(self, "_normal_balance_voltage_tapered", {})
        voltage_taper_latched = voltage_tapered.get(coordinator, False)
        if max_cell_voltage is not None:
            try:
                max_cell_voltage_f = float(max_cell_voltage)
                if max_cell_voltage_f >= NORMAL_BALANCE_TAPER_CELL_VOLTAGE:
                    voltage_taper_latched = True
                    voltage_tapered[coordinator] = True
                elif not self._normal_balance_zone_active(coordinator):
                    voltage_tapered.pop(coordinator, None)
                    voltage_taper_latched = False
                if voltage_taper_latched:
                    limit = min(limit, NORMAL_BALANCE_CHARGE_POWER_W)
            except (TypeError, ValueError):
                pass

        return self._apply_slot_power_ceiling(coordinator, True, limit)

    def update_pd_parameters(self):
        """Re-read PD controller parameters from config_entry.data (hot-reload)."""
        # Update weekly full charge settings; reset completion state if day changed
        new_weekly_day = self.config_entry.data.get(CONF_WEEKLY_FULL_CHARGE_DAY, "sun")
        new_weekly_enabled = self.config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE, False)
        day_changed = new_weekly_day != self.weekly_full_charge_day
        feature_disabled = self.weekly_full_charge_enabled and not new_weekly_enabled
        if day_changed or feature_disabled:
            _LOGGER.info("Weekly Full Charge: %s - resetting completion state",
                         f"day changed from {self.weekly_full_charge_day.upper()} to {new_weekly_day.upper()}"
                         if day_changed else "feature disabled")
            # If registers were written for a charge still in progress, schedule a hardware restore
            if self.weekly_full_charge_registers_written and not self.weekly_full_charge_complete:
                _LOGGER.info("Weekly Full Charge: Mid-charge abort detected - hardware restore pending")
                self._weekly_charge_needs_restore = True
            self.weekly_full_charge_complete = False
            self.weekly_full_charge_registers_written = False
        self.weekly_full_charge_enabled = new_weekly_enabled
        self.weekly_full_charge_day = new_weekly_day

        self.deadband = self.config_entry.data.get(CONF_PD_DEADBAND, DEFAULT_PD_DEADBAND)
        self.kp = self.config_entry.data.get(CONF_PD_KP, DEFAULT_PD_KP)
        self.kd = self.config_entry.data.get(CONF_PD_KD, DEFAULT_PD_KD)
        self.max_power_change_per_cycle = self.config_entry.data.get(CONF_PD_MAX_POWER_CHANGE, DEFAULT_PD_MAX_POWER_CHANGE)
        self.direction_hysteresis = self.config_entry.data.get(CONF_PD_DIRECTION_HYSTERESIS, DEFAULT_PD_DIRECTION_HYSTERESIS)
        self.min_charge_power = self.config_entry.data.get(CONF_PD_MIN_CHARGE_POWER, DEFAULT_PD_MIN_CHARGE_POWER)
        self.min_discharge_power = self.config_entry.data.get(CONF_PD_MIN_DISCHARGE_POWER, DEFAULT_PD_MIN_DISCHARGE_POWER)
        self._relay_cooldown_s = self.config_entry.data.get(CONF_PD_RELAY_COOLDOWN, DEFAULT_PD_RELAY_COOLDOWN)
        self._min_cycle_interval_s = self.config_entry.data.get(CONF_PD_MIN_CYCLE_INTERVAL, DEFAULT_PD_MIN_CYCLE_INTERVAL)
        self.target_grid_power = self.config_entry.data.get(CONF_TARGET_GRID_POWER, DEFAULT_TARGET_GRID_POWER)
        self.enable_system_power_limits = self.config_entry.data.get(
            CONF_ENABLE_SYSTEM_POWER_LIMITS,
            (
                (self.config_entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER) or 0) > 0
                or (self.config_entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER) or 0) > 0
            ),
        )
        self.system_max_charge_power = self.config_entry.data.get(CONF_SYSTEM_MAX_CHARGE_POWER, DEFAULT_SYSTEM_MAX_CHARGE_POWER)
        self.system_max_discharge_power = self.config_entry.data.get(CONF_SYSTEM_MAX_DISCHARGE_POWER, DEFAULT_SYSTEM_MAX_DISCHARGE_POWER)
        self._refresh_effective_system_capacities()
        self._setpoint_offsets["user_target"] = self.target_grid_power
        self.max_contracted_power = self.config_entry.data.get(CONF_MAX_CONTRACTED_POWER, 7000)
        self._delay_safety_margin_h = self.config_entry.data.get(CONF_DELAY_SAFETY_MARGIN_MIN, DEFAULT_DELAY_SAFETY_MARGIN_MIN) / 60.0
        self._charge_delay_status["safety_margin_min"] = int(self._delay_safety_margin_h * 60)
        self._delay_soc_setpoint_enabled = self.config_entry.data.get(CONF_DELAY_SOC_SETPOINT_ENABLED, DEFAULT_DELAY_SOC_SETPOINT_ENABLED)
        self._delay_soc_setpoint = self.config_entry.data.get(CONF_DELAY_SOC_SETPOINT, DEFAULT_DELAY_SOC_SETPOINT)
        self._balance_monitor_enabled = True
        self._predictive_safety_margin_kwh = self.config_entry.data.get(CONF_PREDICTIVE_SAFETY_MARGIN_KWH, DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH)
        self._predictive_grid_charge_margin_pct = self.config_entry.data.get(CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT, DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT)
        self._charge_delay_status["soc_setpoint"] = self._delay_soc_setpoint if self._delay_soc_setpoint_enabled else None
        self.charge_delay_enabled = self.config_entry.data.get(
            CONF_ENABLE_CHARGE_DELAY,
            self.config_entry.data.get(CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY, False)
        )
        self.solar_forecast_sensor = self.config_entry.data.get(CONF_SOLAR_FORECAST_SENSOR, None)
        self.household_consumption_sensor = self.config_entry.data.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR, None)
        self.solar_production_sensor = self.config_entry.data.get(CONF_SOLAR_PRODUCTION_SENSOR, None)
        self.predictive_charging_mode = self.config_entry.data.get(CONF_PREDICTIVE_CHARGING_MODE, PREDICTIVE_MODE_TIME_SLOT)
        self.price_sensor = self.config_entry.data.get(CONF_PRICE_SENSOR, None)
        self.price_integration_type = self.config_entry.data.get(CONF_PRICE_INTEGRATION_TYPE, PRICE_INTEGRATION_NORDPOOL)
        self.max_price_threshold = self.config_entry.data.get(CONF_MAX_PRICE_THRESHOLD, None)
        self.capacity_protection_enabled = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_ENABLED, False)
        self.capacity_protection_soc_threshold = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_SOC_THRESHOLD, DEFAULT_CAPACITY_PROTECTION_SOC)
        self.capacity_protection_limit = self.config_entry.data.get(CONF_CAPACITY_PROTECTION_LIMIT, DEFAULT_CAPACITY_PROTECTION_LIMIT)

        # Hourly balance: ON→OFF cleans up offset; flag change is enough for async_process to react
        new_hb_enabled = self.config_entry.data.get(CONF_ENABLE_HOURLY_BALANCE, False)
        if self.hourly_balance_enabled and not new_hb_enabled:
            if self._hourly_balance_mgr is not None:
                self._hourly_balance_mgr.clear_offset()
            else:
                self.remove_setpoint_offset("hourly_balance")
            _LOGGER.info("Hourly Net Balance: DISABLED via hot-reload")
        elif not self.hourly_balance_enabled and new_hb_enabled:
            _LOGGER.info("Hourly Net Balance: ENABLED via hot-reload")
        self.hourly_balance_enabled = new_hb_enabled

        _LOGGER.info(
            "PD parameters hot-reloaded: Kp=%.2f, Kd=%.2f, deadband=%d, max_change=%d, "
            "hysteresis=%d, min_charge=%d, min_discharge=%d, system_limits=%s, system_max_charge=%d, "
            "system_max_discharge=%d",
            self.kp, self.kd, self.deadband, self.max_power_change_per_cycle,
            self.direction_hysteresis, self.min_charge_power, self.min_discharge_power,
            self.enable_system_power_limits,
            self.system_max_charge_power, self.system_max_discharge_power,
        )

    def _update_pd_quality_metrics(self, error: float, sign_changed: bool, active_target: float, pd_limited: bool) -> None:
        """Update control-quality EMAs (grid-error RMS and oscillation rate).

        Called once per active PD cycle (skipped when the controller is paused by
        restrictions). Uses real monotonic elapsed time so the averaging window is
        constant under the variable event-driven cadence.

        A setpoint/target step (hourly balance, capacity protection, a user target
        change, ...) makes the error spike while the battery ramps to the new target;
        that transient is skipped through a short grace window so it doesn't inflate
        the metric. Detection is source-agnostic: it keys on active_target moving.

        While the PD is battery-limited (no headroom to reduce the error) the residual
        error is not a tuning fault, so the metric is skipped too — the sensor reports
        the "battery_limited" state instead.
        """
        now = time.monotonic()
        if (
            self._pd_quality_prev_target is not None
            and abs(active_target - self._pd_quality_prev_target) > max(self.deadband, 20.0)
        ):
            self._pd_quality_settle_until = now + self._pd_quality_step_grace_s
        self._pd_quality_prev_target = active_target

        if pd_limited or now < self._pd_quality_settle_until:
            # Keep the timestamp fresh so the EMA resumes smoothly (small dt) instead
            # of seeing one huge gap that would snap it to the post-step value.
            self._pd_quality_last_ts = now
            return

        if self._pd_quality_last_ts is None:
            self._pd_quality_last_ts = now
            self._pd_quality_rms_ema = error * error
            return
        dt = now - self._pd_quality_last_ts
        self._pd_quality_last_ts = now
        if dt <= 0:
            return
        alpha = dt / (self._pd_quality_tau + dt)
        sq = error * error
        if self._pd_quality_rms_ema is None:
            self._pd_quality_rms_ema = sq
        else:
            self._pd_quality_rms_ema += alpha * (sq - self._pd_quality_rms_ema)
        # Oscillation rate in events/min: the instantaneous rate for this gap is
        # (60/dt) when a sign change occurred this cycle, 0 otherwise; smoothed.
        inst_per_min = (60.0 / dt) if sign_changed else 0.0
        self._pd_quality_osc_ema += alpha * (inst_per_min - self._pd_quality_osc_ema)

    @property
    def pd_quality_rms_error(self) -> float | None:
        """RMS of the grid-control error over the metric window (W), or None."""
        if self._pd_quality_rms_ema is None:
            return None
        return math.sqrt(max(0.0, self._pd_quality_rms_ema))

    @property
    def pd_quality_oscillation_per_min(self) -> float:
        """Smoothed error-sign-change rate (events/min); a hunting indicator."""
        return self._pd_quality_osc_ema

    def _make_block_record(self, registry: dict, source: str, reason: str, details: dict | None) -> dict:
        """Build a blocker record, preserving the original activation time."""
        existing = registry.get(source)
        return {
            "reason": reason,
            "details": details or {},
            "since": existing.get("since") if existing else dt_util.utcnow(),
        }

    def _serialize_blockers(self, registry: dict[str, dict]) -> dict:
        """Return blockers with JSON/state-attribute friendly values."""
        return {
            source: {
                "reason": record.get("reason"),
                "details": dict(record.get("details") or {}),
                "since": record["since"].isoformat() if record.get("since") else None,
            }
            for source, record in registry.items()
        }

    @staticmethod
    def _format_blockers_for_log(blockers: dict) -> str:
        """Return a compact one-line blocker summary for logs."""
        if not blockers:
            return "none"

        parts = []
        for source, record in blockers.items():
            reason = record.get("reason") or source
            details = record.get("details") or {}
            detail_text = ",".join(
                f"{key}={value}"
                for key, value in details.items()
                if value is not None
            )
            if detail_text:
                parts.append(f"{source}:{reason}({detail_text})")
            else:
                parts.append(f"{source}:{reason}")
        return ";".join(parts)

    def _format_setpoint_summary_for_log(self) -> str:
        """Return current target contributors in a compact form."""
        offsets = ",".join(
            f"{source}={value:.1f}W"
            for source, value in self._setpoint_offsets.items()
        ) or "none"
        overrides = {
            source: {"priority": priority, "value": round(value, 1)}
            for source, (priority, value) in self._setpoint_overrides.items()
        }
        if self._setpoint_overrides:
            active_source, (_, active_value) = max(
                self._setpoint_overrides.items(),
                key=lambda item: item[1][0],
            )
            override = f"{active_source}={active_value:.1f}W"
        else:
            override = "none"
        return f"offsets={offsets} active_override={override} overrides={overrides or 'none'}"

    def _should_log_rate_limiter(self, requested_change_w: float) -> bool:
        """Return True when rate limiting newly matters enough to log."""
        direction = 1 if requested_change_w > 0 else -1
        previous_change = self._rate_limiter_last_logged_change
        change_threshold = max(250.0, self.max_power_change_per_cycle * 0.25)

        should_log = (
            not self._rate_limiter_was_active
            or direction != self._rate_limiter_last_direction
            or previous_change is None
            or abs(requested_change_w - previous_change) >= change_threshold
        )

        self._rate_limiter_was_active = True
        self._rate_limiter_last_direction = direction
        if should_log:
            self._rate_limiter_last_logged_change = requested_change_w
        return should_log

    def _clear_rate_limiter_state(self) -> None:
        """Mark the rate limiter as inactive so the next clamp is logged once."""
        self._rate_limiter_was_active = False
        self._rate_limiter_last_direction = 0
        self._rate_limiter_last_logged_change = None

    def _block_registry(self, is_charging: bool, coordinator=None) -> dict:
        """Return the mutable blocker registry for a direction and scope."""
        if coordinator is None:
            return self._global_charge_blockers if is_charging else self._global_discharge_blockers
        registries = self._battery_charge_blockers if is_charging else self._battery_discharge_blockers
        return registries.setdefault(coordinator, {})

    def _set_operation_block(self, is_charging: bool, source: str, reason: str, details: dict | None = None, coordinator=None) -> None:
        registry = self._block_registry(is_charging, coordinator)
        old = registry.get(source)
        registry[source] = self._make_block_record(registry, source, reason, details)
        if old is None:
            scope = "global" if coordinator is None else coordinator.name
            _LOGGER.debug(
                "%s block added [%s]: %s",
                "Charge" if is_charging else "Discharge",
                scope,
                self._format_blockers_for_log({source: registry[source]}),
            )

    def _remove_operation_block(self, is_charging: bool, source: str, coordinator=None) -> None:
        if coordinator is None:
            registry = self._global_charge_blockers if is_charging else self._global_discharge_blockers
        else:
            registries = self._battery_charge_blockers if is_charging else self._battery_discharge_blockers
            registry = registries.get(coordinator)
            if registry is None:
                return
        removed = registry.pop(source, None)
        if removed is not None:
            scope = "global" if coordinator is None else coordinator.name
            _LOGGER.debug(
                "%s block removed [%s]: %s",
                "Charge" if is_charging else "Discharge",
                scope,
                self._format_blockers_for_log({source: removed}),
            )
        if coordinator is not None and not registry:
            registries.pop(coordinator, None)

    def set_charge_block(self, source: str, reason: str, details: dict | None = None, coordinator=None) -> None:
        """Register or update a charge blocker."""
        self._set_operation_block(True, source, reason, details, coordinator)

    def remove_charge_block(self, source: str, coordinator=None) -> None:
        """Remove a charge blocker."""
        self._remove_operation_block(True, source, coordinator)

    def set_discharge_block(self, source: str, reason: str, details: dict | None = None, coordinator=None) -> None:
        """Register or update a discharge blocker."""
        self._set_operation_block(False, source, reason, details, coordinator)

    def remove_discharge_block(self, source: str, coordinator=None) -> None:
        """Remove a discharge blocker."""
        self._remove_operation_block(False, source, coordinator)

    def is_charge_blocked(self, coordinator=None) -> bool:
        """Return True if charge is blocked globally or for the given battery."""
        if self._global_charge_blockers:
            return True
        return bool(coordinator is not None and self._battery_charge_blockers.get(coordinator))

    def is_discharge_blocked(self, coordinator=None) -> bool:
        """Return True if discharge is blocked globally or for the given battery."""
        if self._global_discharge_blockers:
            return True
        return bool(coordinator is not None and self._battery_discharge_blockers.get(coordinator))

    def get_charge_blockers(self, coordinator=None) -> dict:
        """Return charge blockers for the requested scope."""
        if coordinator is None:
            return self._serialize_blockers(self._global_charge_blockers)
        merged = dict(self._global_charge_blockers)
        merged.update(self._battery_charge_blockers.get(coordinator, {}))
        return self._serialize_blockers(merged)

    def get_discharge_blockers(self, coordinator=None) -> dict:
        """Return discharge blockers for the requested scope."""
        if coordinator is None:
            return self._serialize_blockers(self._global_discharge_blockers)
        merged = dict(self._global_discharge_blockers)
        merged.update(self._battery_discharge_blockers.get(coordinator, {}))
        return self._serialize_blockers(merged)

    def get_battery_charge_blockers(self) -> dict:
        """Return per-battery charge blockers for diagnostics."""
        return {
            coordinator.name: self._serialize_blockers(blockers)
            for coordinator, blockers in self._battery_charge_blockers.items()
            if blockers
        }

    def get_battery_discharge_blockers(self) -> dict:
        """Return per-battery discharge blockers for diagnostics."""
        return {
            coordinator.name: self._serialize_blockers(blockers)
            for coordinator, blockers in self._battery_discharge_blockers.items()
            if blockers
        }

    def _known_batteries_for_block_summary(self) -> list:
        """Return batteries with enough data to summarize effective blockers."""
        return [
            coordinator
            for coordinator in self.coordinators
            if coordinator.data is not None and coordinator.is_available
        ]

    def is_charge_effectively_blocked(self) -> bool:
        """Return True when no known battery can currently accept charge."""
        if self._global_charge_blockers:
            return True
        batteries = self._known_batteries_for_block_summary()
        return bool(batteries) and all(
            self.is_charge_blocked(coordinator) for coordinator in batteries
        )

    def is_discharge_effectively_blocked(self) -> bool:
        """Return True when no known battery can currently discharge."""
        if self._global_discharge_blockers:
            return True
        batteries = self._known_batteries_for_block_summary()
        return bool(batteries) and all(
            self.is_discharge_blocked(coordinator) for coordinator in batteries
        )

    def _slot_battery_key(self, coordinator) -> str | None:
        """Return 'battery_<N>' for this coordinator's index, or None if unknown."""
        try:
            idx = self.coordinators.index(coordinator)
        except ValueError:
            return None
        return f"battery_{idx + 1}"

    def _slot_battery_limits(self, slot: dict, coordinator) -> dict:
        """Return per-battery override values from `slot['battery_limits']` for this coord."""
        bkey = self._slot_battery_key(coordinator)
        if bkey is None:
            return {}
        return slot.get("battery_limits", {}).get(bkey) or {}

    def _slot_applies_to_battery(self, slot: dict, coordinator) -> bool:
        """Return True if `slot.battery_scope` matches this coordinator (or is 'all')."""
        scope = slot.get("battery_scope", "all")
        if scope == "all":
            return True
        bkey = self._slot_battery_key(coordinator)
        if bkey is None:
            return False
        return scope == bkey

    @staticmethod
    def _slot_time_matches(slot: dict, now_time) -> bool:
        """Return True if the current local time falls within the slot's window.

        Supports midnight crossing when start_time > end_time (e.g. 22:00–06:00).
        """
        from datetime import time as dt_time
        try:
            start = dt_time.fromisoformat(slot["start_time"])
            end = dt_time.fromisoformat(slot["end_time"])
        except Exception as e:
            _LOGGER.error("Error parsing time slot: %s", e)
            return False
        if start <= end:
            return start <= now_time <= end
        # Midnight crossing: matches if outside the [end, start] gap.
        return now_time >= start or now_time <= end

    def _is_time_slot_allowed(self, coordinator, is_charging: bool) -> bool:
        """Per-battery, per-direction whitelist check for time slots.

        Behaviour:
          - No slots configured → allowed.
          - No slot for this battery has `allow_<direction>=True` → whitelist
            inactive for that direction → allowed.
          - Otherwise: allowed only if the current time matches a slot whose
            `allow_<direction>=True`, scope applies, and day matches.
        """
        from datetime import datetime

        all_slots = self.config_entry.data.get("no_discharge_time_slots", [])
        slots = [s for s in all_slots if s.get("enabled", True)]
        if not slots:
            return True

        field = "allow_charge" if is_charging else "allow_discharge"
        relevant = [s for s in slots if self._slot_applies_to_battery(s, coordinator)]
        if not any(s.get(field, False) for s in relevant):
            return True

        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]

        for slot in relevant:
            if not slot.get(field, False):
                continue
            if current_day not in slot.get("days", []):
                continue
            if self._slot_time_matches(slot, current_time):
                return True
        return False

    def _refresh_time_slot_blocks(self) -> None:
        """Update per-battery charge/discharge blockers from the configured slots."""
        for coordinator in self.coordinators:
            if self._is_time_slot_allowed(coordinator, True):
                self.remove_charge_block("time_slot_charge", coordinator=coordinator)
            else:
                self.set_charge_block(
                    "time_slot_charge",
                    "time_slot",
                    {"direction": "charge", "battery": coordinator.name},
                    coordinator=coordinator,
                )

            if self._is_time_slot_allowed(coordinator, False):
                self.remove_discharge_block("time_slot_discharge", coordinator=coordinator)
            else:
                self.set_discharge_block(
                    "time_slot_discharge",
                    "time_slot",
                    {"direction": "discharge", "battery": coordinator.name},
                    coordinator=coordinator,
                )

    def _refresh_user_battery_blocks(self) -> None:
        """Update per-battery blockers from the software allow switches."""
        for coordinator in self.coordinators:
            if getattr(coordinator, "allow_charge", True):
                self.remove_charge_block("user_battery_charge_disabled", coordinator=coordinator)
            else:
                self.set_charge_block(
                    "user_battery_charge_disabled",
                    "user_disabled",
                    {"battery": coordinator.name},
                    coordinator=coordinator,
                )

            if getattr(coordinator, "allow_discharge", True):
                self.remove_discharge_block("user_battery_discharge_disabled", coordinator=coordinator)
            else:
                self.set_discharge_block(
                    "user_battery_discharge_disabled",
                    "user_disabled",
                    {"battery": coordinator.name},
                    coordinator=coordinator,
                )

    def _weekly_full_charge_unlocked(self) -> bool:
        """Return True when charging to 100% should bypass configured max SOC."""
        weekly_charge_active = self._weekly_charge_mgr.is_active()
        return weekly_charge_active and (
            not self.charge_delay_enabled
            or self._charge_delay_unlocked
            or self._balance_monitor_overrides_delay()
        )

    def _effective_charge_max_soc(self, coordinator, weekly_100_unlocked: bool) -> tuple[float, str]:
        """Return the current per-battery charge ceiling and the source of that ceiling."""
        if weekly_100_unlocked:
            return 100, "weekly_full_charge"

        if self.grid_charging_active and self._predictive_charge_target_soc is not None:
            per_battery_target = self._predictive_charge_target_soc.get(coordinator)
            if per_battery_target is not None:
                return min(coordinator.max_soc, per_battery_target), "predictive_target"

        slot = self._get_active_slot(coordinator, "charge")
        if slot and slot.get("soc_override_enabled"):
            limits = self._slot_battery_limits(slot, coordinator)
            slot_max = limits.get("soc_max")
            if slot_max is not None:
                try:
                    return max(12, min(100, int(slot_max))), "slot_soc_override"
                except (TypeError, ValueError):
                    pass

        return coordinator.max_soc, "max_soc"

    def _effective_discharge_min_soc(self, coordinator) -> tuple[float, str]:
        """Return the current per-battery discharge floor and the source of that floor."""
        slot = self._get_active_slot(coordinator, "discharge")
        if slot and slot.get("soc_override_enabled"):
            limits = self._slot_battery_limits(slot, coordinator)
            slot_min = limits.get("soc_min")
            if slot_min is not None:
                try:
                    return max(12, min(100, int(slot_min))), "slot_soc_override"
                except (TypeError, ValueError):
                    pass
        return coordinator.min_soc, "min_soc"

    def _refresh_battery_charge_limit_blocks(self) -> None:
        """Expose max-SOC and hysteresis charge availability as per-battery blockers."""
        weekly_100_unlocked = self._weekly_full_charge_unlocked()

        for coordinator in self.coordinators:
            if coordinator.data is None:
                self.remove_charge_block("max_soc", coordinator=coordinator)
                self.remove_charge_block("charge_hysteresis", coordinator=coordinator)
                continue

            current_soc = coordinator.data.get("battery_soc", 0)
            active_balance_enabled = bool(
                getattr(coordinator, "active_balance_mode_enabled", False)
            )

            if active_balance_enabled:
                if coordinator.enable_charge_hysteresis and coordinator._hysteresis_active:
                    _LOGGER.debug(
                        "%s: Temporarily ignoring hysteresis for active balance mode",
                        coordinator.name,
                    )
                self.remove_charge_block("max_soc", coordinator=coordinator)
                self.remove_charge_block("charge_hysteresis", coordinator=coordinator)
                continue

            if weekly_100_unlocked:
                if coordinator.enable_charge_hysteresis and coordinator._hysteresis_active:
                    _LOGGER.debug("%s: Overriding hysteresis for weekly full charge", coordinator.name)
                coordinator._hysteresis_active = False
                coordinator._hysteresis_base_soc = None
                self.remove_charge_block("max_soc", coordinator=coordinator)
                self.remove_charge_block("charge_hysteresis", coordinator=coordinator)
                continue

            if self._normal_balance_recal_override.get(coordinator):
                # SOC recalibration: don't let top-voltage hysteresis stop the
                # charge before the BMS cutoff.
                if coordinator.enable_charge_hysteresis and coordinator._hysteresis_active:
                    _LOGGER.debug("%s: Overriding hysteresis for SOC recalibration", coordinator.name)
                coordinator._hysteresis_active = False
                coordinator._hysteresis_base_soc = None
                self.remove_charge_block("max_soc", coordinator=coordinator)
                self.remove_charge_block("charge_hysteresis", coordinator=coordinator)
                continue

            effective_max_soc, max_soc_source = self._effective_charge_max_soc(
                coordinator,
                weekly_100_unlocked,
            )
            bms_cutoff = self._weekly_charge_mgr.is_battery_full(coordinator)

            if coordinator.enable_charge_hysteresis:
                # Activate hysteresis when cell voltage hits the BMS cutoff threshold,
                # regardless of whether the charge tapper feature is enabled.
                # Uses effective_max_soc so slot/predictive overrides are respected.
                taper_at_top_voltage = False
                if effective_max_soc >= 100:
                    _vmax = coordinator.data.get("max_cell_voltage")
                    if _vmax is not None:
                        try:
                            taper_at_top_voltage = float(_vmax) >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE
                        except (TypeError, ValueError):
                            pass
                if current_soc >= coordinator.max_soc or bms_cutoff or taper_at_top_voltage:
                    coordinator._hysteresis_active = True
                    if coordinator._hysteresis_base_soc is None:
                        coordinator._hysteresis_base_soc = current_soc

                hysteresis_base = (
                    coordinator._hysteresis_base_soc
                    if coordinator._hysteresis_base_soc is not None
                    else coordinator.max_soc
                )
                charge_threshold = hysteresis_base - coordinator.charge_hysteresis_percent

                if current_soc < charge_threshold:
                    coordinator._hysteresis_active = False
                    coordinator._hysteresis_base_soc = None

                if coordinator._hysteresis_active:
                    if current_soc >= effective_max_soc or bms_cutoff:
                        self.set_charge_block(
                            "max_soc",
                            "max_soc",
                            {
                                "battery": coordinator.name,
                                "soc": current_soc,
                                "max_soc": coordinator.max_soc,
                                "effective_max_soc": effective_max_soc,
                                "source": max_soc_source,
                                "bms_cutoff": bms_cutoff,
                            },
                            coordinator=coordinator,
                        )
                    else:
                        self.remove_charge_block("max_soc", coordinator=coordinator)
                    self.set_charge_block(
                        "charge_hysteresis",
                        "hysteresis",
                        {
                            "battery": coordinator.name,
                            "soc": current_soc,
                            "max_soc": coordinator.max_soc,
                            "threshold": charge_threshold,
                            "base_soc": hysteresis_base,
                            "hysteresis_percent": coordinator.charge_hysteresis_percent,
                            "bms_cutoff": bms_cutoff,
                        },
                        coordinator=coordinator,
                    )
                    continue

            self.remove_charge_block("charge_hysteresis", coordinator=coordinator)

            if current_soc >= effective_max_soc or bms_cutoff:
                self.set_charge_block(
                    "max_soc",
                    "max_soc",
                    {
                        "battery": coordinator.name,
                        "soc": current_soc,
                        "max_soc": coordinator.max_soc,
                        "effective_max_soc": effective_max_soc,
                        "source": max_soc_source,
                        "bms_cutoff": bms_cutoff,
                    },
                    coordinator=coordinator,
                )
            else:
                self.remove_charge_block("max_soc", coordinator=coordinator)

    def _refresh_battery_discharge_limit_blocks(self) -> None:
        """Expose min-SOC discharge availability as per-battery blockers."""
        for coordinator in self.coordinators:
            if coordinator.data is None:
                self.remove_discharge_block("min_soc", coordinator=coordinator)
                continue

            current_soc = coordinator.data.get("battery_soc", 0)
            effective_min_soc, min_soc_source = self._effective_discharge_min_soc(coordinator)
            if current_soc <= effective_min_soc:
                self.set_discharge_block(
                    "min_soc",
                    "min_soc",
                    {
                        "battery": coordinator.name,
                        "soc": current_soc,
                        "min_soc": coordinator.min_soc,
                        "effective_min_soc": effective_min_soc,
                        "source": min_soc_source,
                    },
                    coordinator=coordinator,
                )
            else:
                self.remove_discharge_block("min_soc", coordinator=coordinator)

    def _refresh_ev_blocks(self) -> None:
        """Update EV charger blockers from no-telemetry charger state."""
        ev_pause_active, ev_charging_active = self._check_ev_charger_state()
        if ev_pause_active:
            self.set_charge_block("ev_pause", "ev_pause", {"duration": "5_min"})
            self.set_discharge_block("ev_pause", "ev_pause", {"duration": "5_min"})
        else:
            self.remove_charge_block("ev_pause")
            self.remove_discharge_block("ev_pause")

        if ev_charging_active:
            self.set_discharge_block("ev_charging", "ev_charging")
        else:
            self.remove_discharge_block("ev_charging")

    def _refresh_operation_blockers(self) -> None:
        """Refresh all runtime operation blockers for the current control cycle."""
        if (
            self.charge_delay_enabled
            and self._is_charge_delayed()
            and not self._active_balance_overrides_delay()
        ):
            self.set_charge_block(
                "charge_delay",
                "charge_delay",
                {"state": self._charge_delay_status.get("state")},
            )
        else:
            self.remove_charge_block("charge_delay")

        self._refresh_time_slot_blocks()
        self._apply_price_discharge_block()
        self._refresh_ev_blocks()
        self._refresh_user_battery_blocks()
        self._refresh_normal_balance_blocks()
        self._refresh_battery_charge_limit_blocks()
        self._refresh_battery_discharge_limit_blocks()
        self._price_based_discharge_blocked = "price_discharge" in self._global_discharge_blockers

    def _is_operation_allowed(self, is_charging: bool) -> bool:
        """Return True if the refreshed blocker registry allows this operation."""
        return not (self.is_charge_blocked() if is_charging else self.is_discharge_blocked())

    def _get_active_slot(self, coordinator=None, direction: str = "any") -> dict | None:
        """Return the active slot for a battery/direction, or None.

        Args:
            coordinator: per-battery filter. If None, ignore battery_scope.
            direction: "charge", "discharge", or "any". When "charge"/"discharge",
                only slots with `allow_<direction>=True` are considered.
        """
        from datetime import datetime

        slots = self.config_entry.data.get("no_discharge_time_slots", [])
        if not slots:
            return None

        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]

        for slot in slots:
            if not slot.get("enabled", True):
                continue
            if coordinator is not None and not self._slot_applies_to_battery(slot, coordinator):
                continue
            if direction == "charge" and not slot.get("allow_charge", False):
                continue
            if direction == "discharge" and not slot.get("allow_discharge", False):
                continue
            if current_day not in slot.get("days", []):
                continue
            if self._slot_time_matches(slot, current_time):
                return slot
        return None

    def _get_available_batteries(self, is_charging: bool, include_operation_blocks: bool = True) -> list:
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
            if self._non_responsive.is_excluded(coordinator):
                _LOGGER.debug("%s: Skipping - excluded due to non-responsive behavior", coordinator.name)
                continue

            if self._is_active_balance_mode_running(coordinator):
                _LOGGER.debug("%s: Skipping - active balance mode owns this battery", coordinator.name)
                continue

            # Skip batteries with backup function active (they manage themselves autonomously)
            if self._is_backup_function_active(coordinator):
                _LOGGER.debug("%s: Skipping - backup function is active", coordinator.name)
                continue

            # Skip batteries the user excluded from integration control: RS485 control
            # disabled means the battery is driven by the official app / its own logic.
            if coordinator.rs485_user_disabled:
                _LOGGER.debug("%s: Skipping - RS485 control disabled by user", coordinator.name)
                continue

            if self._is_manual_slot_owned(coordinator):
                _LOGGER.debug("%s: Skipping - manual time slot owns this battery", coordinator.name)
                continue

            active_balance_enabled = bool(
                getattr(coordinator, "active_balance_mode_enabled", False)
            )

            if include_operation_blocks and is_charging:
                charge_blockers = self.get_charge_blockers(coordinator)
                if active_balance_enabled:
                    charge_blockers = {
                        source: block
                        for source, block in charge_blockers.items()
                        if source not in {"max_soc", "charge_hysteresis"}
                    }
                if charge_blockers:
                    _LOGGER.debug(
                        "%s: Skipping charge - blocked by %s",
                        coordinator.name,
                        ", ".join(charge_blockers.keys()),
                    )
                    continue

            if include_operation_blocks and not is_charging and self.is_discharge_blocked(coordinator):
                _LOGGER.debug(
                    "%s: Skipping discharge - blocked by %s",
                    coordinator.name,
                    ", ".join(self.get_discharge_blockers(coordinator).keys()),
                )
                continue

            current_soc = coordinator.data.get("battery_soc", 0)
            
            if is_charging:
                # Check if weekly full charge is active AND 100% is actually unlocked
                weekly_100_unlocked = self._weekly_full_charge_unlocked()

                # Determine effective max SOC (respects slot/predictive overrides)
                effective_max_soc, max_soc_source = self._effective_charge_max_soc(
                    coordinator,
                    weekly_100_unlocked,
                )

                # Update hysteresis state if enabled
                if coordinator.enable_charge_hysteresis:
                    # Only override hysteresis when an explicit full/top-balance
                    # run is active.
                    if active_balance_enabled:
                        # Active balance temporarily bypasses hysteresis, but keeps
                        # the previous latch so it is restored when the mode stops.
                        if coordinator._hysteresis_active:
                            _LOGGER.debug(
                                "%s: Temporarily ignoring hysteresis for active balance mode",
                                coordinator.name,
                            )
                    elif weekly_100_unlocked:
                        # Force-disable hysteresis during weekly full charge.
                        if coordinator._hysteresis_active:
                            _LOGGER.debug(
                                "%s: Overriding hysteresis for weekly full charge",
                                coordinator.name,
                            )
                        coordinator._hysteresis_active = False
                        coordinator._hysteresis_base_soc = None
                    elif self._normal_balance_recal_override.get(coordinator):
                        # SOC recalibration: bypass top-voltage hysteresis so the
                        # charge continues to the BMS cutoff.
                        if coordinator._hysteresis_active:
                            _LOGGER.debug(
                                "%s: Overriding hysteresis for SOC recalibration",
                                coordinator.name,
                            )
                        coordinator._hysteresis_active = False
                        coordinator._hysteresis_base_soc = None
                    else:
                        # Normal hysteresis logic
                        _vmax_hysteresis = coordinator.data.get("max_cell_voltage") if coordinator.data else None
                        _taper_at_top = False
                        if effective_max_soc >= 100 and _vmax_hysteresis is not None:
                            try:
                                _taper_at_top = float(_vmax_hysteresis) >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE
                            except (TypeError, ValueError):
                                pass
                        if current_soc >= coordinator.max_soc or _taper_at_top:
                            coordinator._hysteresis_active = True
                            # Capture the actual SOC that triggered hysteresis (may be 100% after full charge)
                            if coordinator._hysteresis_base_soc is None:
                                coordinator._hysteresis_base_soc = current_soc

                        # Use actual peak SOC as threshold base (handles post-full-charge case)
                        hysteresis_base = coordinator._hysteresis_base_soc if coordinator._hysteresis_base_soc else coordinator.max_soc
                        charge_threshold = hysteresis_base - coordinator.charge_hysteresis_percent
                        if current_soc < charge_threshold:
                            coordinator._hysteresis_active = False
                            coordinator._hysteresis_base_soc = None

                        if coordinator._hysteresis_active:
                            _LOGGER.debug("%s: Skipping charge - Hysteresis active (SOC %.1f%%, threshold: %.1f%%, base: %.1f%%)",
                                         coordinator.name, current_soc, charge_threshold, hysteresis_base)
                            continue

                if max_soc_source == "weekly_full_charge":
                    _LOGGER.debug("%s: Weekly Full Charge active - effective_max_soc=100%% (configured: %d%%)",
                                 coordinator.name, coordinator.max_soc)
                elif max_soc_source == "predictive_target":
                    # Predictive grid charging: per-battery target so each battery
                    # charges only the portion solar cannot cover for its individual gap
                    per_battery_target = self._predictive_charge_target_soc.get(coordinator)
                    _LOGGER.debug(
                        "%s: Predictive grid charging - effective_max_soc=%.1f%% "
                        "(target=%.1f%%, configured=%d%%)",
                        coordinator.name, effective_max_soc,
                        per_battery_target, coordinator.max_soc,
                    )

                # BMS cutoff detection: counter is maintained by tick_bms_cutoff() which
                # runs unconditionally at the top of handle_registers() each cycle.
                # is_battery_full() is a read-only query shared with handle_registers().
                if self._weekly_charge_mgr.is_battery_full(coordinator):
                    if coordinator.enable_charge_hysteresis and not coordinator._hysteresis_active:
                        coordinator._hysteresis_active = True
                        if coordinator._hysteresis_base_soc is None:
                            coordinator._hysteresis_base_soc = current_soc
                        _LOGGER.debug(
                            "%s: BMS cutoff at %d%% — activating hysteresis",
                            coordinator.name, current_soc,
                        )
                    else:
                        _LOGGER.debug(
                            "%s: BMS cutoff at %d%% — skipping charge allocation",
                            coordinator.name, current_soc,
                        )
                    continue

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

    def _is_backup_function_active(self, coordinator) -> bool:
        """Return True if the battery must be excluded from PD control due to backup mode.

        A battery is excluded when:
          - The Backup Function switch is enabled (register value == 0) AND
          - The AC offgrid power sensor reads above the user-configured threshold
            (default 50 W), OR the sensor is unavailable.

        Additionally, a 5-minute cooldown is applied after the offgrid load
        drops to 0: the battery stays excluded until the cooldown expires to
        avoid sending write commands immediately after a backup event ends.

        The switch turning OFF clears the cooldown immediately.
        """
        if coordinator.data is None:
            return False

        now = dt_util.utcnow()

        # From SWITCH_DEFINITIONS: command_on = 0 (enabled), command_off = 1 (disabled)
        backup_value = coordinator.data.get("backup_function")
        if backup_value is None or backup_value != 0:
            # Switch is off — clear any lingering cooldown and allow PD control
            self._backup_cooldown_until.pop(coordinator, None)
            return False

        # Switch is ON. Check whether the battery is actively providing offgrid power.
        ac_offgrid = coordinator.data.get("ac_offgrid_power")

        # Small permanent loads (e.g. a PoE switch, router, or AP connected to the
        # offgrid port) should not trigger backup exclusion. Only a substantial load
        # — indicative of a real grid-outage scenario — warrants excluding the battery
        # from PD control. The threshold is user-configurable (default 50 W).
        threshold = coordinator.backup_offgrid_threshold

        if ac_offgrid is not None and ac_offgrid <= threshold:
            # Offgrid power is zero or a small standby load — check post-backup cooldown
            cooldown_until = self._backup_cooldown_until.get(coordinator)
            if cooldown_until and now < cooldown_until:
                remaining = int((cooldown_until - now).total_seconds() / 60)
                _LOGGER.debug(
                    "%s: Backup cooldown active — %d min remaining before re-entering PD control",
                    coordinator.name, remaining
                )
                return True
            # Cooldown expired (or was never set) — allow PD control
            self._backup_cooldown_until.pop(coordinator, None)
            return False

        # Offgrid power > threshold (or sensor not available): backup is actively running.
        # Refresh the cooldown window so it starts counting from the last active reading.
        if ac_offgrid is not None:
            _LOGGER.debug(
                "%s: Backup active — offgrid load %.0fW exceeds %.0fW threshold, excluding from PD control",
                coordinator.name, ac_offgrid, threshold
            )
        self._backup_cooldown_until[coordinator] = now + timedelta(minutes=5)
        return True

    @property
    def non_responsive_battery_names(self) -> list[str]:
        """Return names of batteries excluded or currently unreachable."""
        names: list[str] = []
        for name in self._non_responsive.excluded_names():
            if name not in names:
                names.append(name)

        for coordinator in self.coordinators:
            if (
                not coordinator.is_available
                and not getattr(coordinator, "_is_shutting_down", False)
                and getattr(coordinator, "_consecutive_failures", 0) > 0
                and coordinator.name not in names
            ):
                names.append(coordinator.name)

        return names

    # -------------------------------------------------------------------------


    def _apply_meter_transform(self, state) -> float | None:
        """Read and transform a grid meter state.

        Handles:
        - Auto kW detection: if unit_of_measurement is 'kW', multiplies by 1000.
        - Inverted sign: if meter_inverted is True, negates the value.

        Returns the value in Watts with correct sign convention, or None on error.
        """
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        unit = state.attributes.get("unit_of_measurement", "W")
        if unit == "kW":
            value *= 1000.0
        if self.meter_inverted:
            value = -value
        return value

    def _balance_monitor_overrides_delay(self) -> bool:
        """Return True when the full-charge-day skip-delay option is active for the current day."""
        return self._balance_monitor_enabled and self._weekly_charge_mgr.is_active()

    def _active_balance_overrides_delay(self) -> bool:
        return self._active_balance_mgr._active_balance_overrides_delay()

    # -------------------------------------------------------------------------
    # Setpoint offset management
    #
    # Reference = 0 W (zero grid flow). Two layers:
    #
    #   1. Additive offsets (_setpoint_offsets):
    #      Summed to form the default target.
    #      Use for preferences that compose with each other.
    #      Examples:
    #        "user_target" = -50 W  (slight export preference from config)
    #        "hourly_balance" = +200 W  (shift to compensate hourly deficit)
    #
    #   2. Absolute overrides (_setpoint_overrides):
    #      Each has a priority (int). When any override is active, the one
    #      with the highest priority wins and REPLACES the additive sum.
    #      Use for modes that need full control of the target.
    #      Examples:
    #        "capacity_protection" (pri=10) → 2000 W  (peak shaving limit)
    #        "hourly_balance"      (pri=5)  → -1500 W (compensate surplus)
    #
    # Resolution:
    #   active_target = highest-priority override  (if any override exists)
    #                 | sum(additive offsets)       (otherwise)
    # -------------------------------------------------------------------------

    def compute_active_target(self) -> float:
        """Compute the effective PD target from offsets and overrides."""
        if self._setpoint_overrides:
            # Highest priority override wins
            source, (_, value) = max(self._setpoint_overrides.items(), key=lambda x: x[1][0])
            return value
        return sum(self._setpoint_offsets.values())

    def compute_active_target_excluding(self, excluded_source: str) -> float:
        """Compute the active target while ignoring one override source."""
        overrides = {
            source: override
            for source, override in self._setpoint_overrides.items()
            if source != excluded_source
        }
        if overrides:
            source, (_, value) = max(overrides.items(), key=lambda x: x[1][0])
            return value
        return sum(self._setpoint_offsets.values())

    def set_setpoint_offset(self, source: str, offset_w: float) -> None:
        """Register or update an additive offset (summed with others)."""
        old = self._setpoint_offsets.get(source)
        self._setpoint_offsets[source] = offset_w
        if old != offset_w:
            _LOGGER.debug("Setpoint offset '%s': %s → %.0fW",
                          source, f"{old:.0f}W" if old is not None else "None", offset_w)

    def remove_setpoint_offset(self, source: str) -> None:
        """Remove an additive offset. No-op if not present."""
        removed = self._setpoint_offsets.pop(source, None)
        if removed is not None:
            _LOGGER.debug("Setpoint offset '%s' removed (was %.0fW)", source, removed)

    def set_setpoint_override(self, source: str, value_w: float, priority: int = 0) -> None:
        """Register an absolute override. Highest priority wins over all offsets."""
        old = self._setpoint_overrides.get(source)
        self._setpoint_overrides[source] = (priority, value_w)
        old_str = f"{old[1]:.0f}W (pri={old[0]})" if old else "None"
        _LOGGER.debug("Setpoint override '%s': %s → %.0fW (pri=%d)",
                      source, old_str, value_w, priority)

    def remove_setpoint_override(self, source: str) -> None:
        """Remove an absolute override. No-op if not present."""
        removed = self._setpoint_overrides.pop(source, None)
        if removed is not None:
            _LOGGER.debug("Setpoint override '%s' removed (was %.0fW, pri=%d)",
                          source, removed[1], removed[0])

    def get_setpoint_offset(self, source: str) -> float:
        """Return the current additive offset for *source*, or 0.0 if not set."""
        return self._setpoint_offsets.get(source, 0.0)

    def clear_all_setpoint_offsets(self) -> None:
        """Remove all additive offsets and overrides."""
        if self._setpoint_offsets:
            _LOGGER.debug("Clearing all setpoint offsets: %s", dict(self._setpoint_offsets))
            self._setpoint_offsets.clear()
        if self._setpoint_overrides:
            _LOGGER.debug("Clearing all setpoint overrides: %s",
                          {k: v[1] for k, v in self._setpoint_overrides.items()})
            self._setpoint_overrides.clear()

    def _apply_capacity_protection(
        self, sensor_actual: float, active_target: float
    ) -> tuple[float, float]:
        """Apply peak-shaving override and return the effective target and sensor value."""
        if not self.capacity_protection_enabled:
            self.remove_setpoint_override("capacity_protection")
            self._capacity_protection_active = False
            self._capacity_protection_status["active"] = False
            self._capacity_protection_status["action"] = "disabled"
            return self.compute_active_target(), sensor_actual

        coordinators_with_data = [c for c in self.coordinators if c.data]
        if coordinators_with_data:
            avg_soc = (
                sum(c.data.get("battery_soc", 0) for c in coordinators_with_data)
                / len(coordinators_with_data)
            )
        else:
            avg_soc = 100  # Assume full if no data, don't activate protection

        # Use the non-capacity-protection target for decisions. The previous
        # cycle's capacity_protection override may still be registered here; if
        # we compare against it, normal below-limit import can be mistaken for
        # solar surplus and the controller starts a short discharge/stop loop.
        active_target = self.compute_active_target_excluding("capacity_protection")
        original_target = active_target

        if avg_soc < self.capacity_protection_soc_threshold:
            # Estimate house consumption: grid reading minus what the battery is currently doing
            # sensor_actual = grid power (positive=import), previous_power > 0 = charging, < 0 = discharging
            # Add back excluded-device adjustment so capacity protection sees the REAL grid load
            # including devices marked as "included in consumption". This ensures capacity
            # protection can shave peaks even when those devices are normally excluded.
            estimated_house_load = (sensor_actual + self._excluded_included_adjustment) - self.previous_power

            if estimated_house_load > self.capacity_protection_limit:
                # House load exceeds peak limit: discharge only the excess
                # Undo excluded-device adjustment so PD controller can discharge against real grid
                if self._excluded_included_adjustment > 0:
                    _LOGGER.info(
                        "Capacity Protection overriding excluded device adjustment (%.0fW) for peak shaving",
                        self._excluded_included_adjustment,
                    )
                    sensor_actual += self._excluded_included_adjustment
                self.set_setpoint_override("capacity_protection", self.capacity_protection_limit, priority=10)
                active_target = self.compute_active_target()
                _LOGGER.info(
                    "Capacity Protection ACTIVE: SOC=%.1f%% < %d%%, house_load=%.0fW > limit=%dW -> target=%dW",
                    avg_soc,
                    self.capacity_protection_soc_threshold,
                    estimated_house_load,
                    self.capacity_protection_limit,
                    active_target,
                )
                self._capacity_protection_active = True
                self._capacity_protection_status.update({
                    "active": True, "avg_soc": round(avg_soc, 1),
                    "estimated_house_load": round(estimated_house_load),
                    "action": "shaving",
                    "original_target": original_target, "adjusted_target": active_target,
                })
            elif estimated_house_load > active_target:
                # House load is below peak limit but above normal target: hold the
                # current grid level and stop any existing discharge immediately.
                # Undo excluded-device adjustment so target aligns with real grid reading
                if self._excluded_included_adjustment > 0:
                    _LOGGER.info(
                        "Capacity Protection overriding excluded device adjustment (%.0fW) for conservation",
                        self._excluded_included_adjustment,
                    )
                    sensor_actual += self._excluded_included_adjustment
                self.set_setpoint_override("capacity_protection", sensor_actual, priority=10)
                active_target = self.compute_active_target()
                if self.previous_power < 0:
                    self._capacity_protection_force_idle = True
                _LOGGER.info(
                    "Capacity Protection ACTIVE: SOC=%.1f%% < %d%%, house_load=%.0fW <= limit=%dW -> idle (target=%.0fW)",
                    avg_soc,
                    self.capacity_protection_soc_threshold,
                    estimated_house_load,
                    self.capacity_protection_limit,
                    active_target,
                )
                self._capacity_protection_active = True
                self._capacity_protection_status.update({
                    "active": True, "avg_soc": round(avg_soc, 1),
                    "estimated_house_load": round(estimated_house_load),
                    "action": "conserving",
                    "original_target": original_target, "adjusted_target": active_target,
                })
            else:
                # Solar surplus: normal charging, but SOC is still below threshold
                self.remove_setpoint_override("capacity_protection")
                active_target = self.compute_active_target()
                self._capacity_protection_active = True
                self._capacity_protection_status.update({
                    "active": True, "avg_soc": round(avg_soc, 1),
                    "estimated_house_load": round(estimated_house_load),
                    "action": "charging",
                    "original_target": original_target, "adjusted_target": active_target,
                })
        else:
            # SOC above threshold: protection not needed
            self.remove_setpoint_override("capacity_protection")
            active_target = self.compute_active_target()
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
        return active_target, sensor_actual

    def _is_capacity_protection_soc_limited(self) -> bool:
        """Return True when peak shaving should be active based on current SOC."""
        if not self.capacity_protection_enabled:
            return False
        coordinators_with_data = [c for c in self.coordinators if c.data]
        if not coordinators_with_data:
            return False
        avg_soc = (
            sum(c.data.get("battery_soc", 0) for c in coordinators_with_data)
            / len(coordinators_with_data)
        )
        return avg_soc < self.capacity_protection_soc_threshold

    def _is_charge_delayed(self) -> bool:
        """Unified gate: check if charging should be delayed based on solar forecast.

        Returns True if charging should be blocked, False if allowed.
        Called from _is_operation_allowed() for every charge attempt.
        """
        if not self.charge_delay_enabled:
            self._charge_delay_status["state"] = "Disabled"
            return False

        # Skip delay entirely on the weekly full charge day when opted in
        if self._balance_monitor_overrides_delay():
            self._charge_delay_status["state"] = "Skipped - Full Charge Day"
            return False

        target_soc = self._consumption_tracker.get_today_target_soc()
        self._charge_delay_status["target_soc"] = target_soc

        # Already unlocked today?
        if self._charge_delay_unlocked:
            self._charge_delay_status["state"] = "Charging allowed"
            return False

        # SOC setpoint: delay only kicks in once all batteries reach the setpoint.
        # Hysteresis prevents oscillation: once the setpoint is reached, charging
        # only resumes if SOC drops DELAY_SOC_SETPOINT_HYSTERESIS % below it.
        if self._delay_soc_setpoint_enabled:
            min_soc = min(
                (c.data.get("battery_soc", 100) for c in self.coordinators if c.data),
                default=100,
            )
            if not self._delay_setpoint_reached:
                if min_soc < self._delay_soc_setpoint:
                    self._charge_delay_status["state"] = "Charging to setpoint"
                    return False
                self._delay_setpoint_reached = True
                self._schedule_charge_delay_state_save()
            else:
                low_threshold = self._delay_soc_setpoint - DELAY_SOC_SETPOINT_HYSTERESIS
                if min_soc < low_threshold:
                    self._delay_setpoint_reached = False
                    self._schedule_charge_delay_state_save()
                    self._charge_delay_status["state"] = "Charging to setpoint"
                    return False

        # Evaluate delay conditions
        if self._should_delay_charge(target_soc):
            return True  # Keep delay active (block charging)

        # Delay conditions no longer met - unlock permanently for today
        self._charge_delay_unlocked = True
        self._schedule_charge_delay_state_save()
        _LOGGER.info("Charge Delay: Unlocked (target_soc=%d%%) - charging now allowed", target_soc)
        # Persist unlock state if on weekly charge day
        if self._weekly_charge_mgr.is_active():
            asyncio.create_task(self._weekly_charge_mgr.save_state())
        return False

    def _should_delay_charge(self, target_soc: int) -> bool:
        """Determine if charging should be delayed based on solar forecast.

        Unified method for both daily (max_soc) and weekly (100%) charge delay.
        Uses the live solar forecast sensor (updated throughout the day).

        Returns True to keep delay active (block charging),
        False to unlock charging.

        Fail-safe: any failure → unlock (allow charging).

        Decision flow:
        1. No forecast sensor or unavailable → unlock immediately
        2. Energy balance check: (usable_energy + forecast) < consumption → unlock (grid needed)
           Recalculated only when forecast value changes (> 0.05 kWh).
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
        _h_to_hhmm = self._consumption_tracker.h_to_hhmm

        def _unlock(reason):
            """Set status and return False (unlock)."""
            status["unlock_reason"] = reason
            status["state"] = f"Unlocking ({reason})"
            return False

        # Update common status fields
        status["solar_t_start"] = _h_to_hhmm(self._solar_t_start)

        # --- Exception 1: No solar forecast sensor or unavailable ---
        if not self.solar_forecast_sensor:
            _LOGGER.info("Charge Delay: No solar forecast sensor configured - unlocking (reason: no_forecast)")
            return _unlock("no_forecast")

        # A configured forecast sensor can briefly read unavailable/unknown/invalid
        # while it updates. Treating that transient blip as "no forecast" would
        # commit a PERMANENT daily unlock (see _is_charge_delayed), so a momentary
        # gap silently disables the delay for the rest of the day. Instead, hold the
        # current delay through a short grace window and only unlock if the sensor
        # stays unavailable. (A sensor that is not configured at all still unlocks
        # immediately above — that is a deliberate fail-safe, not a transient.)
        forecast_state = self.hass.states.get(self.solar_forecast_sensor)
        raw_forecast = None
        if forecast_state is not None and forecast_state.state not in ("unknown", "unavailable"):
            try:
                raw_forecast = float(forecast_state.state)
            except (ValueError, TypeError):
                raw_forecast = None

        if raw_forecast is None:
            mono = monotonic()
            if self._forecast_unavailable_since is None:
                self._forecast_unavailable_since = mono
            unavailable_s = mono - self._forecast_unavailable_since
            if unavailable_s < self._forecast_grace_s:
                status["state"] = "Waiting for forecast"
                _LOGGER.debug(
                    "Charge Delay: forecast unavailable for %.0fs (< %ds grace) - holding delay",
                    unavailable_s, self._forecast_grace_s,
                )
                return True  # keep the delay active; re-evaluate when the sensor recovers
            _LOGGER.info(
                "Charge Delay: Solar forecast unavailable for %.0fs (> grace) - unlocking (reason: no_forecast)",
                unavailable_s,
            )
            return _unlock("no_forecast")

        # Forecast recovered / valid — clear the transient tracker.
        self._forecast_unavailable_since = None
        forecast_today = raw_forecast * 0.85  # 15% conservative correction
        status["forecast_kwh"] = raw_forecast

        # --- Exception 2: Energy balance check (dynamic, recalculated only when forecast changes) ---
        total_capacity_kwh = sum(
            c.data.get("battery_total_energy", 0) for c in self.coordinators if c.data
        )
        if total_capacity_kwh <= 0:
            _LOGGER.info("Charge Delay: Invalid battery capacity - unlocking")
            return _unlock("no_forecast")

        if (
            self._charge_delay_forecast_cache is None
            or abs(forecast_today - self._charge_delay_forecast_cache) > 0.05
        ):
            coordinators_with_data = [c for c in self.coordinators if c.data]
            avg_soc = (
                sum(c.data.get("battery_soc", 0) for c in coordinators_with_data)
                / len(coordinators_with_data)
            ) if coordinators_with_data else 0
            min_soc_values = [c.min_soc for c in self.coordinators]
            min_soc = max(min_soc_values) if min_soc_values else 20
            usable_energy_kwh = max(0, ((avg_soc - min_soc) / 100) * total_capacity_kwh)
            avg_consumption_kwh = self._consumption_tracker.get_avg_daily_consumption()
            prev_cache = self._charge_delay_forecast_cache
            self._charge_delay_balance_needs_charge = (
                (usable_energy_kwh + forecast_today) < avg_consumption_kwh
            )
            self._charge_delay_forecast_cache = forecast_today
            _LOGGER.info(
                "Charge Delay: Forecast %s (%.2f → %.2f kWh) → "
                "balance: %.2f usable + %.2f solar = %.2f kWh vs %.2f kWh consumption → %s",
                "initialised" if prev_cache is None else "changed",
                prev_cache if prev_cache is not None else 0.0, forecast_today,
                usable_energy_kwh, forecast_today, usable_energy_kwh + forecast_today,
                avg_consumption_kwh,
                "grid needed (unlock delay)" if self._charge_delay_balance_needs_charge else "solar sufficient (keep delay)",
            )

        if self._charge_delay_balance_needs_charge:
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
        t_end = self._consumption_tracker.estimate_t_end()
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
        max_charge_power_kw = self._effective_system_capacity(
            self.coordinators,
            is_charging=True,
        ) / 1000.0
        if max_charge_power_kw <= 0:
            return _unlock("no_charge_power")
        charge_time_h = energy_needed_kwh / (max_charge_power_kw * CHARGE_EFFICIENCY)

        # Remaining solar and consumption
        if self.household_consumption_sensor and self._solar_production_accumulator > 0:
            # Use actual measured solar production to estimate remaining
            remaining_solar_kwh = max(0.0, forecast_today - self._solar_production_accumulator)
            status["solar_produced_today_kwh"] = round(self._solar_production_accumulator, 2)
        else:
            solar_fraction_done = self._consumption_tracker.get_solar_fraction_done(now_h, self._solar_t_start, t_end)
            remaining_solar_kwh = forecast_today * (1.0 - solar_fraction_done)

        hours_to_t_end = max(0, t_end - now_h)
        # avg_consumption is measured over the consumption window (outside any
        # charging_time_slot, or 24h if none is configured) — see
        # ConsumptionTracker.is_in_consumption_window. Prorate against the
        # portion of [now, t_end] that overlaps that same window.
        window_hours_per_day = self._consumption_tracker.get_consumption_window_hours_per_day()
        if window_hours_per_day > 0 and hours_to_t_end > 0:
            avg_consumption = self._consumption_tracker.get_avg_daily_consumption()
            remaining_window_hours = self._consumption_tracker.consumption_window_hours_in_range(
                now_h, t_end
            )
            remaining_consumption_kwh = avg_consumption * (
                remaining_window_hours / window_hours_per_day
            )
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
        if (
            energy_balance_unlock_h is not None
            and energy_balance_unlock_h <= now_h
            and not energy_insufficient
        ):
            energy_balance_unlock_h = None
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
        daylight_hours = t_end - t_start
        if daylight_hours <= 0:
            return None

        # Keep this aligned with _should_delay_charge(): avg_consumption is
        # measured over the configured consumption window, not daylight hours.
        avg_consumption = self._consumption_tracker.get_avg_daily_consumption()
        window_hours_per_day = self._consumption_tracker.get_consumption_window_hours_per_day()
        threshold = energy_needed_kwh * DELAY_SAFETY_FACTOR

        def net_solar_at(t: float) -> float:
            """Net solar available for battery at time t."""
            progress = max(0.0, min(1.0, (t - t_start) / daylight_hours))
            fraction_done = (1.0 - math.cos(math.pi * progress)) / 2.0
            remaining_solar = forecast_kwh * (1.0 - fraction_done)
            remaining_window_hours = self._consumption_tracker.consumption_window_hours_in_range(
                t, t_end
            )
            remaining_consumption = (
                avg_consumption * (remaining_window_hours / window_hours_per_day)
                if window_hours_per_day > 0 and remaining_window_hours > 0
                else 0.0
            )
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
        self._grid_filter_ema = None
        self.first_execution = True  # Force re-initialization on next cycle
        
        _LOGGER.info("PID: State reset complete - system will re-initialize on next control cycle")

    async def _startup_dynamic_pricing_evaluation(self) -> None:
        """Run dynamic pricing evaluation at startup if the 00:05 window was missed.

        Called once via async_create_task after integration load. Waits 15 s for
        coordinators to complete their first poll, then evaluates if today's schedule
        has not been built yet (e.g. HA restarted after 00:05).
        """
        now = datetime.now()

        # Nothing to do if we're still before the normal 00:05 window
        eval_cutoff = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if now < eval_cutoff:
            _LOGGER.debug("Dynamic pricing: startup check skipped — before 00:05 window")
            return

        # Already evaluated today (00:05 ran before the restart)
        if self._dynamic_pricing_evaluated_date == now.date():
            _LOGGER.debug("Dynamic pricing: startup check skipped — already evaluated today")
            return

        # Give coordinators time to finish their first Modbus poll cycle
        await asyncio.sleep(15)

        if not self.predictive_charging_enabled:
            return  # Unloaded during sleep

        coordinators_with_data = [c for c in self.coordinators if c.data]
        if not coordinators_with_data:
            _LOGGER.warning(
                "Dynamic pricing: startup evaluation skipped — no coordinator data after 15 s"
            )
            return

        _LOGGER.info(
            "Dynamic pricing: running startup evaluation "
            "(restarted at %s, schedule not yet built for %s)",
            now.strftime("%H:%M"), now.date()
        )
        await self._evaluate_dynamic_pricing()

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

        # Safety margin: user-configurable buffer added to consumption forecast.
        # Guardrail: never exceed total system capacity.
        safety_margin_kwh = min(self._predictive_safety_margin_kwh, total_capacity_kwh)

        # Get dynamic consumption forecast
        avg_consumption_kwh = await self._consumption_tracker.get_dynamic_base_consumption()
        days_in_history = len(self._daily_consumption_history)

        # === STEP 4: Get Solar Forecast ===
        # Use the live sensor value directly — today's forecast updates throughout the day
        # and reflects improving accuracy as actual weather conditions develop.
        forecast_state = self.hass.states.get(self.solar_forecast_sensor)
        if forecast_state is None or forecast_state.state in ("unknown", "unavailable"):
            # Conservative mode: assume zero solar, compare usable vs consumption
            total_available_kwh = usable_energy_kwh
            energy_deficit_kwh = avg_consumption_kwh + safety_margin_kwh - total_available_kwh
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
            energy_deficit_kwh = avg_consumption_kwh + safety_margin_kwh - total_available_kwh
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
        energy_deficit_kwh = avg_consumption_kwh + safety_margin_kwh - total_available_kwh
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
            "    - Safety margin: %.2f kWh\n"
            "    - Total available: %.2f kWh (usable + solar)\n"
            "    - Energy deficit: %.2f kWh (consumption + margin - available)\n"
            "  → Decision: %s",
            total_capacity_kwh,
            avg_soc, stored_energy_kwh,
            min_soc, cutoff_energy_kwh,
            usable_energy_kwh,
            solar_forecast_kwh,
            avg_consumption_kwh, days_in_history,
            safety_margin_kwh,
            total_available_kwh,
            energy_deficit_kwh,
            "ACTIVATE CHARGING" if should_charge else "NO CHARGING NEEDED"
        )

        # === STEP 7: Return Complete Decision Data ===
        # Grid-only charge split: how much comes from grid vs solar
        _max_soc_values = [c.max_soc for c in coordinators_with_data]
        _config_max_soc = min(_max_soc_values) if _max_soc_values else 95
        _gap_to_max_kwh = max(0.0, (_config_max_soc - avg_soc) / 100.0 * total_capacity_kwh)
        solar_surplus_kwh = max(0.0, solar_forecast_kwh - avg_consumption_kwh)
        _grid_margin_factor = 1.0 + self._predictive_grid_charge_margin_pct / 100.0
        grid_charge_kwh = min(
            _gap_to_max_kwh,
            max(0.0, _gap_to_max_kwh - solar_surplus_kwh) * _grid_margin_factor,
        )

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
            "solar_surplus_kwh": solar_surplus_kwh,
            "grid_charge_kwh": grid_charge_kwh,
            "consumption_source": "household_sensor" if self.household_consumption_sensor else "battery_discharge",
            "reason": (
                f"Energy deficit: {energy_deficit_kwh:.2f} kWh "
                f"(available: {total_available_kwh:.2f} kWh < consumption: {avg_consumption_kwh:.2f} kWh"
                + (f" + margin: {safety_margin_kwh:.2f} kWh" if safety_margin_kwh > 0 else "") + ")"
                if should_charge else
                f"Sufficient energy: {total_available_kwh:.2f} kWh available "
                f"≥ {avg_consumption_kwh:.2f} kWh consumption"
                + (f" + {safety_margin_kwh:.2f} kWh margin" if safety_margin_kwh > 0 else "")
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
    


    def _excluded_devices_consumption_delta_kw(self) -> float:
        """Net kW correction to apply to the home sensor for excluded-device accounting.

        Returns a value to ADD to the raw home sensor reading so the accumulator
        reflects only the load the battery is expected to cover:
          - included_in_consumption=True  → device IS in home sensor but battery skips it → subtract
          - included_in_consumption=False → device NOT in home sensor but battery covers it → add
        ev_charger_no_telemetry devices are skipped (no numeric power sensor).
        Unavailable sensors are silently ignored.
        """
        excluded_devices = self.config_entry.data.get("excluded_devices", [])
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
            state = self.hass.states.get(power_sensor)
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

    def _is_in_predictive_charging_slot(self) -> bool:
        """Check if we're currently within the predictive charging time slot."""
        if not self.predictive_charging_enabled or self.charging_time_slot is None:
            return False

        # Check manual override
        if self.predictive_charging_overridden:
            return False

        return self._check_time_window()

    def _compute_predictive_target_soc(self) -> Optional[dict]:
        """Calculate per-battery grid-only SOC targets for predictive charging.

        Each battery's share of grid charge is proportional to its gap to max_soc,
        so batteries with a larger gap get more grid charge and batteries that are
        already near max_soc rely mostly on solar.

          total_gap     = Σ (max_soc_i - soc_i) / 100 × capacity_i
          solar_surplus = max(0, solar_forecast - consumption_forecast)
          grid_charge   = max(0, total_gap - solar_surplus)
          share_i       = (gap_i / total_gap) × grid_charge
          target_soc_i  = min(max_soc_i, soc_i + share_i / capacity_i × 100)

        Returns dict {coordinator: target_soc_%} or None if data is insufficient
        (callers fall back to max_soc behaviour when None is returned).
        """
        decision_data = self._last_decision_data
        if not decision_data:
            return None

        coordinators_with_data = [c for c in self.coordinators if c.data]
        if not coordinators_with_data:
            return None

        solar_forecast_kwh = decision_data.get("solar_forecast_kwh") or 0.0
        avg_consumption_kwh = decision_data.get("avg_consumption_kwh", 0.0)

        # Per-battery gap to max_soc (kWh)
        gaps: dict = {}
        for c in coordinators_with_data:
            capacity = c.data.get("battery_total_energy", 0)
            current_soc = c.data.get("battery_soc", 0)
            gaps[c] = max(0.0, (c.max_soc - current_soc) / 100.0 * capacity)

        total_gap_kwh = sum(gaps.values())
        if total_gap_kwh <= 0:
            return None

        solar_surplus_kwh = max(0.0, solar_forecast_kwh - avg_consumption_kwh)
        margin_factor = 1.0 + self._predictive_grid_charge_margin_pct / 100.0
        grid_charge_kwh = min(
            total_gap_kwh,
            max(0.0, total_gap_kwh - solar_surplus_kwh) * margin_factor,
        )

        targets: dict = {}
        for c in coordinators_with_data:
            capacity = c.data.get("battery_total_energy", 0)
            current_soc = c.data.get("battery_soc", 0)
            if capacity <= 0:
                targets[c] = c.max_soc
                continue
            share_kwh = (gaps[c] / total_gap_kwh) * grid_charge_kwh
            target = min(c.max_soc, current_soc + (share_kwh / capacity) * 100.0)
            targets[c] = max(target, current_soc)  # never go below current SOC

        _LOGGER.info(
            "Predictive charging: per-battery grid-only targets "
            "(solar_surplus=%.2f kWh, grid_charge=%.2f kWh / total_gap=%.2f kWh): %s",
            solar_surplus_kwh, grid_charge_kwh, total_gap_kwh,
            {c.name: f"{v:.1f}%" for c, v in targets.items()},
        )
        return targets

    async def _handle_predictive_grid_charging(self):
        """
        Handle predictive grid charging mode.

        Target: Keep consumption/export sensor at max_contracted_power.
        If home consumption increases, reduce battery charging to avoid exceeding ICP.
        """
        if self.is_charge_blocked():
            _LOGGER.debug(
                "Predictive charging paused by charge blockers: %s",
                ", ".join(self.get_charge_blockers().keys()),
            )
            self.grid_charging_active = False
            self._grid_charging_initialized = False
            self.previous_power = 0
            self.previous_error = 0
            for coordinator in self.coordinators:
                if self._is_active_balance_mode_running(coordinator):
                    continue
                await self._set_battery_power(coordinator, 0, 0)
            return

        consumption_state = self.hass.states.get(self.consumption_sensor)
        sensor_raw = self._apply_meter_transform(consumption_state)
        if sensor_raw is None:
            _LOGGER.warning("Consumption sensor unavailable or invalid during predictive charging")
            return

        # Cadence-independent time bases (this loop runs event-driven too). The stored
        # timestamp is shared with the main loop; exactly one of the two runs per cycle.
        sensor_update_time = consumption_state.last_updated
        previous_update_time = self._last_sensor_update_time
        self._last_sensor_update_time = sensor_update_time
        sensor_elapsed_s = (
            (sensor_update_time - previous_update_time).total_seconds()
            if previous_update_time is not None else None
        )
        base_dt = sensor_elapsed_s if (sensor_elapsed_s and sensor_elapsed_s > 0) else self.dt
        real_dt = max(1.0, min(base_dt, 30.0))
        scale_dt = max(0.1, min(base_dt, 30.0))

        # Apply sensor filtering (shared time-constant EMA).
        sensor_filtered = self._filter_grid_sample(sensor_raw, sensor_elapsed_s)
        
        # Get available batteries (respecting max_soc)
        available_batteries = self._get_available_batteries(is_charging=True)
        if not available_batteries:
            _LOGGER.info("Predictive charging complete: all batteries at max_soc - resuming normal operation")
            self.grid_charging_active = False
            self._grid_charging_initialized = False
            self.first_execution = True
            return
        
        # Calculate max available charging power from batteries
        max_battery_charge = self._effective_system_capacity(
            available_batteries,
            is_charging=True,
        )
        
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
            self.derivative_filtered = 0.0  # drop any derivative carried from the main loop
            self.previous_power = -min(max_battery_charge, target_power)  # Start at max charge
            self._grid_charging_initialized = True
            self.first_execution = False  # Mark as initialized to avoid conflicts
            self._predictive_charge_target_soc = self._compute_predictive_target_soc()
            _LOGGER.info("Initialized predictive charging: target=%dW, initial_charge=%dW",
                        target_power, abs(self.previous_power))
        
        # Calculate derivative over real elapsed time, low-pass filtered (see main loop).
        error_derivative_raw = (error - self.previous_error) / real_dt
        d_alpha = real_dt / (self.derivative_tau + real_dt)
        self.derivative_filtered += d_alpha * (error_derivative_raw - self.derivative_filtered)

        # PD terms. P is applied incrementally (integral action), so scale it by elapsed
        # time normalized to the nominal dt to keep tuning cadence-independent.
        P = self.kp * error * (scale_dt / self.dt)
        D = self.kd * self.derivative_filtered
        pd_adjustment = P + D
        
        # Calculate new charging power (incremental)
        # If error > 0 (importing too little) -> increase charging (adjustment is positive -> previous_power becomes more negative)
        # If error < 0 (importing too much) -> reduce charging (adjustment is negative -> previous_power becomes less negative)
        new_power_raw = self.previous_power - pd_adjustment
        
        # Apply rate limiter (per-cycle cap scaled to a constant W/s under variable cadence)
        max_change = self.max_power_change_per_cycle * (scale_dt / self.dt)
        power_change = new_power_raw - self.previous_power
        if abs(power_change) > max_change:
            sign = 1 if power_change > 0 else -1
            clamped_change = sign * max_change
            new_power = self.previous_power + clamped_change
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
                if self._is_active_balance_mode_running(coordinator):
                    continue
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
            limits[c] = self._battery_power_limit(c, is_charging)

        total_capacity = sum(limits.values())
        if total_capacity <= 0:
            return {c: 0 for c in available_batteries}

        # Clamp total request to selected-battery capacity and optional system cap.
        remaining_power = self._clamp_to_system_capacity(
            min(total_power, total_capacity),
            available_batteries,
            is_charging,
        )

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
        """Select minimum batteries needed for efficient load sharing.

        Activation threshold is derived per step from absolute efficiency crossover
        wattages (where splitting across 2 batteries beats a single battery on η external):
        - Discharge: 1500 W crossover → threshold = 1500 / this_battery_max
        - Charge:    1750 W crossover → threshold = 1750 / this_battery_max
        Clamped to [MIN_ACTIVATION, MAX_ACTIVATION] from const.py.
        Using each battery's own capacity ensures correct behaviour in heterogeneous
        setups (e.g. v3 2500 W + Venus A 1500 W).

        Prioritizes:
        - Discharge: Highest SOC first (drain fullest battery first)
        - Charge: Lowest SOC first (fill emptiest battery first)

        Hysteresis:
        - SOC: Active batteries get 5% effective SOC advantage to avoid ping-pong
        - Power: Deactivation threshold = activation threshold − 10 pp
        """
        # No power requested: clear load-sharing state. This must run before
        # the single-battery fast path so a one-battery system is not retained
        # as active while the controller is intentionally idle.
        if total_power <= 0:
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            self._discharge_selection_hold_until.clear()
            self._charge_selection_hold_until.clear()
            return []

        if len(available_batteries) <= 1:
            # Even with a single battery, update tracking state so the Active
            # Batteries diagnostic sensor correctly reflects charging/discharging
            # instead of always showing "Idle".
            selected = list(available_batteries)
            if is_charging:
                self._active_charge_batteries = selected
                self._active_discharge_batteries = []
                self._discharge_selection_hold_until.clear()
                self._charge_selection_hold_until.clear()
            else:
                self._active_discharge_batteries = selected
                self._active_charge_batteries = []
                self._discharge_selection_hold_until.clear()
                self._charge_selection_hold_until.clear()
            return selected

        # Clamp the request to the capacity of currently available batteries.
        total_power = self._clamp_to_system_capacity(
            total_power,
            available_batteries,
            is_charging,
        )

        crossover_w = (
            MULTI_BATTERY_CHARGE_CROSSOVER_W if is_charging
            else MULTI_BATTERY_DISCHARGE_CROSSOVER_W
        )
        activation_threshold = MULTI_BATTERY_MIN_ACTIVATION  # updated per step in loop
        SOC_HYSTERESIS = 5.0
        ENERGY_HYSTERESIS = 2.5  # kWh advantage for active battery in tiebreaker

        previous_active = (
            self._active_charge_batteries if is_charging
            else self._active_discharge_batteries
        )
        hold_until = (
            self._charge_selection_hold_until if is_charging
            else self._discharge_selection_hold_until
        )
        now = time.monotonic()

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
            limit = self._battery_power_limit(battery, is_charging)
            combined_capacity += limit
            activation_threshold = max(
                MULTI_BATTERY_MIN_ACTIVATION,
                min(MULTI_BATTERY_MAX_ACTIVATION, crossover_w / limit)
            )
            if total_power <= combined_capacity * activation_threshold:
                break

        # Power hysteresis: avoid oscillating near the activation threshold.
        if len(available_batteries) > 1 and previous_active:
            # Case A — deactivation hysteresis: the loop dropped a previously-active battery.
            # Only confirm its removal if power fell clearly below the activation threshold;
            # otherwise re-add it so it stays active until the load genuinely drops.
            for battery in previous_active:
                if battery not in selected and battery in available_batteries:
                    limit = self._battery_power_limit(battery, is_charging)
                    first_limit = (
                        self._battery_power_limit(selected[0], is_charging)
                    ) if selected else limit
                    act_thr = max(MULTI_BATTERY_MIN_ACTIVATION,
                                  min(MULTI_BATTERY_MAX_ACTIVATION, crossover_w / first_limit))
                    deact_thr = max(MULTI_BATTERY_MIN_ACTIVATION, act_thr - MULTI_BATTERY_HYSTERESIS_GAP)
                    if total_power > combined_capacity * deact_thr:
                        selected.append(battery)
                        combined_capacity += limit

            # Case B — activation hysteresis: the loop just added a battery that was not
            # previously active.  Only commit to using it if power is clearly above the
            # threshold; if it is near the boundary, keep a single battery to prevent
            # rapid on/off cycling.
            if len(selected) > 1:
                last = selected[-1]
                if last not in previous_active:
                    last_limit = self._battery_power_limit(last, is_charging)
                    capacity_without_last = combined_capacity - last_limit
                    prev_limit = self._battery_power_limit(selected[-2], is_charging)
                    act_thr_with_hyst = min(
                        max(MULTI_BATTERY_MIN_ACTIVATION,
                            min(MULTI_BATTERY_MAX_ACTIVATION, crossover_w / prev_limit))
                        + MULTI_BATTERY_HYSTERESIS_GAP,
                        MULTI_BATTERY_MAX_ACTIVATION,
                    )
                    if total_power <= capacity_without_last * act_thr_with_hyst:
                        selected.pop()
                        combined_capacity -= last_limit

        split_condition_active = len(selected) > 1
        hold_refreshed = set()

        # Minimum split duration: when the selector decides that more than one
        # battery should participate, refresh a wall-clock hold for every battery
        # in the split. Deadband early returns may skip selector calls, so expiry
        # must be time-based rather than tied to PD write cycles.
        if split_condition_active:
            for battery in selected:
                hold_until[battery] = now + MULTI_BATTERY_SELECTION_HOLD_SECONDS
                hold_refreshed.add(battery)

        for battery in previous_active:
            if (
                battery not in selected
                and battery in available_batteries
                and hold_until.get(battery, 0) > now
            ):
                selected.append(battery)
                held_limit = self._battery_power_limit(battery, is_charging)
                combined_capacity += held_limit
                remaining_seconds = math.ceil(hold_until[battery] - now)
                _LOGGER.debug(
                    "Load sharing [%s]: holding %s active for %d more seconds",
                    "charge" if is_charging else "discharge",
                    battery.name,
                    remaining_seconds,
                )

        for battery in list(hold_until):
            if hold_until[battery] <= now or battery not in selected:
                hold_until.pop(battery, None)

        # Log when selection changes
        if set(selected) != set(previous_active):
            mode = "charge" if is_charging else "discharge"
            _LOGGER.info(
                "Load sharing [%s]: %d/%d batteries active (%s) for %dW "
                "(activation=%.0f%%)",
                mode, len(selected), len(available_batteries),
                ", ".join(c.name for c in selected), int(total_power),
                activation_threshold * 100,
            )

        # Update tracking state: clear opposite list since charge/discharge are mutually exclusive
        if is_charging:
            self._active_charge_batteries = list(selected)
            self._active_discharge_batteries = []
            self._discharge_selection_hold_until.clear()
        else:
            self._active_discharge_batteries = list(selected)
            self._active_charge_batteries = []
            self._charge_selection_hold_until.clear()

        return selected

    async def _rebalance_expired_load_sharing_hold(
        self,
        *,
        grid_w: float,
        target_w: float,
    ) -> bool:
        """Release expired split-load holds even when the PD loop is in deadband."""
        if self.previous_power == 0:
            return False

        is_charging = self.previous_power > 0
        active_batteries = (
            self._active_charge_batteries if is_charging
            else self._active_discharge_batteries
        )
        if len(active_batteries) <= 1:
            return False

        hold_until = (
            self._charge_selection_hold_until if is_charging
            else self._discharge_selection_hold_until
        )
        now = time.monotonic()
        if not any(hold_until.get(battery, 0) <= now for battery in active_batteries):
            return False

        available_batteries = self._get_available_batteries(is_charging)
        if not available_batteries:
            return False

        selected_batteries = self._select_batteries_for_operation(
            abs(self.previous_power),
            available_batteries,
            is_charging,
        )
        if set(selected_batteries) == set(active_batteries):
            return False

        power_allocation = self._distribute_power_by_limits(
            abs(self.previous_power),
            selected_batteries,
            is_charging,
        )
        self._log_power_command_plan(
            phase="hold_expired_deadband",
            grid_w=grid_w,
            target_w=target_w,
            previous_power_w=self.previous_power,
            requested_power_w=self.previous_power,
            is_charging=is_charging,
            available_batteries=available_batteries,
            selected_batteries=selected_batteries,
            power_allocation=power_allocation,
        )

        for coordinator in selected_batteries:
            power = power_allocation.get(coordinator, 0)
            if is_charging:
                await self._set_battery_power(coordinator, power, 0)
            else:
                await self._set_battery_power(coordinator, 0, power)

        for coordinator in self.coordinators:
            if coordinator not in selected_batteries:
                if self._is_active_balance_mode_running(coordinator):
                    continue
                await self._set_battery_power(coordinator, 0, 0)

        return True

    def _log_power_command_plan(
        self,
        *,
        phase: str,
        grid_w: float,
        target_w: float,
        previous_power_w: float,
        requested_power_w: float,
        is_charging: bool,
        available_batteries: list,
        selected_batteries: list,
        power_allocation: dict,
        operation_restricted: bool = False,
    ) -> None:
        """Log one compact control decision before per-battery writes."""
        mode = "charge" if is_charging else ("discharge" if requested_power_w < 0 else "idle")
        selected_names = [coordinator.name for coordinator in selected_batteries]
        allocation = {
            coordinator.name: int(power)
            for coordinator, power in power_allocation.items()
        }
        charge_blocks = self._format_blockers_for_log(self.get_charge_blockers())
        discharge_blocks = self._format_blockers_for_log(self.get_discharge_blockers())
        setpoints = self._format_setpoint_summary_for_log()

        _LOGGER.debug(
            "Power plan [%s]: mode=%s grid=%.1fW target=%.1fW error=%.1fW "
            "prev=%.1fW request=%.1fW allocated=%dW available=%d selected=%s "
            "allocation=%s restricted=%s charge_blocks=%s discharge_blocks=%s setpoints=%s",
            phase,
            mode,
            grid_w,
            target_w,
            grid_w - target_w,
            previous_power_w,
            requested_power_w,
            sum(allocation.values()),
            len(available_batteries),
            selected_names,
            allocation,
            operation_restricted,
            charge_blocks,
            discharge_blocks,
            setpoints,
        )

    def _log_low_power_delivery(
        self,
        coordinator: MarstekVenusDataUpdateCoordinator,
        *,
        command: str,
        commanded_power: float,
        feedback: dict,
    ) -> None:
        """Log a compact diagnostic when ACK succeeds but delivered power is low."""
        data = coordinator.data or {}
        actual_power = feedback["battery_power"]
        actual_abs = abs(actual_power)
        threshold = max(25.0, commanded_power * 0.10)

        if commanded_power < 100 or actual_abs >= threshold:
            return

        _LOGGER.debug(
            "[%s] Power delivery low: command=%s commanded=%dW "
            "readback(force=%d charge=%dW discharge=%dW) actual=%dW "
            "threshold=%.0fW soc=%s%% min_soc=%d%% max_soc=%d%% inverter=%s",
            coordinator.name,
            command,
            int(commanded_power),
            feedback["force_mode"],
            feedback["set_charge_power"],
            feedback["set_discharge_power"],
            actual_power,
            threshold,
            data.get("battery_soc"),
            coordinator.min_soc,
            coordinator.max_soc,
            data.get("inverter_state"),
        )

    async def _set_battery_power(
        self,
        coordinator: MarstekVenusDataUpdateCoordinator,
        charge_power: float,
        discharge_power: float,
        ignore_charge_blockers: set[str] | None = None,
        ignore_discharge_blockers: set[str] | None = None,
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

        # Skip if backup function is active (battery manages itself autonomously)
        if self._is_backup_function_active(coordinator):
            _LOGGER.debug(
                "[%s] Skipping power write - backup function is active",
                coordinator.name
            )
            return False

        # Skip if the user disabled RS485 control (battery driven by the official
        # app / its own logic — must stay out of all PD power writes).
        if coordinator.rs485_user_disabled:
            _LOGGER.debug(
                "[%s] Skipping power write - RS485 control disabled by user",
                coordinator.name
            )
            return False

        # Skip if a manual time slot already commanded this coord this cycle.
        if self._is_manual_slot_owned(coordinator):
            _LOGGER.debug(
                "[%s] Skipping power write - manual time slot owns this battery",
                coordinator.name
            )
            return False

        if charge_power > 0:
            charge_blockers = self.get_charge_blockers(coordinator)
            if ignore_charge_blockers:
                charge_blockers = {
                    source: block
                    for source, block in charge_blockers.items()
                    if source not in ignore_charge_blockers
                }
        else:
            charge_blockers = {}

        if charge_power > 0 and charge_blockers:
            _LOGGER.debug(
                "[%s] Charge command suppressed by blockers: %s",
                coordinator.name,
                ", ".join(charge_blockers.keys()),
            )
            charge_power = 0

        if discharge_power > 0:
            discharge_blockers = self.get_discharge_blockers(coordinator)
            if ignore_discharge_blockers:
                discharge_blockers = {
                    source: block
                    for source, block in discharge_blockers.items()
                    if source not in ignore_discharge_blockers
                }
        else:
            discharge_blockers = {}

        if discharge_power > 0 and discharge_blockers:
            _LOGGER.debug(
                "[%s] Discharge command suppressed by blockers: %s",
                coordinator.name,
                ", ".join(discharge_blockers.keys()),
            )
            discharge_power = 0

        # Clear any legacy balance hold that may have been restored from storage.
        if coordinator.balance_hold and discharge_power > 0:
            _LOGGER.debug("[%s] Legacy balance hold active - discharge suppressed", coordinator.name)
            discharge_power = 0

        # Determine expected force mode
        if charge_power > 0:
            expected_force_mode = 1  # Charge
        elif discharge_power > 0:
            expected_force_mode = 2  # Discharge
        else:
            expected_force_mode = 0  # None

        # Attempt atomic write + verify, with one retry on failure.
        # last_fail_reason carries the most specific failure category seen across
        # both attempts so the non-responsive tracker can surface *why*.
        last_fail_reason: str | None = None
        for attempt in range(2):
            feedback = await coordinator.write_power_atomic(
                int(discharge_power), int(charge_power), expected_force_mode
            )

            if feedback is None:
                last_fail_reason = getattr(
                    coordinator, "_last_write_failure_reason", None
                ) or "comm_failure"
                if not coordinator._is_shutting_down:
                    _LOGGER.warning(
                        "[%s] Power write/feedback failed (attempt %d/2, reason=%s)",
                        coordinator.name, attempt + 1, last_fail_reason
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
                    "[%s] Power ACK: requested(force=%d charge=%dW discharge=%dW) "
                    "readback(force=%d charge=%dW discharge=%dW battery=%dW)",
                    coordinator.name,
                    expected_force_mode,
                    int(charge_power),
                    int(discharge_power),
                    feedback["force_mode"],
                    feedback["set_charge_power"],
                    feedback["set_discharge_power"],
                    feedback["battery_power"],
                )
                if charge_power > 0:
                    self._log_low_power_delivery(
                        coordinator,
                        command="charge",
                        commanded_power=charge_power,
                        feedback=feedback,
                    )
                elif discharge_power > 0:
                    self._log_low_power_delivery(
                        coordinator,
                        command="discharge",
                        commanded_power=discharge_power,
                        feedback=feedback,
                    )
                # Detect non-responsive battery: ACK ok but not delivering discharge power
                if discharge_power >= 100 and charge_power == 0:
                    actual_abs = abs(feedback["battery_power"])
                    if actual_abs < 0.10 * discharge_power:
                        # Skip non-responsive recording when the BMS is legitimately
                        # refusing discharge: either at/near the configured min-SOC, or
                        # anywhere below the low-SOC protective floor where the BMS may
                        # cut discharge on its own (e.g. a weak cell sagging under load)
                        # even though the reported SOC is still above min_soc. 0W output
                        # is then expected behaviour, not a fault. Low-SOC counterpart to
                        # the high-SOC BMS-cutoff handling.
                        current_soc = coordinator.data.get("battery_soc", 100) if coordinator.data else 100
                        bms_cutoff_floor = max(coordinator.min_soc + 1, BMS_DISCHARGE_CUTOFF_SOC)
                        if current_soc <= bms_cutoff_floor:
                            _LOGGER.debug(
                                "[%s] No discharge delivered but SOC=%.1f%% is in the BMS "
                                "low-SOC cutoff range (min_soc=%d%%, floor=%d%%) — not a fault",
                                coordinator.name, current_soc, coordinator.min_soc, bms_cutoff_floor,
                            )
                            # Comms and battery are fine, just protecting itself.
                            self._non_responsive.clear(coordinator)
                        else:
                            # ACK'd but no power: separate a battery sitting in standby
                            # (likely dropped RS485 control) from one that is awake but
                            # still refusing.
                            inv_state = coordinator.data.get("inverter_state") if coordinator.data else None
                            try:
                                is_standby = (
                                    inv_state is not None
                                    and int(inv_state) == NORMAL_BALANCE_RECAL_INVERTER_STANDBY
                                )
                            except (TypeError, ValueError):
                                is_standby = False
                            reason = "standby_no_delivery" if is_standby else "non_delivery"
                            just_excluded = self._non_responsive.record_non_delivery(
                                coordinator, discharge_power, actual_abs,
                                reason=reason, retry_attempted=attempt > 0,
                            )
                            # One-shot wake nudge, only at the moment of exclusion —
                            # a last-ditch RS485 re-assert before dropping it from the pool.
                            if just_excluded:
                                woke = await self._attempt_wake(coordinator)
                                self._non_responsive.set_wake_attempted(coordinator, woke)
                    else:
                        self._non_responsive.clear(coordinator)
                return True

            last_fail_reason = "ack_mismatch"
            if attempt == 0:
                _LOGGER.warning(
                    "[%s] Power command not ACK'd (attempt 1/2), retrying. "
                    "requested(force=%d charge=%dW discharge=%dW) "
                    "readback(force=%d charge=%dW discharge=%dW battery=%dW)",
                    coordinator.name,
                    expected_force_mode,
                    int(charge_power),
                    int(discharge_power),
                    feedback["force_mode"],
                    feedback["set_charge_power"],
                    feedback["set_discharge_power"],
                    feedback["battery_power"],
                )

        # Both attempts failed at the Modbus/ACK level — feed the tracker so the
        # diagnostic sensor can report the specific reason (and so repeated comms
        # failures eventually exclude the battery, same as non-delivery).
        if not coordinator._is_shutting_down:
            self._non_responsive.record_comm_failure(
                coordinator, last_fail_reason or "comm_failure"
            )
            _LOGGER.error(
                "[%s] Power command failed after 2 attempts (reason=%s). "
                "Battery may not have received command.",
                coordinator.name, last_fail_reason or "comm_failure"
            )
        return False

    async def _attempt_wake(self, coordinator) -> bool:
        """Toggle RS485 control off→on as a wake nudge for an unresponsive battery.

        A battery that ACKs power commands but delivers 0 W has usually dropped its
        RS485 control mode (e.g. it slipped into standby). Simply re-asserting the
        enable value is a no-op if the battery already believes it is enabled, so we
        force a real state transition: disable (0x55BB), wait 1 s, then re-enable
        (0x55AA). Skipped when the user has disabled RS485 control. Returns True if
        the re-enable write succeeded.
        """
        if coordinator.rs485_user_disabled:
            return False
        rs485_reg = coordinator.get_register("rs485_control")
        if not rs485_reg:
            return False
        _LOGGER.info(
            "[%s] Non-delivery — RS485 wake toggle (disable 0x55BB → 1s → enable 0x55AA)",
            coordinator.name,
        )
        await coordinator.write_register(rs485_reg, 21947, do_refresh=False)  # 0x55BB disable
        await asyncio.sleep(1)
        return await coordinator.write_register(rs485_reg, 21930, do_refresh=False)  # 0x55AA enable

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
            self._excluded_included_adjustment = 0.0
            return 0.0

        is_charging = self.previous_power >= 0

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
        self._excluded_included_adjustment = included_adjustment
        return total_adjustment

    def _check_ev_charger_state(self) -> tuple[bool, bool]:
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
        excluded_devices = self.config_entry.data.get("excluded_devices", [])
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

            state = self.hass.states.get(sensor_id)
            if state is None or state.state in ("unknown", "unavailable"):
                continue

            state_lower = state.state.lower().strip()
            is_charging = "charg" in state_lower or "cargand" in state_lower

            prev_charging = self._ev_charging_states.get(sensor_id, False)

            if is_charging and not prev_charging:
                # EV just started charging – start 5-minute battery pause
                self._ev_pause_until[sensor_id] = now + timedelta(minutes=5)
                _LOGGER.info(
                    "EV charger %s: charging detected – 5-minute battery pause started",
                    sensor_id,
                )
            elif not is_charging and prev_charging:
                # EV stopped charging – cancel any remaining pause
                self._ev_pause_until.pop(sensor_id, None)
                _LOGGER.info(
                    "EV charger %s: charging stopped – normal battery operation resumed",
                    sensor_id,
                )

            self._ev_charging_states[sensor_id] = is_charging

            pause_until = self._ev_pause_until.get(sensor_id)
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
                    self._ev_pause_until.pop(sensor_id, None)
                    if is_charging:
                        ev_charging_active = True
            elif is_charging:
                ev_charging_active = True

        return pause_active, ev_charging_active

    # =========================================================================
    # DYNAMIC PRICING: Price parsing methods
    # =========================================================================

    def _parse_nordpool_prices(self, attrs: dict) -> list:
        """Parse Nordpool / Energi Data Service price attributes.

        Expected format in raw_today / raw_tomorrow:
            [{"start": datetime, "end": datetime, "value": float}, ...]
        Returns list[PriceSlot] in local time.
        """
        from homeassistant.util import dt as dt_util

        slots = []
        for key in ("raw_today", "raw_tomorrow"):
            entries = attrs.get(key) or []
            for entry in entries:
                try:
                    start = entry.get("start")
                    end = entry.get("end")
                    value = entry.get("value")
                    if start is None or end is None or value is None:
                        continue
                    # Convert to local datetime if timezone-aware
                    if hasattr(start, "tzinfo") and start.tzinfo is not None:
                        start = dt_util.as_local(start).replace(tzinfo=None)
                    if hasattr(end, "tzinfo") and end.tzinfo is not None:
                        end = dt_util.as_local(end).replace(tzinfo=None)
                    slots.append(PriceSlot(start=start, end=end, price=float(value)))
                except Exception as exc:
                    _LOGGER.debug("Dynamic pricing: failed to parse Nordpool entry %s: %s", entry, exc)
        return slots

    def _parse_pvpc_prices(self, attrs: dict) -> list:
        """Parse PVPC (ESIOS REE, Spain) price attributes.

        Expected format: "price_00h", "price_01h", ..., "price_23h" (float, €/kWh).
        PVPC publishes next-day prices around 20:00; at 00:05 the attributes
        reflect the current day's prices (already in effect).
        Returns list[PriceSlot] for today in local time.
        """
        from datetime import date as _date, time as _time

        slots = []
        target_date = _date.today()
        for hour in range(24):
            attr_name = f"price_{hour:02d}h"
            price_val = attrs.get(attr_name)
            if price_val is None:
                continue
            try:
                price = float(price_val)
            except (ValueError, TypeError):
                _LOGGER.debug("Dynamic pricing: failed to parse PVPC attribute %s=%s", attr_name, price_val)
                continue
            start = datetime.combine(target_date, _time(hour=hour, minute=0))
            end = start + timedelta(hours=1)
            slots.append(PriceSlot(start=start, end=end, price=price))
        return slots

    def _parse_ckw_prices(self, attrs: dict) -> list:
        """Parse CKW (Switzerland) price attributes.

        Expected format in 'prices':
            [{"start": "2026-03-27T00:00+01:00", "end": "2026-03-27T00:15+01:00", "price": 0.2402}, ...]
        96 slots per day (15-minute intervals). Prices in CHF/kWh.
        Returns list[PriceSlot] in local time.
        """
        from homeassistant.util import dt as dt_util
        from datetime import datetime as _dt

        slots = []
        entries = attrs.get("prices") or []
        for entry in entries:
            try:
                start = entry.get("start")
                end = entry.get("end")
                price_val = entry.get("price")
                if price_val is None:
                    # Some CKW-derived sensors expose the total price under a
                    # generic/value-style key. Values are expected in CHF/kWh.
                    price_val = entry.get("value", entry.get("integrated"))
                if start is None or end is None or price_val is None:
                    continue
                # Parse ISO 8601 string timestamps if needed
                if isinstance(start, str):
                    start = _dt.fromisoformat(start)
                if isinstance(end, str):
                    end = _dt.fromisoformat(end)
                # Convert to local naive datetime
                if hasattr(start, "tzinfo") and start.tzinfo is not None:
                    start = dt_util.as_local(start).replace(tzinfo=None)
                if hasattr(end, "tzinfo") and end.tzinfo is not None:
                    end = dt_util.as_local(end).replace(tzinfo=None)
                slots.append(PriceSlot(start=start, end=end, price=float(price_val)))
            except Exception as exc:
                _LOGGER.debug("Dynamic pricing: failed to parse CKW entry %s: %s", entry, exc)
        return slots

    def _parse_epex_prices(self, attrs: dict) -> list:
        """Parse EPEX Spot (e.g. aWATTar) price attributes.

        Expected format in 'data':
            [{"start_time": "2026-05-22T00:00:00+02:00",
              "end_time":   "2026-05-22T01:00:00+02:00",
              "price_per_kwh": 0.14977}, ...]
        Hourly slots in EUR/kWh, typically covering today and tomorrow
        once published.
        Returns list[PriceSlot] in local naive time.
        """
        from homeassistant.util import dt as dt_util
        from datetime import datetime as _dt

        slots = []
        entries = attrs.get("data") or []
        for entry in entries:
            try:
                start = entry.get("start_time")
                end = entry.get("end_time")
                price_val = entry.get("price_per_kwh")
                if start is None or end is None or price_val is None:
                    continue
                if isinstance(start, str):
                    start = _dt.fromisoformat(start)
                if isinstance(end, str):
                    end = _dt.fromisoformat(end)
                if hasattr(start, "tzinfo") and start.tzinfo is not None:
                    start = dt_util.as_local(start).replace(tzinfo=None)
                if hasattr(end, "tzinfo") and end.tzinfo is not None:
                    end = dt_util.as_local(end).replace(tzinfo=None)
                slots.append(PriceSlot(start=start, end=end, price=float(price_val)))
            except Exception as exc:
                _LOGGER.debug("Dynamic pricing: failed to parse EPEX entry %s: %s", entry, exc)
        return slots

    def _parse_entsoe_prices(self, attrs: dict) -> list:
        """Parse ENTSO-e Transparency Platform prices (HA jaapp integration).

        Expected attributes:
            prices_today / prices_tomorrow:
                [{"time": "2026-05-13 00:00:00+02:00", "price": 0.26027}, ...]
        Slots may be hourly or 15-minute. Each slot's end is inferred from the
        next slot's start time; the last slot inherits the previous delta and
        falls back to 60 minutes when only one entry exists.
        Returns list[PriceSlot] in local naive time, in chronological order.
        """
        from homeassistant.util import dt as dt_util
        from datetime import datetime as _dt, timedelta as _td

        raw = []
        for key in ("prices_today", "prices_tomorrow"):
            entries = attrs.get(key) or []
            for entry in entries:
                try:
                    start = entry.get("time")
                    price_val = entry.get("price")
                    if start is None or price_val is None:
                        continue
                    if isinstance(start, str):
                        start = _dt.fromisoformat(start)
                    if hasattr(start, "tzinfo") and start.tzinfo is not None:
                        start = dt_util.as_local(start).replace(tzinfo=None)
                    raw.append((start, float(price_val)))
                except Exception as exc:
                    _LOGGER.debug("Dynamic pricing: failed to parse ENTSO-e entry %s: %s", entry, exc)

        if not raw:
            return []

        raw.sort(key=lambda x: x[0])
        slots = []
        for i, (start, price) in enumerate(raw):
            if i + 1 < len(raw):
                end = raw[i + 1][0]
            elif i > 0:
                end = start + (raw[i][0] - raw[i - 1][0])
            else:
                end = start + _td(hours=1)
            slots.append(PriceSlot(start=start, end=end, price=price))
        return slots

    def _get_price_unit(self) -> str:
        """Return the price unit label for the configured integration."""
        if self.price_integration_type == PRICE_INTEGRATION_CKW:
            return "CHF/kWh"
        return "€/kWh"

    def _get_current_price(self) -> Optional[float]:
        """Return the current period price from the configured price sensor."""
        if not self.price_sensor:
            return None

        price_state = self.hass.states.get(self.price_sensor)
        if price_state is None:
            return None

        if self.price_integration_type == PRICE_INTEGRATION_CKW:
            now = datetime.now()
            for slot in self._parse_ckw_prices(price_state.attributes):
                if slot.start <= now < slot.end:
                    return slot.price

        if self.price_integration_type == PRICE_INTEGRATION_EPEX:
            now = datetime.now()
            for slot in self._parse_epex_prices(price_state.attributes):
                if slot.start <= now < slot.end:
                    return slot.price

        if self.price_integration_type == PRICE_INTEGRATION_ENTSOE:
            now = datetime.now()
            for slot in self._parse_entsoe_prices(price_state.attributes):
                if slot.start <= now < slot.end:
                    return slot.price

        try:
            return float(price_state.state)
        except (ValueError, TypeError):
            return None

    def _parse_price_data(self) -> list:
        """Read price sensor and return list[PriceSlot] for the next 24 hours.

        Dispatches to the correct parser based on price_integration_type.
        Returns empty list on error.
        """
        if not self.price_sensor:
            _LOGGER.warning("Dynamic pricing: no price sensor configured")
            self._price_data_status = "no_sensor"
            return []

        state = self.hass.states.get(self.price_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            _LOGGER.warning("Dynamic pricing: price sensor %s unavailable", self.price_sensor)
            self._price_data_status = "sensor_unavailable"
            return []

        attrs = state.attributes
        if self.price_integration_type == PRICE_INTEGRATION_PVPC:
            raw_slots = self._parse_pvpc_prices(attrs)
        elif self.price_integration_type == PRICE_INTEGRATION_CKW:
            raw_slots = self._parse_ckw_prices(attrs)
        elif self.price_integration_type == PRICE_INTEGRATION_EPEX:
            raw_slots = self._parse_epex_prices(attrs)
        elif self.price_integration_type == PRICE_INTEGRATION_ENTSOE:
            raw_slots = self._parse_entsoe_prices(attrs)
        else:
            # Nordpool
            raw_slots = self._parse_nordpool_prices(attrs)

        if not raw_slots:
            _LOGGER.warning(
                "Dynamic pricing: no price data parsed from %s (integration=%s)",
                self.price_sensor, self.price_integration_type
            )
            self._price_data_status = "no_slots"
            return []

        # Filter to remaining slots of the current day (00:00–23:59:59 today).
        # Using end-of-day instead of now+24h ensures that a mid-day restart does
        # not pull in tomorrow's cheap slots — those are handled by the 00:05 evaluation.
        now = datetime.now()
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        filtered = [s for s in raw_slots if s.end > now and s.start <= end_of_day]
        self._price_data_status = f"ok ({len(filtered)} slots)"
        _LOGGER.info("Dynamic pricing: parsed %d slots (%d remaining today)", len(raw_slots), len(filtered))
        return filtered

    # =========================================================================
    # DYNAMIC PRICING: Scheduling methods
    # =========================================================================

    def _calculate_charging_hours_needed(self, deficit_kwh: float) -> float:
        """Calculate how many hours of charging are needed to cover deficit.

        Uses the effective charge power: min(ICP limit, total battery charge capacity).
        If ICP > battery capacity, the batteries are the bottleneck and using ICP alone
        would underestimate the number of hours needed.
        """
        effective_power_kw = min(self.max_contracted_power, self.max_charge_capacity) / 1000.0
        if effective_power_kw <= 0:
            return 1.0  # Fallback: at least 1 hour if no power info available
        hours = deficit_kwh / (effective_power_kw * CHARGE_EFFICIENCY)
        return math.ceil(hours * 2) / 2  # Round up to nearest 0.5h

    def _select_cheapest_blocks(self, slots: list, hours_needed: float, slot_duration_h: float) -> list:
        """Select cheapest slots using a block strategy for sub-hourly granularity.

        Groups consecutive slots into 1-hour blocks (e.g. 4 × 15-min slots).
        Selects the cheapest block first, then the next cheapest, etc.
        Any remainder hours (e.g. 0.5h) use the cheapest consecutive sub-block
        of the appropriate size from the remaining slots.

        Args:
            slots: list[PriceSlot] already filtered (future + threshold)
            hours_needed: fractional hours of charging needed
            slot_duration_h: duration of each slot in hours (e.g. 0.25 for 15-min)

        Returns:
            Sorted (by start time) list of selected PriceSlot
        """
        block_size = max(1, round(1.0 / slot_duration_h))  # 4 for 15-min slots
        sorted_slots = sorted(slots, key=lambda s: s.start)
        n = len(sorted_slots)

        full_blocks_needed = int(hours_needed)
        remainder_slots_needed = round((hours_needed - full_blocks_needed) / slot_duration_h)

        def find_cheapest_window(available: list, window_size: int):
            """Return indices (into sorted_slots) of the cheapest time-consecutive window."""
            best_avg = float("inf")
            best_window = None
            for i in range(len(available) - window_size + 1):
                candidate = available[i:i + window_size]
                # Verify slots are time-consecutive (gap <= 1 min tolerance)
                consecutive = all(
                    abs((sorted_slots[candidate[j + 1]].start - sorted_slots[candidate[j]].end).total_seconds()) < 60
                    for j in range(len(candidate) - 1)
                )
                if not consecutive:
                    continue
                avg = sum(sorted_slots[idx].price for idx in candidate) / window_size
                # Prefer lower price; break ties by earlier start time
                if avg < best_avg or (avg == best_avg and best_window is not None and
                        sorted_slots[candidate[0]].start < sorted_slots[best_window[0]].start):
                    best_avg = avg
                    best_window = list(candidate)
            return best_window

        available = list(range(n))
        selected_indices = []

        # Select full 1-hour blocks
        for block_num in range(full_blocks_needed):
            window = find_cheapest_window(available, block_size)
            if window is None:
                _LOGGER.warning(
                    "Dynamic pricing: no consecutive block of %d slots available for block %d/%d, "
                    "falling back to cheapest individual slots",
                    block_size, block_num + 1, full_blocks_needed
                )
                # Fall back: pick cheapest individual available slots for this block
                by_price = sorted(available, key=lambda i: sorted_slots[i].price)
                take = min(block_size, len(by_price))
                window = by_price[:take]

            selected_indices.extend(window)
            for idx in window:
                available.remove(idx)

        # Select partial block (remainder)
        if remainder_slots_needed > 0 and available:
            window = find_cheapest_window(available, remainder_slots_needed)
            if window is None:
                _LOGGER.warning(
                    "Dynamic pricing: no consecutive window of %d slots for remainder, "
                    "falling back to cheapest individual slots",
                    remainder_slots_needed
                )
                by_price = sorted(available, key=lambda i: sorted_slots[i].price)
                window = by_price[:remainder_slots_needed]
            selected_indices.extend(window)

        hours_accumulated = len(selected_indices) * slot_duration_h
        if hours_accumulated < hours_needed:
            _LOGGER.warning(
                "Dynamic pricing: only %.1fh selected in blocks, needed %.1fh "
                "(threshold may be too low or not enough consecutive slots)",
                hours_accumulated, hours_needed
            )

        _LOGGER.info(
            "Dynamic pricing (block strategy): %d blocks × %d slots + %d remainder slots selected "
            "(%.1fh total, slot_duration=%.2fh)",
            full_blocks_needed, block_size, remainder_slots_needed,
            hours_accumulated, slot_duration_h
        )
        return sorted([sorted_slots[i] for i in selected_indices], key=lambda s: s.start)

    def _select_cheapest_hours(self, slots: list, hours_needed: float) -> list:
        """Filter slots by max_price_threshold, sort by price, return cheapest N.

        For sub-hourly granularity (e.g. 15-min slots) dispatches to
        _select_cheapest_blocks to avoid scattered fragmented charging windows.

        Args:
            slots: list[PriceSlot] available in next 24h
            hours_needed: fractional hours of charging needed

        Returns:
            Sorted (by start time) list of selected PriceSlot
        """
        now = datetime.now()

        # Remove past slots
        future_slots = [s for s in slots if s.end > now]

        # Apply price threshold filter
        if self.max_price_threshold is not None:
            future_slots = [s for s in future_slots if s.price <= self.max_price_threshold]
            _LOGGER.info(
                "Dynamic pricing: %d slots after price threshold filter (max=%.3f)",
                len(future_slots), self.max_price_threshold
            )

        if not future_slots:
            _LOGGER.warning("Dynamic pricing: no slots available after filtering")
            return []

        # Dispatch to block strategy for sub-hourly granularity
        slot_duration_h = (future_slots[0].end - future_slots[0].start).total_seconds() / 3600.0
        if slot_duration_h < 0.9:
            return self._select_cheapest_blocks(future_slots, hours_needed, slot_duration_h)

        # Hourly slots: sort by price, accumulate until hours_needed is met
        sorted_slots = sorted(future_slots, key=lambda s: (s.price, s.start))

        selected = []
        hours_accumulated = 0.0
        for slot in sorted_slots:
            slot_duration = (slot.end - slot.start).total_seconds() / 3600.0
            selected.append(slot)
            hours_accumulated += slot_duration
            if hours_accumulated >= hours_needed:
                break

        if hours_accumulated < hours_needed:
            _LOGGER.warning(
                "Dynamic pricing: only %.1fh available, needed %.1fh (threshold may be too low)",
                hours_accumulated, hours_needed
            )

        # Return sorted by start time for chronological execution
        return sorted(selected, key=lambda s: s.start)

    def _is_in_dynamic_pricing_slot(self) -> bool:
        """Return True if current time falls within a selected cheap slot."""
        if not self._dynamic_pricing_schedule:
            return False
        now = datetime.now()
        return any(s.start <= now < s.end for s in self._dynamic_pricing_schedule.selected_slots)

    def _is_dynamic_pricing_evaluation_time(self) -> bool:
        """Return True if it's 00:05 ±5 min and we haven't evaluated today."""
        now = datetime.now()
        today = now.date()

        if self._dynamic_pricing_evaluated_date == today:
            return False

        eval_time = now.replace(hour=0, minute=5, second=0, microsecond=0)
        time_diff = abs((now - eval_time).total_seconds())
        return time_diff <= 5 * 60  # ±5 minutes tolerance

    def _format_predictive_notification_message(
        self,
        decision_data: dict,
        is_daily_evaluation: bool = False,
    ) -> tuple[str, str]:
        """Format notification title and message from decision data.

        Args:
            decision_data: Dict from _should_activate_grid_charging() with energy balance data
            is_daily_evaluation: True when called from daily evaluation in automation_slots mode

        Returns:
            tuple: (title, message)
        """
        from datetime import time as dt_time

        should_charge = decision_data["should_charge"]
        solar_forecast = decision_data["solar_forecast_kwh"]
        usable_energy = decision_data["usable_energy_kwh"]
        avg_soc = decision_data["avg_soc"]
        avg_consumption = decision_data["avg_consumption_kwh"]
        total_available = decision_data["total_available_kwh"]
        energy_deficit = decision_data["energy_deficit_kwh"]
        days_in_history = decision_data["days_in_history"]

        solar_str = f"{solar_forecast:.2f} kWh" if solar_forecast is not None else "unavailable"
        consumption_str = (
            f"{avg_consumption:.2f} kWh (default)" if days_in_history == 0
            else f"{avg_consumption:.2f} kWh ({days_in_history}-day avg)"
        )
        effective_power = min(self.max_contracted_power, self.max_charge_capacity)
        power_str = (
            f"{effective_power}W (ICP: {self.max_contracted_power}W, batteries: {self.max_charge_capacity}W)"
        )

        # Safe mode: no solar forecast
        if solar_forecast is None:
            title = "Predictive Charging: Safe mode"
            message = (
                f"⚠️ No solar forecast available — conservative mode\n\n"
                f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                f"📊 Consumption: {consumption_str}\n\n"
                f"Grid charging NOT activated."
            )
            return (title, message)

        # Sufficient energy — no charging needed
        if not should_charge:
            title = "Predictive Charging: Not required"
            message = (
                f"✓ Sufficient energy for today\n\n"
                f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                f"☀️ Solar forecast: {solar_str}\n"
                f"📊 Consumption: {consumption_str}\n"
                f"✅ Available: {total_available:.2f} kWh ≥ {avg_consumption:.2f} kWh needed\n\n"
                f"No grid charging required."
            )
            return (title, message)

        # Charging needed
        try:
            start_time = dt_time.fromisoformat(self.charging_time_slot["start_time"])
            end_time = dt_time.fromisoformat(self.charging_time_slot["end_time"])
            slot_str = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        except Exception:
            slot_str = None

        if is_daily_evaluation:
            title = "Predictive Charging: Expected today"
            timing_line = "⏰ Charging will activate when prices are low\n"
        else:
            title = "Predictive Charging: STARTED"
            timing_line = (
                f"⏰ Charging until: {end_time.strftime('%H:%M')}\n"
                if slot_str else "⏰ Charging now from grid\n"
            )

        grid_charge = decision_data.get("grid_charge_kwh")
        solar_surplus = decision_data.get("solar_surplus_kwh")
        if grid_charge is not None and solar_surplus is not None:
            # When charging triggers, solar_surplus ≤ gap_to_max, so solar will contribute exactly solar_surplus to battery
            charge_split_line = (
                f"🔌 Grid: {grid_charge:.2f} kWh — solar will charge the remaining {solar_surplus:.2f} kWh\n"
            )
        else:
            charge_split_line = f"⚡ Deficit: {energy_deficit:.2f} kWh\n"

        message = (
            f"⚡ Energy deficit — grid charging needed\n\n"
            f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
            f"☀️ Solar forecast: {solar_str}\n"
            f"📊 Consumption: {consumption_str}\n"
            f"{charge_split_line}\n"
            f"{timing_line}"
            f"Max charge power: {power_str}"
        )

        return (title, message)

    # =========================================================================
    # DYNAMIC PRICING: Evaluation and notification methods
    # =========================================================================

    async def _evaluate_dynamic_pricing(self) -> None:
        """Main evaluation at 00:05: energy balance + prices → schedule."""
        now = datetime.now()
        today = now.date()

        _LOGGER.info("Dynamic pricing: running evaluation at %s", now.strftime("%H:%M"))

        # Step 1: Energy balance
        decision_data = await self._should_activate_grid_charging()
        self._last_decision_data = decision_data
        charging_needed = decision_data["should_charge"]

        # Step 2: Parse price data (always, even without deficit — for diagnostics)
        slots = self._parse_price_data()
        if slots:
            self._dp_daily_avg_price = sum(s.price for s in slots) / len(slots)
            _LOGGER.debug("Dynamic pricing: daily average price %.4f from %d slots", self._dp_daily_avg_price, len(slots))
        if not slots:
            if not charging_needed:
                # No deficit + no price data: nothing to evaluate
                self._dynamic_pricing_schedule = None
                self._dynamic_pricing_evaluated_date = today
                self._dp_eval_retry_count = 0
                _LOGGER.info("Dynamic pricing: no charging needed and no price data available")
                await self._send_dynamic_pricing_notification(decision_data=decision_data, schedule=None)
                return
            # Has deficit but no price data: retry
            self._dp_eval_retry_count += 1
            _LOGGER.warning(
                "Dynamic pricing: no price data available at 00:05 (retry %d/4)",
                self._dp_eval_retry_count
            )
            return  # Will retry up to 4 times (~30 min intervals via control loop)

        # Step 3: Calculate hours needed and select cheapest slots
        deficit_kwh = decision_data["energy_deficit_kwh"]
        if charging_needed:
            hours_needed = self._calculate_charging_hours_needed(deficit_kwh)
        else:
            # No deficit — use daily consumption as reference so the number of
            # selected hours is meaningful (same basis the algorithm uses to decide)
            hours_needed = self._calculate_charging_hours_needed(
                decision_data["avg_consumption_kwh"]
            )
        selected = self._select_cheapest_hours(slots, hours_needed)

        if not selected:
            self._dynamic_pricing_schedule = None
            self._dynamic_pricing_evaluated_date = today
            self._dp_eval_retry_count = 0
            _LOGGER.warning("Dynamic pricing: no slots selected (all above threshold?)")
            await self._send_dynamic_pricing_notification(decision_data=decision_data, schedule=None)
            return

        # Step 4: Build schedule
        avg_price = sum(s.price for s in selected) / len(selected)
        effective_power_kw = min(self.max_contracted_power, self.max_charge_capacity) / 1000.0
        estimated_cost = avg_price * effective_power_kw * hours_needed

        schedule = DynamicPricingSchedule(
            hours_needed=hours_needed,
            selected_slots=selected,
            average_price=avg_price,
            estimated_cost=estimated_cost,
            total_available_slots=len(slots),
            evaluation_time=now,
            energy_deficit_kwh=deficit_kwh,
            charging_needed=charging_needed,
        )
        self._dynamic_pricing_schedule = schedule
        # Use the date of the selected slots (tomorrow at eval time) so the midnight
        # reset only fires the day AFTER the slots — not before they can be used.
        slots_date = selected[0].start.date() if selected else (now.date() + timedelta(days=1))
        self._dynamic_pricing_evaluated_date = slots_date
        self._dp_eval_retry_count = 0

        _LOGGER.info(
            "Dynamic pricing: evaluation complete — %d slots selected, %.1fh, avg=%.3f %s, charging_needed=%s",
            len(selected), hours_needed, avg_price, self._get_price_unit(), charging_needed
        )
        await self._send_dynamic_pricing_notification(decision_data=decision_data, schedule=schedule)

    def _format_dynamic_pricing_notification(
        self,
        decision_data: dict,
        schedule: Optional[DynamicPricingSchedule]
    ) -> tuple[str, str]:
        """Format dynamic pricing evaluation notification."""
        avg_soc = decision_data.get("avg_soc", 0)
        usable_energy = decision_data.get("usable_energy_kwh", 0)
        solar_forecast = decision_data.get("solar_forecast_kwh")
        avg_consumption = decision_data.get("avg_consumption_kwh", 0)
        energy_deficit = decision_data.get("energy_deficit_kwh", 0)
        days_in_history = decision_data.get("days_in_history", 0)

        solar_str = f"{solar_forecast:.2f} kWh" if solar_forecast is not None else "N/A"
        consumption_str = (
            f"{avg_consumption:.2f} kWh ({days_in_history}-day avg)"
            if days_in_history > 0 else f"{avg_consumption:.2f} kWh (default)"
        )

        if schedule is None or not schedule.selected_slots:
            if not decision_data.get("should_charge", False):
                title = "Predictive Charging: Price Optimization - NOT needed"
                message = (
                    f"✓ Sufficient energy for today\n\n"
                    f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                    f"☀️ Solar forecast: {solar_str}\n"
                    f"📊 Consumption: {consumption_str}\n\n"
                    f"✅ Available: {decision_data.get('total_available_kwh', 0):.2f} kWh ≥ {avg_consumption:.2f} kWh needed\n"
                    f"No grid charging required."
                )
            else:
                title = "Predictive Charging: Price Optimization - No slots available"
                message = (
                    f"⚠️ Charging needed but no valid price slots found\n\n"
                    f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                    f"☀️ Solar forecast: {solar_str}\n"
                    f"📊 Consumption: {consumption_str}\n"
                    f"⚡ Energy deficit: {energy_deficit:.2f} kWh\n\n"
                    f"Check price sensor or raise max price threshold."
                )
        else:
            hours_needed = schedule.hours_needed
            n_slots = len(schedule.selected_slots)
            slots_label = f"{n_slots} slot{'s' if n_slots != 1 else ''}" if n_slots != int(hours_needed) else ""
            hours_label = f"{hours_needed:.1f}h" + (f" ({slots_label})" if slots_label else "")
            title = f"Predictive Charging: Price Optimization - {hours_label} selected"

            unit = self._get_price_unit()
            cost_unit = unit.split("/")[0]  # "€/kWh" → "€", "CHF" → "CHF"
            slot_lines = "\n".join(
                f"  • {s.start.strftime('%H:%M')}-{s.end.strftime('%H:%M')} → {s.price:.4f} {unit}"
                for s in schedule.selected_slots
            )
            threshold_line = (
                f"Max price limit: {self.max_price_threshold:.4f} {unit}\n"
                if self.max_price_threshold is not None else ""
            )
            if not schedule.charging_needed:
                title = f"Predictive Charging: Price Info - {hours_label} cheapest"
                message = (
                    f"✓ No grid charging needed today\n\n"
                    f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                    f"☀️ Solar forecast: {solar_str}\n"
                    f"📊 Consumption: {consumption_str}\n"
                    f"✅ Available: {decision_data.get('total_available_kwh', 0):.2f} kWh ≥ {decision_data.get('avg_consumption_kwh', 0):.2f} kWh needed\n\n"
                    f"💰 Cheapest hours today (informational):\n{slot_lines}\n\n"
                    f"Average price: {schedule.average_price:.4f} {unit}\n"
                    f"{threshold_line}"
                    f"No charging will activate."
                )
            else:
                message = (
                    f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
                    f"☀️ Solar forecast: {solar_str}\n"
                    f"📊 Consumption: {consumption_str}\n"
                    f"⚡ Energy deficit: {energy_deficit:.2f} kWh → {hours_needed:.1f}h of charging needed\n\n"
                    f"💰 Selected hours (cheapest):\n{slot_lines}\n\n"
                    f"Average price: {schedule.average_price:.4f} {unit}\n"
                    f"Estimated cost: ~{schedule.estimated_cost:.2f} {cost_unit}\n"
                    f"{threshold_line}"
                    f"Max charge power: {min(self.max_contracted_power, self.max_charge_capacity)}W "
                    f"(ICP: {self.max_contracted_power}W, batteries: {self.max_charge_capacity}W)"
                )

        return (title, message)

    async def _send_dynamic_pricing_notification(
        self,
        decision_data: dict,
        schedule: Optional[DynamicPricingSchedule]
    ) -> None:
        """Send persistent notification for dynamic pricing evaluation."""
        title, message = self._format_dynamic_pricing_notification(decision_data, schedule)
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": "predictive_charging_evaluation",
            },
        )

    async def _send_dynamic_pricing_slot_start_notification(self, slot: PriceSlot) -> None:
        """Send notification when a cheap pricing slot starts."""
        schedule = self._dynamic_pricing_schedule
        if not schedule:
            return

        remaining_slots = [
            s for s in schedule.selected_slots if s.start > slot.start
        ]
        next_slot_str = (
            f"Next slot: {remaining_slots[0].start.strftime('%H:%M')}"
            if remaining_slots else "Last slot"
        )
        remaining_str = (
            f"{len(remaining_slots)} slot(s) remaining"
            if remaining_slots else "No more slots today"
        )

        title = f"Predictive Charging STARTED ({slot.price:.4f} {self._get_price_unit()})"
        message = (
            f"⚡ Charging at max {self.max_contracted_power}W\n"
            f"Slot: {slot.start.strftime('%H:%M')}-{slot.end.strftime('%H:%M')}\n"
            f"{next_slot_str} · {remaining_str}"
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": "predictive_charging_evaluation",
            },
        )

    async def _check_dp_pre_slot_reevaluation(self) -> None:
        """Re-evaluate energy balance 1 hour before each upcoming dynamic pricing slot.

        If the system already charged in an earlier slot and the battery is now
        sufficiently charged (solar + current SOC covers consumption), marks the
        next slot as skippable so it does not activate unnecessarily.
        Called every 2.5 s from the dynamic pricing control loop handler.
        """
        if not self._dynamic_pricing_schedule or not self._dynamic_pricing_schedule.charging_needed:
            return

        now = datetime.now()
        upcoming = [s for s in self._dynamic_pricing_schedule.selected_slots if s.start > now]
        if not upcoming:
            return  # No future slots left

        next_slot = upcoming[0]

        # Only act during the ±5-minute window that is exactly 1 hour before the slot
        pre_eval_time = next_slot.start - timedelta(hours=1)
        if abs((now - pre_eval_time).total_seconds()) > 5 * 60:
            return

        # Already evaluated this slot → nothing to do
        if next_slot.start in self._dp_pre_evaluated_slots:
            return

        # Skip re-evaluation if we're currently charging — the battery hasn't
        # benefited from the ongoing charge yet, so the result would be the same
        # as the original 00:05 evaluation (misleading and noisy).
        # This covers back-to-back slots where the pre-eval window of slot B
        # coincides with the active charging window of slot A.
        if self._current_price_slot_active:
            return

        _LOGGER.info(
            "Dynamic pricing: running pre-slot re-evaluation for slot at %s",
            next_slot.start.strftime("%H:%M")
        )
        decision = await self._should_activate_grid_charging()
        should_charge = decision["should_charge"]
        self._dp_pre_evaluated_slots[next_slot.start] = should_charge

        if should_charge:
            await self._send_dp_pre_slot_reevaluation_notification(next_slot, decision)

    async def _send_dp_pre_slot_reevaluation_notification(
        self, slot: PriceSlot, decision: dict
    ) -> None:
        """Send notification when a pre-slot re-evaluation confirms charging is still needed.

        Only called when should_charge=True. Skipped slots are logged silently.
        """
        avg_soc = decision.get("avg_soc", 0)
        usable_energy = decision.get("usable_energy_kwh", 0)
        solar_forecast = decision.get("solar_forecast_kwh")
        avg_consumption = decision.get("avg_consumption_kwh", 0)
        energy_deficit = decision.get("energy_deficit_kwh", 0)
        days_in_history = decision.get("days_in_history", 0)
        unit = self._get_price_unit()

        solar_str = f"{solar_forecast:.2f} kWh" if solar_forecast is not None else "N/A"
        consumption_str = (
            f"{avg_consumption:.2f} kWh ({days_in_history}-day avg)"
            if days_in_history > 0 else f"{avg_consumption:.2f} kWh (default)"
        )

        title = f"Predictive Charging: slot {slot.start.strftime('%H:%M')} confirmed — charging needed"
        message = (
            f"🔋 Battery: {avg_soc:.0f}% ({usable_energy:.2f} kWh usable)\n"
            f"☀️ Solar forecast: {solar_str}\n"
            f"📊 Consumption: {consumption_str}\n"
            f"⚡ Energy deficit: {energy_deficit:.2f} kWh\n\n"
            f"Slot: {slot.start.strftime('%H:%M')}–{slot.end.strftime('%H:%M')} "
            f"@ {slot.price:.4f} {unit}\n"
            f"→ Charging will activate at {slot.start.strftime('%H:%M')}"
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": "predictive_charging_evaluation",
            },
        )

    # =========================================================================
    # DYNAMIC PRICING: Control loop handler
    # =========================================================================

    def _is_evening_reevaluation_time(self) -> bool:
        """Return True when it's time for the late-day battery re-evaluation.

        Triggers once per day either:
        - 1.5 h before estimated T_end (when solar T_start was detected), or
        - at EVENING_REEVAL_FALLBACK_HOUR (16:00) when no T_start was seen today.

        Does not trigger after 23:00 to avoid clashing with the 00:05 evaluation.
        """
        from datetime import datetime
        now = datetime.now()

        if self._dp_evening_reevaluated_date == now.date():
            return False

        now_h = now.hour + now.minute / 60.0
        if now_h >= 23.0:
            return False

        if self._solar_t_start is not None:
            trigger_h = self._consumption_tracker.estimate_t_end() - EVENING_REEVAL_HOURS_BEFORE_TEND
        else:
            trigger_h = EVENING_REEVAL_FALLBACK_HOUR

        return now_h >= trigger_h

    async def _evaluate_evening_recharge(self) -> None:
        """Late-day re-evaluation: charge batteries cheaply if solar fell short.

        Runs once per day around T_end - 1.5h.  Checks the current battery SOC
        against the configured max_soc and, accounting for remaining solar, decides
        whether to schedule cheap remaining slots from now until midnight.

        Decision flow:
        1. Batteries already at target → skip.
        2. Calculate remaining solar (actual accumulator if available, else sinusoidal).
        3. Net deficit = energy_to_full - remaining_solar_for_battery.
        4. Deficit < EVENING_DEFICIT_THRESHOLD_KWH → skip.
        5. Parse today's future price slots; select cheapest to cover the deficit.
        6. Merge into existing schedule (or create a new one).
        7. Send notification.
        """
        from datetime import datetime

        now = datetime.now()
        today = now.date()
        self._dp_evening_reevaluated_date = today  # mark before any early-returns

        _LOGGER.info("Dynamic pricing: running evening re-evaluation at %s", now.strftime("%H:%M"))

        # --- Battery state ---
        coordinators_with_data = [c for c in self.coordinators if c.data]
        if not coordinators_with_data:
            _LOGGER.info("Evening recharge: no battery data, skipping")
            return

        # Energy needed to bring all batteries to their max_soc
        energy_to_full_kwh = sum(
            max(0.0, (c.max_soc - (c.data.get("battery_soc", c.max_soc) or 0)) / 100.0
                * (c.data.get("battery_total_energy", 0) or 0))
            for c in coordinators_with_data
        )

        if energy_to_full_kwh <= EVENING_DEFICIT_THRESHOLD_KWH:
            _LOGGER.info(
                "Evening recharge: batteries essentially full (%.2f kWh to target), skipping",
                energy_to_full_kwh,
            )
            return

        # --- Remaining solar estimate ---
        now_h = now.hour + now.minute / 60.0
        remaining_solar_kwh = 0.0

        if self.solar_forecast_sensor:
            forecast_state = self.hass.states.get(self.solar_forecast_sensor)
            if forecast_state and forecast_state.state not in ("unknown", "unavailable"):
                try:
                    forecast_today = float(forecast_state.state) * 0.85
                    if self.household_consumption_sensor and self._solar_production_accumulator > 0:
                        remaining_solar_kwh = max(0.0, forecast_today - self._solar_production_accumulator)
                    elif self._solar_t_start is not None:
                        t_end = self._consumption_tracker.estimate_t_end()
                        fraction_done = self._consumption_tracker.get_solar_fraction_done(now_h, self._solar_t_start, t_end)
                        remaining_solar_kwh = forecast_today * (1.0 - fraction_done)
                except (ValueError, TypeError):
                    pass

        # Subtract remaining house consumption from remaining solar (solar not available for battery)
        if self._solar_t_start is not None:
            t_end = self._consumption_tracker.estimate_t_end()
            daylight_h = max(0.0, t_end - self._solar_t_start)
            hours_to_t_end = max(0.0, t_end - now_h)
            if daylight_h > 0:
                avg_consumption_kwh = self._consumption_tracker.get_avg_daily_consumption()
                remaining_consumption_kwh = (avg_consumption_kwh / daylight_h) * hours_to_t_end
                remaining_solar_kwh = max(0.0, remaining_solar_kwh - remaining_consumption_kwh)

        # --- Net deficit ---
        # Apply the configurable grid-charge margin so optimistic solar forecasts
        # are hedged by booking extra cheap grid slots. Capped at energy_to_full.
        margin_factor = 1.0 + self._predictive_grid_charge_margin_pct / 100.0
        evening_deficit_kwh = min(
            energy_to_full_kwh,
            max(0.0, energy_to_full_kwh - remaining_solar_kwh) * margin_factor,
        )

        if evening_deficit_kwh < EVENING_DEFICIT_THRESHOLD_KWH:
            _LOGGER.info(
                "Evening recharge: remaining solar sufficient "
                "(to_full=%.2f kWh, solar_remaining=%.2f kWh) — no action",
                energy_to_full_kwh, remaining_solar_kwh,
            )
            return

        _LOGGER.info(
            "Evening recharge: deficit %.2f kWh (to_full=%.2f, solar_remaining=%.2f) "
            "— searching for cheap slots",
            evening_deficit_kwh, energy_to_full_kwh, remaining_solar_kwh,
        )

        # --- Find cheap slots (today, future only) ---
        slots = self._parse_price_data()
        if not slots:
            _LOGGER.warning("Evening recharge: no price data available")
            return

        # Exclude slots already in the morning schedule
        if self._dynamic_pricing_schedule:
            scheduled_starts = {s.start for s in self._dynamic_pricing_schedule.selected_slots}
            slots = [s for s in slots if s.start not in scheduled_starts]

        if not slots:
            _LOGGER.info("Evening recharge: no additional slots available (all already scheduled)")
            return

        hours_needed = self._calculate_charging_hours_needed(evening_deficit_kwh)
        selected = self._select_cheapest_hours(slots, hours_needed)

        if not selected:
            _LOGGER.warning("Evening recharge: no slots below price threshold")
            return

        # --- Merge into schedule ---
        if self._dynamic_pricing_schedule:
            merged = sorted(
                self._dynamic_pricing_schedule.selected_slots + selected,
                key=lambda s: s.start,
            )
            self._dynamic_pricing_schedule.selected_slots = merged
            self._dynamic_pricing_schedule.charging_needed = True
        else:
            avg_price = sum(s.price for s in selected) / len(selected)
            effective_power_kw = min(self.max_contracted_power, self.max_charge_capacity) / 1000.0
            self._dynamic_pricing_schedule = DynamicPricingSchedule(
                hours_needed=hours_needed,
                selected_slots=selected,
                average_price=avg_price,
                estimated_cost=avg_price * effective_power_kw * hours_needed,
                total_available_slots=len(slots),
                evaluation_time=now,
                energy_deficit_kwh=evening_deficit_kwh,
                charging_needed=True,
            )
            self._dynamic_pricing_evaluated_date = today

        _LOGGER.info(
            "Evening recharge: scheduled %d slot(s) (%.1fh) for %.2f kWh deficit",
            len(selected), hours_needed, evening_deficit_kwh,
        )
        await self._send_evening_recharge_notification(evening_deficit_kwh, selected)

    async def _send_evening_recharge_notification(
        self, deficit_kwh: float, slots: list
    ) -> None:
        """Send notification for the evening re-evaluation result."""
        slots_str = ", ".join(
            f"{s.start.strftime('%H:%M')}-{s.end.strftime('%H:%M')} ({s.price:.4f} {self._get_price_unit()})"
            for s in slots
        )
        avg_soc = sum(
            (c.data.get("battery_soc", 0) or 0)
            for c in self.coordinators if c.data
        ) / max(1, sum(1 for c in self.coordinators if c.data))
        message = (
            f"☀️ Solar ending — batteries not full ({avg_soc:.0f}% avg)\n"
            f"⚡ Deficit: {deficit_kwh:.2f} kWh\n\n"
            f"Cheap slots scheduled:\n{slots_str}"
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Predictive Charging: Evening re-evaluation",
                "message": message,
                "notification_id": "predictive_charging_evening_reeval",
            },
        )

    async def _handle_dynamic_pricing_predictive_charging(self) -> None:
        """Handle predictive charging in dynamic pricing mode (called every 2.5s)."""
        now = datetime.now()

        # Phase 1: Evaluation at 23:00
        if self._is_dynamic_pricing_evaluation_time():
            await self._evaluate_dynamic_pricing()
            return

        # Phase 2: Retry if prices weren't available at 00:05 (e.g. sensor update delay)
        if (
            self._dynamic_pricing_evaluated_date != now.date()
            and self._dp_eval_retry_count > 0
            and self._dp_eval_retry_count < 5
            and now.hour == 0  # Only retry within the first hour of the day
        ):
            # Retry every 15 min starting from 00:05
            retry_minute = now.minute
            expected_retry_minute = 5 + self._dp_eval_retry_count * 15
            if abs(retry_minute - expected_retry_minute) <= 2:
                _LOGGER.info("Dynamic pricing: retrying evaluation (attempt %d)", self._dp_eval_retry_count + 1)
                await self._evaluate_dynamic_pricing()
                return

        # Phase 2.5: Pre-slot re-evaluation (1h before each upcoming slot)
        await self._check_dp_pre_slot_reevaluation()

        # Phase 2.6: Evening re-evaluation when solar is winding down
        if self._is_evening_reevaluation_time():
            await self._evaluate_evening_recharge()

        # Phase 3: Daily reset at midnight
        today = now.date()
        if self._dynamic_pricing_evaluated_date is not None:
            if today > self._dynamic_pricing_evaluated_date:
                _LOGGER.info("Dynamic pricing: new day — resetting schedule")
                self._dynamic_pricing_schedule = None
                self._dynamic_pricing_evaluated_date = None
                self._current_price_slot_active = False
                self._dp_eval_retry_count = 0
                self._dp_pre_evaluated_slots = {}
                self._dp_daily_avg_price = None
                self._dp_evening_reevaluated_date = None

        # Phase 4: Check if we're in a selected cheap slot
        if self._dynamic_pricing_schedule and not self.predictive_charging_overridden:
            in_slot = self._is_in_dynamic_pricing_slot()

            if in_slot and not self._current_price_slot_active:
                # Informational schedule only — no grid charging needed
                if not self._dynamic_pricing_schedule.charging_needed:
                    _LOGGER.debug(
                        "Dynamic pricing: inside cheap slot window but charging not needed "
                        "(solar/battery sufficient) — skipping"
                    )
                    # Fall through to discharge control below (do not return early)

                # Respect charge delay: if configured and still active, hold until it unlocks
                elif self.is_charge_blocked():
                    _LOGGER.info(
                        "Dynamic pricing: inside cheap slot window but charge delay is active — holding"
                    )
                    # Fall through to discharge control below (do not return early)

                else:
                    # Find which slot we're entering
                    current_slot = next(
                        (s for s in self._dynamic_pricing_schedule.selected_slots if s.start <= now < s.end),
                        None
                    )

                    # Skip if pre-evaluation decided charging is no longer needed for this slot
                    if current_slot and self._dp_pre_evaluated_slots.get(current_slot.start) is False:
                        _LOGGER.info(
                            "Dynamic pricing: skipping slot %s — pre-evaluation found sufficient energy",
                            current_slot.start.strftime("%H:%M")
                        )
                        # Fall through to discharge control below (do not return early)

                    else:
                        # Entering a cheap slot
                        self._current_price_slot_active = True
                        self._grid_charging_initialized = False
                        self.grid_charging_active = True
                        if current_slot:
                            await self._send_dynamic_pricing_slot_start_notification(current_slot)
                        _LOGGER.info(
                            "Dynamic pricing: entering cheap slot %s",
                            current_slot.start.strftime("%H:%M") if current_slot else "unknown"
                        )

            elif not in_slot and self._current_price_slot_active:
                # Exiting a cheap slot
                self._current_price_slot_active = False
                self._grid_charging_initialized = False
                self.grid_charging_active = False
                self.previous_power = 0
                self.previous_error = 0
                _LOGGER.info("Dynamic pricing: exiting cheap slot — resuming normal control")

            if self._current_price_slot_active:
                await self._handle_predictive_grid_charging()
                return

        # Phase 5: Override active — resume normal PD control
        if self.predictive_charging_overridden:
            if self.grid_charging_active:
                self.grid_charging_active = False
                self._grid_charging_initialized = False
                self._current_price_slot_active = False
                self.first_execution = True

        # Not in a cheap slot — fall through to normal PD control (no return here)
        # Note: ``_price_based_discharge_blocked`` is computed centrally in
        # ``async_update_charge_discharge`` via ``_apply_price_discharge_block``
        # before this handler runs, so the early ``return`` at the cheap-slot path
        # above does not leave it unset for downstream enforcement.

    # =========================================================================
    # REAL-TIME PRICE: reactive charging based on current price every cycle
    # =========================================================================

    async def _handle_realtime_price_predictive_charging(self) -> None:
        """Handle predictive charging in real-time price mode (called every 2.5s).

        Reads the current price every cycle and activates/deactivates grid charging
        immediately when the price crosses the threshold, with no pre-scheduling.
        If an average_price_sensor is configured its value is used as the threshold
        instead of the fixed max_price_threshold.
        """
        current_price = self._get_current_price()
        if current_price is None:
            _LOGGER.debug("Real-time price: price sensor %s unavailable", self.price_sensor)
            if self._realtime_price_charging:
                self._realtime_price_charging = False
                self.grid_charging_active = False
                self._grid_charging_initialized = False
                self.previous_power = 0
                self.previous_error = 0
            return

        # Determine threshold: average sensor if configured, else fixed threshold
        threshold = None
        if self.average_price_sensor:
            avg_state = self.hass.states.get(self.average_price_sensor)
            if avg_state is not None:
                try:
                    threshold = float(avg_state.state)
                except (ValueError, TypeError):
                    pass
        if threshold is None:
            threshold = self.max_price_threshold

        if threshold is None:
            _LOGGER.debug("Real-time price: no threshold configured, skipping")
            return

        # Override active — stop any active charging and do not start new
        if self.predictive_charging_overridden:
            if self._realtime_price_charging or self.grid_charging_active:
                self._realtime_price_charging = False
                self.grid_charging_active = False
                self._grid_charging_initialized = False
                self.previous_power = 0
                self.previous_error = 0
            return

        price_is_cheap = current_price <= threshold
        _LOGGER.debug(
            "Real-time price: current=%.4f threshold=%.4f cheap=%s charging=%s",
            current_price, threshold, price_is_cheap, self._realtime_price_charging,
        )

        # Note: ``_price_based_discharge_blocked`` is set in
        # ``async_update_charge_discharge`` via ``_apply_price_discharge_block``
        # before this handler runs, so any early ``return`` above does not skip it.

        if price_is_cheap and not self._realtime_price_charging:
            if not self._is_operation_allowed(is_charging=True):
                if self.charge_delay_enabled and self._is_charge_delayed():
                    reason = "charge delay active"
                else:
                    reason = "time slot configuration"
                _LOGGER.debug(
                    "Real-time price: cheap price but charging NOT ALLOWED by %s",
                    reason,
                )
            else:
                # Evaluate whether charging is actually needed before starting
                decision_data = await self._should_activate_grid_charging()
                self._last_decision_data = decision_data
                if decision_data["should_charge"]:
                    self._realtime_price_charging = True
                    self._grid_charging_initialized = False
                    self.grid_charging_active = True
                    _LOGGER.info(
                        "Real-time price: charging STARTED (price=%.4f <= threshold=%.4f)",
                        current_price, threshold,
                    )
                else:
                    _LOGGER.info(
                        "Real-time price: cheap price but charging NOT needed (sufficient energy)",
                    )

        elif not price_is_cheap and self._realtime_price_charging:
            self._realtime_price_charging = False
            self.grid_charging_active = False
            self._grid_charging_initialized = False
            self.previous_power = 0
            self.previous_error = 0
            _LOGGER.info(
                "Real-time price: charging STOPPED (price=%.4f > threshold=%.4f)",
                current_price, threshold,
            )

        if self.grid_charging_active:
            if not self._is_operation_allowed(is_charging=True):
                # Time slot ended while charging was active — stop immediately
                self._realtime_price_charging = False
                self.grid_charging_active = False
                self._grid_charging_initialized = False
                self.previous_power = 0
                self.previous_error = 0
                _LOGGER.debug(
                    "Real-time price: charging stopped — outside charge time slot",
                )
                return
            await self._handle_predictive_grid_charging()

    # =========================================================================
    # TIME SLOT: extracted handler
    # =========================================================================

    async def _handle_time_slot_predictive_charging(self) -> None:
        """Handle predictive charging in time slot mode (extracted from main loop)."""
        # Check if we're in the actual time slot
        in_time_window = (
            self.charging_time_slot is not None and
            self._check_time_window()
        )

        if in_time_window:
            if self.predictive_charging_overridden:
                _LOGGER.debug("Predictive charging overridden by user - continuing normal operation")
                if self.grid_charging_active:
                    self.grid_charging_active = False
                    self._grid_charging_initialized = False
                    self.first_execution = True
                return

            current_avg_soc = sum(c.data.get("battery_soc", 0) for c in self.coordinators if c.data) / len(self.coordinators)
            is_initial_eval = self.last_evaluation_soc is None

            # On slot entry, wait 5 minutes before the initial evaluation so the
            # forecast sensor (which resets at midnight) has time to update.
            if is_initial_eval:
                if self._slot_entry_time is None:
                    self._slot_entry_time = datetime.now()
                    _LOGGER.info(
                        "Time slot entered (SOC: %.1f%%) — waiting 5 min before evaluation "
                        "to allow forecast sensor to update",
                        current_avg_soc,
                    )
                wait_elapsed_s = (datetime.now() - self._slot_entry_time).total_seconds()
                if wait_elapsed_s < 5 * 60:
                    _LOGGER.debug(
                        "Predictive charging: waiting for forecast sensor (%.0f / 300 s) - normal operation continues",
                        wait_elapsed_s,
                    )
                    return

            should_reevaluate = (
                is_initial_eval or
                abs(current_avg_soc - self.last_evaluation_soc) >= SOC_REEVALUATION_THRESHOLD
            )

            if should_reevaluate:
                if is_initial_eval:
                    _LOGGER.info("INITIAL evaluation of predictive grid charging (SOC: %.1f%%)", current_avg_soc)
                else:
                    _LOGGER.info("RE-EVALUATING predictive grid charging due to SOC drop (%.1f%% -> %.1f%%)",
                                self.last_evaluation_soc, current_avg_soc)

                decision_data = await self._should_activate_grid_charging()
                self.grid_charging_active = decision_data["should_charge"]
                self.last_evaluation_soc = current_avg_soc
                self._last_decision_data = decision_data

                if is_initial_eval:
                    await self._send_predictive_charging_notification(
                        decision_data=decision_data
                    )

            if self.grid_charging_active:
                _LOGGER.info("Predictive Grid Charging ACTIVE - target power: %dW", self.max_contracted_power)
                await self._handle_predictive_grid_charging()
                return
            else:
                _LOGGER.info("In predictive charging slot but charging not needed - continuing normal operation")
                return
        else:
            if self.grid_charging_active or self._grid_charging_initialized:
                _LOGGER.info("Exiting predictive grid charging slot - returning to normal mode")
                self.grid_charging_active = False
                self.last_evaluation_soc = None
                self._grid_charging_initialized = False
                self.error_integral = 0.0
                self.previous_error = 0.0
                self.sign_changes = 0
                await self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": "predictive_charging_evaluation"},
                )

            self._slot_entry_time = None

    async def _send_predictive_charging_notification(
        self,
        decision_data: dict,
        is_daily_evaluation: bool = False,
    ):
        """Send notification about predictive charging evaluation result.

        Args:
            decision_data: Dict from _should_activate_grid_charging() with decision factors
            is_daily_evaluation: True when called from daily evaluation in automation_slots mode
        """
        # Format the notification using the helper method
        title, message = self._format_predictive_notification_message(
            decision_data, is_daily_evaluation
        )

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
    
    def _apply_price_discharge_block(self) -> None:
        """Set ``_price_based_discharge_blocked`` from current price vs threshold.

        Centralised so the flag is set every cycle BEFORE mode dispatch — even when
        the mode handler returns early (override active, DP cheap-slot active,
        max_soc transition, etc.). Previously the flag was set inside each handler
        and any early ``return`` left it at the cycle-start ``False`` reset, letting
        PD discharge under cheap prices.
        """
        mode = self.predictive_charging_mode

        if mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
            if not self.dp_price_discharge_control or not self.price_sensor:
                self.remove_discharge_block("price_discharge")
                return
        elif mode == PREDICTIVE_MODE_REALTIME_PRICE:
            if not self.rt_price_discharge_control or not self.price_sensor:
                self.remove_discharge_block("price_discharge")
                return
        else:
            self.remove_discharge_block("price_discharge")
            return

        # Reactive per-cycle price check. DP uses the configured fixed threshold
        # when present, otherwise the daily slot average. RT keeps its explicit
        # average-sensor vs fixed-threshold behaviour.
        # DP no longer relies on selected_slots membership for the
        # discharge decision — the slot list governs grid-charging only.
        # This eliminates the post-restart and post-midnight blind windows
        # where _dynamic_pricing_schedule is None.
        threshold = None
        if mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
            threshold = self.max_price_threshold
            if threshold is None:
                threshold = self._dp_daily_avg_price
        elif self.average_price_sensor:
            avg_state = self.hass.states.get(self.average_price_sensor)
            if avg_state is not None:
                try:
                    threshold = float(avg_state.state)
                except (ValueError, TypeError):
                    pass
        if threshold is None and mode == PREDICTIVE_MODE_REALTIME_PRICE:
            threshold = self.max_price_threshold

        if threshold is None:
            self.remove_discharge_block("price_discharge")
            return

        current_price = self._get_current_price()
        if current_price is None:
            self.remove_discharge_block("price_discharge")
            return

        if current_price > threshold:
            self.remove_discharge_block("price_discharge")
            self._price_based_discharge_blocked = False
            return

        self.set_discharge_block(
            "price_discharge",
            "price",
            {"current_price": current_price, "threshold": threshold, "mode": mode},
        )
        self._price_based_discharge_blocked = True
        if self._price_based_discharge_blocked:
            _LOGGER.debug(
                "Price-based discharge BLOCKED (current=%.4f <= threshold=%.4f, mode=%s)",
                current_price, threshold, mode,
            )

    async def _stop_all_batteries_for_block(self, direction: str) -> None:
        """Stop all battery commands after a global operation block becomes active."""
        _LOGGER.debug("ChargeDischargeController: stopping all batteries due to %s block", direction)
        for coordinator in self.coordinators:
            if self._is_active_balance_mode_running(coordinator):
                continue
            await self._set_battery_power(coordinator, 0, 0)
        self.previous_power = 0
        self._active_discharge_batteries = []
        self._active_charge_batteries = []

    async def _stop_blocked_active_batteries(self) -> bool:
        """Stop batteries that were active before a per-battery block appeared."""
        stopped = False
        for coordinator in list(self._active_charge_batteries):
            if self.is_charge_blocked(coordinator):
                await self._set_battery_power(coordinator, 0, 0)
                self._active_charge_batteries.remove(coordinator)
                stopped = True
        for coordinator in list(self._active_discharge_batteries):
            if self.is_discharge_blocked(coordinator):
                await self._set_battery_power(coordinator, 0, 0)
                self._active_discharge_batteries.remove(coordinator)
                stopped = True
        return stopped

    def _measured_battery_power(self):
        """Aggregate measured AC power across batteries, in controller convention.

        The ac_power register is + discharge / - charge (see aggregate_sensors), the
        opposite of the controller's + charge / - discharge, so it is negated. Uses
        the AC-side power (what the grid meter sees, excludes DC PV on vA/vD). Returns
        None if no battery reports a value (e.g. right after a restart).
        """
        total = 0.0
        seen = False
        for coordinator in self.coordinators:
            if not coordinator.data:
                continue
            value = coordinator.data.get("ac_power")
            if value is None:
                continue
            total += -float(value)
            seen = True
        return total if seen else None

    def _filter_grid_sample(self, sensor_raw, elapsed_s):
        """Time-constant EMA on the grid sample (replaces the fixed 2-sample average).

        alpha = elapsed/(tau+elapsed) keeps the smoothing time constant regardless of
        the variable event-driven cadence. The first sample seeds the filter directly.
        elapsed_s == 0 (a stale recalculation, no new data) leaves the value unchanged;
        elapsed_s None (callers that don't track elapsed) falls back to the nominal dt.
        """
        if self._grid_filter_ema is None:
            self._grid_filter_ema = sensor_raw
        elif elapsed_s is None or elapsed_s > 0:
            dt = elapsed_s if (elapsed_s is not None and elapsed_s > 0) else self.dt
            alpha = dt / (self._grid_filter_tau + dt)
            self._grid_filter_ema += alpha * (sensor_raw - self._grid_filter_ema)
        return self._grid_filter_ema

    async def async_update_charge_discharge(self, now=None):
        """Run one control cycle, guarded against overlapping triggers.

        Invoked by both the periodic safety timer and the consumption-sensor
        state-change event. If a cycle is already running, the overlapping
        trigger is skipped: the in-flight cycle already reads the current state,
        so re-entering would only risk concurrent Modbus writes.
        """
        # Event-driven rate limit: drop a consumption-sensor trigger that lands
        # within _min_cycle_interval_s of the last cycle, so a fast-publishing
        # meter can't flood slow Modbus bridges (e.g. Elfin EW11) with write
        # bursts. The periodic safety timer (now is a datetime) is never gated:
        # it keeps the time-based subsystems running and forces a recalc within
        # its own period. 0 = disabled.
        if now is None and self._min_cycle_interval_s > 0:
            elapsed = time.monotonic() - self._last_cycle_monotonic
            if elapsed < self._min_cycle_interval_s:
                if DEBUG_CONTROL_LOOP_DETAIL:
                    _LOGGER.debug(
                        "Event trigger throttled: %.2fs since last cycle < %.2fs min interval",
                        elapsed, self._min_cycle_interval_s,
                    )
                return
        if self._control_lock.locked():
            if DEBUG_CONTROL_LOOP_DETAIL:
                _LOGGER.debug("Control cycle already running; skipping overlapping trigger.")
            return
        async with self._control_lock:
            self._last_cycle_monotonic = time.monotonic()
            await self._run_control_cycle(now)

    async def _run_control_cycle(self, now=None):
        """Update the charge/discharge power of the batteries."""
        if DEBUG_CONTROL_LOOP_DETAIL:
            _LOGGER.debug("ChargeDischargeController: async_update_charge_discharge started.")

        # === SHUTDOWN CHECK (absolute priority) ===
        # Skip all operations if any coordinator is shutting down (integration unloading)
        if any(c._is_shutting_down for c in self.coordinators):
            return

        # === HOUSEHOLD CONSUMPTION ACCUMULATION ===
        # Run before manual mode check so samples are never lost
        if self._consumption_tracker is not None:
            self._consumption_tracker.handle_accumulator_daily_reset()
            await self._consumption_tracker.accumulate_household_consumption()
            await self._consumption_tracker.accumulate_solar_production()
            # Exact full-day totals from the real power sensors (panel "Energía hoy")
            self._consumption_tracker.handle_daily_energy_reset()
            await self._consumption_tracker.accumulate_daily_solar_energy()
            await self._consumption_tracker.accumulate_daily_home_energy()
            await self._consumption_tracker.accumulate_daily_grid_energy()
            self._consumption_tracker.maybe_save_accumulators()

        # === BALANCE MONITOR ===
        # Run before manual mode and PD control checks so readings are never gated
        # by deadband, stale sensor, or any other early return in the control loop.
        if self._balance_monitor is not None:
            for coordinator in self.coordinators:
                await self._balance_monitor.async_process(coordinator)

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
        await self._weekly_charge_mgr.handle_registers()

        # === CHARGE DELAY: Daily reset and solar detection ===
        if self.charge_delay_enabled:
            from datetime import date
            today = date.today()
            if self._charge_delay_last_date != today:
                if self._charge_delay_last_date is not None:
                    # Real day change: reset delay state
                    self._charge_delay_unlocked = False
                    self._delay_setpoint_reached = False
                    self._solar_t_start = None
                    self._forecast_unavailable_since = None
                # On first cycle after HA restart (_charge_delay_last_date is None),
                # _charge_delay_unlocked may have been restored from storage by
                # _weekly_charge_mgr.load_state() — preserve it rather than wiping it.
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
                self._charge_delay_forecast_cache = None
                self._charge_delay_balance_needs_charge = True
                self._schedule_charge_delay_state_save()
                _LOGGER.info("Charge Delay: New day - state reset")
            # Detect solar production start (shared with weekly charge)
            self._consumption_tracker.detect_solar_t_start()
            # Proactively evaluate delay to keep ChargeDelaySensor populated
            self._is_charge_delayed()

        # Refresh all operation blockers before mode dispatch and PD early returns.
        # This makes charge/discharge permission a shared registry instead of a
        # collection of independent flags and one-off checks.
        self._refresh_operation_blockers()

        # Manual time slots take ownership of their batteries before any other
        # control logic runs. Owned batteries are skipped by PD/predictive.
        await self._try_apply_manual_slot()

        # Per-battery scheduled active balance mode has priority over global
        # modes. It owns only the selected battery; PD can still use the rest.
        await self._handle_active_balance_mode()

        if await self._handle_normal_max_soc_active_balancing():
            self.previous_power = 0
            self.previous_sensor = None
            self.previous_error = 0
            self.last_output_sign = 0
            self.sign_changes = 0
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            return

        # === Predictive Grid Charging Logic (mode dispatch) ===
        if self.predictive_charging_enabled:
            if self.predictive_charging_mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
                await self._handle_dynamic_pricing_predictive_charging()
                # Dynamic pricing falls through to normal PD control when not in a slot;
                # it only returns early when actively charging.
                if self.grid_charging_active:
                    return
            elif self.predictive_charging_mode == PREDICTIVE_MODE_REALTIME_PRICE:
                await self._handle_realtime_price_predictive_charging()
                if self.grid_charging_active:
                    return
            else:
                # Default: time slot mode
                await self._handle_time_slot_predictive_charging()
                # Time slot handler always returns early from its own logic,
                # so we only reach here when outside the slot (normal PD control).
                if self.grid_charging_active:
                    return

        # === Operation blockers: enforce BEFORE deadband / stale early-returns ===
        # Without this guard the deadband and stale-sensor paths could keep a
        # command alive after a feature or user switch blocked that direction.
        if self.previous_power > 0 and self.is_charge_blocked():
            _LOGGER.debug(
                "ChargeDischargeController: Charge block active - stopping charge (was %.0fW)",
                abs(self.previous_power),
            )
            await self._stop_all_batteries_for_block("charge")
            return

        if self.previous_power < 0 and self.is_discharge_blocked():
            _LOGGER.debug(
                "ChargeDischargeController: Discharge block active - stopping discharge (was %.0fW)",
                abs(self.previous_power),
            )
            await self._stop_all_batteries_for_block("discharge")
            return

        blocked_active_changed = await self._stop_blocked_active_batteries()

        # === Continue with normal PD control ===
        consumption_state = self.hass.states.get(self.consumption_sensor)
        sensor_raw = self._apply_meter_transform(consumption_state)
        if sensor_raw is None:
            if consumption_state is None:
                _LOGGER.warning(f"Consumption sensor {self.consumption_sensor} not found.")
            else:
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
        # Real time since the last sensor update — single source of truth for every
        # cadence-dependent term (filter, derivative, P scaling, rate limiter).
        sensor_elapsed_s = (
            (sensor_update_time - previous_update_time).total_seconds()
            if previous_update_time is not None else None
        )

        if is_stale:
            self._stale_cycles += 1
            capacity_protection_must_recheck = (
                self.previous_power < 0
                and self._is_capacity_protection_soc_limited()
            )
            if (
                self._stale_cycles <= self._max_stale_cycles
                and not capacity_protection_must_recheck
                and not blocked_active_changed
            ):
                if DEBUG_CONTROL_LOOP_DETAIL:
                    _LOGGER.debug(
                        "ChargeDischargeController: Sensor stale (cycle %d/%d), maintaining last command %.1fW",
                        self._stale_cycles, self._max_stale_cycles, self.previous_power
                    )
                return
            elif capacity_protection_must_recheck:
                _LOGGER.debug(
                    "ChargeDischargeController: Sensor stale but peak shaving is SOC-limited; recalculating instead of maintaining discharge %.1fW",
                    self.previous_power,
                )
            else:
                _LOGGER.debug(
                    "ChargeDischargeController: Sensor stale for %d cycles (~%.0fs). Safety recalculation.",
                    self._stale_cycles, self._stale_cycles * 2.0
                )
        else:
            self._stale_cycles = 0

        # Smooth instantaneous spikes with a time-constant EMA (advances only on a real
        # update; a stale recalculation passes elapsed 0 and keeps the last value).
        sensor_filtered = self._filter_grid_sample(
            sensor_raw, 0.0 if is_stale else sensor_elapsed_s
        )

        active_target = self.compute_active_target()
        min_charge = self.min_charge_power
        min_discharge = self.min_discharge_power

        # Use filtered sensor directly - it shows the real grid imbalance we need to correct
        sensor_actual = sensor_filtered

        if DEBUG_CONTROL_LOOP_DETAIL:
            _LOGGER.debug("Sensor: raw=%.1fW, filtered=%.1fW", sensor_raw, sensor_filtered)

        # Adjust for excluded/additional devices before dynamic setpoint decisions.
        # Positive adjustment = reduce battery discharge (excluded devices)
        # Negative adjustment = increase battery discharge (additional devices not in home sensor)
        excluded_adjustment = self._calculate_excluded_devices_adjustment(sensor_actual)
        if excluded_adjustment != 0:
            if excluded_adjustment > 0:
                _LOGGER.info("Reducing battery demand by %.1fW (excluded devices)", excluded_adjustment)
            else:
                _LOGGER.info("Increasing battery demand by %.1fW (additional devices)", abs(excluded_adjustment))
            sensor_actual -= excluded_adjustment

        # HOURLY NET BALANCE: Update setpoint offset based on current-hour net energy.
        # Runs before capacity protection so the offset is already in _setpoint_offsets
        # when compute_active_target() is called; CP override wins automatically.
        if self._hourly_balance_mgr is not None:
            await self._hourly_balance_mgr.async_process()
            active_target = self.compute_active_target()

        # CAPACITY PROTECTION MODE: When enabled and SOC is below threshold,
        # only discharge to cover consumption above the peak limit. This must run
        # before deadband and first-execution handling, otherwise a previous
        # hourly-balance discharge can be kept alive by an early return.
        active_target, sensor_actual = self._apply_capacity_protection(sensor_actual, active_target)

        if self._capacity_protection_force_idle:
            self._capacity_protection_force_idle = False
            _LOGGER.info(
                "Capacity Protection conserving capacity: stopping existing discharge command"
            )
            for coordinator in self.coordinators:
                if self._is_active_balance_mode_running(coordinator):
                    continue
                await self._set_battery_power(coordinator, 0, 0)
            self.previous_power = 0
            self.previous_sensor = sensor_actual
            self.previous_error = 0
            self.last_output_sign = 0
            self.sign_changes = 0
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            return

        # CRITICAL: Check deadband on FILTERED sensor (actual grid balance) BEFORE compensation
        # Deadband is centered around the active target grid power
        if not blocked_active_changed and abs(sensor_filtered - active_target) < self.deadband:
            if DEBUG_CONTROL_LOOP_DETAIL:
                _LOGGER.debug(
                    "ChargeDischargeController: Filtered sensor %.1fW within deadband of target %dW (+/-%dW), no action.",
                    sensor_filtered,
                    active_target,
                    self.deadband,
                )
            
            # Reset integral when within deadband to prevent accumulation (only if Ki > 0)
            if self.ki > 0 and self.error_integral != 0.0:
                _LOGGER.info("PD: Resetting integral term (was %.1fW) - system is balanced within deadband", 
                           self.error_integral)
                self.error_integral = 0.0
                self.sign_changes = 0  # Reset oscillation counter
            
            # Update previous_sensor for next cycle
            self.previous_sensor = sensor_filtered
            # Keep the derivative reference current while idling in the deadband, so
            # leaving it does not compute Δerror against a stale pre-deadband error
            # over one sample (a derivative kick). Drop the filtered derivative too.
            self.previous_error = sensor_actual - active_target
            self.derivative_filtered = 0.0
            # NOTE: Do NOT clear load sharing state here. Batteries keep executing
            # their last command during deadband, so the active battery lists must
            # remain accurate for the diagnostic sensor.
            if await self._rebalance_expired_load_sharing_hold(
                grid_w=sensor_actual,
                target_w=active_target,
            ):
                _LOGGER.debug(
                    "Load sharing: expired wall-clock hold released while within deadband"
                )
            return
        
        if len(self.coordinators) == 0:
            _LOGGER.debug("ChargeDischargeController: No batteries configured.")
            return

        if DEBUG_CONTROL_LOOP_DETAIL:
            _LOGGER.debug("ChargeDischargeController: sensor_actual=%fW, previous_sensor=%s, previous_power=%fW",
                          sensor_actual, self.previous_sensor, self.previous_power)

        # FIRST EXECUTION: Initialize with sensor reading
        if self.first_execution:
            _LOGGER.info("ChargeDischargeController: First execution - initializing with sensor value: %fW (target: %dW)", sensor_actual, active_target)
            self.previous_sensor = sensor_actual
            # Initial power counteracts the difference from target grid power
            self.previous_power = -(sensor_actual - active_target)
            self.derivative_filtered = 0.0  # drop any derivative carried across a mode change
            self.first_execution = False

            # Get available batteries and set initial power
            is_charging = self.previous_power > 0

            # Check time slot restrictions BEFORE sending any power to batteries
            operation_allowed = self._is_operation_allowed(is_charging)
            if not operation_allowed:
                if is_charging:
                    reason = (
                        "charge delay active"
                        if self.charge_delay_enabled and self._is_charge_delayed()
                        else "time slot configuration"
                    )
                    _LOGGER.debug("ChargeDischargeController: First execution - Charging NOT ALLOWED by %s, starting at 0W", reason)
                else:
                    _LOGGER.debug("ChargeDischargeController: First execution - Discharging NOT ALLOWED by time slot, starting at 0W")
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
                    if self._is_active_balance_mode_running(coordinator):
                        continue
                    await self._set_battery_power(coordinator, 0, 0)
                return

            # Check price-based discharge block (e.g. RT price mode: cheap price blocks discharge)
            if not is_charging and self._price_based_discharge_blocked:
                _LOGGER.debug("ChargeDischargeController: First execution - Discharging NOT ALLOWED by price-based control, starting at 0W")
                self.previous_power = 0
                self.error_integral = 0.0
                self.previous_error = -(sensor_actual - active_target)
                self.last_output_sign = 0
                self.sign_changes = 0
                self._active_discharge_batteries = []
                self._active_charge_batteries = []
                for coordinator in self.coordinators:
                    if self._is_active_balance_mode_running(coordinator):
                        continue
                    await self._set_battery_power(coordinator, 0, 0)
                return

            available_batteries = self._get_available_batteries(is_charging)

            if not available_batteries:
                _LOGGER.debug("ChargeDischargeController: No available batteries for initial setup.")
                self._active_discharge_batteries = []
                self._active_charge_batteries = []
                return

            if self.previous_power != 0:
                limit = self._effective_system_capacity(available_batteries, is_charging)
                if is_charging and self.previous_power > limit:
                    self.previous_power = limit
                elif not is_charging and abs(self.previous_power) > limit:
                    self.previous_power = -limit

            # Select batteries via load sharing, then distribute power
            selected_batteries = self._select_batteries_for_operation(abs(self.previous_power), available_batteries, is_charging)
            power_allocation = self._distribute_power_by_limits(abs(self.previous_power), selected_batteries, is_charging)

            self._log_power_command_plan(
                phase="initial",
                grid_w=sensor_actual,
                target_w=active_target,
                previous_power_w=0,
                requested_power_w=self.previous_power,
                is_charging=is_charging,
                available_batteries=available_batteries,
                selected_batteries=selected_batteries,
                power_allocation=power_allocation,
            )

            for coordinator in selected_batteries:
                power = power_allocation.get(coordinator, 0)
                if is_charging:
                    await self._set_battery_power(coordinator, power, 0)
                else:
                    await self._set_battery_power(coordinator, 0, power)

            # Set all other batteries to 0 (non-available + available-but-not-selected)
            for coordinator in self.coordinators:
                if coordinator not in selected_batteries:
                    if self._is_active_balance_mode_running(coordinator):
                        continue
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
        if DEBUG_CONTROL_LOOP_DETAIL:
            _LOGGER.debug("ChargeDischargeController: sensor_actual=%fW, UPDATING BATTERIES!",
                          sensor_actual)
        self._refresh_effective_system_capacities()
        
        # PD CONTROLLER: Calculate adjustment based on grid imbalance relative to target
        # error > 0: grid power above target → need to discharge more / charge less
        # error < 0: grid power below target → need to charge more / discharge less
        # active_target was calculated before deadband check (reuse it here)
        error = sensor_actual - active_target

        # ANTI-WINDUP (back-calculation): the incremental loop assumes the batteries
        # delivered exactly the last commanded power. When they can't (SOC/voltage
        # taper, ramp lag, internal derating not captured by the capacity clamp),
        # previous_power drifts past reality and the integral-like P term winds up,
        # causing an overshoot/export spike when load later drops. Re-anchor the
        # increment base to the MEASURED AC power once under-delivery is sustained
        # (a single cycle may just be scan-interval lag). The sign guard prevents a
        # transient near-zero reading from flipping direction, and we only ever clamp
        # the base DOWN toward reality, never inflate it.
        measured_power = self._measured_battery_power()
        if (
            measured_power is not None
            and self.previous_power != 0
            and (self.previous_power > 0) == (measured_power >= 0)
            and abs(self.previous_power) - abs(measured_power) > self.saturation_backcalc_threshold
        ):
            self._saturation_cycles += 1
            if self._saturation_cycles >= self.saturation_backcalc_cycles:
                _LOGGER.debug(
                    "PD anti-windup: re-anchoring base %.0fW -> measured %.0fW (shortfall %.0fW)",
                    self.previous_power, measured_power,
                    abs(self.previous_power) - abs(measured_power),
                )
                self.previous_power = measured_power
        else:
            self._saturation_cycles = 0

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
        
        # Time bases for the cadence-dependent terms. The derivative keeps a 1 s floor
        # (dividing by a sub-second dt would amplify noise into a spike); the P-term and
        # rate-limiter scaling use a smaller floor so they stay accurate for sub-second
        # sensors (a 1 s floor there would over-weight fast cadences).
        if self._stale_cycles > self._max_stale_cycles:
            # Safety valve: suppress derivative to avoid spike from stale data
            real_dt = self.dt
            scale_dt = self.dt
            error_derivative = 0.0
            self.derivative_filtered = 0.0  # drop stale derivative state
        else:
            base_dt = sensor_elapsed_s if (sensor_elapsed_s and sensor_elapsed_s > 0) else self.dt
            real_dt = max(1.0, min(base_dt, 30.0))
            scale_dt = max(0.1, min(base_dt, 30.0))
            error_derivative_raw = (error - self.previous_error) / real_dt
            # Low-pass the derivative: differentiating a barely-filtered grid signal
            # (2-sample moving average) amplifies PWM/quantization noise, which the D
            # term would otherwise inject into the output. EMA with a real-time alpha.
            d_alpha = real_dt / (self.derivative_tau + real_dt)
            self.derivative_filtered += d_alpha * (error_derivative_raw - self.derivative_filtered)
            error_derivative = self.derivative_filtered
        
        # PID terms
        # The P term is applied incrementally (new_power -= P) every cycle, so it acts
        # as integral action whose effective rate scales with cycle frequency. The loop
        # is now event-driven (variable cadence, ~1 s) rather than a fixed 2 s timer, so
        # scale by real elapsed time normalized to the nominal dt — this keeps the
        # per-second correction, and therefore the tuning, independent of cadence.
        P = self.kp * error * (scale_dt / self.dt)
        I = self.ki * self.error_integral
        D = self.kd * error_derivative
        
        # Calculate ADJUSTMENT to apply to current power (incremental control)
        # P term responds to current error
        # D term dampens rapid changes
        pd_adjustment = P + I + D
        
        # Apply adjustment to previous power to get new target
        new_power_raw = self.previous_power - pd_adjustment  # Minus because we're correcting the imbalance
        
        # RATE LIMITER: Prevent abrupt changes that cause overshoot. The configured
        # value is a per-cycle cap calibrated for the nominal dt; scale by real elapsed
        # time so the effective ramp rate (W/s) stays constant under the variable
        # event-driven cadence (otherwise faster cycles would multiply the ramp rate).
        max_change = self.max_power_change_per_cycle * (scale_dt / self.dt)
        power_change = new_power_raw - self.previous_power
        if abs(power_change) > max_change:
            # Clamp the change to maximum allowed rate
            sign = 1 if power_change > 0 else -1
            new_power = self.previous_power + (sign * max_change)
            if self._should_log_rate_limiter(power_change):
                _LOGGER.info(
                    "PD rate limiter: requested_change=%.1fW limit=+/-%.0fW applied_change=%.1fW",
                    power_change,
                    max_change,
                    new_power - self.previous_power,
                )
        else:
            self._clear_rate_limiter_state()
            new_power = new_power_raw
        
        if DEBUG_CONTROL_LOOP_DETAIL:
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

        # RELAY ANTI-CHATTER (minimum-ON dwell): once the battery has engaged, keep
        # the relay engaged for at least `_relay_cooldown_s` seconds before letting it
        # fall back to idle. Stops the relay toggling on/off when the grid signal
        # hovers at the deadband edge during solar ramp-up/down. Only the active->idle
        # transition is gated; charge<->discharge flips keep the relay engaged anyway.
        # A large imbalance bypasses the hold (cost-capped: we only hold while the
        # over/under-shoot stays small, ~3x deadband), so a sudden real load isn't
        # left on the grid. The cap measures imbalance BEYOND the power the battery was
        # already handling: at shut-off the grid swings by ~previous_power (the battery's
        # own delivery now reads as grid export/import), so comparing raw error would
        # trip the cap on every shut-off above ~3x deadband and skip the hold entirely.
        if (
            self._relay_cooldown_s > 0
            and new_power == 0
            and self.previous_power != 0
            and self._relay_engage_since is not None
            and abs(error) - abs(self.previous_power) < max(self.deadband * 3, RELAY_COOLDOWN_HOLD_POWER)
        ):
            held_s = (dt_util.utcnow() - self._relay_engage_since).total_seconds()
            if 0 <= held_s < self._relay_cooldown_s:
                if self.previous_power > 0:
                    new_power = self.min_charge_power or RELAY_COOLDOWN_HOLD_POWER
                else:
                    new_power = -(self.min_discharge_power or RELAY_COOLDOWN_HOLD_POWER)
                _LOGGER.debug(
                    "Relay cooldown: holding %s engaged at %.0fW (%.0fs/%.0fs elapsed)",
                    "charge" if new_power > 0 else "discharge",
                    abs(new_power), held_s, self._relay_cooldown_s,
                )

        # Log control output
        if self.ki > 0:
            # Calculate integral utilization percentage for monitoring
            if self.error_integral > 0:  # Integral is positive (charging direction)
                integral_percent = (self.error_integral / self.max_charge_capacity) * 100 if self.max_charge_capacity > 0 else 0
            elif self.error_integral < 0:  # Integral is negative (discharging direction)
                integral_percent = (abs(self.error_integral) / self.max_discharge_capacity) * 100 if self.max_discharge_capacity > 0 else 0
            else:
                integral_percent = 0
            
            if DEBUG_CONTROL_LOOP_DETAIL:
                _LOGGER.debug("ChargeDischargeController: PD Control - Grid=%.1fW, P=%.1fW, I=%.1fW (%.0f%%), D=%.1fW, Adjustment=%.1fW, New=%.1fW",
                              error, P, I, integral_percent, D, pd_adjustment, new_power)
        else:
            # Integral disabled - simpler log
            if DEBUG_CONTROL_LOOP_DETAIL:
                _LOGGER.debug("ChargeDischargeController: PD Control - Grid=%.1fW, P=%.1fW, D=%.1fW, Adjustment=%.1fW, New=%.1fW",
                              error, P, D, pd_adjustment, new_power)
        
        # Determine if charging or discharging (before applying restrictions)
        is_charging = new_power > 0
        
        # Check if the operation is allowed based on time slots
        operation_restricted = not self._is_operation_allowed(is_charging)
        if operation_restricted:
            if is_charging:
                reason = (
                    "charge delay active"
                    if self.charge_delay_enabled and self._is_charge_delayed()
                    else "time slot configuration"
                )
                _LOGGER.debug("ChargeDischargeController: Charging NOT ALLOWED by %s - controller paused", reason)
            else:
                _LOGGER.debug("ChargeDischargeController: Discharging NOT ALLOWED by time slot configuration - controller paused")
            new_power = 0
            is_charging = False  # Reset since we're forcing to 0
            self._active_discharge_batteries = []
            self._active_charge_batteries = []

        # Check price-based discharge control (set each cycle by pricing mode handlers)
        if not operation_restricted and self._price_based_discharge_blocked and not is_charging:
            _LOGGER.debug("ChargeDischargeController: Discharging NOT ALLOWED by price-based control - controller paused")
            new_power = 0
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            operation_restricted = True  # Freeze PD state downstream (same as timeslot restriction)

        # Check EV charger no-telemetry: 5-min full pause then discharge-block mode
        if not operation_restricted:
            ev_pause_active, ev_charging_active = self._check_ev_charger_state()
            if ev_pause_active:
                _LOGGER.info(
                    "ChargeDischargeController: EV charger detected – 5-minute battery pause, forcing 0W"
                )
                new_power = 0
                is_charging = False
                self._active_discharge_batteries = []
                self._active_charge_batteries = []
                operation_restricted = True  # Freeze PD state during pause
            elif ev_charging_active and new_power < 0:
                # EV is charging (pause expired) – block discharge, solar charging still allowed
                _LOGGER.info(
                    "ChargeDischargeController: EV charging active – blocking battery discharge"
                )
                new_power = 0
                self._active_discharge_batteries = []
                operation_restricted = True

        # Get available batteries (after checking restrictions to determine correct operation mode)
        available_batteries = self._get_available_batteries(is_charging)
        
        # Apply limits: calculate max total power based on AVAILABLE batteries (not all coordinators)
        # This ensures we only compare against batteries that can actually participate
        if available_batteries:
            max_total_discharge = self._effective_system_capacity(
                available_batteries,
                is_charging=False,
            )
            max_total_charge = self._effective_system_capacity(
                available_batteries,
                is_charging=True,
            )
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

        # ICP CONTRACTED-POWER CLAMP: cap battery charging so the projected grid
        # import stays at or below the contracted power, preventing the main breaker
        # from tripping. Uses the real meter reading (sensor_filtered), not the
        # excluded-devices/capacity-protection-adjusted sensor_actual, because the
        # breaker sees total grid flow. Marginal model: shifting battery power by
        # (new_power - previous_power) shifts grid by the same amount (more charge =
        # more import). Only limits charging; never forces a discharge.
        if self.max_contracted_power > 0 and new_power > 0:
            charge_import_cap = self.max_contracted_power - sensor_filtered + self.previous_power
            if new_power > charge_import_cap:
                clamped = max(0.0, charge_import_cap)
                _LOGGER.info(
                    "ICP clamp: limiting charge %.0fW -> %.0fW (grid %.0fW, contracted %.0fW)",
                    new_power, clamped, sensor_filtered, self.max_contracted_power,
                )
                new_power = clamped

        if DEBUG_CONTROL_LOOP_DETAIL:
            _LOGGER.debug("ChargeDischargeController: sensor_actual=%fW, previous_power=%fW, new_power=%fW (available: %d batteries)",
                         sensor_actual, self.previous_power, new_power, len(available_batteries))

        # GRID-AT-MIN-SOC ACCUMULATOR: track grid import that the battery couldn't cover
        # Conditions:
        #   - All reachable batteries are at/below min_soc (system truly depleted for discharge)
        #   - Not intentionally grid-charging (predictive/dynamic pricing)
        #   - Within a discharge window (inside a timeslot, or no timeslots configured)
        #   - Grid is importing (sensor_actual > 0)
        discharge_available = self._get_available_batteries(
            is_charging=False,
            include_operation_blocks=False,
        )
        has_reachable = any(c.is_available for c in self.coordinators)
        all_at_min_soc = (len(discharge_available) == 0) and has_reachable
        if all_at_min_soc and not self.grid_charging_active and sensor_actual > 0:
            time_slots = self.config_entry.data.get("no_discharge_time_slots", [])
            in_discharge_window = (not time_slots) or any(
                self._get_active_slot(c, "discharge") is not None for c in self.coordinators
            )
            if in_discharge_window:
                # Cycle cadence is now variable (event- and timer-driven), so integrate
                # over the real elapsed time since the last accumulation instead of a
                # fixed step. A gap (>10s) means the condition was inactive in between;
                # treat it as a fresh start so we never count energy across the gap.
                now_ts = dt_util.utcnow()
                last_ts = self._grid_at_min_soc_last_ts
                self._grid_at_min_soc_last_ts = now_ts
                if last_ts is not None and (now_ts - last_ts).total_seconds() <= 10.0:
                    dt_s = (now_ts - last_ts).total_seconds()
                    interval_kwh = sensor_actual * dt_s / 3_600_000
                    self._daily_grid_at_min_soc_kwh += interval_kwh
                    if self._grid_at_min_soc_sensor:
                        self._grid_at_min_soc_sensor.async_write_ha_state()
                    _LOGGER.debug(
                        "Grid-at-min-soc: +%.4f kWh (grid=%.0fW, dt=%.1fs), daily total=%.3f kWh",
                        interval_kwh, sensor_actual, dt_s, self._daily_grid_at_min_soc_kwh,
                    )
                    # Persist to Store periodically so reloads don't lose the day's accumulation
                    if self._consumption_tracker is not None:
                        await self._consumption_tracker.maybe_save_grid_at_min_soc_history()

        if not available_batteries:
            _LOGGER.debug("ChargeDischargeController: No available batteries, setting all to 0.")
            for coordinator in self.coordinators:
                if self._is_active_balance_mode_running(coordinator):
                    continue
                await self._set_battery_power(coordinator, 0, 0)
            self.previous_power = 0
            self.previous_sensor = sensor_actual
            self._active_discharge_batteries = []
            self._active_charge_batteries = []
            # No battery can act: demand outside the deadband is battery-limited, not
            # a tuning fault (surfaced as "battery_limited", keeps the metric clean).
            self._pd_limited = abs(error) > self.deadband
            return
        
        # Select batteries via load sharing, then distribute power
        selected_batteries = self._select_batteries_for_operation(abs(new_power), available_batteries, is_charging)
        power_allocation = self._distribute_power_by_limits(abs(new_power), selected_batteries, is_charging)

        self._log_power_command_plan(
            phase="pd",
            grid_w=sensor_actual,
            target_w=active_target,
            previous_power_w=self.previous_power,
            requested_power_w=new_power,
            is_charging=is_charging,
            available_batteries=available_batteries,
            selected_batteries=selected_batteries,
            power_allocation=power_allocation,
            operation_restricted=operation_restricted,
        )

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
                if self._is_active_balance_mode_running(coordinator):
                    continue
                await self._set_battery_power(coordinator, 0, 0)
        
        # Update state for next cycle
        # Stamp the idle->active transition so the relay cooldown can measure dwell.
        if new_power != 0 and self.previous_power == 0:
            self._relay_engage_since = dt_util.utcnow()
        elif new_power == 0:
            self._relay_engage_since = None
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
            sign_changed = False  # captured for the control-quality oscillation metric

            if error_outside_deadband:
                # Error is outside deadband - controller is actively trying to correct
                current_error_sign = 1 if error > 0 else (-1 if error < 0 else 0)

                # Only count sign changes when BOTH current and previous errors were outside deadband
                if current_error_sign != 0 and self.last_error_sign != 0:
                    if current_error_sign != self.last_error_sign:
                        # Sign changed while outside deadband - potential oscillation
                        self.sign_changes += 1
                        sign_changed = True
                        
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
            # Battery-limited: the PD commanded the most it can in the needed
            # direction but the error persists (battery full/empty, or surplus beyond
            # the charge/discharge rate). Not a tuning fault — flag it so the metric
            # skips it and the sensor reports "battery_limited".
            pd_limited = abs(error) > self.deadband and (
                (error < 0 and new_power >= max_total_charge - 1)
                or (error > 0 and new_power <= -max_total_discharge + 1)
            )
            self._pd_limited = pd_limited
            self._update_pd_quality_metrics(error, sign_changed, active_target, pd_limited)
            self.previous_error = error
            self.last_output_sign = current_output_sign
            if DEBUG_CONTROL_LOOP_DETAIL:
                _LOGGER.debug("ChargeDischargeController: PD state updated - previous_error=%.1fW, error_sign=%d, output_sign=%d",
                             self.previous_error, self.last_error_sign, self.last_output_sign)
        else:
            # Controller is paused by restrictions - DO NOT update error tracking
            # This prevents false oscillation detection from natural load fluctuations
            if DEBUG_CONTROL_LOOP_DETAIL:
                _LOGGER.debug("ChargeDischargeController: PD state FROZEN (restricted) - error tracking paused to prevent false oscillation warnings")
        
        if DEBUG_CONTROL_LOOP_DETAIL:
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
            (date.fromisoformat(date_str), round(consumption, 2))
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


def _migrate_time_slots_v2_to_v3(old_slots: list[dict]) -> list[dict]:
    """Convert legacy slots ({start, end, days, apply_to_charge}) to v3 schema.

    Preserves existing behaviour: apply_to_charge=False slot → discharge whitelist
    only. apply_to_charge=True slot → both directions whitelisted.
    """
    from .const import (
        DEFAULT_SLOT_MODE,
        SLOT_BATTERY_SCOPE_ALL,
    )

    new_slots: list[dict] = []
    for s in old_slots or []:
        if not isinstance(s, dict):
            continue
        apply_to_charge = bool(s.get("apply_to_charge", False))
        new_slots.append({
            "start_time": s.get("start_time", "00:00:00"),
            "end_time": s.get("end_time", "00:00:00"),
            "days": s.get("days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
            "enabled": s.get("enabled", True),
            "battery_scope": SLOT_BATTERY_SCOPE_ALL,
            "allow_charge": apply_to_charge,
            "allow_discharge": True,
            "soc_override_enabled": False,
            "power_override_enabled": False,
            "battery_limits": {},
            "mode": DEFAULT_SLOT_MODE,
        })
    return new_slots


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry versions.

    v1 -> v2: add port to unique_ids and device identifiers.
    v2 -> v3: expand time slots from {apply_to_charge} to per-direction tick schema.
    v3 -> v4: lower PD defaults (Kp 0.65->0.35, Kd 0.5->0.3) for installs still on
              the old defaults, to curb overshoot under the cadence-independent loop.
    v4 -> v5: re-enable cell voltage sensors that the integration disabled before
              they were switched to enabled_by_default. Only re-enables entities
              disabled by the integration, leaving user-disabled ones untouched.
    """
    if entry.version >= 5:
        return True

    new_data = dict(entry.data)

    if entry.version < 2:
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import device_registry as dr

        pairs: list[tuple[str, int]] = []
        for battery in entry.data.get("batteries", []):
            host = battery.get(CONF_HOST)
            port = battery.get(CONF_PORT)
            if host is not None and port is not None:
                pairs.append((host, port))

        if not pairs:
            _LOGGER.error("Cannot migrate to v2: no batteries with host/port in entry.data")
            return False

        new_prefixes = {f"{h}_{p}_" for h, p in pairs}

        @callback
        def _update_unique_id(entity_entry):
            uid = entity_entry.unique_id
            if not uid or any(uid.startswith(np) for np in new_prefixes):
                return None
            for h, p in pairs:
                old_prefix = f"{h}_"
                if uid.startswith(old_prefix):
                    return {"new_unique_id": f"{h}_{p}_" + uid[len(old_prefix):]}
            return None

        await er.async_migrate_entries(hass, entry.entry_id, _update_unique_id)

        dev_reg = dr.async_get(hass)
        for h, p in pairs:
            device = dev_reg.async_get_device(identifiers={(DOMAIN, h)})
            if device:
                dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, f"{h}_{p}")})

        _LOGGER.info("Marstek: migrated config entry to version 2 (unique_ids now include port)")

    if entry.version < 3:
        old_slots = entry.data.get("no_discharge_time_slots", []) or []
        new_slots = _migrate_time_slots_v2_to_v3(old_slots)
        new_data["no_discharge_time_slots"] = new_slots
        _LOGGER.info(
            "Marstek: migrated config entry to version 3 (expanded %d time slot(s) to per-direction schema)",
            len(new_slots),
        )

    if entry.version < 4:
        # Lower the PD defaults to reduce overshoot. Only migrate installs still on
        # the OLD defaults (or that never set Kp/Kd); hand-tuned values are left
        # untouched. Require BOTH Kp and Kd to match the old defaults so a user who
        # customized only one is treated as tuned.
        OLD_DEFAULT_PD_KP = 0.65
        OLD_DEFAULT_PD_KD = 0.5
        on_old_kp = abs(float(new_data.get(CONF_PD_KP, OLD_DEFAULT_PD_KP)) - OLD_DEFAULT_PD_KP) < 1e-9
        on_old_kd = abs(float(new_data.get(CONF_PD_KD, OLD_DEFAULT_PD_KD)) - OLD_DEFAULT_PD_KD) < 1e-9
        if on_old_kp and on_old_kd:
            new_data[CONF_PD_KP] = DEFAULT_PD_KP
            new_data[CONF_PD_KD] = DEFAULT_PD_KD
            _LOGGER.info(
                "Marstek: migrated config entry to version 4 (PD defaults Kp->%.2f, Kd->%.2f)",
                DEFAULT_PD_KP, DEFAULT_PD_KD,
            )
        else:
            _LOGGER.info(
                "Marstek: config entry to version 4 (PD gains hand-tuned, left as Kp=%s, Kd=%s)",
                new_data.get(CONF_PD_KP), new_data.get(CONF_PD_KD),
            )

    if entry.version < 5:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        targets = ("_max_cell_voltage", "_min_cell_voltage")
        count = 0
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if (
                ent.disabled_by is er.RegistryEntryDisabler.INTEGRATION
                and ent.unique_id.endswith(targets)
            ):
                ent_reg.async_update_entity(ent.entity_id, disabled_by=None)
                count += 1
        _LOGGER.info(
            "Marstek: migrated config entry to version 5 "
            "(re-enabled %d integration-disabled cell voltage sensor(s))",
            count,
        )

    hass.config_entries.async_update_entry(entry, data=new_data, version=5)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Venus Energy Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Register the sidebar dashboard panel (once per HA instance, non-blocking).
    await _async_register_frontend_panel(hass, entry)

    # Migration: Add default version for existing installations
    from .const import CONF_BATTERY_VERSION, DEFAULT_VERSION, CONF_SLAVE_ID, DEFAULT_SLAVE_ID

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
            slave_id=battery_config.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID),
            consumption_sensor=entry.data["consumption_sensor"],
            battery_version=battery_config.get(CONF_BATTERY_VERSION, DEFAULT_VERSION),
            max_charge_power=battery_config["max_charge_power"],
            max_discharge_power=battery_config["max_discharge_power"],
            max_soc=battery_config["max_soc"],
            min_soc=battery_config["min_soc"],
            enable_charge_hysteresis=battery_config.get("enable_charge_hysteresis", False),
            charge_hysteresis_percent=battery_config.get("charge_hysteresis_percent", 5),
            backup_offgrid_threshold=battery_config.get("backup_offgrid_threshold", 50),
            allow_charge=battery_config.get("allow_charge", True),
            allow_discharge=battery_config.get("allow_discharge", True),
            active_balance_mode_enabled=battery_config.get(CONF_ACTIVE_BALANCE_MODE_ENABLED, False),
            full_charge_voltage_taper_enabled=battery_config.get(
                CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
            ),
        )

        # Restore persisted RS485 user preference and store entry reference for future persistence
        coordinator._config_entry = entry
        coordinator.rs485_user_disabled = battery_config.get("rs485_user_disabled", False)
        coordinator.active_balance_mode_started_ts = battery_config.get("active_balance_mode_started_ts")
        coordinator.active_balance_mode_run_date = battery_config.get("active_balance_mode_run_date")
        coordinator.active_balance_mode_phase = battery_config.get("active_balance_mode_phase")
        coordinator.active_balance_mode_top_reached = battery_config.get("active_balance_mode_top_reached", False)
        coordinator.active_balance_mode_completed_date = battery_config.get("active_balance_mode_completed_date")
        coordinator.active_balance_mode_completion_reason = battery_config.get("active_balance_mode_completion_reason")
        coordinator.active_balance_mode_saved_max_soc = battery_config.get("active_balance_mode_saved_max_soc")
        coordinator.active_balance_mode_start_delta_mv = battery_config.get("active_balance_mode_start_delta_mv")
        coordinator.active_balance_mode_start_delta_source = battery_config.get("active_balance_mode_start_delta_source")
        coordinator.active_balance_mode_start_max_cell_voltage = battery_config.get("active_balance_mode_start_max_cell_voltage")
        coordinator.active_balance_mode_start_min_cell_voltage = battery_config.get("active_balance_mode_start_min_cell_voltage")
        coordinator.active_balance_mode_last_cutoff_ts = battery_config.get("active_balance_mode_last_cutoff_ts")
        coordinator.active_balance_mode_last_cutoff_delta_mv = battery_config.get("active_balance_mode_last_cutoff_delta_mv")
        coordinator.active_balance_mode_last_cutoff_source = battery_config.get("active_balance_mode_last_cutoff_source")
        coordinator.active_balance_mode_last_cutoff_max_cell_voltage = battery_config.get("active_balance_mode_last_cutoff_max_cell_voltage")
        coordinator.active_balance_mode_last_cutoff_min_cell_voltage = battery_config.get("active_balance_mode_last_cutoff_min_cell_voltage")
        coordinator.active_balance_mode_last_cutoff_soc = battery_config.get("active_balance_mode_last_cutoff_soc")
        coordinator.active_balance_mode_wait_started_ts = battery_config.get("active_balance_mode_wait_started_ts")
        coordinator.active_balance_mode_retry_voltage = battery_config.get("active_balance_mode_retry_voltage")
        coordinator.active_balance_mode_last_cutoff_delta_v = battery_config.get("active_balance_mode_last_cutoff_delta_v")
        coordinator._shadow_selects = {
            k[len("shadow_select_"):]: v
            for k, v in battery_config.items()
            if k.startswith("shadow_select_")
        }

        # Connect and fetch initial data
        try:
            connected = await coordinator.connect()
            if not connected:
                # V3 batteries / Modbus bridges (e.g. EW11B) accept only one TCP
                # connection; the slot from the previous session may not be released
                # yet on restart. Retry with escalating delays before giving up.
                for _delay in (2.0, 5.0, 10.0):
                    _LOGGER.warning(
                        "Initial connection to %s failed, retrying in %.0fs...",
                        coordinator.host, _delay,
                    )
                    await asyncio.sleep(_delay)
                    connected = await coordinator.connect()
                    if connected:
                        break
            if not connected:
                # Don't silently continue with an unconnected coordinator (entities
                # would be unavailable and HA would think setup succeeded). Raise
                # ConfigEntryNotReady so HA retries setup with backoff.
                raise ConfigEntryNotReady(
                    f"Could not connect to {coordinator.host}:{coordinator.port} — "
                    "the device may still be releasing the previous TCP connection slot. "
                    "HA will retry setup automatically."
                )
            else:
                # Enable RS485 Control Mode first (required to apply configuration changes)
                # Only done during integration setup/reload, not repeated during runtime
                # Skip if the user explicitly disabled RS485 via the switch.
                if coordinator.rs485_user_disabled:
                    _LOGGER.info("Skipping RS485 enable for %s (user disabled)", battery_config[CONF_NAME])
                else:
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

    from .consumption_tracker import ConsumptionTracker
    consumption_tracker = ConsumptionTracker(hass, entry, controller)
    controller._consumption_tracker = consumption_tracker

    # Restore daily consumption history: try Store first (survives reloads), then binary sensor fallback
    loaded = await consumption_tracker.load_consumption_history()
    if not loaded:
        await _restore_consumption_history(hass, entry, controller)
        # If restored from binary sensor, migrate to Store for future reloads
        if controller._daily_consumption_history:
            await consumption_tracker.save_consumption_history()

    # If no history was restored from either source, initialize with default values
    if not controller._daily_consumption_history:
        consumption_tracker.initialize_history_with_defaults()
        await consumption_tracker.save_consumption_history()

    # Restore household and solar accumulators from persistent storage
    await consumption_tracker.load_accumulators()
    await consumption_tracker.load_daily_energy()

    # Restore weekly charge completion state from previous session
    await controller._weekly_charge_mgr.load_state()
    await controller.load_charge_delay_state()
    # Restore solar T_start if not already restored by weekly charge state (date-based check)
    if controller._solar_t_start is None:
        await consumption_tracker.load_solar_t_start()

    # Set up periodic timers and store unsub callbacks for manual cancellation during unload.
    # Each unsub is registered twice: stored in hass.data so async_unload_entry can cancel
    # the timers early (before platform teardown), and via entry.async_on_unload so HA cleans
    # up on setup failure. The state-change tracker's unsub raises on a second call
    # (list.remove(x): x not in list), so wrap every unsub to be call-once.
    def _call_once(unsub):
        done = False

        def _wrapped():
            nonlocal done
            if not done:
                done = True
                unsub()

        return _wrapped

    unsub_control = _call_once(async_track_time_interval(
        hass, controller.async_update_charge_discharge, timedelta(seconds=2.0)
    ))
    entry.async_on_unload(unsub_control)

    # Force coordinator updates every 1.5 seconds with timestamp-based per-sensor polling
    # This ensures all sensors update according to their scan_interval
    async def _force_coordinator_refresh(now):
        """Force coordinator to check and update data based on timestamp thresholds."""
        await asyncio.gather(*[coordinator.async_request_refresh() for coordinator in coordinators])

    _LOGGER.debug("Setting up periodic refresh for all coordinators")

    unsub_refresh = _call_once(async_track_time_interval(
        hass, _force_coordinator_refresh, timedelta(seconds=1.5)
    ))
    entry.async_on_unload(unsub_refresh)

    # Event-driven control: also run the control cycle the instant the grid
    # consumption sensor publishes a new value, so PD reacts at the sensor's
    # native cadence instead of waiting for the next safety-timer tick. The
    # timer above stays as a watchdog (runs the time-based subsystems and forces
    # a safety recalculation if the sensor goes silent). Overlapping triggers
    # are serialized by the controller's _control_lock.
    async def _on_consumption_changed(event):
        # Do not forward the Event as `now`; the handler expects datetime|None.
        await controller.async_update_charge_discharge()

    unsub_consumption = _call_once(async_track_state_change_event(
        hass, [controller.consumption_sensor], _on_consumption_changed
    ))
    entry.async_on_unload(unsub_consumption)

    # Set up hourly balance manager if enabled
    if controller._hourly_balance_mgr is not None:
        await controller._hourly_balance_mgr.async_setup()

    # Set up balance monitor. This is always enabled so users always get
    # battery health history from top-voltage balance measurements.
    from .balance_monitor import BalanceMonitor
    balance_monitor = BalanceMonitor(hass, entry, controller)
    await balance_monitor.async_setup()
    for coordinator in coordinators:
        await balance_monitor.async_restore_coordinator(coordinator)
    controller._balance_monitor = balance_monitor

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinators": coordinators,
        "controller": controller,
        "unsub_control": unsub_control,
        "unsub_refresh": unsub_refresh,
        "unsub_consumption": unsub_consumption,
        "balance_monitor": balance_monitor,
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
                hass, consumption_tracker.capture_daily_consumption, hour=23, minute=55, second=0
            )
        )
        _LOGGER.info("Daily consumption capture scheduled at 23:55 local time")

    # Schedule midnight reset for the grid-at-min-soc daily accumulator
    entry.async_on_unload(
        async_track_time_change(
            hass, consumption_tracker.reset_daily_grid_at_min_soc, hour=0, minute=0, second=5
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Replace default consumption data with real recorder data
    # On reload HA is already running, so backfill immediately;
    # on fresh boot, wait for homeassistant_started so the recorder is ready
    if needs_consumption_capture:
        if hass.state == CoreState.running:
            await consumption_tracker.startup_backfill_consumption()
            _LOGGER.info("Startup consumption backfill executed immediately (reload)")
        else:
            async def _on_homeassistant_started(_event):
                await consumption_tracker.startup_backfill_consumption()

            entry.async_on_unload(
                hass.bus.async_listen(
                    "homeassistant_started", _on_homeassistant_started
                )
            )
            _LOGGER.info("Startup consumption backfill scheduled for after HA fully started")

    # Dynamic pricing: evaluate at startup if restarted after the 00:05 window
    if (
        controller.predictive_charging_enabled
        and controller.predictive_charging_mode == PREDICTIVE_MODE_DYNAMIC_PRICING
    ):
        hass.async_create_task(controller._startup_dynamic_pricing_evaluation())
        _LOGGER.info("Dynamic pricing: startup evaluation task scheduled")

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
        if unsub := data.get("unsub_consumption"):
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
                # Skip shutdown writes if device was unreachable to avoid blocking
                # on TCP connection timeout (~10s per register write attempt)
                if not coordinator._is_connected:
                    _LOGGER.info(
                        "Skipping shutdown writes for %s - device was not connected",
                        coordinator.name,
                    )
                    continue

                # Skip batteries that are actively providing offgrid backup power
                # (backup switch ON and ac_offgrid_power exceeds threshold, or sensor unavailable)
                if coordinator.data and coordinator.data.get("backup_function") == 0:
                    ac_offgrid = coordinator.data.get("ac_offgrid_power")
                    if ac_offgrid is None or ac_offgrid > coordinator.backup_offgrid_threshold:
                        _LOGGER.info("%s: Skipping shutdown writes - backup function active with offgrid load", coordinator.name)
                        continue

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

        # Persist hourly balance state
        controller = data.get("controller")
        if controller and controller._hourly_balance_mgr is not None:
            await controller._hourly_balance_mgr.async_unload()

        # Persist all throttled accumulators (consumption history + grid-at-min-soc,
        # daily solar/home/grid energy totals, household/solar accumulators) so a
        # reload doesn't revert these TOTAL_INCREASING sensors to the last throttled
        # (~5 min) save, which would step their values backwards and spam the log.
        if controller and controller._consumption_tracker is not None:
            await controller._consumption_tracker.async_save_all()

        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove the sidebar panel only when no config entries remain.
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        _async_unregister_frontend_panel(hass)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow removal of stale battery devices via the HA UI.

    Returns True when the device is not associated with any currently
    configured battery, letting the user delete orphaned devices left
    behind after the battery count was reduced or a battery's host/port
    changed.
    """
    from .const import CONF_SLAVE_ID, DEFAULT_SLAVE_ID

    active_identifiers: set[tuple[str, str]] = {(DOMAIN, "marstek_venus_system")}
    for battery in config_entry.data.get("batteries", []):
        host = battery.get(CONF_HOST)
        port = battery.get(CONF_PORT)
        if host and port:
            # Must match MarstekVenusDataUpdateCoordinator.device_key: slave id 1
            # keeps the historical {host}_{port} form, others get a suffix.
            slave_id = battery.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
            device_key = f"{host}_{port}" if slave_id == 1 else f"{host}_{port}_{slave_id}"
            active_identifiers.add((DOMAIN, device_key))

    return not (device_entry.identifiers & active_identifiers)
