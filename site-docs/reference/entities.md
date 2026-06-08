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

## Cell balance monitor sensors (per battery)

Only present when the [cell balance monitor](../features/cell-balance-monitor.md) is enabled in the weekly full charge configuration.

| Entity | Description | Unit |
|---|---|---|
| `sensor.*_cell_delta` | Voltage spread between max and min cell at last OCV reading | mV |
| `sensor.*_balance_status` | Balance result: `green` / `yellow` / `orange` / `red` | — |
| `sensor.*_delta_trend` | Trend over last formal readings: `rising` / `stable` / `falling` | — |
| `sensor.*_last_balance_read` | Timestamp of the last reading | timestamp |
| `sensor.*_delta_avg_4w` | Rolling average of the last 4 formal readings | mV |

## Device information sensors

| Entity | Description |
|---|---|
| `sensor.*_device_name` | Device name |
| `sensor.*_sn_code` | Serial number |
| `sensor.*_software_version` | Firmware version |
| `sensor.*_bms_version` | BMS version |
| `sensor.*_mac_address` | MAC address |
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
| `number.marstek_venus_system_system_max_charge_power` | Optional combined charge cap for the whole system (`0 W` = disabled). Only created when system power limits are enabled. | 0–15000 W |
| `number.marstek_venus_system_system_max_discharge_power` | Optional combined discharge cap for the whole system (`0 W` = disabled). Only created when system power limits are enabled. | 0–15000 W |
| `number.*_max_soc` | Maximum SOC | 0–100 % |
| `number.*_min_soc` | Minimum SOC | 0–100 % |
| `number.*_max_charge_power` | Max charge power | W |
| `number.*_max_discharge_power` | Max discharge power | W |

## Selects

| Entity | Options |
|---|---|
| `select.*_force_mode` | None / Charge / Discharge |
| `select.marstek_venus_system_pd_tuning_profile` | Very smooth / Smooth / Balanced / Aggressive / Very aggressive / Custom — one-click PD presets that set `Kp`, `Kd` and the rate limit together (deadband stays user-owned) |

## Switches

| Entity | Description |
|---|---|
| `switch.*_rs485_control` | RS485 control mode |
| `switch.*_allow_charge` | Software control that allows this battery to participate in automatic charging |
| `switch.*_allow_discharge` | Software control that allows this battery to participate in automatic discharging |
| `switch.*_backup_function` | Backup function — when enabled **and** AC offgrid power ≠ 0 W, the battery is excluded from PD control (no write commands sent) |
| `switch.marstek_venus_system_override_predictive_charging` | Override predictive charging |

## Buttons

| Entity | Description |
|---|---|
| `button.*_reset` | Device reset |

## System sensors

### Integration Status

`sensor.marstek_venus_system_integration_status` shows at a glance what the integration is currently doing. It reflects the highest-priority active mode:

| State | Description |
|---|---|
| `Charging from Grid` | Predictive grid charging is active |
| `Weekly Full Charge` | Charging to 100 % for cell balancing |
| `Charge Delayed` | Charging blocked, waiting for optimal time based on solar forecast |
| `Waiting for Solar` | Charge delay: waiting for solar production to start |
| `Charging to Setpoint` | Charge delay: charging to the configured minimum SOC |
| `Capacity Protection` | Discharge limited due to low SOC (peak shaving active) |
| `No-Discharge Window` | Inside a configured no-discharge time slot |
| `Charging` | Charging (solar surplus or other) |
| `Discharging` | Discharging to cover home consumption |
| `Standby` | System balanced within deadband, no action needed |
| `Manual Mode` | Manual mode active — integration sends no automatic commands |
| `Initializing` | First controller cycle not yet completed |

The sensor also exposes blocker diagnostics as attributes:

| Attribute | Description |
|---|---|
| `charge_blocked` | `true` when charge is effectively blocked system-wide, either by a global blocker or because every known battery is charge-blocked |
| `discharge_blocked` | `true` when discharge is effectively blocked system-wide, either by a global blocker or because every known battery is discharge-blocked |
| `charge_blockers` | Active system-wide charge blockers with reason, details, and timestamp |
| `discharge_blockers` | Active system-wide discharge blockers with reason, details, and timestamp |
| `battery_charge_blockers` | Active per-battery charge blockers grouped by battery, including manual allow-charge, maximum SOC, and charge hysteresis |
| `battery_discharge_blockers` | Active per-battery discharge blockers grouped by battery, including manual allow-discharge and minimum SOC |

### PD Control Quality

`sensor.marstek_venus_system_pd_control_quality` reports how well the PD controller holds the grid target, so the effect of a [tuning profile](../features/pd-controller.md#tuning-profiles) or slider change is visible. The state is a verdict:

| State | Meaning |
|---|---|
| `stable` | PD tracks the target well |
| `oscillating` | Hunting — use a smoother profile or raise the deadband |
| `sluggish` | Too slow — use a more aggressive profile |
| `battery_limited` | Battery full/empty or at its power rail; the PD cannot act (not a tuning issue) |
| `collecting_data` | Warming up |

Attributes: `rms_error_w` (average grid-tracking error), `oscillation_per_min`, the active `kp` / `kd` / `deadband_w` / `max_power_change_w`, and `active_profile`. The metric is a 60 s rolling average and is paused briefly after a target change and while battery-limited, so allow 1–2 min after a change.

### Aggregate sensors

Available under the `sensor.marstek_venus_system_*` prefix, summing values across all batteries:

- `system_battery_power` — Total system power
- `system_battery_soc` — System average SOC
- `system_total_charging_energy` — Total system charging energy
- `system_total_discharging_energy` — Total system discharging energy
- `grid_at_min_soc` — Grid import during min SOC periods (kWh)
- `system_alarm_status` — Aggregated alarm state across all batteries (`OK` / `Warning` / `Fault`); attributes list active conditions per battery
- `system_home_consumption` — Instantaneous home consumption (W). Reads the household sensor when configured, otherwise derives it from `grid + battery AC + solar`.
- `system_daily_home_energy` — Today's home consumption (kWh), integrated from the Home Consumption value above. Resets at midnight (local time).
- `system_battery_power` — Total system power
- `system_battery_soc` — System average SOC
- `system_total_charging_energy` — Total system charging energy
- `system_total_discharging_energy` — Total system discharging energy
- `grid_at_min_soc` — Grid import during min SOC periods (kWh)
- `system_alarm_status` — Aggregated alarm state across all batteries (`OK` / `Warning` / `Fault`); attributes list active conditions per battery
- `system_home_consumption` — Instantaneous home consumption (W). Reads the household sensor when configured, otherwise derives it from `grid + battery AC + solar`.
- `system_daily_home_energy` — Today's home consumption (kWh), integrated from the Home Consumption value above. Resets at midnight (local time).

### Configuration Summary

`sensor.marstek_venus_system_configuration_summary` is a hidden diagnostic sensor intended for support reports. It exposes configuration attributes without battery IP addresses or ports.

Relevant power-limit attributes include:

| Attribute | Description |
|---|---|
| `total_max_charge_power_W` | Sum of configured per-battery charge limits |
| `total_max_discharge_power_W` | Sum of configured per-battery discharge limits |
| `system_power_limits_enabled` | Whether system-wide power caps are enabled |
| `system_max_charge_power_W` | Configured system-wide charge cap (`0` = disabled) |
| `system_max_discharge_power_W` | Configured system-wide discharge cap (`0` = disabled) |
| `effective_total_max_charge_power_W` | Total charge capacity after applying the system cap |
| `effective_total_max_discharge_power_W` | Total discharge capacity after applying the system cap |

![Entity list in Home Assistant](../assets/screenshots/reference/entities-list.png){ width="700"  style="display: block; margin: 0 auto;"}
