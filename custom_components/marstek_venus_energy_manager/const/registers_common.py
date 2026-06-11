"""Shared Modbus register infrastructure for all Marstek Venus battery versions.

Contains: REGISTER_MAP, MESSAGE_WAIT_MS, bit-description maps, and
calculated-sensor definition lists (cycle, solar power, battery cell power).
"""

# Version-specific register map for control operations
# Maps logical register names to physical addresses per battery version
REGISTER_MAP = {
    "v2": {
        "rs485_control": 42000,
        "force_mode": 42010,
        "set_charge_power": 42020,
        "set_discharge_power": 42021,
        "charging_cutoff_capacity": 44000,      # Hardware cutoff
        "discharging_cutoff_capacity": 44001,   # Hardware cutoff
        "max_charge_power": 44002,
        "max_discharge_power": 44003,
        "battery_soc": 32104,
        "battery_power": 32102,
        "user_work_mode": None,
    },
    "v3": {
        "rs485_control": 42000,
        "force_mode": 42010,
        "set_charge_power": 42020,
        "set_discharge_power": 42021,
        "charging_cutoff_capacity": None,       # NOT AVAILABLE - software enforcement
        "discharging_cutoff_capacity": None,    # NOT AVAILABLE - software enforcement
        "max_charge_power": 44002,
        "max_discharge_power": 44003,
        "battery_soc": 37005,
        "battery_power": 30001,
        "user_work_mode": None,
    },
    "vA": {
        "rs485_control": 42000,
        "force_mode": 42010,
        "set_charge_power": 42020,
        "set_discharge_power": 42021,
        "charging_cutoff_capacity": None,       # NOT AVAILABLE - software enforcement
        "discharging_cutoff_capacity": None,    # NOT AVAILABLE - software enforcement
        "max_charge_power": 44002,
        "max_discharge_power": 44003,
        "battery_soc": 32104,
        "battery_power": 30001,
        "user_work_mode": None,
    },
    "vD": {
        "rs485_control": 42000,
        "force_mode": 42010,
        "set_charge_power": 42020,
        "set_discharge_power": 42021,
        "charging_cutoff_capacity": None,       # NOT AVAILABLE - software enforcement
        "discharging_cutoff_capacity": None,    # NOT AVAILABLE - software enforcement
        "max_charge_power": 44002,
        "max_discharge_power": 44003,
        "battery_soc": 32104,
        "battery_power": 30001,
        "user_work_mode": None,
    },
}

# Version-specific Modbus timing (ms between messages)
MESSAGE_WAIT_MS = {
    "v2": 50,
    "v3": 150,  # Firmware v3 requires minimum 150ms between messages
    "vA": 150,
    "vD": 150,
}

# Standalone bit-description maps — used by both sensor definitions and the
# alarm notification / SystemAlarmSensor logic so we avoid duplicating them.
FAULT_BIT_DESCRIPTIONS: dict[int, str] = {
    # Register 36100 (bits 0-15)
    0: "Grid Overvoltage",
    1: "Grid Undervoltage",
    2: "Grid Overfrequency",
    3: "Grid Underfrequency",
    4: "Grid Peak Voltage",
    5: "Current Dcover",
    6: "Voltage Dcover",
    # Register 36101 (bits 16-31)
    16: "BAT Overvoltage",
    17: "BAT Undervoltage",
    18: "BAT Overcurrent",
    19: "BAT Low SOC",
    20: "BAT Communication Failure",
    21: "BMS Protect",
    22: "Inverter Soft Start Timeout",
    23: "Self-Checking Failure",
    24: "EEPROM Failure",
    25: "Other System Failure",
    26: "Hardware Bus Overvoltage",
    27: "Hardware Output Overcurrent",
    28: "Hardware Trans Overcurrent",
    29: "Hardware Battery Overcurrent",
    30: "Hardware Protection",
    31: "Output Overcurrent",
}

ALARM_BIT_DESCRIPTIONS: dict[int, str] = {
    # Register 36000 (bits 0-15)
    0: "PLL Abnormal Restart",
    1: "Overtemperature Limit",
    2: "Low Temperature Limit",
    3: "Fan Abnormal Warning",
    4: "Low Battery SOC Warning",
    5: "Output Overcurrent Warning",
    6: "Abnormal Line Sequence Detection",
    # Register 36001 (bits 16-31)
    16: "WiFi Abnormal",
    17: "BLE Abnormal",
    18: "Network Abnormal",
    19: "CT Connection Abnormal",
}

# Calculated cycle count sensor (all versions):
# cycles = (total_discharge + total_charge) / 2 / battery_capacity
CYCLE_SENSOR_DEFINITIONS = [
    {
        "key": "battery_cycle_count_calc",
        "name": "Battery Cycle Count Calc",
        "icon": "mdi:counter",
        "state_class": "measurement",
        "dependency_keys": {
            "discharge": "total_discharging_energy",
            "charge": "total_charging_energy",
            "capacity": "battery_total_energy",
        },
    }
]

# Per-battery total DC-coupled PV power (sum of MPPT inputs) — vA/vD only.
SOLAR_POWER_SENSOR_DEFINITIONS = [
    {
        "key": "solar_power",
        "name": "Solar Power",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
        "dependency_keys": {
            "mppt": ["mppt1_power", "mppt2_power", "mppt3_power", "mppt4_power"],
        },
    }
]

# Per-battery true battery cell power (DC terminal net of DC PV) — vA/vD only. The
# battery_power register lumps in the DC PV feeding the bus, so subtract the unit's
# MPPT to recover the battery's own charge/discharge. Sign follows battery_power
# (+ charge / - discharge).
BATTERY_CELL_POWER_SENSOR_DEFINITIONS = [
    {
        "key": "battery_cell_power",
        "name": "Battery Cell Power",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:home-battery",
        "dependency_keys": {
            "battery": "battery_power",
            "mppt": ["mppt1_power", "mppt2_power", "mppt3_power", "mppt4_power"],
        },
    }
]
