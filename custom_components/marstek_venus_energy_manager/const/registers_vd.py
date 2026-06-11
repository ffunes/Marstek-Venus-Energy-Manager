"""Modbus register and entity definitions for Marstek Venus D hardware."""

from .registers_va import SENSOR_DEFINITIONS_VA, _WIFI_CLOUD_BINARY_SENSORS
from .registers_v3 import SWITCH_DEFINITIONS_V3, BUTTON_DEFINITIONS_V3

# Venus D has the same sensor registers as Venus A
SENSOR_DEFINITIONS_VD = SENSOR_DEFINITIONS_VA

BINARY_SENSOR_DEFINITIONS_VD = _WIFI_CLOUD_BINARY_SENSORS

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
    {
        "name": "User Work Mode",
        "register": 43000,
        "key": "user_work_mode",
        "enabled_by_default": False,
        "data_type": "uint16",
        "scan_interval": "high",
        "use_shadow_state": True,
        "options": {"manual": 0, "anti_feed": 1, "trade_mode": 2},
    },
]

SWITCH_DEFINITIONS_VD = SWITCH_DEFINITIONS_V3
BUTTON_DEFINITIONS_VD = BUTTON_DEFINITIONS_V3

NUMBER_DEFINITIONS_VD = [
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
