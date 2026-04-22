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

## Charge target

When charging is triggered, the integration does not charge all the way to `max_soc` from the grid. Instead it calculates a **grid-only target SOC** — enough to cover only what solar will not be able to provide during the day:

```
solar_surplus = max(0, solar_forecast − estimated_consumption)
grid_charge   = max(0, gap_to_max − solar_surplus)
target_soc    = current_soc + grid_charge / capacity × 100
```

`gap_to_max` is the kWh distance from the current SOC to `max_soc`. Solar output in excess of household demand charges the battery the rest of the way during the day.

**Example**: the battery needs 5 kWh to reach max_soc. Solar forecast is 13 kWh, expected consumption is 10 kWh — a surplus of 3 kWh available for the battery. The integration charges only **2 kWh** from the grid; solar handles the remaining 3 kWh during the day.

### Multi-battery systems

In systems with multiple batteries at different SOC levels the grid charge is distributed **proportionally to each battery's individual gap to max_soc**. A battery further from full receives a larger share; a battery already close to full relies mostly on solar for its remainder. This prevents overcharging any single unit from the grid and minimises total grid import.

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
