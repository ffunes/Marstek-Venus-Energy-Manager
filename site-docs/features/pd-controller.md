# PD Controller

The PD (Proportional-Derivative) controller is the core of the integration. It runs **event-driven** — recalculating each time the grid consumption sensor publishes a new value — and adjusts battery power to keep grid flow close to the configured target (default: 0 W).

## Algorithm

```
error = grid_power - target_power

P = Kp × error
D = Kd × (error - previous_error) / dt

adjustment = P + D
new_power = current_power + adjustment
```

Because the loop is event-driven (variable cadence), the `P` term and the rate limit are internally scaled by the real elapsed time between sensor updates, so the tuning behaves the same regardless of how fast your sensor publishes.

### Default parameters

| Parameter | Value | Description |
|---|---|---|
| `Kp` | `0.65` | Proportional gain |
| `Kd` | `0.5` | Derivative gain |
| Deadband | `±40 W` | Dead zone: ignores small errors |
| Rate limit | `±800 W/cycle` | Maximum change per cycle |

## Control cadence

The controller is **event-driven**: it recalculates the moment the grid consumption sensor publishes a new value, so it reacts at the sensor's native rate (often once per second) instead of waiting for a fixed timer tick.

A periodic **2-second watchdog** runs in parallel. While the sensor is updating normally it does almost nothing — the event has already handled the latest value. Its job is to keep the time-based subsystems running and to force a **safety recalculation if the sensor goes silent** (after ~30 s without updates the controller re-evaluates instead of holding the last command indefinitely).

Overlapping runs are prevented by a lock: if a cycle is still in progress when the next trigger fires, that trigger is skipped (the running cycle already reads the current state). This keeps the battery Modbus writes serialised.

## Stabilisation mechanisms

### Deadband (dead zone)

If the error is less than ±40 W, the controller does not adjust power. This prevents continuous micro-oscillations caused by sensor noise.

### Rate limiting

Power changes are limited per cycle to smooth transitions and protect the battery from abrupt changes. A "cycle" is one control update, driven by each new sensor value. The configured per-cycle limit is internally scaled by the real elapsed time between updates, so the effective ramp rate (W/s) stays constant regardless of how fast the sensor publishes. Lower the limit if the response feels abrupt.

### Oscillation detection

The controller monitors frequent direction reversals (charge↔discharge). If sustained oscillation is detected, the effective gain is temporarily reduced.

### Directional hysteresis

Prevents direction changes from momentary load variations (such as appliance start-ups). The controller requires the error to exceed a threshold for several cycles before switching from charging to discharging or vice versa.

### Derivative filtering

The derivative term is low-pass filtered (short time constant) before it reaches the output. Differentiating a barely-smoothed grid signal would otherwise amplify meter quantisation and inverter PWM noise and inject it into battery power; filtering keeps the derivative useful without that noise.

### Measured-power anti-windup

The controller assumes each battery delivers exactly the power it was commanded. When a battery cannot — for example because of SOC/voltage taper or ramp lag — the controller detects the sustained shortfall by comparing the command against the measured AC power, and re-anchors its internal baseline to reality. This prevents the control output from "winding up" past what the hardware actually delivered, which would otherwise cause an overshoot or a brief grid export when the load later drops.

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
