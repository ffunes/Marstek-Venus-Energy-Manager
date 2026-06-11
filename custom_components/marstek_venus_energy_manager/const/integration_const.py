"""Integration-level configuration constants for the Marstek Venus Energy Manager."""

DOMAIN = "marstek_venus_energy_manager"

# Prefix for every persistent_notification this integration creates/dismisses.
# Lets automations (e.g. the Telegram-forwarding blueprint) reliably select only
# our notifications by ID. All notification_id values MUST start with this.
NOTIFICATION_ID_PREFIX = "marstek_venus_"

# Internal debug switches for maintainer-level troubleshooting.
# Keep these disabled for normal Home Assistant debug logging; enabling them can
# generate very large logs on systems with fast polling or multiple batteries.
DEBUG_RAW_MODBUS_READS = False
DEBUG_POLL_SENSOR_SKIPS = False
DEBUG_POLL_SENSOR_VALUES = False
DEBUG_CONTROL_LOOP_DETAIL = False

SCAN_INTERVAL = {
    "high": 2,       # fast-changing sensors, e.g., power, alarms
    "medium": 5,     # moderately changing sensors, e.g., voltage, current
    "low": 30,        # slow-changing sensors, e.g., cumulative energy counters
    "very_low": 600   # rarely changing info, e.g., device info, firmware versions
}

# Battery version support
CONF_BATTERY_VERSION = "battery_version"
SUPPORTED_VERSIONS = ["v2", "v3", "vA", "vD"]

# Modbus slave/unit id. Default 1 (Marstek factory default for a direct
# connection). A Modbus TCP proxy that fans out to several batteries on one
# host:port distinguishes them by slave id, so this must be configurable.
CONF_SLAVE_ID = "slave_id"
DEFAULT_SLAVE_ID = 1

# Maximum power (W) per battery version — used by config_flow to set slider limits
MAX_POWER_BY_VERSION = {
    "v2": 2500,
    "v3": 2500,
    "vA": 1500,
    "vD": 2500,
}
DEFAULT_VERSION = "v2"

# Multi-battery activation thresholds derived from efficiency tables (η external)
# Crossover = power at which splitting load across 2 batteries becomes more efficient
# than running a single battery.  Based on Venus efficiency measurements at 2500 W max.
MULTI_BATTERY_DISCHARGE_CROSSOVER_W = 1500   # 60% of 2500 W physical max
MULTI_BATTERY_CHARGE_CROSSOVER_W    = 1750   # 70% of 2500 W physical max
MULTI_BATTERY_HYSTERESIS_GAP        = 0.10   # fraction gap: activation → deactivation
MULTI_BATTERY_MIN_ACTIVATION        = 0.50   # floor: never activate below this fraction
# Cap at 0.95: stage 5% before single-battery saturation to absorb demand transients,
# even when efficiency analysis alone would keep a single battery active.
MULTI_BATTERY_MAX_ACTIVATION        = 0.95
# Keep additional batteries active long enough to avoid pulsing when bursty loads
# repeatedly cross the split-load threshold. Refreshed while the split condition holds.
MULTI_BATTERY_SELECTION_HOLD_SECONDS = 120

# Predictive Grid Charging Configuration
CONF_ENABLE_PREDICTIVE_CHARGING = "enable_predictive_charging"
CONF_CHARGING_TIME_SLOT = "charging_time_slot"
CONF_SOLAR_FORECAST_SENSOR = "solar_forecast_sensor"
CONF_SOLAR_PRODUCTION_SENSOR = "solar_production_sensor"
CONF_HOUSEHOLD_CONSUMPTION_SENSOR = "household_consumption_sensor"
CONF_MAX_CONTRACTED_POWER = "max_contracted_power"


def should_use_household_sensor(data) -> bool:
    """Whether to read the dedicated household sensor instead of deriving home power.

    The household sensor is honoured only when configured AND no solar production
    sensor exists. With a solar sensor the derived value (grid + battery AC + solar)
    is fully accurate and preferred, so the household sensor (a legacy precision
    override, no longer offered in the config flow) is ignored.
    """
    return bool(data.get(CONF_HOUSEHOLD_CONSUMPTION_SENSOR)) and not bool(
        data.get(CONF_SOLAR_PRODUCTION_SENSOR)
    )

# Time slots (operation slots) — v3 schema keys
CONF_TIME_SLOTS = "no_discharge_time_slots"  # legacy key, kept for compat
CONF_SLOT_START_TIME = "start_time"
CONF_SLOT_END_TIME = "end_time"
CONF_SLOT_DAYS = "days"
CONF_SLOT_ENABLED = "enabled"
CONF_SLOT_BATTERY_SCOPE = "battery_scope"
CONF_SLOT_ALLOW_CHARGE = "allow_charge"
CONF_SLOT_ALLOW_DISCHARGE = "allow_discharge"
CONF_SLOT_SOC_OVERRIDE_ENABLED = "soc_override_enabled"
CONF_SLOT_SOC_MAX = "soc_max"
CONF_SLOT_SOC_MIN = "soc_min"
CONF_SLOT_POWER_OVERRIDE_ENABLED = "power_override_enabled"
CONF_SLOT_MAX_CHARGE_POWER_W = "max_charge_power_w"
CONF_SLOT_MAX_DISCHARGE_POWER_W = "max_discharge_power_w"
CONF_SLOT_MODE = "mode"

SLOT_BATTERY_SCOPE_ALL = "all"
SLOT_MODE_PD = "pd"
SLOT_MODE_MANUAL = "manual"

DEFAULT_SLOT_BATTERY_SCOPE = SLOT_BATTERY_SCOPE_ALL
DEFAULT_SLOT_ALLOW_CHARGE = False
DEFAULT_SLOT_ALLOW_DISCHARGE = True
DEFAULT_SLOT_SOC_OVERRIDE_ENABLED = False
DEFAULT_SLOT_POWER_OVERRIDE_ENABLED = False
DEFAULT_SLOT_MODE = SLOT_MODE_PD
DEFAULT_SLOT_SOC_MIN_FLOOR = 12
DEFAULT_SLOT_SOC_MAX_CEILING = 100
MAX_TIME_SLOTS = 8

# Default base consumption fallback (kWh/day)
DEFAULT_BASE_CONSUMPTION_KWH = 5.0  # Fallback when no consumption history available

# Predictive charging safety margin
CONF_PREDICTIVE_SAFETY_MARGIN_KWH = "predictive_safety_margin_kwh"
DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH = 0.0  # kWh added to consumption forecast; 0 = no margin

# Predictive charging grid-charge margin
# Extra % charged from grid on top of the solar-deficit, to hedge against
# optimistic solar forecasts / worse-than-expected weather. 0 = no margin.
# Capped so the charge never exceeds the gap to max SOC.
CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT = "predictive_grid_charge_margin_pct"
DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT = 0.0

# Re-evaluation thresholds
SOC_REEVALUATION_THRESHOLD = 30  # Re-evaluate every 30% SOC drop

# Weekly Full Charge Configuration
CONF_ENABLE_WEEKLY_FULL_CHARGE = "enable_weekly_full_charge"
CONF_MANUAL_MODE_ENABLED = "manual_mode_enabled"
CONF_PREDICTIVE_CHARGING_OVERRIDDEN = "predictive_charging_overridden"
CONF_WEEKLY_FULL_CHARGE_DAY = "weekly_full_charge_day"
CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY = "enable_weekly_full_charge_delay"
CONF_WEEKLY_FULL_CHARGE_SKIP_DELAY = "weekly_full_charge_skip_delay"
DEFAULT_WEEKLY_FULL_CHARGE_SKIP_DELAY = False
CONF_ENABLE_BALANCE_MONITOR = "enable_balance_monitor"

# Cell Balance Monitor
BALANCE_STORAGE_KEY = "balance_history"
BALANCE_STORAGE_VERSION = 1
# Marstek cells ship from the factory with a sizeable top-of-charge imbalance
# (commonly ~170-180 mV). At 3.55 V the LiFePO4 curve is very steep, so this
# factory spread is normal — not a fault. The status thresholds below are
# absolute raw-delta values chosen to sit above that factory baseline, so a
# fresh battery reads green. The baseline offset is subtracted only in the
# rising-trend magnitude gate, so steady factory-level readings do not trip a
# trend alert (slope is unaffected — subtracting a constant does not change it).
BALANCE_BASELINE_OFFSET_MV = 180  # mV — factory top-of-charge imbalance, used by the trend gate
BALANCE_THRESHOLD_YELLOW = 200    # mV — raw delta above this: yellow
BALANCE_THRESHOLD_ORANGE = 230    # mV — raw delta above this: orange
BALANCE_THRESHOLD_RED = 250       # mV — raw delta above this: red
BALANCE_HISTORY_MAX = 52         # ~1 year of weekly readings
BALANCE_RED_CONSECUTIVE_ALERT = 2
BALANCE_TREND_ALERT_AVG_MV = 40.0   # baseline-corrected avg must exceed this (raw avg > 220 mV) to fire a rising-trend alert
BALANCE_NOTIFY_COOLDOWN_DAYS = 7    # min days between cell-imbalance notifications per battery

# Optional normal full-charge protection.
# When enabled per battery, slow charging only while the target is 100% and
# cells enter the top voltage range. This is voltage-only; SOC is intentionally
# ignored because some batteries report it unreliably near the top.
NORMAL_BALANCE_TAPER_CELL_VOLTAGE = 3.48
NORMAL_BALANCE_PAUSE_CELL_VOLTAGE = 3.58
NORMAL_BALANCE_CHARGE_POWER_W = 95
NORMAL_BALANCE_MEASURE_WAIT_SECONDS = 60
# Once the top voltage is reached the taper stops charging and latches. It does
# NOT re-trickle when the cell relaxes (that would pin the cell at the top
# voltage and keep some v3 BMSs from leaving standby to discharge). The latch
# releases — allowing a later top-up to taper again — only after the battery has
# actually been discharged by this SOC margin from where it latched.
NORMAL_BALANCE_RESUME_SOC_DROP = 3             # %: SOC must fall this far below the latch SOC before charging may resume

# SOC recalibration on a stuck top voltage.
# Some packs hit the top cell voltage (pause point) while the BMS still reports a
# SOC far below full — a sign the BMS coulomb counter has drifted. In that case,
# instead of holding at the pause voltage, keep charging at the tapered power
# until the BMS itself cuts off, which forces it to recalibrate SOC to 100%.
NORMAL_BALANCE_RECAL_SOC_THRESHOLD = 90        # %: reported SOC below this at the pause voltage = miscalibration
NORMAL_BALANCE_RECAL_CUTOFF_POWER_W = 10       # W: charge collapsed (BMS terminated)
NORMAL_BALANCE_RECAL_CUTOFF_CYCLES = 5         # consecutive cycles to confirm the BMS cutoff
NORMAL_BALANCE_RECAL_INVERTER_STANDBY = 1      # inverter_state raw value for Standby

# BMS low-SOC discharge cutoff (low-SOC counterpart to NORMAL_BALANCE_RECAL_*).
# Below this SOC the BMS may refuse to discharge on its own (protective cutoff,
# e.g. a weak cell sagging under load) even though the reported SOC is still
# above the configured min_soc. The battery then ACKs the discharge command but
# delivers ~0W. Treat that as an expected BMS cutoff instead of a non-responsive
# fault, so the battery stays in the PD pool.
BMS_DISCHARGE_CUTOFF_SOC = 20                  # %: below this, refused discharge = BMS cutoff, not a fault

# Active balance mode.
# Once the battery has reached the top, keep the cells in the balancing window
# with gentle charge/discharge micro-cycles instead of only resting at 100% SOC.
ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE = 3.49
ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE = 3.58
ACTIVE_BALANCE_DISCHARGE_STOP_CELL_VOLTAGE = 3.49
ACTIVE_BALANCE_FINAL_DISCHARGE_STOP_CELL_VOLTAGE = 3.48
ACTIVE_BALANCE_MEASURE_WAIT_SECONDS = 60
ACTIVE_BALANCE_ADAPTIVE_RESUME_STEP_V = 0.01
ACTIVE_BALANCE_ADAPTIVE_MIN_RESUME_CELL_VOLTAGE = 3.40
# Consecutive ~0 W charge-rejection detections required before treating a charge
# below the stop voltage as a real BMS cut. The control loop runs every ~2 s, so
# a single transient (charge ramp-up after escape discharge, or natural current
# taper approaching the stop voltage) clears within 1-2 cycles and must not be
# logged as a real cutoff measurement. 3 cycles (~6 s) means the cells are truly
# at rest before recording a delta and ratcheting the retry voltage down.
ACTIVE_BALANCE_CHARGE_REJECT_DEBOUNCE_CYCLES = 3
ACTIVE_BALANCE_CHARGE_POWER_W = 95
ACTIVE_BALANCE_DISCHARGE_POWER_W = 200
ACTIVE_BALANCE_MODE_TARGET_DELTA_V = 0.03

# Per-battery scheduled active balance mode.
CONF_ACTIVE_BALANCE_MODE_ENABLED = "active_balance_mode_enabled"
CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED = "full_charge_voltage_taper_enabled"
DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED = True

CONF_ENABLE_CHARGE_DELAY = "enable_charge_delay"
CONF_DELAY_SAFETY_MARGIN_MIN = "delay_safety_margin_min"
DEFAULT_DELAY_SAFETY_MARGIN_MIN = 60
CONF_DELAY_SOC_SETPOINT_ENABLED = "delay_soc_setpoint_enabled"
DEFAULT_DELAY_SOC_SETPOINT_ENABLED = False
CONF_DELAY_SOC_SETPOINT = "delay_soc_setpoint"
DEFAULT_DELAY_SOC_SETPOINT = 50  # % — default when the setpoint is enabled
DELAY_SOC_SETPOINT_HYSTERESIS = 3  # % — SOC must drop this far below setpoint before recharging

# Hourly Net Balance
CONF_ENABLE_HOURLY_BALANCE = "enable_hourly_balance"
CONF_HOURLY_BALANCE_TARGET_NET_WH = "hourly_balance_target_net_wh"
CONF_HOURLY_BALANCE_MAX_OFFSET_W = "hourly_balance_max_offset_w"
CONF_HOURLY_BALANCE_DEADBAND_WH = "hourly_balance_deadband_wh"
CONF_HOURLY_BALANCE_HYSTERESIS_W = "hourly_balance_hysteresis_w"

DEFAULT_HOURLY_BALANCE_TARGET_NET_WH = 0.0
DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W = 1000
DEFAULT_HOURLY_BALANCE_DEADBAND_WH = 0.0
DEFAULT_HOURLY_BALANCE_HYSTERESIS_W = 15

# Hardcoded — not user-configurable
HOURLY_BALANCE_RAMP_IN_MIN = 5

HOURLY_BALANCE_STORAGE_KEY = "hourly_balance"
HOURLY_BALANCE_STORAGE_VERSION = 1
HOURLY_BALANCE_FORCE_RECALC_REMAINING_MIN = 10  # bypass hysteresis near end of hour
HOURLY_BALANCE_MIN_REMAINING_MIN = 1   # below this, offset = 0

# External net balance sensor candidates (checked in order; first match wins).
# Positive sensor value = net export to grid. Flip sign in _read_external_net_wh if reversed.
EXTERNAL_NET_BALANCE_CANDIDATES: list[str] = ["sensor.balance_neto"]

# Weekly Full Charge Delay Constants
CHARGE_EFFICIENCY = 0.85  # Conservative factor for charge power estimation
DELAY_SAFETY_FACTOR = 1.3  # 30% margin on energy balance
LOW_FORECAST_THRESHOLD_FACTOR = 1.5  # forecast < 1.5 × capacity → bad solar day
T_START_THRESHOLD_KWH = 0.1  # Threshold to detect solar production start
T_START_FALLBACK_HOUR = 11  # If no T_start by 11:00, unlock immediately

EVENING_REEVAL_HOURS_BEFORE_TEND = 1.5  # Trigger evening re-evaluation 1.5h before estimated T_end
EVENING_REEVAL_FALLBACK_HOUR = 16.0     # Fallback trigger hour when T_start was never detected
EVENING_DEFICIT_THRESHOLD_KWH = 0.3    # Minimum deficit to bother scheduling evening charging

# Weekday mapping (mon=0, sun=6, matches datetime.weekday())
WEEKDAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6
}

# Capacity Protection Mode Configuration
CONF_CAPACITY_PROTECTION_ENABLED = "capacity_protection_enabled"
CONF_CAPACITY_PROTECTION_SOC_THRESHOLD = "capacity_protection_soc_threshold"
CONF_CAPACITY_PROTECTION_LIMIT = "capacity_protection_limit"

DEFAULT_CAPACITY_PROTECTION_SOC = 30
DEFAULT_CAPACITY_PROTECTION_LIMIT = 2500

# PD Controller Advanced Configuration Keys
CONF_PD_KP = "pd_controller_kp"
CONF_PD_KD = "pd_controller_kd"
CONF_PD_DEADBAND = "pd_controller_deadband"
CONF_PD_MAX_POWER_CHANGE = "pd_controller_max_power_change"
CONF_PD_DIRECTION_HYSTERESIS = "pd_controller_direction_hysteresis"
CONF_PD_MIN_CHARGE_POWER = "pd_min_charge_power"
CONF_PD_MIN_DISCHARGE_POWER = "pd_min_discharge_power"
CONF_PD_RELAY_COOLDOWN = "pd_relay_cooldown"
CONF_PD_MIN_CYCLE_INTERVAL = "pd_min_cycle_interval"
CONF_TARGET_GRID_POWER = "pd_target_grid_power"
CONF_ENABLE_SYSTEM_POWER_LIMITS = "enable_system_power_limits"
CONF_SYSTEM_MAX_CHARGE_POWER = "system_max_charge_power"
CONF_SYSTEM_MAX_DISCHARGE_POWER = "system_max_discharge_power"

# Default PD Controller Parameters
# Lowered from Kp 0.65 / Kd 0.5 to curb overshoot under the cadence-independent
# control loop; existing installs on the old defaults are migrated (see
# async_migrate_entry, config entry v3 -> v4).
DEFAULT_PD_KP = 0.35
DEFAULT_PD_KD = 0.3
DEFAULT_PD_DEADBAND = 40
DEFAULT_PD_MAX_POWER_CHANGE = 800
DEFAULT_PD_DIRECTION_HYSTERESIS = 60
DEFAULT_PD_MIN_CHARGE_POWER = 0       # Minimum charge power (0 = disabled)
DEFAULT_PD_MIN_DISCHARGE_POWER = 0    # Minimum discharge power (0 = disabled)
# Relay anti-chatter: minimum time (s) the battery stays engaged after leaving
# idle before it may return to 0. Stops the relay toggling on/off when the grid
# signal hovers at the deadband edge during solar ramp-up/down. 0 = disabled
# (default: preserves the pre-feature behaviour; opt-in via the slider).
DEFAULT_PD_RELAY_COOLDOWN = 0
# Power held in the already-engaged direction while the cooldown is running, when
# the user's min charge/discharge power is 0 (otherwise that min is used).
RELAY_COOLDOWN_HOLD_POWER = 100
# Minimum spacing (s) between event-driven control cycles. The grid sensor can
# publish several times per second; without a floor, each out-of-deadband cycle
# issues a Modbus write burst, which slow TCP-serial bridges (e.g. Elfin EW11)
# can choke on. Drops surplus sensor-triggered cycles; the 2 s safety timer is
# never gated. 0 = disabled (pre-feature behaviour); default 1 s caps bursts.
DEFAULT_PD_MIN_CYCLE_INTERVAL = 1.0
DEFAULT_TARGET_GRID_POWER = 0
DEFAULT_ENABLE_SYSTEM_POWER_LIMITS = False
DEFAULT_SYSTEM_MAX_CHARGE_POWER = 0       # 0 = disabled
DEFAULT_SYSTEM_MAX_DISCHARGE_POWER = 0    # 0 = disabled

# Legacy alias so existing __init__.py imports don't break during transition
DEFAULT_SLOT_TARGET_GRID_POWER = DEFAULT_TARGET_GRID_POWER

# PD Tuning Profiles
# One-click presets for the PD response-shape parameters (Kp, Kd, max power
# change). Selecting a profile writes those at once; the "custom" profile leaves
# the sliders to the user. Profiles are ordered smoothest → fastest. "balanced"
# equals the shipping defaults, so an untouched install maps onto it.
#
# Deadband is deliberately NOT part of the profiles: it is both the user's
# precision/meter-noise preference and the reference the control-quality sensor
# measures against (oscillation is counted only outside the deadband). Bundling it
# into a profile would clobber that preference and bias the sensor's own yardstick.
CONF_PD_TUNING_PROFILE = "pd_tuning_profile"
PD_PROFILE_CUSTOM = "custom"
DEFAULT_PD_TUNING_PROFILE = PD_PROFILE_CUSTOM

PD_TUNING_PROFILES = {
    "very_smooth": {
        CONF_PD_KP: 0.22,
        CONF_PD_KD: 0.15,
        CONF_PD_MAX_POWER_CHANGE: 400,
    },
    "smooth": {
        CONF_PD_KP: 0.30,
        CONF_PD_KD: 0.25,
        CONF_PD_MAX_POWER_CHANGE: 600,
    },
    "balanced": {
        CONF_PD_KP: DEFAULT_PD_KP,
        CONF_PD_KD: DEFAULT_PD_KD,
        CONF_PD_MAX_POWER_CHANGE: DEFAULT_PD_MAX_POWER_CHANGE,
    },
    "aggressive": {
        CONF_PD_KP: 0.55,
        CONF_PD_KD: 0.45,
        CONF_PD_MAX_POWER_CHANGE: 1200,
    },
    "very_aggressive": {
        CONF_PD_KP: 0.75,
        CONF_PD_KD: 0.45,
        CONF_PD_MAX_POWER_CHANGE: 2000,
    },
}

# Option order shown in the select (custom last); 6 total incl. manual.
PD_TUNING_PROFILE_OPTIONS = list(PD_TUNING_PROFILES.keys()) + [PD_PROFILE_CUSTOM]

# Effective value of each profiled PD param when absent from config_entry.data.
_PD_PROFILE_PARAM_DEFAULTS = {
    CONF_PD_KP: DEFAULT_PD_KP,
    CONF_PD_KD: DEFAULT_PD_KD,
    CONF_PD_MAX_POWER_CHANGE: DEFAULT_PD_MAX_POWER_CHANGE,
}


def pd_profile_from_params(data) -> str:
    """Return the preset name whose values match the PD gain params in `data`.

    Falls back to PD_PROFILE_CUSTOM when no preset matches (i.e. the user has
    hand-tuned the sliders). Deadband is not considered — it is user-owned and not
    part of the profiles. Compared with a small epsilon to tolerate float Kp/Kd.
    """
    for name, params in PD_TUNING_PROFILES.items():
        if all(
            abs(float(data.get(key, _PD_PROFILE_PARAM_DEFAULTS[key])) - float(value)) < 1e-6
            for key, value in params.items()
        ):
            return name
    return PD_PROFILE_CUSTOM


# Dynamic Pricing Mode Configuration
CONF_PREDICTIVE_CHARGING_MODE = "predictive_charging_mode"
CONF_PRICE_SENSOR = "price_sensor"
CONF_PRICE_INTEGRATION_TYPE = "price_integration_type"
CONF_MAX_PRICE_THRESHOLD = "max_price_threshold"

PREDICTIVE_MODE_TIME_SLOT = "time_slot"
PREDICTIVE_MODE_DYNAMIC_PRICING = "dynamic_pricing"
PREDICTIVE_MODE_REALTIME_PRICE = "realtime_price"

CONF_AVERAGE_PRICE_SENSOR = "average_price_sensor"

CONF_METER_INVERTED = "meter_inverted"
CONF_DP_PRICE_DISCHARGE_CONTROL = "dp_price_discharge_control"
CONF_RT_PRICE_DISCHARGE_CONTROL = "rt_price_discharge_control"

PRICE_INTEGRATION_NORDPOOL = "nordpool"
PRICE_INTEGRATION_PVPC = "pvpc"
PRICE_INTEGRATION_CKW = "ckw"
PRICE_INTEGRATION_EPEX = "epex"
PRICE_INTEGRATION_ENTSOE = "entsoe"

# Configuration Number Definitions (for config entities exposed in the UI)
CONFIG_NUMBER_DEFINITIONS = [
    {
        "key": CONF_PD_KP,
        "name": "PD Kp",
        "min": 0.1,
        "max": 2.0,
        "step": 0.05,
        "default": DEFAULT_PD_KP,
        "icon": "mdi:tune",
    },
    {
        "key": CONF_PD_KD,
        "name": "PD Kd",
        "min": 0.0,
        "max": 2.0,
        "step": 0.05,
        "default": DEFAULT_PD_KD,
        "icon": "mdi:tune",
    },
    {
        "key": CONF_PD_DEADBAND,
        "name": "PD Deadband",
        "min": 0,
        "max": 200,
        "step": 5,
        "unit": "W",
        "default": DEFAULT_PD_DEADBAND,
        "icon": "mdi:arrow-collapse-horizontal",
    },
    {
        "key": CONF_PD_MAX_POWER_CHANGE,
        "name": "PD Max Power Change",
        "min": 100,
        "max": 2000,
        "step": 50,
        "unit": "W",
        "default": DEFAULT_PD_MAX_POWER_CHANGE,
        "icon": "mdi:delta",
    },
    {
        "key": CONF_PD_DIRECTION_HYSTERESIS,
        "name": "PD Direction Hysteresis",
        "min": 0,
        "max": 200,
        "step": 5,
        "unit": "W",
        "default": DEFAULT_PD_DIRECTION_HYSTERESIS,
        "icon": "mdi:swap-horizontal",
    },
    {
        "key": CONF_PD_MIN_CHARGE_POWER,
        "name": "PD Min Charge Power",
        "min": 0,
        "max": 2000,
        "step": 10,
        "unit": "W",
        "default": DEFAULT_PD_MIN_CHARGE_POWER,
        "icon": "mdi:battery-charging-low",
    },
    {
        "key": CONF_PD_MIN_DISCHARGE_POWER,
        "name": "PD Min Discharge Power",
        "min": 0,
        "max": 2000,
        "step": 10,
        "unit": "W",
        "default": DEFAULT_PD_MIN_DISCHARGE_POWER,
        "icon": "mdi:battery-low",
    },
    {
        "key": CONF_PD_RELAY_COOLDOWN,
        "name": "PD Relay Cooldown",
        "min": 0,
        "max": 60,
        "step": 1,
        "unit": "s",
        "default": DEFAULT_PD_RELAY_COOLDOWN,
        "icon": "mdi:timer-cog-outline",
    },
    {
        "key": CONF_PD_MIN_CYCLE_INTERVAL,
        "name": "PD Min Cycle Interval",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "unit": "s",
        "default": DEFAULT_PD_MIN_CYCLE_INTERVAL,
        "icon": "mdi:timer-pause-outline",
    },
    {
        "key": CONF_TARGET_GRID_POWER,
        "name": "PD Target Grid Power",
        "min": -2500,
        "max": 2500,
        "step": 10,
        "unit": "W",
        "default": DEFAULT_TARGET_GRID_POWER,
        "icon": "mdi:transmission-tower-export",
    },
    {
        "key": CONF_SYSTEM_MAX_CHARGE_POWER,
        "name": "System Max Charge Power",
        "min": 0,
        "max": 15000,
        "step": 50,
        "unit": "W",
        "default": DEFAULT_SYSTEM_MAX_CHARGE_POWER,
        "icon": "mdi:battery-arrow-up-outline",
        "condition": CONF_ENABLE_SYSTEM_POWER_LIMITS,
        "condition_enabled": True,
    },
    {
        "key": CONF_SYSTEM_MAX_DISCHARGE_POWER,
        "name": "System Max Discharge Power",
        "min": 0,
        "max": 15000,
        "step": 50,
        "unit": "W",
        "default": DEFAULT_SYSTEM_MAX_DISCHARGE_POWER,
        "icon": "mdi:battery-arrow-down-outline",
        "condition": CONF_ENABLE_SYSTEM_POWER_LIMITS,
        "condition_enabled": True,
    },
    {
        "key": CONF_MAX_CONTRACTED_POWER,
        "name": "Max Contracted Power",
        "min": 1000,
        "max": 15000,
        "step": 100,
        "unit": "W",
        "default": 7000,
        "icon": "mdi:transmission-tower",
        "condition": CONF_ENABLE_PREDICTIVE_CHARGING,
    },
    {
        "key": CONF_DELAY_SAFETY_MARGIN_MIN,
        "name": "Charge Delay Safety Margin",
        "min": 1,
        "max": 6,
        "step": 0.5,
        "unit": "h",
        "scale": 60,
        "default": DEFAULT_DELAY_SAFETY_MARGIN_MIN,
        "icon": "mdi:timer-sand",
        "condition": CONF_ENABLE_CHARGE_DELAY,
    },
    {
        "key": CONF_DELAY_SOC_SETPOINT,
        "name": "Charge Delay SOC Setpoint",
        "min": 12,
        "max": 90,
        "step": 5,
        "unit": "%",
        "default": DEFAULT_DELAY_SOC_SETPOINT,
        "icon": "mdi:battery-charging-50",
        "condition": CONF_DELAY_SOC_SETPOINT_ENABLED,
    },
    {
        "key": CONF_CAPACITY_PROTECTION_SOC_THRESHOLD,
        "name": "Capacity Protection SOC Threshold",
        "min": 20,
        "max": 100,
        "step": 1,
        "unit": "%",
        "default": DEFAULT_CAPACITY_PROTECTION_SOC,
        "icon": "mdi:battery-alert-variant-outline",
        "condition": CONF_CAPACITY_PROTECTION_ENABLED,
    },
    {
        "key": CONF_CAPACITY_PROTECTION_LIMIT,
        "name": "Capacity Protection Peak Limit",
        "min": 500,
        "max": 10000,
        "step": 100,
        "unit": "W",
        "default": DEFAULT_CAPACITY_PROTECTION_LIMIT,
        "icon": "mdi:flash-alert",
        "condition": CONF_CAPACITY_PROTECTION_ENABLED,
    },
    {
        "key": CONF_PREDICTIVE_SAFETY_MARGIN_KWH,
        "name": "Solar Forecast Safety Margin",
        "min": 0.0,
        "max": 20.0,
        "step": 0.1,
        "unit": "kWh",
        "default": DEFAULT_PREDICTIVE_SAFETY_MARGIN_KWH,
        "icon": "mdi:solar-power-variant",
        "condition": CONF_ENABLE_PREDICTIVE_CHARGING,
    },
    {
        "key": CONF_PREDICTIVE_GRID_CHARGE_MARGIN_PCT,
        "name": "Predictive Grid Charge Margin",
        "min": 0.0,
        "max": 100.0,
        "step": 5.0,
        "unit": "%",
        "default": DEFAULT_PREDICTIVE_GRID_CHARGE_MARGIN_PCT,
        "icon": "mdi:transmission-tower-import",
        "condition": CONF_ENABLE_PREDICTIVE_CHARGING,
    },
]
