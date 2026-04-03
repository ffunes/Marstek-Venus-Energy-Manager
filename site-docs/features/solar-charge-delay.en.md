# Solar charge delay

Delays morning grid charging while the expected solar production is sufficient to cover the required energy. Avoids buying grid energy that would later be displaced by solar.

## When it applies

- Morning charge after the battery has discharged overnight.
- Weekly 100% charge (waits for the sun to complete the charge before resorting to the grid).

## Solar model

The integration uses a **sinusoidal model** based on the stored overnight forecast to estimate hour-by-hour solar production throughout the day. It compares the expected cumulative production from the current hour until sunset with the remaining energy needed.

```
If remaining_solar_production >= energy_to_charge:
    Wait (the sun will charge it)
Else:
    Start grid charging
```

## Stored overnight forecast

Every night, the integration saves tomorrow's solar forecast. This stored forecast is used throughout the following day for the delay model, ensuring a consistent estimate even if the forecast sensor changes during the day.

## Requirements

- Solar forecast sensor configured in the [initial setup step](../configuration/main-sensor.md).

![Solar charge delay attributes](../assets/screenshots/features/solar-charge-delay-attributes.png){ width="650"  style="display: block; margin: 0 auto;"}
