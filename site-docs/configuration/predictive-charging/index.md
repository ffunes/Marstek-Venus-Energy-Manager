# Predictive charging

Predictive charging is an **optional** feature that charges batteries from the grid when the expected energy balance for the following day is negative.

## Decision logic

```
If (Usable battery + Solar forecast) < Expected consumption:
    Charge from grid the exact deficit
Else:
    Do not charge (cost saving)
```

- **Usable battery**: energy currently stored above the configured min SOC.
- **Solar forecast**: estimated production for tomorrow (Solcast/Forecast.Solar sensor).
- **Expected consumption**: 7-day rolling average. See [Daily consumption estimate](../../features/consumption-estimate.md).

---

## Available modes

| Mode | Description |
|---|---|
| [Time Slot](time-slot.md) | Charges during a fixed window (e.g. overnight off-peak tariff) |
| [Dynamic Pricing](dynamic-pricing.md) | Automatically selects the cheapest hours of the day |
| [Real-Time Price](real-time-price.md) | Activates/deactivates charging based on the current price |

![Predictive charging mode selector](../../assets/screenshots/configuration/predictive-charging/mode-selector.png){ width="600"  style="display: block; margin: 0 auto;"}

---

## Notifications

The integration sends Home Assistant notifications:

- **1 hour before** the slot starts: energy balance analysis and charging decision.
- **When the slot starts**: confirmation that charging has begun.

Use the **Override Predictive Charging** switch to cancel predictive charging at any time.

![Predictive charging notification](../../assets/screenshots/configuration/predictive-charging/notification-example.png){ width="500"  style="display: block; margin: 0 auto;"}
