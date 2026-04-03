# Predictive charging — Time Slot mode

Charges from the grid during a **fixed time window** (typically cheap overnight tariff).

## Configuration

| Field | Description |
|---|---|
| **Time window** | Start and end of the charging slot (e.g. `02:00` – `05:00`) |
| **Solar forecast sensor** | Next-day production sensor in kWh (optional) |
| **Contracted grid power (ICP)** | Grid connection limit (W). Ensures charging + household load does not trip the main breaker |

!!! note "No solar sensor"
    If you have no solar panels, leave the forecast sensor empty. The system will charge whenever battery energy is insufficient to cover expected consumption.

![Configuration form — Time Slot mode](../../assets/screenshots/configuration/predictive-charging/time-slot-form.png){ width="650"  style="display: block; margin: 0 auto;"}

## Evaluation flow

1. **1 hour before** the slot starts: preliminary evaluation with notification.
2. **When the slot starts**: final confirmation and charging begins.
3. Charging continues until the battery reaches the calculated level or the window ends.

## Mid-day re-evaluation

When multiple cheap slots are selected, the system re-evaluates **1 hour before each slot** whether charging is still needed. If the battery already has enough energy (solar + current SOC covers consumption), the slot is silently skipped.
