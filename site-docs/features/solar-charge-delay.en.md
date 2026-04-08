# Solar charge delay

!!! danger "Breaking change in v1.6.0"
    The integration now uses **today's** solar forecast instead of tomorrow's. If you have this feature configured, you must update the solar forecast sensor in settings to point to the **today** sensor (e.g. `sensor.solcast_pv_forecast_forecast_today`) instead of the tomorrow sensor.

Delays morning battery charging (both from solar and from the grid) while the expected solar production is sufficient to cover the required energy. Avoids charging the battery early — whether from solar or the grid — when the sun will be able to do it later.

## When it applies

- Morning charge after the battery has discharged overnight.
- Weekly 100% charge (waits for the sun to complete the charge before resorting to the grid).

## Solar model

The integration uses a **sinusoidal model** based on the current day's solar forecast to estimate hour-by-hour solar production throughout the day. It compares the expected cumulative production from the current hour until sunset with the remaining energy needed.

```
If remaining_solar_production >= energy_to_charge:
    Wait (the sun will charge it)
Else:
    Start charging (solar or grid)
```

## Live forecast

The integration reads the solar forecast sensor live, with no nightly capture or storage. Most solar forecast integrations (Solcast, Forecast.Solar, etc.) update their today sensor multiple times throughout the day, becoming progressively more accurate as actual weather conditions develop.

Every time the sensor value changes by more than 0.05 kWh, the integration re-evaluates the energy balance:

- **Forecast degrades** until `(usable_energy + forecast) < avg_daily_consumption` → the delay unlocks and charging starts immediately.
- **Forecast improves** while the delay is still active → the system keeps waiting for the sun to charge the battery.

Once the delay is unlocked it stays unlocked for the rest of the day.

## SOC setpoint

An optional SOC setpoint (12–90 %, disabled by default) splits charging into two phases:

1. **Below the setpoint** — the battery charges freely (solar and grid), the delay is inactive. Sensor state: `Charging to setpoint`.
2. **At or above the setpoint** — the solar delay logic activates and decides whether to keep charging or wait.

This is useful when the battery is deeply discharged and needs a guaranteed minimum charge before the solar decision is made. For example, with a setpoint of 50 % the battery charges to 50 % without restrictions; above 50 % the system evaluates whether remaining solar production is enough to complete the charge and waits if it is.

The setpoint is enabled with a dedicated checkbox in the configuration. When disabled, the delay applies from the very start of charging. The minimum value is 12 % — the minimum discharge SOC of the Venus batteries.

## Requirements

- Solar forecast sensor configured in the [initial setup step](../configuration/main-sensor.md).

![Solar charge delay attributes](../assets/screenshots/features/solar-charge-delay-attributes.png){ width="650"  style="display: block; margin: 0 auto;"}
