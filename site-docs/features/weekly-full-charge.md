# Weekly full charge

Charges batteries to **100% once a week** to balance the cells and maintain battery health (cell balancing).

## Behaviour

1. On the configured day of the week, if the usual max SOC is below 100%, the integration temporarily raises the charging cutoff limit to 100%.
2. The battery charges until all available batteries reach 100% SOC or the BMS has clearly stopped charging near the top.
3. Once the top is reached, the integration starts active top-balancing instead of immediately reverting to the configured max SOC.
4. Active balancing uses the same per-battery cell-voltage profile documented in [Cell balance monitor](cell-balance-monitor.md): 90 W charge, 30 W hold charge and 30 W discharge micro-cycles.
5. The weekly run keeps active balancing for 4 hours.
6. After completion, the max SOC limit automatically reverts to the user's configured value.

If cell-voltage data is not available for a battery during the balancing phase, that battery is held at 0 W until the data returns or the 4-hour window finishes.

## Cell balance monitor

The weekly full charge configuration step includes an option to enable the **cell balance monitor**. When enabled, the integration measures the voltage spread between the strongest and weakest cell after each full charge to track battery health over time.

See [Cell balance monitor](cell-balance-monitor.md) for full details.

## Interaction with solar charge delay

If [solar charge delay](solar-charge-delay.md) is active, the weekly charge is postponed while the forecast solar production is sufficient to reach 100%. The battery only starts grid charging when the solar model determines that the sun will not complete the charge.

When the cell balance monitor is enabled, the solar charge delay is automatically bypassed on the weekly full charge day so the battery can reach the top and run the active-balancing phase before the OCV reading is taken.

## Modbus register involved

This feature manipulates register **44000** (charging cutoff) to temporarily raise the limit.

!!! info
    This feature is available for all supported battery versions (v2, v3, vA, vD).

![Weekly full charge configuration](../assets/screenshots/features/weekly-full-charge-config.png){ width="650"  style="display: block; margin: 0 auto;"}
