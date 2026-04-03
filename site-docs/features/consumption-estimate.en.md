# Daily consumption estimate

Predictive charging needs to know how much energy your home consumes each day to decide whether grid charging is needed. Instead of a fixed value, the integration calculates a **dynamic consumption estimate** from the real history of the past 7 days.

---

## What the estimate measures

The estimated consumption for a day is the sum of two components:

```
Day consumption = Actual battery discharge + Unmet demand (grid at min SOC)
```

### 1. Actual battery discharge

The energy the battery has discharged during the day, read directly from each battery's coordinator (`total_daily_discharging_energy`). This value resets at midnight according to the battery's internal clock.

### 2. Unmet demand — Grid at min SOC

When **all batteries are at min SOC** and can no longer discharge, the household must draw from the grid to cover its consumption. That grid-imported energy is real household consumption the battery could not serve.

The integration accumulates it in real time every controller cycle (~2.5 s) while all of these conditions are simultaneously met:

| Condition | Detail |
|---|---|
| All batteries at min SOC | No battery available to discharge |
| No active grid charging | System is not in predictive/dynamic pricing charge mode |
| Within a discharge window | A time slot is active, or no time slots are configured |
| Grid is importing | Grid sensor reads a positive value |

When all conditions are met, the accumulator grows proportionally to grid import:

```
increment (kWh) = grid_power (W) × 2.5 s / 3,600,000
```

This accumulator is exposed as the **`Grid at Min SOC`** sensor (kWh) and resets at midnight.

---

## Daily capture at 23:55

Every day at **23:55 (local time)** the integration saves the day's consumption by computing:

```
day_value = accumulated_battery_discharge + grid_at_min_soc_accumulated
```

The value is only stored if it is ≥ 1.5 kWh (to discard days without meaningful data). If lower, that day's entry is omitted from the history.

---

## 7-day history

The integration maintains a rolling history of the last **7 entries** in `(date, kWh)` format. This history is persisted to disk so it survives Home Assistant restarts.

### Fallback value

While fewer than 7 real days have accumulated (e.g. just after installing the integration), missing entries are filled with the fallback value **`DEFAULT_BASE_CONSUMPTION_KWH = 5.0 kWh`**. This value acts only as a placeholder and is replaced as soon as real data is available.

### Backfill from recorder history

At startup, the integration automatically tries to recover any missing days by querying the **Home Assistant recorder**. For each of the past 7 days it queries:

- `sensor.marstek_venus_system_daily_discharging_energy` — battery discharge
- `sensor.marstek_venus_system_daily_grid_at_min_soc_energy` — unmet demand

And sums both values exactly as the 23:55 capture would. This ensures that even after an HA restart or a fresh installation, the history is built with real data from the very first moment.

---

## 7-day rolling average

The consumption estimate used by predictive charging is the **arithmetic mean** of all values in the history:

```
expected_consumption = Σ(consumption_i) / n days
```

where `n` may be less than 7 if not enough real days have accumulated yet (fallback values also count in the average until replaced).

---

## Full example

```
Monday:    battery discharged 4.2 kWh + grid at min SOC 0.8 kWh = 5.0 kWh
Tuesday:   battery discharged 5.1 kWh + grid at min SOC 0.0 kWh = 5.1 kWh
Wednesday: battery discharged 3.8 kWh + grid at min SOC 1.5 kWh = 5.3 kWh
Thursday:  battery discharged 4.5 kWh + grid at min SOC 0.3 kWh = 4.8 kWh
Friday:    battery discharged 4.9 kWh + grid at min SOC 0.0 kWh = 4.9 kWh
Saturday:  battery discharged 6.1 kWh + grid at min SOC 0.2 kWh = 6.3 kWh
Sunday:    battery discharged 5.5 kWh + grid at min SOC 0.5 kWh = 6.0 kWh

Expected consumption = (5.0 + 5.1 + 5.3 + 4.8 + 4.9 + 6.3 + 6.0) / 7 = 5.34 kWh
```

Without the grid-at-min-SOC component (discharge only), the average would have been 4.87 kWh — 9% lower, which could have led to under-charging.

---

## Why the grid-at-min-SOC component matters

Without this adjustment, days when the battery empties before midnight are **underestimated** in the history: only the battery discharge is recorded, but the household's real consumption was higher. The resulting average would undervalue consumption, causing the system to charge less than needed the following night.

By adding the energy that entered from the grid while all batteries were at min SOC within a discharge window, the history reflects the **total real household consumption**, not just what the battery could cover.

---

## Diagnostic sensor

| Sensor | Description | Reset |
|---|---|---|
| `sensor.marstek_venus_system_daily_grid_at_min_soc_energy` | Grid energy accumulated during min SOC periods | Midnight (local time) |

The `binary_sensor.marstek_venus_system_predictive_charging_active` sensor exposes the 7-day consumption history and the count of real vs. fallback entries in its attributes, useful to verify the learning status.

![Consumption history attributes in HA](../assets/screenshots/features/consumption-estimate-attributes.png){ width="700"  style="display: block; margin: 0 auto;"}
