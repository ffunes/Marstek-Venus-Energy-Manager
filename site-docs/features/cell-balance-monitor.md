# Cell balance monitor

Tracks the voltage spread between the strongest and weakest battery cell after each weekly full charge, giving you a long-term picture of how well your battery cells are staying in balance.

## How to enable

The balance monitor is enabled in the **Weekly full charge** configuration step (initial wizard or options flow). Enabling it also bypasses the solar charge delay on the weekly full charge day, keeping the battery in float while solar is available — maximising the time available for passive cell balancing.

## How it works

### OCV reading sequence (weekly full charge day)

When the battery reaches 100 % SOC on the weekly full charge day, the integration:

1. **Holds discharge** — prevents the battery from discharging so the cells can rest under no-load conditions.
2. **Waits 15 minutes** — allows BMS active balancing to settle and surface voltages to stabilise.
3. **Checks stability** — requires at least 5 consecutive polls with power below 50 W and voltage change below 5 mV between polls.
4. **Takes the reading** — records `delta_mV = (Vmax − Vmin) × 1000`.
5. **Releases discharge** — unless the result is orange (see thresholds below).

### Orange hold (2.5-hour passive balancing)

If the reading lands in the orange zone (100–149 mV), discharge remains blocked for 2.5 hours to let passive balancing work. After the hold period a follow-up reading is taken and discharge is released regardless of the result.

### Opportunistic readings

On days other than the weekly full charge day, if the battery is already at 100 % SOC and power is already below 50 W, the integration takes a lightweight reading without blocking discharge. Limited to once every 24 hours.

## Thresholds

| Status | Delta range | Meaning |
|---|---|---|
| 🟢 Green | < 50 mV | Good balance |
| 🟡 Yellow | 50 – 99 mV | Minor imbalance — monitor over time |
| 🟠 Orange | 100 – 149 mV | Moderate imbalance — 2.5 h passive balancing hold initiated |
| 🔴 Red | ≥ 150 mV | High imbalance |

Thresholds are fixed and apply equally to all LFP cell chemistries.

## Notifications

The integration sends Home Assistant persistent notifications for the following events:

| Event | Notification title |
|---|---|
| Orange or red reading | ⚠️ Cell imbalance — {battery name} |
| Orange persists after 2.5 h hold | ⚠️ Cell imbalance persists — {battery name} |
| Red on 2 or more consecutive charges | 🔴 Possible degraded cell — {battery name} |
| Rising trend with average above 75 mV | 📈 Rising imbalance trend — {battery name} |

## Sensor entities

Five sensor entities are created per battery when the feature is enabled:

| Entity | Description | Unit |
|---|---|---|
| `sensor.*_cell_delta` | Voltage spread between max and min cell | mV |
| `sensor.*_balance_status` | Balance result: `green` / `yellow` / `orange` / `red` | — |
| `sensor.*_delta_trend` | Trend over the last formal readings: `rising` / `stable` / `falling` | — |
| `sensor.*_last_balance_read` | Timestamp of the last reading | timestamp |
| `sensor.*_delta_avg_4w` | Rolling average of the last 4 formal readings | mV |

Values are restored from persistent storage after a Home Assistant restart so sensors show the last known state immediately on startup.

## Technical notes

- The voltage spike visible at 100 % SOC (before the wait period) is normal BMS active balancing behaviour — not a real imbalance. The 15-minute wait ensures the reading is taken at true open-circuit voltage.
- Up to 52 readings are stored per battery (approximately one year of weekly charges).
- The 4-week average and trend are calculated from formal readings only (not opportunistic), so they reflect the pattern at true open-circuit voltage.

!!! info
    Cell voltage registers (`max_cell_voltage`, `min_cell_voltage`) are read from all supported battery versions (v2, v3, vA, vD).
