# Cell balance monitor

Tracks the voltage spread between the strongest and weakest battery cell after each weekly full charge, giving you a long-term picture of how well your battery cells are staying in balance.

## How to enable

The balance monitor is enabled in the **Weekly full charge** configuration step (initial wizard or options flow). Enabling it also bypasses the solar charge delay on the weekly full charge day so the battery can reach the top, run active balancing, and then take the formal OCV reading.

## How it works

### Normal high-SOC charge protection

This protection is always active during automatic charging. It is not an active
recovery mode and it does not force the battery to charge. It only limits or
pauses charging when a battery is already near the top of its SOC/voltage range,
so normal daily operation does not make cell imbalance worse.

The logic is evaluated per battery. In a multi-battery system, one battery can be
paused or tapered while another battery continues charging normally.

#### Charge power limits

| Condition for one battery | Maximum charge allocation for that battery |
|---|---:|
| SOC below 95 % and `max_cell_voltage` below 3.45 V | Normal configured limit |
| SOC at or above 95 % | 200 W |
| SOC at or above 98 % | 90 W |
| `max_cell_voltage` at or above 3.45 V | 90 W |
| `max_cell_voltage` at or above 3.60 V | Charging paused |

The effective limit is the most restrictive matching rule. For example, at
96 % SOC the limit is normally 200 W, but if the highest cell has already
reached 3.45 V the limit becomes 90 W.

#### Voltage taper latch

When `max_cell_voltage` reaches 3.45 V, the battery enters the 90 W voltage
taper. This taper is latched while the battery remains in the high-SOC/top
balancing zone, so the charge power does not jump back up just because the cell
voltage briefly settles below 3.45 V.

The latch is cleared only after the battery leaves the top-balancing zone:

- SOC falls below 95 %, and
- `max_cell_voltage` is below 3.45 V.

#### Pause and resume behavior

If `max_cell_voltage` reaches 3.60 V, charging is paused for that battery. This
is a per-battery charge block, so the controller writes 0 W charge to that unit
while still allowing other eligible batteries to charge.

Charging resumes only when `max_cell_voltage` settles back to 3.50 V or below.
After resuming, the battery remains in the latched 90 W voltage taper while it
is still in the high-SOC/top-balancing zone.

This normal protection path does not force a discharge to lower the cell
voltage. It waits for the voltage to settle naturally. Controlled discharge is
used only by the active top-balancing profile described below.

#### Daily high-SOC exposure limit

For each battery, the controller tracks how long it has spent in the
top-balancing zone during the current day. The zone is counted when either of
these is true:

- SOC is at or above 95 %, or
- `max_cell_voltage` is at or above 3.45 V.

After 4 hours in that zone on the same day, normal automatic charging is no
longer extended for that battery. This prevents normal use from keeping a
battery at high SOC for too long.

The daily limit does not block the weekly/manual full-charge balancing path once
that path has explicitly unlocked charging to 100 %. It also does not block the
active top-balancing profile when the user intentionally sets a battery's normal
max SOC to 100 %. It is meant to protect normal operation, not to prevent an
intentional full-charge balancing run.

### Active top-balancing profile

Active top-balancing is used in two situations:

- **Normal max SOC set to 100 %**: per battery, when that battery reaches 100 %
  or confirmed BMS cutoff near the top.
- **Weekly full charge day or manual full-charge trigger**: globally, after all
  participating batteries have reached 100 % or confirmed BMS cutoff near the top.
- **Scheduled 48-hour active balance mode**: per battery, when the per-battery
  switch is enabled and the selected weekday arrives.

Once active, the controller uses `max_cell_voltage` to keep cells in the
top-balancing window:

| Condition for one battery | Command |
|---|---:|
| `max_cell_voltage <= 3.45 V` | Enter 90 W charge |
| During 90 W charge, until `max_cell_voltage >= 3.53 V` | Continue 90 W charge |
| `3.53 V <= max_cell_voltage < 3.59 V` | Hold charge at 30 W |
| Lost/idle phase, full SOC, inverter standby, near-zero real power and `max_cell_voltage > 3.45 V` | Discharge at 30 W |
| High SOC, active charge/hold, inverter standby and near-zero real power from `max_cell_voltage >= 3.58 V` | Discharge at 30 W |
| `max_cell_voltage >= 3.62 V` | Discharge at 30 W as a safety limit |
| During discharge, until `max_cell_voltage <= 3.45 V` | Continue 30 W discharge |

The 3.45/3.53 V split is intentional: after a balancing discharge, the
controller does not request charge again until the highest cell has fallen to
3.45 V, avoiding a premature retry while the BMS still considers the battery
full. After an integration reload or restart, the scheduled mode restores the
last persisted per-battery phase (`CHARGE`, `HOLD` or `DISCHARGE`). If no phase
was persisted and the controller is left idling, it reconstructs discharge when
it sees full SOC, standby, near-zero real power and `max_cell_voltage` still
above 3.45 V. This recovery path does not apply during an active charge phase.
Once 90 W charge starts, it continues until 3.53 V and then falls back to 30 W hold charge.
`3.62 V` remains the hard safety limit for batteries that can reach it. If the
BMS stops accepting charge while the controller is charging or holding charge at
high SOC and the inverter goes to standby, the controller treats that as a
signal to discharge and start a new micro-cycle even before the highest cell
reaches `3.62 V`.

The normal `max_soc=100 %` case keeps running while the battery remains
configured to 100 % and no higher-priority mode takes over. When solar charge
delay is enabled, it exits per battery once the PD input detects household/grid
demand above the active target plus deadband, so normal PD control can serve the
house.

It also exits or pauses per battery when:

- cell-voltage data is no longer available,
- the battery no longer has `max_soc` set to 100 %,
- the battery no longer has valid data,
- a weekly/manual full-charge run starts, which takes priority.

The weekly/manual full-charge case exits globally after 4 hours of active
balancing. If cell-voltage data is unavailable for a battery during this phase,
that battery is held at 0 W until the data returns or the 4-hour window finishes.

#### Scheduled 48-hour balance mode

Each battery exposes:

- a switch to enable or disable the scheduled active balance mode,
- a day selector that chooses when the 48-hour run starts.

When the selected day arrives, that battery is reserved by the balance mode and
is excluded from normal PD allocation. Other batteries can still be used by the
PD controller. The mode uses the same 90/30/30 W profile as weekly full charge
balancing and exits when either:

- the cell delta falls to the reasonable range (`delta_mV <= 50`), or
- 48 hours have elapsed.

Changing the selected day clears the "completed today" marker so a newly
selected day can run again. Disabling the switch stops the current run without
marking it complete.

#### Diagnostics

The **Integration Status** sensor exposes a `normal_balance_protection`
attribute with per-battery details:

| Attribute | Meaning |
|---|---|
| `in_zone` | Whether the battery is currently in the top-balancing zone |
| `exposure_h` | Hours spent in that zone today |
| `daily_limit_h` | Current daily exposure limit, normally 4 h |
| `paused` | Whether charging is currently paused by high cell voltage |
| `max_cell_voltage` / `min_cell_voltage` | Current cell voltage extremes |
| `delta_mV` | Current voltage spread between highest and lowest cell |
| `voltage_taper_latched` | Whether the 90 W voltage taper is latched |
| `active_balance_phase` | Current normal `max_soc=100 %` active-balancing phase, if any |
| `charge_limit_w` | Effective per-battery charge limit before allocation |

### OCV reading sequence (weekly full charge day)

After the weekly full charge has completed its active top-balancing phase, the
cell balance monitor can still take the formal OCV reading used for long-term
health tracking. At that point the integration:

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
