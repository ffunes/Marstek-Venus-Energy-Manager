# Solar charge delay

Delays morning battery charging (both from solar and from the grid) while the expected solar production is sufficient to cover the required energy. Avoids charging the battery early — whether from solar or the grid — when the sun will be able to do it later.

## When it applies

- Morning charge after the battery has discharged overnight.
- Weekly 100% charge (waits for the sun to complete the charge before resorting to the grid).

## Solar model

The integration uses a **sinusoidal model** based on the stored overnight forecast to estimate hour-by-hour solar production throughout the day. It compares the expected cumulative production from the current hour until sunset with the remaining energy needed.

```
If remaining_solar_production >= energy_to_charge:
    Wait (the sun will charge it)
Else:
    Start charging (solar or grid)
```

## Stored overnight forecast

Every night, the integration saves tomorrow's solar forecast. This stored forecast is used throughout the following day for the delay model, ensuring a consistent estimate even if the forecast sensor changes during the day.

## SOC setpoint

An optional SOC setpoint (0–90 %, default 0 = disabled) splits charging into two phases:

1. **Below the setpoint** — the battery charges freely (solar and grid), the delay is inactive. Sensor state: `Charging to setpoint`.
2. **At or above the setpoint** — the solar delay logic activates and decides whether to keep charging or wait.

This is useful when the battery is deeply discharged and needs a guaranteed minimum charge before the solar decision is made. For example, with a setpoint of 50 % the battery charges to 50 % without restrictions; above 50 % the system evaluates whether remaining solar production is enough to complete the charge and waits if it is.

Setting the setpoint to 0 disables this behaviour and applies the delay from the very start of charging, which is the default.

## Requirements

- Solar forecast sensor configured in the [initial setup step](../configuration/main-sensor.md).

![Solar charge delay attributes](../assets/screenshots/features/solar-charge-delay-attributes.png){ width="650"  style="display: block; margin: 0 auto;"}
