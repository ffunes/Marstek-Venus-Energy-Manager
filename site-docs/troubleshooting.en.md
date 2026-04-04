# Troubleshooting

## Marstek app compatibility

You do **not** need to make any changes in the Marstek app for the integration to work — including disabling the energy meter setting or changing any configuration. The integration works alongside the app without requiring any app-side adjustments.

However, **do not change any operating mode or setting from the Marstek app while the Home Assistant integration is running**. Doing so will break compatibility, and you will need to disable and re-enable the integration to restore normal operation.

---

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

## Metering device unavailable or losing connectivity

If the grid sensor (e.g. a power meter with a poor Wi-Fi connection) goes offline, the controller behaves differently depending on how the sensor fails.

### Sensor reports `unavailable` or `unknown`

The control loop exits immediately without sending any new command. The batteries **hold their last commanded power level** until the sensor comes back online.

### Sensor freezes (value stops updating)

The integration detects that the sensor's timestamp has not changed:

- For up to **15 cycles (~30 seconds)** it keeps the last command unchanged.
- After that grace period it performs a safety recalculation using the frozen value, with the derivative term suppressed to avoid power spikes.

### Summary

| Sensor state | Behaviour |
|---|---|
| `unavailable` / `unknown` | Control loop skips — batteries hold last power level |
| Frozen value (no new readings) | ~30 s grace period, then recalculates with stale value |

!!! warning "No automatic fallback to 0 W"
    If the meter goes unavailable while the battery was, for example, discharging at 2000 W, it will **continue discharging at 2000 W** until the meter recovers. There is no built-in timeout that ramps the battery to idle. Consider improving the Wi-Fi reliability of your metering device, or using a wired/Zigbee alternative if dropouts are frequent.

---

## Reporting an issue — Configuration Summary sensor

When opening a bug report or asking for help, it is useful to share the current integration configuration. The **Configuration Summary** sensor exposes the complete setup as entity attributes.

**How to enable it:**

1. Go to **Settings → Devices & Services → Marstek Venus Energy Manager**.
2. Select the **Marstek Venus System** device.
3. Find the **Configuration Summary** sensor (it is hidden by default) and enable it.
4. Open the sensor's detail card and share its attributes (state + attributes).

The sensor is read-only and diagnostic. It does not affect integration behaviour in any way.

---

## Debug logging

Enable `debug` for the integration by clicking in "Enable debug logging" button in the integration settings. Once you have run it for the appropriate time, disable it to avoid filling the logs, and a log file will be created with the debug information.
