"""Constants for the Marstek Venus Energy Manager integration."""

DOMAIN = "marstek_venus_energy_manager"

SCAN_INTERVAL = {
    "high": 2,       # fast-changing sensors, e.g., power, alarms
    "medium": 5,     # moderately changing sensors, e.g., voltage, current
    "low": 30,        # slow-changing sensors, e.g., cumulative energy counters
    "very_low": 600   # rarely changing info, e.g., device info, firmware versions
}

# Battery version support
CONF_BATTERY_VERSION = "battery_version"
SUPPORTED_VERSIONS = ["v2", "v3", "vA", "vD"]

# Maximum power (W) per battery version — used by config_flow to set slider limits
MAX_POWER_BY_VERSION = {
    "v2": 2500,
    "v3": 2500,
    "vA": 1200,
    "vD": 2200,
}
DEFAULT_VERSION = "v2"

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

SENSOR_DEFINITIONS = [

    {
        # Battery State of Charge (SOC) as a percentage
        "name": "Battery SOC",
        "register": 32104,
        "scale": 1,
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "key": "battery_soc",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium"
    },
    {
        # Total stored battery energy in kilowatt-hours
        "name": "Battery Total Energy",
        "register": 32105,
        "scale": 0.001,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total",
        "key": "battery_total_energy",
        "enabled_by_default": True, ###False,
        "data_type": "uint16",
        "precision": 3,
        "scan_interval": "low"
    },
    {
        # Battery power in watts
        "name": "Battery Power",
        "register": 32102,
        "count": 2,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "key": "battery_power",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 1,
        "scan_interval": "high",
        "force_update": True
    },
    {
        # Internal temperature in degrees Celsius
        "name": "Internal Temperature",
        "register": 35000,
        "scale": 0.1,
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "key": "internal_temperature",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 2,
        "scan_interval": "medium"
    },
    {
        # Battery AC power in watts
        "name": "AC Power",
        "register": 32202,
        "count": 2,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "key": "ac_power",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 0,
        "scan_interval": "high",
        "force_update": True
    },
    {
        # Total energy charged into the battery in kilowatt-hours
        "name": "Total Charging Energy",
        "register": 33000,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "key": "total_charging_energy",
        "enabled_by_default": True,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low"
    },
    {
        # Total energy discharged from the battery in kilowatt-hours
        "name": "Total Discharging Energy",
        "register": 33002,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "key": "total_discharging_energy",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 2,
        "scan_interval": "low"
    },
    {
        "register": 33004,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Daily Charging Energy",
        "key": "total_daily_charging_energy",
        "enabled_by_default": True,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33006,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Daily Discharging Energy",
        "key": "total_daily_discharging_energy",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        # Current state of the inverter device
        "name": "Inverter State",
        "register": 35100,
        "scale": 1,
        "unit": None,
        "icon": "mdi:state-machine",
        "key": "inverter_state",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "states": {
            0: "Sleep",
            1: "Standby",
            2: "Charge",
            3: "Discharge",
            4: "Backup Mode",
            5: "OTA Upgrade",
            6: "Bypass",
        },
        "scan_interval": "high"
    },
    {
        # Battery voltage in volts
        "name": "Battery Voltage",
        "register": 32100,
        "scale": 0.01,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "battery_voltage",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium"
    },
    {
        # Minimum cell voltage
        "name": "Max Cell Voltage",
        "register": 37007,
        "scale": 0.001,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "max_cell_voltage",
        "enabled_by_default": False,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "medium"
    },
    {
        # Minimum cell voltage 
        "name": "Min Cell Voltage",
        "register": 37008,
        "scale": 0.001,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "min_cell_voltage",
        "enabled_by_default": False,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "medium"
    },
    {
        # Fault status bits indicating various device faults
        "name": "Fault Status",
        "register": 36100,
        "data_type": "uint32",
        "key": "fault_status",
        "device_class": "problem",
        "icon": "mdi:alert",
        "category": "diagnostic",
        "enabled_by_default": True,
        "scan_interval": "medium",
        "bit_descriptions": {
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
            19: "BAT low SOC",
            20: "BAT communication failure",
            21: "BMS protect",
            22: "Inverter soft start timeout",
            23: "self-checking failure",
            24: "eeprom failure",
            25: "other system failure",
            26: "Hardware Bus overvoltage",
            27: "Hardware Output overcurrent",
            28: "Hardware trans overcurrent",
            29: "Hardware battery overcurrent",
            30: "Hardware Protecion",
            31: "Output Overcurrent"
        }
    },
    {
        # Alarm status bits indicating various device alarms
        "name": "Alarm Status",
        "register": 36000,
        "data_type": "uint32",
        "key": "alarm_status",
        "device_class": "problem",
        "icon": "mdi:alert",
        "enabled_by_default": True,
        "category": "diagnostic",
        "unit": None,
        "precision": 0,
        "scan_interval": "medium",
        "bit_descriptions": {
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
    },
    {
        # AC Offgrid Power in watts
        "name": "AC Offgrid Power",
        "register": 32302,
        "count": 2,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "key": "ac_offgrid_power",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 0,
        "scan_interval": "high"
    },
    {
        "name": "Device Name",
        "register": 31000,
        "count": 10,
        "data_type": "char",
        "unit": None,
        "icon": "mdi:package-variant-closed",
        "key": "device_name",
        "enabled_by_default": True,
        "scan_interval": "very_low",
        "precision": 0,
    },
    {
        "name": "SN Code",
        "register": 31200,
        "count": 10,
        "data_type": "char",
        "unit": None,
        "key": "sn_code",
        "enabled_by_default": False,
        "scan_interval": "very_low",
        "precision": 0,
    },
    {
        "name": "Software Version",
        "register": 31100,
        "scale": 0.01,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "software_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 2,
        "scan_interval": "very_low",
    },
    {
        "name": "BMS Version",
        "register": 31102,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "key": "bms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "EMS Version",
        "register": 31101,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "ems_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scale": 1,
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "Comm Module Firmware",
        "register": 30800,
        "count": 6,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "comm_module_firmware",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "MAC Address",
        "register": 30402,
        "count": 6,
        "unit": None,
        "icon": "mdi:ethernet",
        "key": "mac_address",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },

]

# Definitions for binary sensors that represent on/off states
# Each binary sensor includes the Modbus register and bit position
BINARY_SENSOR_DEFINITIONS = [
    {
        "name": "WiFi Status",
        "register": 30300,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:check-network-outline",
        "key": "wifi_status",
        "enabled_by_default": False,
        "scan_interval": "low",
    },
    {
        "name": "Cloud Status",
        "register": 30302,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:cloud-outline",
        "key": "cloud_status",
        "enabled_by_default": False,
        "scan_interval": "low",
    },
]

# Definitions for selectable options (e.g. operating modes)
# Each entry includes the register, label options, and conversion mappings
SELECT_DEFINITIONS = [
    {
        # Selectable force mode for charging/discharging the battery
        "name": "Force Mode",
        "register": 42010,
        "key": "force_mode",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scan_interval": "high",
        "options": {
            "None": 0,
            "Charge": 1,
            "Discharge": 2
        }
    }
    
]

# Definitions for switch controls that can be toggled on/off
# Each switch includes the Modbus register register and commands for on/off
SWITCH_DEFINITIONS = [
    {
        # Battery backup switch
        "name": "Backup Function",
        "register": 41200,
        "command_on": 0,    # Enable
        "command_off": 1,   # Disable
        "key": "backup_function",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scan_interval": "medium"
    },
    {
        # RS485 communication control mode switch
        "name": "RS485 Control Mode",
        "register": 42000,
        "command_on": 21930,  # 0x55AA in decimal
        "command_off": 21947,  # 0x55BB in decimal
        "key": "rs485_control_mode",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scan_interval": "medium"
    },
]

# Definitions for numeric configuration parameters
# Each number defines a range and step size for setting values
NUMBER_DEFINITIONS = [
    {
        # Set power limit for forced charging in watts
        "name": "Set Forcible Charge Power",
        "register": 42020,
        "key": "set_charge_power",
        "enabled_by_default": True,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 0,
        "max": 2500,
        "step": 5,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high"
    },
    {
        # Set power limit for forced discharging in watts
        "name": "Set Forcible Discharge Power",
        "register": 42021,
        "key": "set_discharge_power",
        "enabled_by_default": True,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 0,
        "max": 2500,
        "step": 5,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high"
    },
    {
        # Maximum power that can be charged into the battery in watts
        "name": "Max Charge Power",
        "register": 44002,
        "key": "max_charge_power",
        "enabled_by_default": True,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 800,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "medium"
    },
    {
        # Maximum power that can be discharged from the battery in watts
        "name": "Max Discharge Power",
        "register": 44003,
        "key": "max_discharge_power",
        "enabled_by_default": True,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 800,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "medium"
    },
    {
        # Charging cutoff capacity as a percentage 
        "name": "Charging Cutoff Capacity",
        "register": 44000,
        "key": "charging_cutoff_capacity",
        "enabled_by_default": True,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 80,
        "max": 100,
        "step": 1,
        "unit": "%",
        "scale": 0.1,
        "data_type": "uint16",
        "scan_interval": "medium"
    },
    {
        # Discharging cutoff capacity as a percentage
        "name": "Discharging Cutoff Capacity",
        "register": 44001,
        "key": "discharging_cutoff_capacity",
        "enabled_by_default": True,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 12,
        "max": 30,
        "step": 1,
        "unit": "%",
        "scale": 0.1,
        "data_type": "uint16",
        "scan_interval": "medium"
    },
]

# Definitions for button actions (one-time triggers)
BUTTON_DEFINITIONS = [
    {
        # Reset device via Modbus command
        "name": "Reset Device",
        "register": 41000,
        "command": 21930,  # 0x55AA
        "icon": "mdi:restart",
        "category": "diagnostic",
        "key": "reset_device",
        "enabled_by_default": False,
        "data_type": "uint16"
    }
]

# Definitions for efficiency sensors
EFFICIENCY_SENSOR_DEFINITIONS = [
    {
        "key": "round_trip_efficiency_total",
        "name": "Round-Trip Efficiency Total",
        "unit": "%",
        "state_class": "measurement",
        "dependency_keys": {
            "charge": "total_charging_energy",            
            "discharge": "total_discharging_energy" 
        },
    }
]

# Definitions for stored energy sensors
STORED_ENERGY_SENSOR_DEFINITIONS = [
    {
        "name": "Stored Energy",
        "key": "stored_energy",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total",
        "dependency_keys": {
            "soc": "battery_soc",            
            "capacity": "battery_total_energy" 
        },       
    }
]

# ============================================================================
# V3 BATTERY DEFINITIONS
# WARNING: v3 registers are UNTESTED
# These definitions are for v3 battery hardware with different Modbus registers
# ============================================================================

SENSOR_DEFINITIONS_V3 = [
    {
        "register": 37005,
        "scale": 1,
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "name": "Battery SOC",
        "key": "battery_soc",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 32105,
        "scale": 0.001,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total",
        "name": "Battery Total Energy",
        "key": "battery_total_energy",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 3,
        "scan_interval": "low",
    },
    {
        "register": 30100,
        "scale": 0.01,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "name": "Battery Voltage",
        "key": "battery_voltage",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 30001,
        "count": 1,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "Battery Power",
        "key": "battery_power",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 1,
        "scan_interval": "high",
        "force_update": True
    },
    {
        "register": 35000,
        "scale": 0.1,
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "name": "Internal Temperature",
        "key": "internal_temperature",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 2,
        "scan_interval": "medium",
    },
    {
        "register": 30006,
        "count": 1,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "AC Power",
        "key": "ac_power",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 0,
        "scan_interval": "high",
        "force_update": True
    },
    {
        "register": 33000,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Charging Energy",
        "key": "total_charging_energy",
        "enabled_by_default": True,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33002,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Discharging Energy",
        "key": "total_discharging_energy",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33004,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Daily Charging Energy",
        "key": "total_daily_charging_energy",
        "enabled_by_default": True,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33006,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Daily Discharging Energy",
        "key": "total_daily_discharging_energy",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 35100,
        "scale": 1,
        "unit": None,
        "icon": "mdi:state-machine",
        "name": "Inverter State",
        "key": "inverter_state",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "states": {
            0: "Sleep",
            1: "Standby",
            2: "Charge",
            3: "Discharge",
            4: "Backup Mode",
            5: "OTA Upgrade",
            6: "Bypass",
        },
        "scan_interval": "high",
    },
    {
        "name": "Max Cell Voltage",
        "register": 37007,
        "scale": 0.001,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "max_cell_voltage",
        "enabled_by_default": False,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "medium",
    },
    {
        "name": "Min Cell Voltage",
        "register": 37008,
        "scale": 0.001,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "min_cell_voltage",
        "enabled_by_default": False,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "medium",
    },
    {
        "name": "Battery Cycle Count",
        "register": 34003,
        "scale": 1,
        "icon": "mdi:counter",
        "state_class": "total_increasing",
        "category": "diagnostic",
        "key": "battery_cycle_count",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "low",
    },
    {
        "name": "Device Name",
        "register": 31000,
        "count": 10,
        "data_type": "char",
        "unit": None,
        "icon": "mdi:package-variant-closed",
        "key": "device_name",
        "enabled_by_default": True,
        "scan_interval": "very_low",
        "precision": 0,
    },
    {
        "name": "BMS Version",
        "register": 30204,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "key": "bms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "VMS Version",
        "register": 30202,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "key": "vms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "EMS Version",
        "register": 30200,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "ems_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scale": 1,
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "Comm Module Firmware",
        "register": 30350,
        "count": 6,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "comm_module_firmware",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "MAC Address",
        "register": 30304,
        "count": 6,
        "unit": None,
        "icon": "mdi:ethernet",
        "key": "mac_address",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
]

BINARY_SENSOR_DEFINITIONS_V3 = [
    {
        "name": "WiFi Status",
        "register": 30300,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:check-network-outline",
        "key": "wifi_status",
        "enabled_by_default": False,
        "scan_interval": "low",
    },
    {
        "name": "Cloud Status",
        "register": 30302,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:cloud-outline",
        "key": "cloud_status",
        "enabled_by_default": False,
        "scan_interval": "low",
    },
]

SELECT_DEFINITIONS_V3 = [
    {
        "register": 42010,
        "name": "Force Mode",
        "key": "force_mode",
        "enabled_by_default": False,
        "scan_interval": "high",
        "data_type": "uint16",
        "options": {"stop": 0, "charge": 1, "discharge": 2},
    },
]

SWITCH_DEFINITIONS_V3 = [
    {
        "register": 41200,
        "command_on": 0,
        "command_off": 1,
        "name": "Backup Function",
        "key": "backup_function",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        # RS485 communication control mode switch
        "name": "RS485 Control Mode",
        "register": 42000,
        "command_on": 21930,  # 0x55AA in decimal
        "command_off": 21947,  # 0x55BB in decimal
        "key": "rs485_control_mode",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scan_interval": "medium",
    },
]

NUMBER_DEFINITIONS_V3 = [
    {
        "register": 42020,
        "name": "Set Charge Power",
        "key": "set_charge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 0,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 42021,
        "name": "Set Discharge Power",
        "key": "set_discharge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 0,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 44002,
        "name": "Max Charge Power",
        "key": "max_charge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 800,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 44003,
        "name": "Max Discharge Power",
        "key": "max_discharge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 800,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
]

BUTTON_DEFINITIONS_V3 = [
    {
        "register": 41000,
        "command": 21930,
        "icon": "mdi:restart",
        "category": "diagnostic",
        "name": "Reset Device",
        "key": "reset_device",
        "enabled_by_default": False,
        "data_type": "uint16",
    },
]

# ============================================================================
# VENUS A BATTERY DEFINITIONS
# WARNING: Venus A registers are UNTESTED
# ============================================================================

SENSOR_DEFINITIONS_VA = [
    {
        "register": 32104,
        "scale": 1,
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "name": "Battery SOC",
        "key": "battery_soc",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 32105,
        "scale": 0.001,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total",
        "name": "Battery Total Energy",
        "key": "battery_total_energy",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 3,
        "scan_interval": "low",
    },
    {
        "register": 30100,
        "scale": 0.01,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "name": "Battery Voltage",
        "key": "battery_voltage",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 30001,
        "count": 1,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "Battery Power",
        "key": "battery_power",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 1,
        "scan_interval": "high",
        "force_update": True,
    },
    {
        "register": 35000,
        "scale": 0.1,
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "name": "Internal Temperature",
        "key": "internal_temperature",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 2,
        "scan_interval": "medium",
    },
    {
        "register": 30006,
        "count": 1,
        "scale": 1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "AC Power",
        "key": "ac_power",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 0,
        "scan_interval": "high",
        "force_update": True,
    },
    {
        "register": 33000,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Charging Energy",
        "key": "total_charging_energy",
        "enabled_by_default": True,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33002,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Discharging Energy",
        "key": "total_discharging_energy",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33004,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Daily Charging Energy",
        "key": "total_daily_charging_energy",
        "enabled_by_default": True,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33006,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Daily Discharging Energy",
        "key": "total_daily_discharging_energy",
        "enabled_by_default": True,
        "data_type": "int32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 35100,
        "scale": 1,
        "unit": None,
        "icon": "mdi:state-machine",
        "name": "Inverter State",
        "key": "inverter_state",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "states": {
            0: "Sleep",
            1: "Standby",
            2: "Charge",
            3: "Discharge",
            4: "Backup Mode",
            5: "OTA Upgrade",
            6: "Bypass",
        },
        "scan_interval": "high",
    },
    {
        "register": 30037,
        "scale": 0.1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "MPPT1 Power",
        "key": "mppt1_power",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "high",
    },
    {
        "register": 30038,
        "scale": 0.1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "MPPT2 Power",
        "key": "mppt2_power",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "high",
    },
    {
        "register": 30039,
        "scale": 0.1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "MPPT3 Power",
        "key": "mppt3_power",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "high",
    },
    {
        "register": 30040,
        "scale": 0.1,
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "name": "MPPT4 Power",
        "key": "mppt4_power",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "high",
    },
    {
        "name": "Device Name",
        "register": 31000,
        "count": 10,
        "data_type": "char",
        "unit": None,
        "icon": "mdi:package-variant-closed",
        "key": "device_name",
        "enabled_by_default": True,
        "scan_interval": "very_low",
        "precision": 0,
    },
    {
        "name": "BMS Version",
        "register": 30204,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "key": "bms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "VMS Version",
        "register": 30202,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "key": "vms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "EMS Version",
        "register": 30200,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "ems_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "scale": 1,
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "Comm Module Firmware",
        "register": 30350,
        "count": 6,
        "unit": None,
        "icon": "mdi:ticket-confirmation-outline",
        "category": "diagnostic",
        "key": "comm_module_firmware",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "MAC Address",
        "register": 30304,
        "count": 6,
        "unit": None,
        "icon": "mdi:ethernet",
        "key": "mac_address",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "name": "Battery Cycle Count",
        "register": 34003,
        "scale": 1,
        "icon": "mdi:counter",
        "state_class": "total_increasing",
        "category": "diagnostic",
        "key": "battery_cycle_count",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "low",
    },
    {
        "name": "Max Cell Voltage",
        "register": 37007,
        "scale": 0.001,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "max_cell_voltage",
        "enabled_by_default": False,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "medium",
    },
    {
        "name": "Min Cell Voltage",
        "register": 37008,
        "scale": 0.001,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "key": "min_cell_voltage",
        "enabled_by_default": False,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "medium",
    },
]

# Venus D has the same sensor registers as Venus A
SENSOR_DEFINITIONS_VD = SENSOR_DEFINITIONS_VA

_WIFI_CLOUD_BINARY_SENSORS = [
    {
        "name": "WiFi Status",
        "register": 30300,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:check-network-outline",
        "key": "wifi_status",
        "enabled_by_default": False,
        "scan_interval": "low",
    },
    {
        "name": "Cloud Status",
        "register": 30302,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:cloud-outline",
        "key": "cloud_status",
        "enabled_by_default": False,
        "scan_interval": "low",
    },
]
BINARY_SENSOR_DEFINITIONS_VA = _WIFI_CLOUD_BINARY_SENSORS
BINARY_SENSOR_DEFINITIONS_VD = _WIFI_CLOUD_BINARY_SENSORS

SELECT_DEFINITIONS_VA = [
    {
        "register": 42010,
        "name": "Force Mode",
        "key": "force_mode",
        "enabled_by_default": False,
        "scan_interval": "high",
        "data_type": "uint16",
        "options": {"stop": 0, "charge": 1, "discharge": 2},
    },
]

SELECT_DEFINITIONS_VD = [
    {
        "register": 42010,
        "name": "Force Mode",
        "key": "force_mode",
        "enabled_by_default": False,
        "scan_interval": "high",
        "data_type": "uint16",
        "options": {"standby": 0, "charge": 1, "discharge": 2},
    },
]

# Venus A/D share the same switch and button registers as V3
SWITCH_DEFINITIONS_VA = SWITCH_DEFINITIONS_V3
SWITCH_DEFINITIONS_VD = SWITCH_DEFINITIONS_V3
BUTTON_DEFINITIONS_VA = BUTTON_DEFINITIONS_V3
BUTTON_DEFINITIONS_VD = BUTTON_DEFINITIONS_V3

NUMBER_DEFINITIONS_VA = [
    {
        "register": 42020,
        "name": "Set Charge Power",
        "key": "set_charge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 0,
        "max": 1200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 42021,
        "name": "Set Discharge Power",
        "key": "set_discharge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 0,
        "max": 1200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 44002,
        "name": "Max Charge Power",
        "key": "max_charge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 0,
        "max": 1200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 44003,
        "name": "Max Discharge Power",
        "key": "max_discharge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 0,
        "max": 1200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 42011,
        "name": "Charge To SOC",
        "key": "charge_to_soc",
        "enabled_by_default": False,
        "icon": "mdi:battery-sync-outline",
        "min": 10,
        "max": 100,
        "step": 1,
        "unit": "%",
        "scale": 1,
        "data_type": "uint16",
        "scan_interval": "high",
    },
]

NUMBER_DEFINITIONS_VD = [
    {
        "register": 42020,
        "name": "Set Charge Power",
        "key": "set_charge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 0,
        "max": 2200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 42021,
        "name": "Set Discharge Power",
        "key": "set_discharge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 0,
        "max": 2200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 44002,
        "name": "Max Charge Power",
        "key": "max_charge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-up-outline",
        "min": 0,
        "max": 2200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 44003,
        "name": "Max Discharge Power",
        "key": "max_discharge_power",
        "enabled_by_default": False,
        "icon": "mdi:battery-arrow-down-outline",
        "min": 0,
        "max": 2200,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 42011,
        "name": "Charge To SOC",
        "key": "charge_to_soc",
        "enabled_by_default": False,
        "icon": "mdi:battery-sync-outline",
        "min": 10,
        "max": 100,
        "step": 1,
        "unit": "%",
        "scale": 1,
        "data_type": "uint16",
        "scan_interval": "high",
    },
]

EFFICIENCY_SENSOR_DEFINITIONS_V3 = [
    {
        "key": "round_trip_efficiency_total",
        "name": "Round-Trip Efficiency Total",
        "unit": "%",
        "state_class": "measurement",
        "dependency_keys": {
            "charge": "total_charging_energy",
            "discharge": "total_discharging_energy",
        },
    },
]

STORED_ENERGY_SENSOR_DEFINITIONS_V3 = [
    {
        "name": "Stored Energy",
        "key": "stored_energy",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total",
        "dependency_keys": {
            "soc": "battery_soc",
            "capacity": "battery_total_energy"
        },
    }
]

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

# Predictive Grid Charging Configuration
CONF_ENABLE_PREDICTIVE_CHARGING = "enable_predictive_charging"
CONF_CHARGING_TIME_SLOT = "charging_time_slot"
CONF_SOLAR_FORECAST_SENSOR = "solar_forecast_sensor"
CONF_MAX_CONTRACTED_POWER = "max_contracted_power"

# Default base consumption fallback (kWh/day)
DEFAULT_BASE_CONSUMPTION_KWH = 5.0  # Fallback when no consumption history available

# Re-evaluation thresholds
SOC_REEVALUATION_THRESHOLD = 30  # Re-evaluate every 30% SOC drop

# Weekly Full Charge Configuration
CONF_ENABLE_WEEKLY_FULL_CHARGE = "enable_weekly_full_charge"
CONF_MANUAL_MODE_ENABLED = "manual_mode_enabled"
CONF_PREDICTIVE_CHARGING_OVERRIDDEN = "predictive_charging_overridden"
CONF_WEEKLY_FULL_CHARGE_DAY = "weekly_full_charge_day"
CONF_ENABLE_WEEKLY_FULL_CHARGE_DELAY = "enable_weekly_full_charge_delay"
CONF_ENABLE_CHARGE_DELAY = "enable_charge_delay"
CONF_DELAY_SAFETY_MARGIN_MIN = "delay_safety_margin_min"
DEFAULT_DELAY_SAFETY_MARGIN_MIN = 60

# Weekly Full Charge Delay Constants
CHARGE_EFFICIENCY = 0.85  # Conservative factor for charge power estimation
DELAY_SAFETY_FACTOR = 1.3  # 30% margin on energy balance
LOW_FORECAST_THRESHOLD_FACTOR = 1.5  # forecast < 1.5 × capacity → bad solar day
T_START_THRESHOLD_KWH = 0.1  # Threshold to detect solar production start
T_START_FALLBACK_HOUR = 11  # If no T_start by 11:00, unlock immediately

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

# Default PD Controller Parameters
DEFAULT_PD_KP = 0.65
DEFAULT_PD_KD = 0.5
DEFAULT_PD_DEADBAND = 40
DEFAULT_PD_MAX_POWER_CHANGE = 800
DEFAULT_PD_DIRECTION_HYSTERESIS = 60
DEFAULT_PD_MIN_CHARGE_POWER = 0       # Minimum charge power (0 = disabled)
DEFAULT_PD_MIN_DISCHARGE_POWER = 0    # Minimum discharge power (0 = disabled)

# Default target grid power per time slot (0W = regulate to zero grid flow)
DEFAULT_SLOT_TARGET_GRID_POWER = 0

# Dynamic Pricing Mode Configuration
CONF_PREDICTIVE_CHARGING_MODE = "predictive_charging_mode"
CONF_PRICE_SENSOR = "price_sensor"
CONF_PRICE_INTEGRATION_TYPE = "price_integration_type"
CONF_MAX_PRICE_THRESHOLD = "max_price_threshold"

PREDICTIVE_MODE_TIME_SLOT = "time_slot"
PREDICTIVE_MODE_DYNAMIC_PRICING = "dynamic_pricing"
PREDICTIVE_MODE_REALTIME_PRICE = "realtime_price"

CONF_AVERAGE_PRICE_SENSOR = "average_price_sensor"

PRICE_INTEGRATION_NORDPOOL = "nordpool"
PRICE_INTEGRATION_PVPC = "pvpc"
PRICE_INTEGRATION_CKW = "ckw"

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
        "key": CONF_CAPACITY_PROTECTION_SOC_THRESHOLD,
        "name": "Capacity Protection SOC Threshold",
        "min": 30,
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
        "min": 2500,
        "max": 8000,
        "step": 100,
        "unit": "W",
        "default": DEFAULT_CAPACITY_PROTECTION_LIMIT,
        "icon": "mdi:flash-alert",
        "condition": CONF_CAPACITY_PROTECTION_ENABLED,
    },
]
