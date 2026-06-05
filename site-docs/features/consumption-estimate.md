# Daily consumption estimate

Predictive charging needs to know how much energy your home consumes each day to decide whether grid charging is needed. Instead of a fixed value, the integration calculates a **dynamic consumption estimate** from the real history of the past 7 days.

---

## What the estimate measures

The estimate is the **total home consumption during the solar+battery window** — the hours outside the grid-charging time slot, when the battery is expected to cover the house. It is averaged over the last 7 days.

### Home consumption source

The per-cycle home power is **derived** from the values the integration already has:

```
home = grid + Σ(battery AC power) + solar
```

This is the same value shown by the energy-flow diagram and the **`sensor.marstek_venus_system_home_consumption`** (Home Consumption, W) sensor. DC-coupled PV (MPPT) does not appear here — it is already netted into each battery's AC power at the inverter.

!!! note "Legacy household sensor"
    A `household_consumption_sensor` saved on an older install is read directly **instead** of deriving, but **only when no solar production sensor is configured** — with a solar sensor the derived value is exact and preferred. The field is no longer offered in setup.

### Excluded / additional devices

If you have configured [excluded or additional devices](excluded-devices.md), the home power is corrected before accumulation:

- **Excluded** (`included_in_consumption = true`): the device is already in the home/grid reading but the battery should not cover it → its power is **subtracted**.
- **Additional** (`included_in_consumption = false`): the device is not visible to the home reading but the battery should cover it → its power is **added**.

---

## Real-time accumulation

On every control cycle (event-driven, at the grid sensor's cadence), the home power is integrated into a daily accumulator **only while `is_in_consumption_window()` is true**: all 24 hours when no charging time slot is configured, or the hours outside the charging slot on slot days. This scoping ensures the measured window matches what predictive charging expects when it later projects remaining demand.

```
increment (kWh) = home_power (W) × Δt (s) / 3,600,000
```

`Δt` is the real elapsed time since the previous sample, so it adapts to the variable cadence. The running daily value is exposed as the `household_consumption_battery_window_kwh` attribute on `binary_sensor.marstek_venus_system_predictive_charging_active`, and is persisted so it survives restarts within the same day.

---

## Daily capture at 23:55

Every day at **23:55 (local time)** the integration snapshots the accumulator into the 7-day history before it resets at midnight. The value is only stored if it is ≥ 1.5 kWh (to discard days without meaningful data).

---

## 7-day history

The integration maintains a rolling history of the last **7 entries** in `(date, kWh)` format, persisted to disk so it survives Home Assistant restarts.

### Fallback value

While fewer than 7 real days have accumulated (e.g. just after installing the integration), missing entries are filled with the fallback value **`DEFAULT_BASE_CONSUMPTION_KWH = 5.0 kWh`**. This acts only as a placeholder and is replaced as soon as real data is available.

### Backfill from recorder history

At startup, the integration recovers missing days by querying the **Home Assistant recorder** for the `sensor.marstek_venus_system_home_consumption` sensor (which already resolves to the derived value, or the legacy household sensor when applicable). For each missing day it integrates that sensor's history over the consumption window, applies the excluded/additional-device adjustments, and stores the result exactly as the 23:55 capture would. This builds the history with real data even after an HA restart or a fresh installation.

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
Monday:    home consumption (battery window) = 5.0 kWh
Tuesday:   home consumption (battery window) = 5.1 kWh
Wednesday: home consumption (battery window) = 5.3 kWh
Thursday:  home consumption (battery window) = 4.8 kWh
Friday:    home consumption (battery window) = 4.9 kWh
Saturday:  home consumption (battery window) = 6.3 kWh
Sunday:    home consumption (battery window) = 6.0 kWh

Expected consumption = (5.0 + 5.1 + 5.3 + 4.8 + 4.9 + 6.3 + 6.0) / 7 = 5.34 kWh
```

---

## Diagnostic sensor

| Sensor | Description | Reset |
|---|---|---|
| `sensor.marstek_venus_system_daily_grid_at_min_soc_energy` | Grid energy imported while all batteries were at min SOC during a discharge window — household demand the battery could not cover | Midnight (local time) |

This **Grid at Min SOC** sensor is informational: it shows demand the battery missed because it was empty. It is no longer summed into the consumption estimate (the derived home consumption already captures total house load, including the part served from the grid).

The `binary_sensor.marstek_venus_system_predictive_charging_active` sensor exposes the 7-day consumption history and the count of real vs. fallback entries in its attributes, useful to verify the learning status.

![Consumption history attributes in HA](../assets/screenshots/features/consumption-estimate-attributes.png){ width="700"  style="display: block; margin: 0 auto;"}
