"""Modbus register and entity definitions for Marstek Venus v2 (unsuffixed) hardware."""

from .registers_common import FAULT_BIT_DESCRIPTIONS, ALARM_BIT_DESCRIPTIONS

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
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "high"
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
        "enabled_by_default": True,
        "data_type": "int16",
        "precision": 3,
        "scan_interval": "high"
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
        "bit_descriptions": FAULT_BIT_DESCRIPTIONS
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
        "bit_descriptions": ALARM_BIT_DESCRIPTIONS
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
    {
        "name": "WiFi Signal Strength",
        "register": 30303,
        "scale": -1,
        "unit": "dBm",
        "device_class": "signal_strength",
        "state_class": "measurement",
        "key": "wifi_signal_strength",
        "enabled_by_default": True,
        "data_type": "uint16",
        "category": "diagnostic",
        "precision": 0,
        "scan_interval": "low",
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
        "enabled_by_default": True,
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
    },
    {
        "name": "User Work Mode",
        "register": 43000,
        "key": "user_work_mode",
        "enabled_by_default": False,
        "data_type": "uint16",
        "scan_interval": "high",
        "use_shadow_state": True,
        "options": {
            "manual": 0,
            "anti_feed": 1,
            "trade_mode": 2,
        },
    },
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
