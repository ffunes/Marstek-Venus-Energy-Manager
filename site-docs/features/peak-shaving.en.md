# Peak shaving

Reserves a portion of battery capacity to cover demand spikes that exceed a configurable power threshold. Instead of the battery covering all household consumption, it holds back energy and only discharges to compensate the portion of demand above the peak limit — keeping capacity in reserve for when it is actually needed.

## Behaviour without peak shaving

The PD controller covers all household consumption → the battery can fully discharge if consumption is high and sustained.

## Behaviour with peak shaving active

When SOC is below the threshold:
- The battery does **not** cover all consumption.
- It only discharges to compensate the portion of consumption that exceeds the configured **peak power limit**.

```
battery_power = max(0, grid_consumption - peak_limit)
```

## Example

```
Peak limit: 3,000 W
Current consumption: 4,500 W

Battery power = 4,500 - 3,000 = 1,500 W
Grid covers 3,000 W and the battery only 1,500 W
```

If consumption were 2,000 W (< limit), the battery would not discharge at all.

## When to use it

Useful when:
- The grid has a fixed cost per maximum contracted power and you want to limit peaks.
- You want to ensure battery reserve for the night.

![Peak shaving configuration](../assets/screenshots/features/peak-shaving-config.png){ width="650"  style="display: block; margin: 0 auto;"}
