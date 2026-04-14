# PD Controller

The PD (Proportional-Derivative) controller is the core of the integration. It runs every **2.5 seconds** and adjusts battery power to keep grid flow close to the configured target (default: 0 W).

## Algorithm

```
error = grid_power - target_power

P = Kp × error
D = Kd × (error - previous_error) / dt

adjustment = P + D
new_power = current_power + adjustment
```

### Default parameters

| Parameter | Value | Description |
|---|---|---|
| `Kp` | `0.65` | Proportional gain |
| `Kd` | `0.5` | Derivative gain |
| Deadband | `±40 W` | Dead zone: ignores small errors |
| Rate limit | `±500 W/cycle` | Maximum change per cycle |

## Stabilisation mechanisms

### Deadband (dead zone)

If the error is less than ±40 W, the controller does not adjust power. This prevents continuous micro-oscillations caused by sensor noise.

### Rate limiting

Power changes are limited to ±500 W per cycle to smooth transitions and protect the battery from abrupt changes.

### Oscillation detection

The controller monitors frequent direction reversals (charge↔discharge). If sustained oscillation is detected, the effective gain is temporarily reduced.

### Directional hysteresis

Prevents direction changes from momentary load variations (such as appliance start-ups). The controller requires the error to exceed a threshold for several cycles before switching from charging to discharging or vice versa.

## Backup function exclusion

A battery is excluded from the PD controller when **both** of the following are true:

1. The **Backup Function** switch (`switch.*_backup_function`) is enabled.
2. The **AC Offgrid Power** sensor (`sensor.*_ac_offgrid_power`) reports a non-zero value — confirming the battery is actually providing offgrid power.

Having the switch on alone is not sufficient. If the switch is on but AC offgrid power reads 0 W (the battery is not actively serving an offgrid load), it continues to participate in PD control normally.

While excluded, the controller sends no power commands, force mode changes, or configuration register writes to the battery. The battery continues to be polled normally so all read-only sensors (SOC, power, temperature, etc.) remain up to date.

### Post-backup cooldown

When the offgrid load drops back to 0 W, the battery does not re-enter PD control immediately. A **5-minute cooldown** keeps the battery excluded after the backup event ends. This avoids sending write commands to a battery that may still be settling after a backup episode.

Turning the **Backup Function** switch off clears the cooldown immediately.

!!! info
    This exclusion also covers the weekly full charge register writes and the shutdown sequence.

## Per-slot target power

Each [time slot](../configuration/time-slots.md) can have its own **target grid power** (`target_grid_power`), allowing different strategies at different times of day.

![PD controller entities in Home Assistant](../assets/screenshots/features/pd-controller-entities.png){ width="700"  style="display: block; margin: 0 auto;"}
