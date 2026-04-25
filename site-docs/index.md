# Marstek Venus Energy Manager

**Marstek Venus Energy Manager** is a custom Home Assistant integration to monitor and control Marstek Venus batteries (E v2/v3, Venus A and Venus D series) via Modbus TCP.
**Marstek Venus Energy Manager** is a custom Home Assistant integration to monitor and control Marstek Venus batteries (E v2/v3, Venus A and Venus D series) via Modbus TCP.

<div class="grid cards" markdown>

-   :material-battery-charging: **Dynamic power control**
-   :material-battery-charging: **Dynamic power control**

    PD controller that keeps grid flow near zero to maximise self-consumption.
    PD controller that keeps grid flow near zero to maximise self-consumption.

-   :material-calendar-clock: **Predictive charging**
-   :material-calendar-clock: **Predictive charging**

    Automatic grid charging when the solar forecast falls short of expected consumption.
    Automatic grid charging when the solar forecast falls short of expected consumption.

-   :material-battery-sync: **Multi-battery**
-   :material-battery-sync: **Multi-battery**

    Intelligent management of up to 6 batteries with optimal power distribution.
    Intelligent management of up to 6 batteries with optimal power distribution.

-   :material-tune: **Highly configurable**
-   :material-tune: **Highly configurable**

    Time slots, excluded devices, peak shaving, weekly full charge and more.
    Time slots, excluded devices, peak shaving, weekly full charge and more.

</div>

## Key features
## Key features

- **PD Controller (Zero Export/Import)**: adjusts battery power in real time to keep grid exchange close to zero.
- **Predictive charging**: three modes (time slot, dynamic pricing, real-time price) that charge from the grid only when the energy balance requires it. Uses a 7-day rolling average of real household consumption to decide whether grid charging is needed.
- **Multi-battery management**: smart selection with SOC priorities, energy hysteresis and efficiency zone operation.
- **Discharge time slots**: define time windows and per-slot target grid power levels.
- **Peak shaving**: reserves battery capacity to cover demand spikes above a configurable power threshold.
- **Weekly full charge**: charges to 100% once a week for cell balancing.
- **Cell balance monitor**: measures the voltage spread between the strongest and weakest cell after each full charge; tracks imbalance trends over time, sends alerts for moderate or high imbalance, and blocks discharge during the open-circuit voltage rest period.
- **Solar charge delay**: postpones morning battery charging (both solar and grid) while expected solar production is enough to cover the remaining energy needed.
- **Load exclusion**: exclude high-power devices (e.g. EV chargers) so the controller does not try to compensate their consumption.
- **Proactive alarm notifications (v2 batteries only)**: monitors battery fault and alarm registers every 5 seconds and sends a Home Assistant notification the moment a new condition is detected, with the exact fault or alarm name. A system-level `System Alarm Status` sensor (`OK` / `Warning` / `Fault`) provides an at-a-glance view across all batteries.

## Disclaimer
## Disclaimer

!!! danger "Liability disclaimer"
    This software is provided "as is", without warranty of any kind. Use is at your own risk. The developer assumes no responsibility for damage to batteries, inverters, electrical installations, financial losses or personal injury.
!!! danger "Liability disclaimer"
    This software is provided "as is", without warranty of any kind. Use is at your own risk. The developer assumes no responsibility for damage to batteries, inverters, electrical installations, financial losses or personal injury.

    **If you do not agree to these terms, DO NOT install or use this integration.**
    **If you do not agree to these terms, DO NOT install or use this integration.**

## Support

If you find this integration useful, you can support the project:

<a href="https://buymeacoffee.com/ffunes" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="40" width="145"></a>
