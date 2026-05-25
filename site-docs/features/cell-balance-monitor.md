# Cell balance monitor

Tracks the voltage spread between the highest and lowest cell at the top of a full charge. The reading is used to show whether the battery pack is staying balanced over time and to trigger imbalance alerts when the spread becomes high.

## Why this is needed on LFP batteries

Marstek Venus batteries use LFP cells. LFP is very stable and long-lived, but its voltage curve is almost flat through most of the usable SOC range. Around the middle of the charge, two cells can have noticeably different SOC while still reporting almost the same voltage. That makes mid-SOC voltage readings poor indicators of cell balance.

The useful balance window is near the top of charge. Above roughly 3.45 V per cell, the LFP voltage curve rises much faster, so differences between cells become visible. That is also the area where the battery BMS is expected to perform passive balancing by bleeding the highest cells.

In practice, the Marstek BMS does not always balance the cells well by itself. If the pack reaches 100% quickly and then immediately returns to normal operation, weak balancing can leave one cell consistently higher than the rest. This integration therefore does two things:

- it slows the final part of a 100% charge so the BMS has time to work in the top-balance window;
- it measures imbalance only at a repeatable top-voltage point, instead of using noisy mid-SOC readings.

## Availability

The cell balance monitor is always active. There is no separate configuration option because the readings are useful battery health data and do not change normal operation by themselves.

There are two related controls that decide when the battery is taken to the top-voltage measurement window:

- **100% charge voltage taper**: per battery option. When the charge target is 100%, the integration slows the final charge and records a top-voltage balance reading.
- **Active balance mode**: per battery switch. When enabled, the integration actively cycles that battery at the top until the measured cell delta is low enough.

The weekly full charge feature can temporarily set the battery max SOC to 100%. Once it does that, the same 100% charge voltage taper rules are used.

## 100% charge voltage taper

This path is used when a battery has a 100% charge target:

- the user configured that battery with `max_soc = 100`, or
- the weekly full charge temporarily raised the battery to 100%.

The weekly full charge does not use a different balance profile. It only changes the target SOC to 100%; voltage thresholds, charge power and measurement logic are the same.

### Charge profile

| Condition for one battery | Action |
|---|---:|
| `max_cell_voltage` below 3.48 V | Normal configured charge limit |
| `max_cell_voltage` at or above 3.48 V | Limit charge to 95 W |
| `max_cell_voltage` at or above 3.58 V | Stop charging and wait 60 s |
| After the 60 s wait | Record `delta_mV = (Vmax - Vmin) * 1000` |

The logic is voltage based. SOC is deliberately not used to decide when the top-voltage taper starts or stops, because SOC can be less reliable near the top than the cell-voltage registers.

There is no extra voltage hysteresis in this path. Once the battery reaches 3.58 V and the reading has been taken, the integration does not force a discharge. It leaves charging stopped at that voltage and lets the normal SOC/charge logic decide when future charging is allowed again.

In a multi-battery system, this is evaluated per battery. One battery can be limited or paused while another continues charging normally.

## Active balance mode

Active balance mode is a stronger per-battery recovery mode for packs that need more time in the balancing window.

When the switch is enabled, that battery is excluded from normal PD control. The rest of the batteries can continue to operate normally. The integration temporarily raises the battery charge target to 100% and commands charge directly for that battery.

### Active balance profile

| Phase | Action |
|---|---|
| Before the top window | Charge from the grid at the battery's configured maximum charge power until `max_cell_voltage >= 3.49 V` |
| Regulated top charge | Charge at 95 W until `max_cell_voltage >= 3.58 V` |
| Measurement wait | Stop charge/discharge, wait 60 s, then measure cell delta |
| If `delta_V > 0.03 V` | Discharge at 25 W until `max_cell_voltage <= 3.49 V`, then charge again |
| If `delta_V <= 0.03 V` | Final discharge at 25 W until `max_cell_voltage <= 3.48 V`, then finish and turn the switch off |

If the BMS accepts the charge command but does not actually charge before reaching 3.58 V, the integration treats that as charge rejection. It discharges first and lowers the retry voltage by 0.01 V, down to a minimum of 3.40 V, so the next cycle can restart from a point where the BMS is more likely to accept charge.

Active balance mode has no fixed 48-hour timeout. It runs until the measured top-voltage delta is at or below 0.03 V, or until the user turns the switch off.

## How imbalance is measured

The only reading that feeds the balance status, alerts and trend is the explicit top-voltage measurement:

1. the battery reaches `max_cell_voltage >= 3.58 V`;
2. charge is stopped;
3. the integration waits 60 seconds;
4. it records the spread between `max_cell_voltage` and `min_cell_voltage`.

Older OCV-style readings, opportunistic readings and long passive-hold readings are no longer used. Measuring at the same top-voltage point makes readings more comparable from one full charge to the next.

## Thresholds

| Status | Delta range | Meaning |
|---|---|---|
| Green | < 50 mV | Good balance |
| Yellow | 50-99 mV | Minor imbalance; monitor over time |
| Orange | 100-149 mV | Moderate imbalance |
| Red | >= 150 mV | High imbalance |

Thresholds are fixed and apply equally to all supported LFP packs.

## Notifications

The integration sends Home Assistant persistent notifications for these events:

| Event | Notification title |
|---|---|
| Orange or red top-voltage reading | Cell imbalance - `{battery name}` |
| Red on 2 or more consecutive full charges | Possible degraded cell - `{battery name}` |
| Rising trend with average above 75 mV | Rising imbalance trend - `{battery name}` |
| Active balance mode start/finish | Active balancing started/finished - `{battery name}` |

## Sensor entities

Five sensor entities are created per battery when the feature is enabled:

| Entity | Description | Unit |
|---|---|---|
| `sensor.*_cell_delta` | Voltage spread between max and min cell | mV |
| `sensor.*_balance_status` | Balance result: `green` / `yellow` / `orange` / `red` | - |
| `sensor.*_delta_trend` | Trend over recent readings: `rising` / `stable` / `falling` | - |
| `sensor.*_last_balance_read` | Timestamp of the last reading | timestamp |
| `sensor.*_delta_avg_4w` | Rolling average of the last 4 readings | mV |

Values are restored from persistent storage after a Home Assistant restart so sensors show the last known state immediately on startup.

## Diagnostics

The **Integration Status** sensor exposes a `normal_balance_protection` attribute with per-battery details:

| Attribute | Meaning |
|---|---|
| `enabled` | Whether 100% voltage taper is enabled for that battery |
| `in_zone` | Whether `max_cell_voltage` is in the top-balance window |
| `paused` | Whether charging is currently stopped by high cell voltage |
| `max_cell_voltage` / `min_cell_voltage` | Current cell voltage extremes |
| `delta_V` | Current voltage spread in volts |
| `voltage_taper_latched` | Whether the 95 W taper is currently active |
| `active_balance_phase` | Current 100% top-measurement phase, if any |
| `charge_limit_w` | Effective per-battery charge limit before allocation |

Active balance mode also exposes its current phase, measured delta, command power and retry voltage through the integration status diagnostics.

!!! info
    Cell voltage registers (`max_cell_voltage`, `min_cell_voltage`) are read from all supported battery versions (v2, v3, vA, vD).
