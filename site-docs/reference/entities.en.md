# Home Assistant entities

The integration automatically creates entities for each configured battery and aggregated sensors for the whole system.

## Sensors (per battery)

| Entity | Description | Unit |
|---|---|---|
| `sensor.*_battery_soc` | State of charge | % |
| `sensor.*_battery_power` | Current power | W |
| `sensor.*_battery_voltage` | Voltage | V |
| `sensor.*_battery_current` | Current | A |
| `sensor.*_battery_temperature` | Temperature | °C |
| `sensor.*_total_charging_energy` | Total charging energy | kWh |
| `sensor.*_total_discharging_energy` | Total discharging energy | kWh |
| `sensor.*_battery_cycle_count` | Cycle count (register, v3/vA/vD) | — |
| `sensor.*_battery_cycle_count_calc` | Calculated cycle count (all versions) | — |
| `sensor.*_max_cell_voltage` | Max cell voltage (v3/vA/vD) | V |
| `sensor.*_min_cell_voltage` | Min cell voltage (v3/vA/vD) | V |
| `sensor.*_alarm_status` | Active alarm conditions (v2) — diagnostic | text |
| `sensor.*_fault_status` | Active fault conditions (v2) — diagnostic | text |

## Device information sensors

| Entity | Description |
|---|---|
| `sensor.*_device_name` | Device name |
| `sensor.*_sn_code` | Serial number |
| `sensor.*_software_version` | Firmware version |
| `sensor.*_bms_version` | BMS version |
| `sensor.*_mac_address` | MAC address |

## Binary sensors

| Entity | Description |
|---|---|
| `binary_sensor.*_wifi_status` | WiFi status |
| `binary_sensor.*_cloud_status` | Cloud status |
| `binary_sensor.marstek_venus_system_predictive_charging_active` | Predictive charging active (system) |

## Numbers (sliders)

| Entity | Description | Range |
|---|---|---|
| `number.*_max_soc` | Maximum SOC | 0–100 % |
| `number.*_min_soc` | Minimum SOC | 0–100 % |
| `number.*_max_charge_power` | Max charge power | W |
| `number.*_max_discharge_power` | Max discharge power | W |

## Selects

| Entity | Options |
|---|---|
| `select.*_force_mode` | None / Charge / Discharge |

## Switches

| Entity | Description |
|---|---|
| `switch.*_rs485_control` | RS485 control mode |
| `switch.*_backup_function` | Backup function — when enabled **and** AC offgrid power ≠ 0 W, the battery is excluded from PD control (no write commands sent) |
| `switch.marstek_venus_system_override_predictive_charging` | Override predictive charging |

## Buttons

| Entity | Description |
|---|---|
| `button.*_reset` | Device reset |

## System aggregate sensors

Available under the `sensor.marstek_venus_system_*` prefix, summing values across all batteries:

- `system_battery_power` — Total system power
- `system_battery_soc` — System average SOC
- `system_total_charging_energy` — Total system charging energy
- `system_total_discharging_energy` — Total system discharging energy
- `grid_at_min_soc` — Grid import during min SOC periods (kWh)
- `system_alarm_status` — Aggregated alarm state across all batteries (`OK` / `Warning` / `Fault`); attributes list active conditions per battery
- `household_energy_today` — Today's household energy consumption accumulated from the optional household power sensor, during the solar+battery window (kWh). Only present when a household consumption sensor is configured. Resets at midnight.

![Entity list in Home Assistant](../assets/screenshots/reference/entities-list.png){ width="700"  style="display: block; margin: 0 auto;"}
