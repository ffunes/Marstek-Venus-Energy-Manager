"""Constants for the Marstek Venus Energy Manager integration."""

DOMAIN = "marstek_venus_energy_manager"

SCAN_INTERVAL = {
    "high": 2,       # fast-changing sensors, e.g., power, alarms
    "medium": 5,     # moderately changing sensors, e.g., voltage, current
    "low": 30,        # slow-changing sensors, e.g., cumulative energy counters
    "very_low": 300   # rarely changing info, e.g., device info, firmware versions
}

# Battery version support
CONF_BATTERY_VERSION = "battery_version"
SUPPORTED_VERSIONS = ["v2", "v3"]
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
    }
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
    }

]

# Definitions for binary sensors that represent on/off states
# Each binary sensor includes the Modbus register and bit position
BINARY_SENSOR_DEFINITIONS = [
    # Empty - binary sensors for battery state will be added here if needed
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
        "min": 0,
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
        "min": 0,
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
    {
        # charge or discharge to SOC as a percentage of total battery capacity
        "name": "Charge to SOC",
        "register": 42011,
        "key": "charge_to_soc",
        "enabled_by_default": True,
        "icon": "mdi:battery-sync-outline",
        "min": 10,
        "max": 100, 
        "step": 1,
        "unit": "%",
        "scale": 1,       
        "data_type": "uint16",        
        "scan_interval": "medium"
    }  
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
        "device_class": "battery",
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
        "register": 31000,
        "count": 10,
        "data_type": "char",
        "unit": None,
        "name": "Device Name",
        "key": "device_name",
        "enabled_by_default": True,
        "scan_interval": "very_low",
        "precision": 0,
    },
    {
        "register": 30204,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "name": "BMS Version",
        "key": "bms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "register": 30202,
        "unit": None,
        "icon": "mdi:battery-check-outline",
        "category": "diagnostic",
        "name": "VMS Version",
        "key": "vms_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "register": 30200,
        "unit": None,
        "category": "diagnostic",
        "icon": "mdi:ticket-confirmation-outline",
        "name": "EMS Version",
        "key": "ems_version",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "register": 30350,
        "count": 6,
        "unit": None,
        "category": "diagnostic",
        "icon": "mdi:ticket-confirmation-outline",
        "name": "Comm Module Firmware",
        "key": "comm_module_firmware",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
    {
        "register": 30304,
        "count": 6,
        "unit": None,
        "name": "MAC Address",
        "key": "mac_address",
        "enabled_by_default": True,
        "data_type": "char",
        "precision": 0,
        "scan_interval": "very_low",
    },
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
        "register": 30101,
        "scale": 0.1,
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "name": "Battery Current",
        "key": "battery_current",
        "enabled_by_default": True,
        "data_type": "int16",
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
        "register": 32200,
        "scale": 0.1,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "name": "AC Voltage",
        "key": "ac_voltage",
        "enabled_by_default": True,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 37004,
        "scale": 0.004,
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "name": "AC Current",
        "key": "ac_current",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 1,
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
        "register": 32204,
        "scale": 0.1,
        "unit": "Hz",
        "device_class": "frequency",
        "state_class": "measurement",
        "name": "AC Frequency",
        "key": "ac_frequency",
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 2,
        "scan_interval": "medium",
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
        "register": 33008,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Monthly Charging Energy",
        "key": "total_monthly_charging_energy",
        "enabled_by_default": False,
        "data_type": "uint32",
        "precision": 2,
        "scan_interval": "low",
    },
    {
        "register": 33010,
        "count": 2,
        "scale": 0.01,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "name": "Total Monthly Discharging Energy",
        "key": "total_monthly_discharging_energy",
        "enabled_by_default": False,
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
        "register": 41100,
        "data_type": "uint16",
        "unit": None,
        "icon": "mdi:home-automation",
        "name": "Modbus Address",
        "key": "modbus_address",
        "enabled_by_default": False,
        "scan_interval": "very_low",
        "precision": 0,
    },
    {
        "register": 32300,
        "scale": 0.1,
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "name": "AC Offgrid Voltage",
        "key": "ac_offgrid_voltage",
        "enabled_by_default": False,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 32301,
        "scale": 0.01,
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "name": "AC Offgrid Current",
        "key": "ac_offgrid_current",
        "enabled_by_default": False,
        "data_type": "uint16",
        "precision": 1,
        "scan_interval": "medium",
    },
    {
        "register": 30303,
        "scale": -1,
        "data_type": "uint16",
        "device_class": "diagnostic",
        "unit": "dBm",
        "icon": "mdi:wifi",
        "category": "diagnostic",
        "name": "WiFi Signal Strength",
        "key": "wifi_signal_strength",
        "enabled_by_default": False,
        "precision": 0,
        "scan_interval": "high",
    },
]

BINARY_SENSOR_DEFINITIONS_V3 = [
    {
        "register": 30300,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:check-network-outline",
        "name": "WiFi Status",
        "key": "wifi_status",
        "enabled_by_default": False,
        "scan_interval": "medium",
    },
    {
        "register": 30302,
        "data_type": "uint16",
        "unit": None,
        "category": "diagnostic",
        "device_class": "connectivity",
        "icon": "mdi:cloud-outline",
        "name": "Cloud Status",
        "key": "cloud_status",
        "enabled_by_default": False,
        "scan_interval": "medium",
    },
]

SELECT_DEFINITIONS_V3 = [
    {
        "register": 43000,
        "name": "User Work Mode",
        "key": "user_work_mode",
        "enabled_by_default": True,
        "scan_interval": "high",
        "options": {"manual": 0, "anti_feed": 1, "trade_mode": 2},
    },
    {
        "register": 42010,
        "name": "Force Mode",
        "key": "force_mode",
        "enabled_by_default": False,
        "scan_interval": "high",
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
        "register": 42000,
        "command_on": 21930,
        "command_off": 21947,
        "name": "RS485 Control Mode",
        "key": "rs485_control_mode",
        "enabled_by_default": False,
        "data_type": "uint16",
        "scan_interval": "high",
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
        "min": 0,
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
        "min": 0,
        "max": 2500,
        "step": 50,
        "unit": "W",
        "data_type": "uint16",
        "scan_interval": "high",
    },
    {
        "register": 42011,
        "name": "Charge to SOC",
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
    {
        "register": 41001,
        "command": 21930,
        "icon": "mdi:factory",
        "category": "diagnostic",
        "name": "Factory Reset",
        "key": "factory_reset",
        "enabled_by_default": False,
        "data_type": "uint16",
    },
]

EFFICIENCY_SENSOR_DEFINITIONS_V3 = [
    {
        "key": "round_trip_efficiency_total",
        "name": "Round-Trip Efficiency Total",
        "unit": "%",
        "device_class": "battery",
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
CONF_WEEKLY_FULL_CHARGE_DAY = "weekly_full_charge_day"

# Weekday mapping (mon=0, sun=6, matches datetime.weekday())
WEEKDAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6
}

# PD Controller Advanced Configuration Keys
CONF_PD_KP = "pd_controller_kp"
CONF_PD_KD = "pd_controller_kd"
CONF_PD_DEADBAND = "pd_controller_deadband"
CONF_PD_MAX_POWER_CHANGE = "pd_controller_max_power_change"
CONF_PD_DIRECTION_HYSTERESIS = "pd_controller_direction_hysteresis"

# Default PD Controller Parameters
DEFAULT_PD_KP = 0.65
DEFAULT_PD_KD = 0.5
DEFAULT_PD_DEADBAND = 40
DEFAULT_PD_MAX_POWER_CHANGE = 800
DEFAULT_PD_DIRECTION_HYSTERESIS = 60
