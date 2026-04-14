# Multi-battery management

The integration manages up to **6 batteries** as an aggregated system, distributing power intelligently to maximise efficiency.

## Efficiency principle

Based on the Venus efficiency curve (peak ~91% between 1000–1500 W), batteries are activated only when total power exceeds **60% of combined capacity**. Running fewer batteries at higher power is more efficient than spreading the same load across all of them.

The following measurements show DC power consumption/output, AC power at the meter (internal clamp) and at the wall outlet (external clamp), and the resulting efficiency at each power level:

**Charging**

| % of max | Setpoint (W) | DC internal (W) | AC internal (W) | AC external (W) | η internal | η external |
|---:|---:|---:|---:|---:|---:|---:|
| 3 % | 63 | 41 | 58 | 68 | 70.7 % | 60.3 % |
| 5 % | 125 | 105 | 123 | 136 | 85.4 % | 77.2 % |
| 10 % | 250 | 232 | 247 | 262 | 93.9 % | 88.5 % |
| 15 % | 375 | 357 | 372 | 387 | 96.0 % | 92.2 % |
| 20 % | 500 | 481 | 497 | 513 | 96.8 % | 93.8 % |
| 25 % | 625 | 604 | 621 | 639 | 97.3 % | 94.5 % |
| 30 % | 750 | 727 | 743 | 766 | 97.8 % | 94.9 % |
| 35 % | 875 | 850 | 871 | 892 | 97.6 % | 95.3 % |
| 40 % | 1000 | 973 | 995 | 1019 | 97.8 % | 95.5 % |
| 45 % | 1125 | 1095 | 1120 | 1146 | 97.8 % | 95.5 % |
| 50 % | 1250 | 1245 | 1271 | 1274 | 98.0 % | 97.7 % |
| 55 % | 1375 | 1339 | 1369 | 1401 | 97.8 % | 95.6 % |
| 60 % | 1500 | 1460 | 1494 | 1530 | 97.7 % | 95.4 % |
| 65 % | 1625 | 1581 | 1618 | 1658 | 97.7 % | 95.4 % |
| 70 % | 1750 | 1702 | 1743 | 1786 | 97.6 % | 95.3 % |
| 75 % | 1875 | 1823 | 1868 | 1916 | 97.6 % | 95.1 % |
| 80 % | 2000 | 1942 | 1992 | 2044 | 97.5 % | 95.0 % |
| 85 % | 2125 | 2062 | 2117 | 2175 | 97.4 % | 94.8 % |
| 90 % | 2250 | 2183 | 2242 | 2304 | 97.4 % | 94.7 % |
| 95 % | 2375 | 2304 | 2366 | 2436 | 97.4 % | 94.6 % |
| 100 % | 2500 | 2424 | 2491 | 2567 | 97.3 % | 94.4 % |

**Discharging**

| % of max | Setpoint (W) | DC internal (W) | AC internal (W) | AC external (W) | η internal | η external |
|---:|---:|---:|---:|---:|---:|---:|
| 3 % | 63 | 80 | 63 | 60 | 78.8 % | 75.0 % |
| 5 % | 125 | 160 | 124 | 118 | 77.5 % | 73.8 % |
| 10 % | 250 | 284 | 249 | 243 | 87.7 % | 85.6 % |
| 15 % | 375 | 416 | 373 | 368 | 89.7 % | 88.5 % |
| 20 % | 500 | 550 | 498 | 494 | 90.5 % | 89.8 % |
| 25 % | 625 | 685 | 623 | 619 | 90.9 % | 90.4 % |
| 30 % | 750 | 820 | 747 | 745 | 91.1 % | 90.9 % |
| 35 % | 875 | 956 | 872 | 870 | 91.2 % | 91.0 % |
| 40 % | 1000 | 1092 | 997 | 996 | 91.3 % | 91.2 % |
| 45 % | 1125 | 1230 | 1121 | 1121 | 91.1 % | 91.1 % |
| 50 % | 1250 | 1369 | 1246 | 1246 | 91.0 % | 91.0 % |
| 55 % | 1375 | 1507 | 1370 | 1372 | 90.9 % | 91.0 % |
| 60 % | 1500 | 1647 | 1495 | 1497 | 90.8 % | 90.9 % |
| 65 % | 1625 | 1789 | 1620 | 1623 | 90.6 % | 90.7 % |
| 70 % | 1750 | 1931 | 1745 | 1748 | 90.4 % | 90.5 % |
| 75 % | 1875 | 2073 | 1869 | 1874 | 90.2 % | 90.4 % |
| 80 % | 2000 | 2218 | 1994 | 1999 | 89.9 % | 90.1 % |
| 85 % | 2125 | 2362 | 2118 | 2124 | 89.7 % | 89.9 % |
| 90 % | 2250 | 2508 | 2243 | 2250 | 89.4 % | 89.7 % |
| 95 % | 2375 | 2654 | 2368 | 2375 | 89.2 % | 89.5 % |
| 100 % | 2500 | 2801 | 2492 | 2501 | 89.0 % | 89.3 % |

## Selection priorities

### Discharge

**Highest SOC first**: the most charged battery discharges first to balance the state of charge across the system.

### Charging

**Lowest SOC first**: the least charged battery receives energy first.

## Hysteresis

To avoid "ping-pong" activation/deactivation, three hysteresis levels are applied:

| Hysteresis | Value | Description |
|---|---|---|
| **SOC** | 5 % | An active battery stays active until another exceeds it by 5% SOC |
| **Lifetime energy** | 2.5 kWh | Breaks SOC ties using accumulated lifetime energy with an advantage for the active battery |
| **Power** | ±100 W | Activates the 2nd battery at 60% of combined capacity; deactivates at 50% |

## Power distribution

Once active batteries are selected, the total power calculated by the [PD controller](pd-controller.md) is distributed among them proportionally, respecting each battery's individual power and SOC limits.

## Compatible modes

Multi-battery distribution applies in all modes:
- Normal PD control
- Solar charging
- Predictive grid charging

![Multi-battery state in Home Assistant](../assets/screenshots/features/multi-battery-entities.png){ width="700"  style="display: block; margin: 0 auto;"}
