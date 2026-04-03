# Time slots

Time slots define windows during which the battery is **allowed to discharge**. Outside these windows, the battery only charges (or remains idle).

## When to use them

- Reserve energy for evening or overnight consumption peaks.
- Optimise tariff arbitrage (discharge during expensive hours, charge during cheap hours).
- Control discharge by day of the week.

---

## Configuring a time slot

| Field | Description |
|---|---|
| **Start / end time** | Slot window (e.g. `14:00` – `18:00`) |
| **Days** | Days of the week the slot applies to |
| **Apply to charging** | If enabled, the slot also restricts charging |
| **Target grid power** | Grid level the controller regulates toward during the slot |

### Target grid power

Default `0 W` (zero grid flow). Range: `-500 W` to `+500 W`.

| Value | Effect |
|---|---|
| `0 W` | Maximum self-consumption, no export |
| `< 0` (e.g. `-150 W`) | Maintains slight export (useful when feed-in tariff is profitable) |
| `> 0` (e.g. `+200 W`) | Allows slight import (reduces battery cycling) |

![Time slot configuration form](../assets/screenshots/configuration/time-slot-form.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Time slots and predictive charging

When predictive charging is active, the controller can use time slots as grid charging windows. See [Predictive charging – Time Slot mode](predictive-charging/time-slot.md) for details.
