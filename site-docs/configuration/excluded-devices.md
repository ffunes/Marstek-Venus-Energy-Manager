# Excluded devices

Allows you to "mask" heavy loads so the battery does not try to cover them.

## Typical use case

If you have a 7 kW EV charger and a 2.5 kW battery, without exclusion the battery will try to compensate the full charger load and drain quickly. With exclusion active, the controller ignores that power and the battery only manages the rest of the household.

---

## Configuring an excluded device

| Field | Description |
|---|---|
| **Device sensor** | HA entity measuring the device's power (e.g. `sensor.wallbox_power`), or a state sensor for EV chargers without power telemetry. |
| **Included in consumption** | Check if your main sensor **already** includes this load |
| **Allow solar surplus** | If enabled, the battery will not charge to compensate this device when there is a solar surplus. Can also be toggled at runtime via a switch entity (see below). |
| **EV charger without power telemetry** | Check if the sensor is a state sensor that reads `Charging` (or a localised equivalent) instead of a watt value. See [EV charger without power telemetry](#ev-charger-without-power-telemetry) below. |

### Included in consumption?

```
Main sensor reads: whole house
EV charger is part of "whole house" → ✅ Included in consumption

Main sensor reads: only domestic circuit
EV charger is on a separate circuit → ❌ Not included in consumption
```

The integration uses this setting to correctly calculate the net consumption without the excluded device.

![Excluded device form](../assets/screenshots/configuration/excluded-device-form.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Solar Surplus switch

For each excluded device a **Solar Surplus** switch entity is automatically created (`Solar Surplus – <device name>`). It mirrors the *Allow solar surplus* setting and can be toggled at any time without entering the options flow.

This makes it possible to change the charging priority from automations — for example:

- Turn ON when the EV is connected, so solar charges the car first.
- Turn OFF at a scheduled time to let the battery capture morning surplus.
- React to battery SOC: turn ON above 80 %, turn OFF below 50 %.

The switch state is persisted in the config entry and survives restarts.

---

## EV charger without power telemetry

Some EV charger integrations do not expose a real-time power sensor — they only report a **charging state** (e.g. `Charging`, `Idle`, `Disconnected`). This option is designed for those chargers.

When enabled, the **Device sensor** field must point to the state entity, not a power sensor. The controller recognises any state that contains `charg` or `cargand` (case-insensitive), covering:

- `Charging` (most English-language integrations)
- `Cargando`, `Cargando VE`, `Cargando Vehículo` (Spanish)

### Behaviour when the EV starts charging

```
t = 0  EV state → "Charging" detected
       Battery immediately set to 0 W (charge AND discharge blocked)
       PD state frozen

t = 5 min  Pause expires
           Battery may charge from solar surplus
           Battery discharge remains permanently blocked while EV is charging

t = N  EV state → any other value (Idle / Disconnected / …)
       Normal operation resumes
```

### Why the 5-minute pause?

When an EV charger activates it negotiates the available current with the car over a brief handshake. Any battery discharge during this window can temporarily reduce the apparent grid capacity, causing the charger to settle at a lower current. The pause gives the handshake time to complete before the battery does anything.

### Comparison with the standard Solar Surplus option

| | Standard exclusion + Solar Surplus | EV without telemetry |
|---|---|---|
| Needs a power sensor | Yes | No |
| Battery discharges for EV | Never | Never |
| Battery charges from solar when EV charges | Yes | Yes (after 5-min pause) |
| Initial 5-min pause | No | Yes |
| Reacts to EV state changes | No | Yes (automatic) |
