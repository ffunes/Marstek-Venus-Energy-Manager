# Troubleshooting

## Battery does not respond to commands

1. Verify that the Modbus TCP converter (Elfin-EW11 or similar) is reachable by IP from Home Assistant.
2. Check that the configured port is correct (default `502`).
3. Make sure the **RS485 Control Mode** switch is enabled.
4. Ensure the configured battery version matches the actual hardware.

!!! note "Delay for v3/vA/vD"
    v3, vA and vD batteries require at least 150 ms between consecutive Modbus messages. The integration applies this automatically based on the configured version.

---

## PD controller oscillates

The system continuously switches between charging and discharging.

**Possible causes and solutions:**

| Cause | Solution |
|---|---|
| Deadband too small | The default ±40 W is appropriate for most installations |
| Grid sensor with high latency | Use a sensor with frequent updates (1–2 s) |
| Loads with sudden start-up | Configure the load as an [excluded device](configuration/excluded-devices.md) |

---

## SOC/power values are not persisted after HA restart

Fixed since v1.5.0. Changes to SOC and power sliders are saved immediately to the config entry and restored on every restart.

If the problem persists, verify you are using version **1.5.0** or later.

---

## Predictive charging does not activate

1. Verify that the solar forecast sensor is available and has a value.
2. Check the `price_data_status` attribute of the `predictive_charging_active` sensor (Dynamic Pricing mode).
3. Review HA notifications: the 00:05 evaluation reports its result.
4. Make sure the energy balance actually requires charging (there may already be enough energy).

---

## RS485 switch re-enables itself after restart

Fixed in v1.5.0. The user's preference is now persisted and restored at startup.

---

## Debug logging

Enable `debug` for the integration by clicking in "Enable debug logging" button in the integration settings. Once you have run it for the appropriate time, disable it to avoid filling the logs, and a log file will be created with the debug information.
