# Weekly full charge

Charges batteries to **100% once a week** so the pack reaches the LFP top-balancing window and the integration can measure cell imbalance under repeatable conditions.

## Behaviour

1. On the configured day of the week, if the usual max SOC is below 100%, the integration temporarily raises the battery charge cutoff to 100%.
2. The battery charges until the top-voltage taper takes over.
3. From `max_cell_voltage >= 3.48 V`, charge is limited to 95 W.
4. At `max_cell_voltage >= 3.58 V`, charging stops and the integration waits 60 seconds.
5. After the wait, the cell balance monitor records `delta_mV = (Vmax - Vmin) * 1000`.
6. After completion, the max SOC limit automatically reverts to the user's configured value.

The weekly full charge uses the same voltage profile as a normal battery configured with `max_soc = 100`. The weekly feature only raises the target to 100%; it does not use a separate balancing algorithm.

## Cell balance monitor

The **cell balance monitor** is always active. It records the voltage spread between the highest and lowest cell after each top-voltage measurement and keeps the sensor history, trend and alerts updated.

See [Cell balance monitor](cell-balance-monitor.md) for full details.

## Interaction with solar charge delay

If [solar charge delay](solar-charge-delay.md) is active, the weekly charge can be postponed while the forecast solar production is sufficient to reach 100%.

When the weekly full charge is active, the integration can bypass the delay so the battery reaches the top-voltage measurement point and the balance reading is not skipped.

## Modbus register involved

This feature manipulates register **44000** (charging cutoff) to temporarily raise the limit.

!!! info
    This feature is available for all supported battery versions (v2, v3, vA, vD).

![Weekly full charge configuration](../assets/screenshots/features/weekly-full-charge-config.png){ width="650"  style="display: block; margin: 0 auto;"}
