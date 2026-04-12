# Battery configuration

## Number of batteries

Select how many Marstek Venus units you have (1–6). The integration will ask you to configure each one separately.

![Number of Batteries slider](../assets/screenshots/configuration/battery-slider.png){ width="650"  style="display: block; margin: 0 auto;"}

---


## Per-battery parameters

| Parameter | Description | Default |
|---|---|---|
| **Name** | Unique identifier (e.g. "Venus 1") | — |
| **Host** | IP address of the Modbus TCP converter | — |
| **Port** | Modbus TCP port | `502` |
| **Version** | Battery model | — |
| **Max charge/discharge power** | Rated power of your setup | — |
| **Max SOC** | Stop charging at this percentage | `100 %` |
| **Min SOC** | Stop discharging at this percentage | `12 %` |
| **Charge hysteresis** | Margin to avoid rapid cycling near the charge limit | — |
| **Backup offgrid threshold** | Minimum offgrid load (W) to be considered an active backup event | `50 W` |

### Battery versions

| Version | Models |
|---|---|
| `v1/v2` | Venus E v1, Venus E v2 |
| `v3` | Venus E v3 |
| `vA` | Venus A |
| `vD` | Venus D |

!!! warning "Maximum power 2500 W"
    Only use **2500 W** mode if you are certain your domestic installation can safely handle that power level.

![Battery connection form](../assets/screenshots/configuration/battery-connection-form.png){ width="650"  style="display: block; margin: 0 auto;"}

![Battery configuration form](../assets/screenshots/configuration/battery-config-form.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## SOC and power limits at runtime

Max/min SOC and max charge/discharge power values can be adjusted at any time using the integration's sliders without reconfiguring. Changes are persisted and restored on every Home Assistant restart.

![SOC and power sliders](../assets/screenshots/configuration/battery-runtime-sliders.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Backup offgrid threshold at runtime

The **Backup Offgrid Threshold** number entity (visible on each battery's device card, under configuration entities) lets you adjust the threshold at any time without entering the options flow. Raise it if your battery has small permanent loads on its offgrid port — such as a PoE switch, router, or IP cameras — that would otherwise keep it permanently excluded from PD control.

| Load scenario | Recommended threshold |
|---|---|
| No permanent offgrid loads | `0 W` (any load triggers exclusion) |
| Small standby loads (router + switch, ~20–40 W) | `50 W` (default) |
| Heavier permanent loads (NAS, AP, cameras, ~80–120 W) | `150 W` |

!!! tip "How it works"
    When the **Backup Function** switch is ON and the measured offgrid load is **above** the threshold, the battery is excluded from PD control and manages itself autonomously. A 5-minute cooldown applies after the load drops back below the threshold, to avoid sending commands immediately after a backup event ends.

