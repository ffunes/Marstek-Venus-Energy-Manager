# Hourly Net Balance

Tracks grid import and export within each civil hour and adjusts the PD setpoint in real time to drive the net energy toward a configurable target. The default target is 0 Wh — net zero each hour — but you can shift it to allow a fixed import or target a fixed export.

## How it works

Every PD cycle (~2.5 s) the manager:

1. Accumulates grid import and export for the current civil hour.
2. Computes the deficit versus the target: `deficit = target_net_Wh − (imp_Wh − exp_Wh)`.
3. Derives a power correction: `offset = deficit / remaining_hours`.
4. Applies a 5-minute ramp-in at the start of each hour to avoid aggressive early corrections.
5. Clamps the offset to the configured maximum.
6. Applies a configurable hysteresis (default 15 W): the offset only updates if it changes by more than this threshold (bypassed during the last 10 minutes of the hour so the hour closes cleanly).
7. Registers the offset via the setpoint registry so it composes cleanly with other features.

The offset is cleared automatically when:

- The current time is outside all configured [discharge time slots](../configuration/time-slots.md) (or 24/7 when no slots are defined).
- Manual mode is active.

## Data source

By default, the integration integrates the grid power sensor using the trapezoidal rule. If a sensor named `sensor.balance_neto` is present in Home Assistant, it is used instead. Detection is automatic:

| Sensor type | Unit | `state_class` | Method |
|---|---|---|---|
| Cumulative energy | kWh / Wh | `total` or `total_increasing` | Snapshot at hour start, delta per cycle |
| Instantaneous energy | kWh / Wh | `measurement` | Read directly |
| Power | W / kW | any | Trapezoidal integration |

If the external sensor becomes unavailable, the integration falls back to trapezoidal automatically. The active source is visible in the `source` attribute of the Balance Neto sensor.

The candidate list is defined in `const.py → EXTERNAL_NET_BALANCE_CANDIDATES`. Sign convention: **positive = net export to grid**.

## Priority and composition

The hourly balance offset is registered as an **additive offset** in the setpoint registry (key `hourly_balance`). It is summed with the user's target grid power preference and any other additive offsets. Capacity Protection uses an absolute override (priority 10) and takes full precedence when active.

## Compensation blocking

Certain conditions prevent the offset from being applied. The `charge_block_reason` attribute on the Balance Neto sensor shows why:

| Reason | What it means |
|---|---|
| `solar_charge_delay` | Solar charge delay is active — both import and export correction are blocked |
| `hysteresis` | Charge hysteresis is active — import correction only is blocked |
| `max_soc` | All batteries are at max SOC — import correction only is blocked |

When blocked, the accumulator continues tracking so the correct offset is applied as soon as the block lifts.

## Balance Neto sensor

A single diagnostic sensor (`sensor.*_balance_neto`) is created when the feature is enabled.

**State**: net kWh for the current hour (positive = net export, negative = net import).

**Attributes**:

| Attribute | Description |
|---|---|
| `status` | `idle`, `out_of_slot`, `capped`, `compensating_import`, `compensating_export`, `compensation_stopped` |
| `offset_w` | Active setpoint correction in watts |
| `imp_wh` | Grid import accumulated so far this hour |
| `exp_wh` | Grid export accumulated so far this hour |
| `target_net_wh` | Configured target in Wh |
| `remaining_min` | Minutes remaining in the current hour |
| `source` | Sensor entity ID used, or `trapezoidal` |
| `hour_iso` | ISO timestamp of the current hour start |
| `charge_block_reason` | Present only when compensation is blocked; contains the block reason |

## Configuration

Enable and configure from **Settings → Devices & Services → Marstek Venus Energy Manager → Configure → Hourly net balance**.

| Parameter | Default | Description |
|---|---|---|
| Target net balance (kWh) | `0.0` | Target net energy per hour. `0` = net zero. Positive = allow net import. Negative = target net export. |
| Maximum offset (W) | `1000` | Maximum power correction the controller can apply. |
| Net balance tolerance (kWh) | `0.0` | Deadband: no correction when the net balance is within ±N kWh of the target. `0` = exact correction. |
| Offset hysteresis (W) | `15` | Minimum offset change required before a new correction is applied. Prevents micro-adjustments every cycle. `0` = update every cycle. |

## Persistence

State is persisted to Home Assistant storage every ~5 minutes and on integration unload. On restart, the current-hour accumulators are restored only if the restart occurred within the same civil hour.
