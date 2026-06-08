# Time slots

Time slots define windows that control how each battery is allowed to operate. From version 2.0.0 every slot exposes independent ticks for charge and discharge, optional SOC and power overrides, a manual-power mode, and a per-battery scope. Up to 8 slots can be defined.

## Model: per-direction whitelist

Each direction (charge, discharge) is evaluated independently:

- If **no slot allows direction X** for a given battery, direction X is unrestricted (the rest of the controller, min/max SOC, EV pause, etc. still apply).
- If **at least one slot allows direction X**, then direction X is only permitted inside an active slot whose `allow_X=True`, day matches, and scope applies. Outside any such slot the direction is blocked.

This preserves the legacy behavior: the existing "no-discharge time slots" remain a discharge whitelist after migration, and the legacy `apply_to_charge` flag maps to `allow_charge=True`.

## Slot fields

| Field | Description |
|---|---|
| **Start / end time** | Window (e.g. `14:00` – `18:00`). Midnight crossing supported (`start > end` ⇒ window spans midnight). |
| **Days** | Days of the week the slot applies to. |
| **Battery scope** | `all` to apply to every battery, or `battery_N` to target one specifically. |
| **Allow charge** | Tick: charge is permitted inside the slot. Activates the charge whitelist if any slot in the system uses it. |
| **Allow discharge** | Tick: discharge is permitted inside the slot. Activates the discharge whitelist if any slot in the system uses it. |
| **SOC override (tick + `soc_min` / `soc_max`)** | When the tick is enabled the slot replaces the battery's max/min SOC inside the window. Clamped to `[12, 100]`. |
| **Power override (tick + `max_charge_power_w` / `max_discharge_power_w`)** | When the tick is enabled the slot caps the PD dynamic power or sets the exact manual power. |
| **Mode** | `pd`: the predictive algorithm regulates within the slot's caps. `manual`: the battery is forced to the configured power (one direction only). |

## Mode behavior

- **PD mode (default)**: the slot acts as a constraint. SOC and power overrides apply on top of the normal PD loop; the controller still reacts to grid/load.
- **Manual mode**: requires the power tick to be on and exactly one of `allow_charge` / `allow_discharge` enabled. The battery is forced to that exact power (force charge or force discharge) and is removed from PD allocation for the cycle. Safety blockers (min SOC, max SOC, EV pause, active balance) still stop the manual write.

## Battery scope

When more than one battery is configured each slot picks a target via `battery_scope`. Multiple slots with different scopes can overlap in time without conflict — they only conflict when both target the same physical battery (`battery_N` vs `battery_N`, or either set to `all`).

## Migration from earlier versions

Slots created before 2.0.0 (`{start_time, end_time, days, apply_to_charge}`) are converted automatically on first start:

| Legacy field | Migrated to |
|---|---|
| `apply_to_charge = False` | `allow_discharge = True`, `allow_charge = False`, scope `all`, mode `pd`, no overrides |
| `apply_to_charge = True` | `allow_discharge = True`, `allow_charge = True`, scope `all`, mode `pd`, no overrides |

Existing installations keep the exact previous behavior with no manual action required.

## Diagnostics

The `binary_sensor.predictive_charging_active` entity exposes two attributes that reflect the current cycle:

- `active_slot_per_battery`: dict (per battery name) with the currently active slot's start/end, scope, ticks, mode and override values.
- `manual_slot_owned`: list of battery names that a manual slot took over this cycle.

## Limits

- Maximum 8 slots per integration.
- SOC override is enforced by software; expect 1–3 control cycles of latency (a few seconds, at the grid sensor's cadence) before charge or discharge stops at the new limit.
- Slots that target a `battery_N` that no longer exists (e.g. the user reduced the battery count) become inert; remove or edit them from the options flow.

![Time slot configuration](../assets/screenshots/configuration/time-slot-form.png){ width="600"  style="display: block; margin: 0 auto;"}
