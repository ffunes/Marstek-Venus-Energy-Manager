# Predictive charging — Time Slot mode

Charges from the grid during a **fixed time window** (typically cheap overnight tariff).

## Configuration

| Field | Description |
|---|---|
| **Time window** | Start and end of the charging slot (e.g. `02:00` – `05:00`) |
| **Solar forecast sensor** | Current-day production sensor in kWh (optional) |
| **Contracted grid power (ICP)** | Grid connection limit (W). Ensures charging + household load does not trip the main breaker |

!!! danger "Breaking change in v1.6.0"
    The solar forecast sensor field must now point to the **today** sensor (e.g. `sensor.solcast_pv_forecast_forecast_today`), not the tomorrow sensor.

!!! note "No solar sensor"
    If you have no solar panels, leave the forecast sensor empty. The system will charge whenever battery energy is insufficient to cover expected consumption.

![Configuration form — Time Slot mode](../../assets/screenshots/configuration/predictive-charging/time-slot-form.png){ width="650"  style="display: block; margin: 0 auto;"}

## Evaluation flow

1. **On slot entry**: batteries are held idle for 5 minutes to allow the solar forecast sensor time to update (particularly relevant when the slot starts at 00:00).
2. **5 minutes in**: the system evaluates the energy balance (`usable energy + solar forecast` vs. `estimated daily consumption`) and decides whether to charge.
3. A notification is sent with the decision.
4. Charging continues until the battery reaches the calculated level or the window ends.

## SOC-drop re-evaluation

If the SOC drops 30 % or more from the last evaluation point during the slot (e.g. due to high consumption), the system automatically re-evaluates the energy balance. No additional notification is sent for these mid-slot re-evaluations.
