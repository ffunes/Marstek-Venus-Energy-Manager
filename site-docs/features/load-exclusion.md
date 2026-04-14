# Load exclusion

See [Excluded devices](../configuration/excluded-devices.md) for configuration.

## How it works internally

When an excluded device is active, the controller subtracts its power from the grid consumption before computing the PD controller adjustment:

```
effective_consumption = grid_consumption - excluded_power
error = effective_consumption - target_grid_power
```

This causes the battery to "ignore" that load and not try to compensate it.

### If the device is NOT included in the main sensor

The integration **adds** the excluded device's power to the measured grid consumption (because the main sensor does not see it) and then subtracts it, resulting in the same net effective consumption.

## "Allow solar surplus" option

When active, if the system is operating on solar surplus (battery is charging from surplus), the exclusion does not apply to the charging side. In other words: the battery will not charge to compensate this device's consumption when solar surplus is already available.

This is the basis for **EV vs. battery charging priority**:

| Mode | Battery charges with solar? | Battery discharges for device? |
|---|---|---|
| Excluded, surplus OFF | Yes | No |
| Excluded, surplus ON | **No** — solar goes to device first | No |

### Solar Surplus switch (runtime control)

Each excluded device gets a dedicated **Solar Surplus** switch entity that toggles this behaviour at runtime without reconfiguring the integration. Use it in HA automations to change priority dynamically:

```yaml
# Example: prioritise EV when connected
automation:
  trigger:
    - platform: state
      entity_id: binary_sensor.ev_connected
      to: "on"
  action:
    - service: switch.turn_on
      target:
        entity_id: switch.solar_surplus_wallbox_power
```

![Excluded device power sensor in HA](../assets/screenshots/features/load-exclusion-entities.png){ width="700"  style="display: block; margin: 0 auto;"}

## EV charger without power telemetry

For EV chargers that only expose a state sensor (no real-time power reading), a dedicated **EV charger without power telemetry** option is available. Instead of reading watts, the controller monitors the sensor state and reacts to any charging string (`Charging`, `Cargando`, etc.).

| Phase | Battery behaviour |
|---|---|
| EV state → Charging (first 5 min) | 0 W — both charge and discharge blocked, PD state frozen |
| EV charging (after 5 min) | Charging from solar surplus allowed; discharge always blocked |
| EV state → anything else | Normal operation |

See [EV charger without power telemetry](../configuration/excluded-devices.md#ev-charger-without-power-telemetry) in the configuration reference for setup details.
