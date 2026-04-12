# Configuration

The integration is configured entirely from the Home Assistant UI through a multi-step wizard.

## Wizard steps

```mermaid
flowchart TD
    A[1. Main sensor] --> B[2. Number of batteries]
    B --> C[3. Per-battery config]
    C --> D{Time slots?}
    D -- Yes --> E[4. Time slots]
    D -- No --> F
    E --> F{Excluded devices?}
    F -- Yes --> G[5. Excluded devices]
    F -- No --> H
    G --> H{Predictive charging?}
    H -- Yes --> I[6. Predictive charging mode]
    H -- No --> J[Done]
    I --> J
```

| Step | Description | Required |
|------|-------------|:--------:|
| [Main sensor](main-sensor.md) | Grid consumption sensor and solar sensor | ✅ |
| Batteries | Number of units and per-battery configuration | ✅ |
| [Batteries](batteries.md) | IP, port, version, power limits and SOC | ✅ |
| [Time slots](time-slots.md) | Discharge windows with per-slot parameters | ❌ |
| [Excluded devices](excluded-devices.md) | Heavy loads to ignore | ❌ |
| [Predictive charging](predictive-charging/index.md) | Grid charging when solar forecast is insufficient | ❌ |
| [Advanced options](advanced.md) | Weekly charge, solar delay, peak shaving | ❌ |

## Modifying the configuration

Once installed, any parameter can be changed at:
**Settings → Devices & Services → Marstek Venus Energy Manager → Configure**
