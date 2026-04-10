# Changelog

## [1.6.1] - 2026-04-10

### Changed
- **Peak shaving renamed from "Capacity Protection"**: The peak shaving feature has been renamed across all UI strings and translations (EN, ES, DE, FR, NL) to better reflect its actual function — limiting grid import peaks by discharging the battery only when consumption exceeds a configured threshold. The previous name "Capacity Protection" was misleading, suggesting the feature protects the battery's physical capacity. Internal configuration keys are unchanged, so existing installations are not affected.

## [1.6.0] - 2026-04-07

> [!IMPORTANT]
> **Breaking change — solar forecast sensor**: The integration now uses **today's** solar forecast instead of tomorrow's. If you have the *Solar Charge Delay* or *Predictive Grid Charging* features configured, you must update the forecast sensor field to point to your integration's **today** sensor (e.g. `sensor.solcast_pv_forecast_forecast_today`) instead of the tomorrow sensor. The stored overnight forecast is no longer used and will be ignored on upgrade.

### Added
- **Solar charge delay SOC setpoint**: New optional feature that splits the morning charge into two phases. A dedicated checkbox enables it; when enabled, a slider (12–90 %, default 50 %) sets the target SOC. Below the setpoint the battery charges freely without any delay applied; once all batteries reach the setpoint the solar delay logic activates as usual. This guarantees a minimum charge level on deeply discharged batteries before the solar energy decision is made, while still maximising self-consumption for the remaining charge. The minimum is 12 % — the Venus battery minimum discharge SOC. Configurable during setup and from the options flow; the setpoint value is also exposed as a number entity (*Charge Delay SOC Setpoint*) on the system device card for runtime adjustment.

### Changed
- **Solar forecast now uses today's live value**: The integration no longer captures and stores tomorrow's forecast at 23:00. Instead, it reads the configured sensor live on every evaluation. Today's forecast is updated multiple times throughout the day by most solar forecast integrations (Solcast, Forecast.Solar, etc.), becoming progressively more accurate as actual weather conditions develop. This removes the 23:00 nightly capture task and eliminates the stale-forecast problem that occurred after an HA restart or when the nightly window was missed.
- **Charge delay threshold is now a dynamic energy balance**: The previous fixed threshold (forecast < 1.5 × battery capacity → unlock) has been replaced with the same energy-balance calculation used by predictive charging: `(usable_energy + forecast) < avg_daily_consumption`. This takes the current battery SOC into account — on a partly-charged morning the threshold is effectively lower — and uses real historical consumption data instead of an arbitrary capacity multiplier. The balance is only recalculated when the forecast value changes by more than 0.05 kWh, avoiding unnecessary computation on every controller cycle.
- **Charge delay re-evaluates forecast changes in real time**: Because the forecast sensor is now read live, any intra-day update is automatically picked up. If the forecast degrades to the point where the energy balance turns negative (grid charging needed), the delay unlocks immediately and morning charging starts. If the forecast improves while the delay is still active, the system keeps waiting for solar. Once the delay is unlocked, it stays unlocked for the day.
- **Predictive charging (Time Slot mode) — initial evaluation delayed 5 minutes**: The energy balance evaluation no longer runs at the exact instant the slot boundary is crossed. Instead the controller waits 5 minutes with the battery in idle before evaluating. This avoids a race condition when the slot starts at 00:00: at that moment the forecast sensor may still be reporting yesterday's final value before the integration resets it for the new day. The 5-minute hold ensures the sensor has updated before the charging decision is made.
- **Predictive charging (Time Slot mode) — pre-evaluation notification removed**: The notification sent 1 hour before the slot start has been removed. A single notification is now sent at the moment the evaluation fires (5 minutes into the slot), reporting the actual decision: charge or no charge needed.

## [1.5.4] - 2026-04-06

### Added
- **Configurable backup offgrid load threshold**: Each battery now has a user-configurable threshold (0–500 W, default 50 W) that determines when an offgrid load is treated as an active backup event. Batteries with small permanent loads on the offgrid port (e.g. a PoE switch, router, or cameras) were previously excluded from PD control indefinitely because any non-zero offgrid reading triggered backup mode. The threshold can be set during initial setup (per-battery limits page in the config flow) and adjusted at any time via a **Backup Offgrid Threshold** number entity on the battery device card — no reconfiguration required. Changes take effect immediately and survive restarts.
- **EV charger without power telemetry** (new excluded-device option): A new checkbox — *EV charger without power telemetry* — is available when configuring an excluded device. When checked, the selected sensor is treated as a **state sensor** rather than a power sensor. The controller monitors it and reacts when the state changes to any recognised charging string (`Charging`, `Cargando`, `Cargando VE`, `Cargando Vehículo`, and case-insensitive variants). On detection, the battery enters a **5-minute full pause** (both charge and discharge set to 0 W, PD state frozen) so the vehicle receives the maximum available current without competition. Once the pause expires the battery may still **charge from solar surplus** but will **never discharge** while the EV remains in a charging state. Normal operation resumes automatically when the sensor leaves the charging state.

### Fixed
- **`Active Batteries` sensor always showing `Idle` when only one battery is available**: `_select_batteries_for_operation` returned early for the single-battery case without updating the `_active_charge_batteries` / `_active_discharge_batteries` tracking lists, so the diagnostic sensor always saw empty lists and displayed `Idle` regardless of actual charge/discharge state.
- **Backup exclusion logic not applied consistently during shutdown**: The `async_unload_entry` shutdown handler used a hardcoded `!= 0` check for the offgrid power sensor instead of the per-battery threshold, meaning batteries with small permanent offgrid loads would incorrectly skip shutdown register writes and be left in an uncontrolled state on integration unload.

Thanks to **[@hdcasey](https://github.com/hdcasey)** for reporting and fixing the first two issues.

## [1.5.3] - 2026-04-05

### Added
- **Proactive battery alarm notifications (v2 only)**: The integration now monitors the `Alarm Status` (register 36000) and `Fault Status` (register 36100) registers every 5 seconds and sends a Home Assistant persistent notification the moment a new alarm or fault bit is set. The notification is titled **"Battery Fault/Warning: \<name\>"** and lists both the newly triggered conditions and all currently active ones. When all alarms and faults clear, the notification is automatically dismissed. Notifications are scoped per battery (separate notification ID per battery name) so multi-battery setups report each device independently. v3, vA and vD batteries do not expose these registers via Modbus and are not affected.
- **System Alarm Status sensor** (`sensor.marstek_venus_system_alarm_status`, **v2 only**): New sensor on the *Marstek Venus System* device that aggregates the alarm state across all batteries. State is `OK` when no conditions are active, `Warning` when one or more alarm bits are set but no fault bits, and `Fault` when at least one fault bit is active on any battery. The `extra_state_attributes` dictionary exposes per-battery detail — each key is the battery name and the value is a list of active condition labels (e.g. `[Fault] BAT Overvoltage`, `[Alarm] Fan Abnormal Warning`) — so the exact source and nature of each event is visible without opening individual battery sensors. The sensor is only populated for v2 batteries.
- **Shared alarm/fault bit-description constants** (`FAULT_BIT_DESCRIPTIONS`, `ALARM_BIT_DESCRIPTIONS` in `const.py`): The 32-bit description maps previously duplicated inline inside `SENSOR_DEFINITIONS` are now standalone module-level dicts. The existing per-battery `Alarm Status` and `Fault Status` sensors reference these constants, eliminating the duplication and making future updates to alarm labels a single-point change.
- **Solar Surplus switch per excluded device**: Each excluded device now gets a dedicated switch entity (`Solar Surplus – <device name>`) that toggles the `allow_solar_surplus` flag at runtime without entering the options flow. When ON, the battery yields solar surplus to that device (e.g. EV charger) instead of charging itself — solar goes to the device first and the battery will not discharge to power it either. When OFF, the battery charges normally with any available solar surplus. The switch is controllable from HA automations, enabling priority changes based on schedules, battery SOC, EV connection state, or any other condition.

### Changed
- **strings.json now in English**: The base translation file (`strings.json`) has been converted to English to serve as the proper fallback language for Home Assistant installations using a language without a dedicated translation file.

### Fixed
- **German translation fix**: Corrected `round_trip_efficiency_total` label from "Gesamte Hin- und Rückfahreffizienz" to "Gesamtwirkungsgrad".

## [1.5.2] - 2026-04-04
 
### Added
- **Configuration Summary diagnostic sensor**: New hidden sensor (`Configuration Summary`) on the Marstek Venus System device that exposes the complete integration configuration as entity attributes. Intended for support purposes — enable it from the entity registry, then share the state card to provide a full picture of the system setup at a glance. Attributes are organised in sections: general (grid sensor, meter inversion, solar forecast sensor), per-battery settings (name, IP, version, power limits, SOC thresholds, hysteresis), time slots, predictive charging (mode, time slot, contracted power, price sensor and thresholds), weekly full charge, charge delay, capacity protection, PD controller parameters, and excluded devices. The sensor is disabled by default and categorised as diagnostic.
- **Backup function exclusion from PD control**: When the **Backup Function** switch is enabled on a battery **and** the **AC Offgrid Power** sensor reports a non-zero value, that battery is automatically excluded from PD controller writes. Having the switch on alone is not sufficient — the battery must actually be providing offgrid power. No power commands, force mode changes, or configuration register writes are sent while both conditions are met. A **5-minute cooldown** is applied after the offgrid load drops back to 0 W, keeping the battery excluded until the window expires to avoid sending commands immediately after a backup event ends. Turning the switch off clears the cooldown immediately. The battery continues to be polled normally so all read-only sensors remain up to date. This applies to all write paths: normal PD control, predictive grid charging, weekly full charge register writes, and the shutdown sequence. The AC Offgrid Power sensor (register 32302) has been added to v3, vA, and vD battery definitions so that the two-condition check works across all versions.

## [1.5.1] - 2026-04-01

### Added
- **Price-based discharge control for Dynamic Pricing and Real-Time Price modes**: New optional checkbox in both pricing mode configurations that restricts battery discharge to periods when the current electricity price exceeds a configurable threshold. When enabled, the battery only discharges if the live price is strictly above the threshold (fixed `max_price_threshold` or a daily average price sensor). If discharge time slots are also configured, both conditions must be met — the price check acts as an additional gate on top of the existing time window restriction. Dynamic Pricing mode gains a new optional `dp_average_price_sensor` field (equivalent to the existing `average_price_sensor` in Real-Time Price mode) to support a dynamic discharge threshold.
- **Grid meter kW auto-detection and inverted sign support**: The controller now automatically detects if the grid meter sensor reports in kW (via its `unit_of_measurement` attribute) and converts to Watts internally — no user action required. A new **"Inverted meter sign"** toggle has been added to the initial setup and options flow for meters that use the opposite sign convention (positive = export, negative = import).

## [1.5.0] - 2026-04-01

### Added
- **New sensors for all battery versions (v2/v3/vA/vD)**: Added device information sensors (`device_name`, `sn_code`, `software_version`, `bms_version`, `vms_version`, `ems_version`, `comm_module_firmware`, `mac_address`) where supported by each battery version. Added cell voltage sensors (`max_cell_voltage`, `min_cell_voltage`) for v3/vA/vD. Added WiFi and Cloud connectivity binary sensors (`wifi_status`, `cloud_status`) for all versions.
- **Battery Cycle Count sensor (v3/vA/vD)**: Direct register-based cycle count sensor reading from the battery firmware for v3, vA, and vD batteries.
- **Calculated Battery Cycle Count sensor (all versions)**: New derived sensor (`battery_cycle_count_calc`) available for all battery versions, calculated as `(total_discharge + total_charge) / 2 / battery_capacity`. Provides cycle count estimation for v2 batteries that lack a direct register, and a cross-check for other versions.
- **Dynamic Pricing Mode for Predictive Grid Charging**: New charging mode that automatically selects the cheapest hours of the day to charge the batteries from the grid. Supports **Nordpool**, **PVPC (ESIOS REE, Spain)**, and **CKW (Switzerland)**. Configured through a new `predictive_charging_mode` step (choose between Time Slot or Dynamic Pricing) and a `dynamic_pricing_config` step (price integration type, price sensor, optional max price threshold, and ICP contracted power).
  - **Automatic cheapest-hour selection**: The controller calculates the energy deficit each day at 00:05 using the effective charge power (`min(ICP, total battery charge capacity)`), then picks the cheapest hours from the price forecast. When no deficit exists, the cheapest equivalent hours are still selected as informational reference.
  - **Max price threshold filter**: Optional ceiling that prevents charging even during cheap hours if prices exceed the configured limit. Unit matches the sensor (€/kWh for Nordpool/PVPC, CHF for CKW).
  - **Daily 00:05 evaluation with retry logic**: Evaluation runs just after midnight when price data for the day is already available. If price data is still unavailable at 00:05, the controller retries every 15 min within the first hour of the day. A `no_price_data` error is surfaced in the config flow if the selected sensor lacks the expected attributes.
  - **Startup evaluation on integration restart**: If Home Assistant restarts after the 00:05 window and no evaluation has been done yet for the current day, the controller runs a one-time evaluation automatically during startup (after a 15-second delay to allow the data coordinator to complete its first poll). This ensures the daily schedule is always built, even when HA is restarted mid-morning. The evaluation only considers slots up to 23:59 of the current day — tomorrow's slots are left to the normal 00:05 evaluation.
  - **`price_data_status` diagnostic attribute**: The `predictive_charging_active` binary sensor exposes a `price_data_status` attribute showing whether the price sensor is being read correctly: `ok (N slots)`, `sensor_unavailable`, `no_slots`, or `not_evaluated`.
  - **`predictive_charging_active` binary sensor — dynamic pricing attributes**: Always exposes the full evaluation result — `charging_needed` flag, selected hours with individual prices, average price, estimated cost, and evaluation timestamp. The schedule persists throughout the day it applies to (not cleared at midnight).
- **Real-Time Price mode for predictive grid charging**: New third charging mode that reads the current electricity price every controller cycle (~2.5 s) and activates or deactivates grid charging immediately when the price crosses a configured threshold. Unlike Dynamic Pricing (which pre-selects the cheapest hours at 00:05), this mode requires no overnight evaluation and no price forecast — it reacts purely to the live price. Supports any HA sensor that exposes the current period price as its state (PVPC, Nordpool, CKW, or any other integration). Optionally accepts a daily average price sensor as a dynamic threshold instead of a fixed value, and evaluates the same solar/battery energy balance as other modes before starting to charge.
- **Solar forecast sensor optional in predictive charging**: The solar forecast sensor field in both Time Slot and Dynamic Pricing configuration steps is now optional. Users without solar panels can leave it empty — the system will activate grid charging whenever the battery's usable energy is insufficient to cover expected daily consumption (same conservative logic already used when the sensor is unavailable or reports an error). Users with solar panels should still configure it so the system only charges when the forecast is insufficient.
- **Improved daily consumption estimate when battery reaches min SOC**: The system now tracks grid energy imported during periods when all batteries are at minimum SOC and the battery would otherwise be discharging (within a configured discharge slot, or always if no slots are defined). This unmet demand is accumulated in a new sensor (`Grid at Min SOC`, kWh, resets at midnight) and added to the battery discharge when capturing the daily consumption figure used by predictive charging. This prevents the 7-day rolling average from underestimating consumption on days where the battery ran out before midnight, which previously caused the system to charge less than needed the following day. Grid import during intentional grid charging (predictive/dynamic pricing) is excluded from the accumulator.
- **Mid-day re-evaluation for dynamic pricing slots**: When multiple cheap slots are selected at 00:05, the system now re-evaluates 1 hour before each subsequent slot whether charging is still needed. If the battery is sufficiently charged (solar + current SOC covers expected consumption), the slot is silently skipped. If charging is still needed, a notification is sent confirming the slot will activate. Re-evaluations are skipped automatically when a previous slot is still actively charging (back-to-back slots), and the per-day state is reset at midnight alongside the main schedule.

### Fixed
- **SOC and power limit sliders not persisted across restarts (complete fix)**: Changes to `Min SOC`, `Max SOC`, `Max Charge Power`, and `Max Discharge Power` sliders were written to the battery hardware registers and updated in memory, but `config_entry.data` was never updated. On every HA restart, `async_setup_entry` overwrote the hardware registers with the original setup values, discarding any runtime changes. The partial fix in 1.4.0 (syncing coordinator attributes from polled register values) was ineffective because the startup sequence writes the stale config values to hardware *before* the first poll completes. Values are now persisted to `config_entry.data` immediately when a slider is changed, using the same pattern as the RS485 switch preference.
- **RS485 switch state not persisted across restarts**: Disabling the RS485 Control Mode switch and restarting Home Assistant would re-enable it automatically. The user's preference is now saved to the config entry and restored on startup. The initial RS485 enable during integration load and the reconnection re-enable are both skipped when the user has explicitly disabled the switch.
- **v3/vA/vD batteries not accepting write commands**: Inter-register write delay in the atomic power write sequence was hardcoded to 50 ms (v2 timing). v3/vA/vD firmware requires a minimum of 150 ms between consecutive Modbus messages; writes now use the version-specific timing from `MESSAGE_WAIT_MS`, matching the delay already applied to polling reads.
- **Non-responsive battery cooldown capped at 30 min**: The exponential backoff for excluded batteries could grow to 30 minutes after repeated failures. The cap is now 5 minutes so a temporarily unresponsive battery is retried more frequently.
- **Dynamic pricing schedule cleared at midnight**: The `_dynamic_pricing_evaluated_date` was stored as the evaluation date (day N), causing the schedule to be wiped at midnight — before any of the selected slots (day N+1 morning) could activate. The evaluated date is now stored as the date the slots belong to, so the schedule persists until the end of that day.
- **Charging hours underestimated when ICP > battery charge capacity**: `_calculate_charging_hours_needed` used only `max_contracted_power` (ICP) as the effective charge power. If the total battery charge capacity is lower than the ICP, the actual charge rate is limited by the batteries, not the ICP — resulting in too few hours being selected and the battery not reaching the target SOC. The calculation now uses `min(ICP, total battery charge capacity)`. Estimated cost in the schedule and notifications is also corrected accordingly.
- **Consumption history always showing 6 days instead of 7**: The cleanup filter used a strict `>` comparison (`d > today − 7`), which excluded the entry for exactly 7 days ago. Replaced date-based cutoff with a trim to the 7 most recent entries (`[-7:]`) so the window is always exactly 7 entries.
- **Consumption history gaps filled with real-data average**: When the startup backfill cannot find recorder data for a day (HA was down, or daily discharge was below the 1.5 kWh representativeness threshold), the missing entry is now filled with the average of the real entries already in the history instead of the fixed 5.0 kWh default. This prevents artificial inflation of the consumption estimate. On first run when no real data exists yet, 5.0 kWh is still used as a conservative bootstrap.
- **Modbus read/write operations now time out on half-open sockets**: `async_read_register` and `async_write_register` now wrap their underlying pymodbus calls in `asyncio.wait_for(timeout=...)` using the client's configured timeout (default 10 s). Previously, a hung write or read on a half-open socket would block indefinitely, preventing the coordinator from recovering after a TCP connection drop. `asyncio.TimeoutError` is now treated the same as `ConnectionException`, triggering the existing reconnect-and-retry path.
- **Battery SOC hidden by efficiency sensor in device card**: The Round-Trip Efficiency sensor shared the `battery` device class with the Battery SOC sensor, causing Home Assistant to display the efficiency percentage instead of the SOC in the top-right corner of the device card. The device class has been removed from the efficiency sensor.

### Changed
- **Predictive charging notifications reformatted**: Both time-slot and dynamic pricing notifications now use a consistent emoji-based layout (🔋 battery, ☀️ solar, 📊 consumption, ⚡ deficit, ⏰ timing). All notifications show the effective charge power as `min(ICP, battery capacity)W (ICP: XW, batteries: YW)`. When dynamic pricing finds no deficit, the notification is clearly labelled as informational ("No charging will activate") and shows the cheapest reference hours without implying grid charging will occur.
- **Clarifying note on solar forecast sensor in secondary configuration steps**: In the Time Slot, Dynamic Pricing, and Charge Delay configuration steps, the solar forecast sensor field now includes a note explaining that it is not required if the sensor was already configured in the initial setup step — it will be used automatically. The German, French, and Dutch translations of the Dynamic Pricing step were also missing this field entirely; it has been added.

### Removed
- **Unused `too_low` translation error key**: Removed the orphaned `too_low` error string (previously defined in all translation files but never raised by the Python code) from EN, ES, DE, FR, and NL translations.
- **`user_work_mode` removed from vA/vD batteries**: The `user_work_mode` select entity (register 43000) is not supported on vA and vD hardware and has been removed from their definitions.

## [1.5.1] - 2026-04-01

### Added
- **Grid meter kW auto-detection and inverted sign support**: The controller now automatically detects if the grid meter sensor reports in kW (via its `unit_of_measurement` attribute) and converts to Watts internally — no user action required. A new **"Inverted meter sign"** toggle has been added to the initial setup and options flow for meters that use the opposite sign convention (positive = export, negative = import).

## [1.4.1] - 2026-03-24

### Added
- **Support for up to 6 batteries**: The battery count slider in both the initial setup and options flow now allows selecting 1–6 batteries (previously capped at 4). No architectural changes were required as the control loop and power distribution are fully dynamic.
- **Non-responsive battery detection**: The control loop now detects when a battery acknowledges a discharge command (registers written correctly) but fails to deliver power. After 3 consecutive cycles with actual output below 10% of the commanded value, the battery is excluded from the active pool with a warning log entry. It is automatically retried after a cooldown period that doubles on each repeated failure (5 → 10 → 20 → 30 min cap) and resets to 5 min after a successful delivery cycle. This prevents a single non-responsive battery from destabilising the PD controller and causing the remaining batteries to oscillate.
- **Non-Responsive Batteries diagnostic sensor**: New sensor on the Marstek Venus System device showing which batteries are currently excluded due to non-responsive behaviour. State is `None` when all batteries are healthy, or a comma-separated list of excluded battery names. Attributes expose per-battery details: exclusion status, cooldown duration, and remaining cooldown minutes. Available in EN, ES, DE, FR, NL.

## [1.4.0] - 2026-03-21

### Added
- **Unified Solar Charge Delay**: New dedicated config step (`Charge Delay`) that replaces the previous weekly-charge-specific delay flag. When enabled, the delay applies **every day**: charging is held back while solar production is forecast to cover the required energy, and unlocked automatically once the energy balance tips. The target SOC is 100% on the configured weekly full charge day, or the configured `max_soc` on all other days. Discharge in configured time slots is unaffected.
- **Unified charge delay config step**: Two new steps in both ConfigFlow and OptionsFlow — a gate step (`Configure charge delay`) and a configuration step with a `Safety margin (hours)` slider (1–5 h, step 0.5 h, default 1 h) and an optional `Solar forecast sensor` field (only shown if not already configured in the predictive charging step).
- **Charge Delay Status diagnostic sensor**: New `Charge Delay Status` sensor on the Marstek Venus System device, replacing the separate weekly and solar delay sensors. State reports `Idle`, `Waiting for solar`, `Delayed (~HH:MM est.)`, `Charging allowed`, or `Disabled`. Attributes expose `target_soc`, `safety_margin_min`, `forecast_kwh`, `solar_t_start`, `solar_t_end`, `energy_needed_kwh`, `remaining_solar_kwh`, `remaining_consumption_kwh`, `net_solar_kwh`, `charge_time_h`, `estimated_unlock_time`, and `unlock_reason`. Populated on every control cycle, not only when a charge attempt is gated.
- **Accurate estimated unlock time**: The `estimated_unlock_time` attribute is now calculated as the earliest of two triggers — the time-backup threshold (`T_end − charge_time − safety_margin`) and the energy-balance crossing point, found via a binary search (40-iteration bisection, <1 s precision) on the sinusoidal solar production model. On good solar days, this reflects the energy-balance unlock ~1–2 hours earlier than the conservative time-backup estimate.
- **Capacity Protection Mode (Peak Shaving)**: New feature that conserves battery energy when SOC drops below a configurable threshold (30–100%). Instead of discharging to cover all household consumption, the battery only discharges to offset consumption that exceeds a configurable peak limit (2500–8000W). When house load is below the limit, the battery stays idle; when it exceeds the limit, the battery discharges only the excess. Solar charging continues unaffected. Configurable in both initial setup and options flow, with a runtime toggle switch and adjustable number entities for SOC threshold and peak limit.
- **Charge Delay switch**: New `Charge Delay` switch on the Marstek Venus System device to enable/disable the charge delay feature at runtime without reconfiguring the integration. Only visible when charge delay is configured.
- **Capacity Protection switch**: New `Capacity Protection` switch on the Marstek Venus System device to enable/disable the feature at runtime without reconfiguring the integration. State persists across restarts.
- **Capacity Protection Active diagnostic sensor**: New `Capacity Protection Active` binary sensor (diagnostic) that turns ON when the protection is actively intervening (SOC below threshold). Attributes expose real-time diagnostic data: `avg_soc`, `soc_threshold`, `peak_limit_w`, `estimated_house_load_w`, `action` (`shaving`/`conserving`/`charging`/`idle`/`disabled`), `original_target_w`, and `adjusted_target_w`.
- **Capacity Protection number entities**: `Capacity Protection SOC Threshold` and `Peak Limit Protection` number entities on the system device for runtime tuning without reconfiguration. Only visible when the feature is enabled.
- **Charge Delay Margin number entity**: New `Charge Delay Margin` slider on the Marstek Venus System device to adjust the safety margin at runtime without reconfiguring the integration. Displayed in hours (1–5 h, step 0.5 h); stored internally in minutes.
- **Entity name and state translations**: All system-level entities (switches, sensors, binary sensors) now use Home Assistant's translation system. Entity names (`Manual Mode`, `Charge Delay`, `Discharge Window`, etc.) and sensor state values (`Idle`, `Disabled`, `Charging allowed`, `Waiting for solar`, `Delayed`, `Active`, `Inactive`, etc.) are now displayed in the user's configured HA language. Supported languages: English, Spanish, German, French, Dutch.

### Removed
- **Force Full Charge button removed**: The `Force Full Charge` button has been replaced by the new `Charge Delay` switch (see above).

### Changed
- **Solar T_start detection rewritten**: The mechanism that detects when solar production begins (used by the Charge Delay feature) has been replaced. The previous approach accumulated daily battery charging energy and triggered at a 0.1 kWh threshold — unreliable because grid charging energy was included in the counter. The new primary mechanism triggers when grid power ≤ 0 W and total battery power ≤ 0 W simultaneously (solar is covering at least the full house load with no battery contribution). A new astronomical fallback kicks in 30 minutes after the estimated sunrise (calculated from HA latitude, longitude, and day of year) if the primary condition has not fired, handling high-consumption days where grid power never reaches zero.
- **Solar forecast corrected by 15 % before use**: A conservative 15 % reduction is applied internally to the captured solar forecast before it is used by the Charge Delay and Predictive Charging algorithms. The raw sensor value is still shown in the `forecast_kwh` diagnostic attribute; only the internal calculation uses the adjusted value.
- **Weekly full charge config simplified**: The `weekly_full_charge_config` step now contains only the day-of-week selector. The delay toggle, safety margin, and solar forecast sensor have been moved to the new dedicated `Charge Delay` steps, which apply to both the weekly 100% charge and the daily max_soc charge.
- **Solar forecast captured every night**: The forecast capture at 23:00 now runs every night (previously only the night before the weekly charge day). The stored value is used the next morning by the delay logic, ensuring the forecast is always from the previous evening — before the sensor resets to the next day's data at midnight.
- **Delay uses stored forecast**: The charge delay algorithm no longer reads the solar forecast sensor live. It uses the value captured the previous night, which corresponds to the current day's production. Live reads would return the *next* day's forecast after midnight.

### Fixed
- **Feature entities disappearing after disabling switch**: The `Charge Delay` sensor and `Capacity Protection` switch and status sensor were only registered at startup when their respective feature was enabled. Disabling the switch persisted the disabled state to config, so after a restart those entities would no longer appear. Registration now checks whether the feature is configured (key exists in config entry) rather than whether it is currently enabled, matching the pattern already used by the `Charge Delay` switch. Affected entities: `Charge Delay` sensor, `Capacity Protection` switch, `Capacity Protection Active` binary sensor.
- **Charge Delay sensor renamed**: The `Charge Delay Status` sensor has been renamed to `Charge Delay` across all supported languages (EN, ES, DE, FR, NL) for brevity.
- **Configuration changes not surviving restart**: Changes to `Min SOC`, `Max SOC`, `Max Charge Power`, and `Max Discharge Power` via the UI were written to the battery's Modbus registers but not persisted to `config_entry.data`. After a restart, the coordinator re-initialised from the original setup values. The coordinator now syncs these attributes from the polled register values after every data refresh, treating the hardware as the source of truth. Separately, the enabled/disabled state of the `Charge Delay` and `Capacity Protection` switches was being saved correctly, but the related entities were not registered when the feature was disabled — making the saved state effectively invisible after a restart. This is resolved by the entity registration fix described above.
- **Solar forecast sensor not shown in initial setup**: The solar forecast sensor field was missing from the first configuration step. It is now included as an optional field alongside the consumption sensor, making it available to both Predictive Grid Charging and Charge Delay without requiring re-entry in each feature's step.
- **Safety Margin description and defaults incorrect in README**: The documented range (10–120 min) and default (40 min) did not match the actual implementation (30–180 min, default 180 min). The description incorrectly stated it was an extra buffer for underperformance; the correct meaning is "minutes before sunset by which charging must be complete — higher values unlock charging earlier".
- **V3 Battery SOC register reverted**: Register 34002 (scale 0.1, introduced in v1.3.0) is not supported on Venus C v3 batteries and caused incorrect readings. SOC is now read again from register 37005 (scale 1, precision 1 decimal) as in versions prior to 1.3.0.
- **Delay evaluation too infrequent**: The charge delay status was only computed when the PD controller attempted to charge the battery. On days where the battery stayed in equilibrium (deadband), the `Charge Delay Status` sensor remained stale and showed `target_soc: Unknown`. Delay evaluation now runs proactively on every 2-second control cycle regardless of charging activity.

## [1.3.4] - 2026-03-17

### Improved
- **Stale sensor detection for PD controller**: The control loop now detects when the consumption sensor hasn't updated between cycles (common with sensors reporting every 5s or slower) and skips PD recalculation to avoid acting on stale data. Sensor history is only populated with real readings, preventing duplicate values from diluting the moving average. The derivative term now uses the actual elapsed time between sensor updates instead of a fixed 2s, eliminating derivative spikes that caused oscillation with slow sensors. A safety valve forces recalculation (proportional only, derivative suppressed) if the sensor stops updating for ~30 seconds.

## [1.3.3] - 2026-03-17

### Fixed
- **Hassfest manifest validation**: Removed unsupported `icon` field from `manifest.json` and added `recorder` to `after_dependencies` to declare the integration's usage of the recorder component.

## [1.3.2] - 2026-03-17

### Changed
- **Min charge/discharge power slider range increased**: The maximum value for `Min Charge Power` and `Min Discharge Power` in both the PD Advanced options flow and the number entities has been raised from 500W to 2000W, allowing higher idle thresholds for systems with large PV Systems.

## [1.3.1] - 2026-03-12

### Fixed
- **System SOC decimal precision for v3 batteries**: The `System SOC` aggregate sensor now displays one decimal place when any battery in the system is a v3/vA/vD model, matching the higher-resolution SOC readings provided by those batteries.

## [1.3.0] - 2026-03-12

### Added
- **Venus A and Venus D battery support**: New battery models `A` (Venus A, max 1200W) and `D` (Venus D, max 2200W) for hybrid inverter setups. Both models share the same Modbus register map and include MPPT power sensors (mppt1–mppt4, enabled by default) for monitoring solar input channels.
- **Dynamic power slider limits in config flow**: The battery configuration wizard now adapts the charge/discharge power sliders to the selected model's maximum (Ev2/Ev3: 2500W, A: 1200W, D: 2200W). The battery setup step has been split into two screens: connection details (name, IP, port, model) and power limits.
- **Battery model version labels updated**: Version labels in the configuration flow now read `Ev2`, `Ev3`, `A`, and `D` for clarity.
- **Weekly Full Charge Delay (Solar-Aware)**: New optional feature that delays the weekly 100% charge until solar production is forecast to be insufficient. Instead of charging to 100% from midnight, the system evaluates the solar forecast and only unlocks the full charge when remaining solar energy won't cover household consumption plus the energy needed to reach 100%. Uses a sinusoidal solar production model with T_start detection from actual battery charging data and solar noon calculated from Home Assistant's configured longitude. Includes configurable safety margins and automatic fallback for days with no forecast data.
- **Solar forecast capture for delay feature**: When the delay feature is enabled, the integration captures the next-day solar forecast at 23:00 and persists it across restarts using HA Store, ensuring the forecast is available on the target day.
- **Weekly Full Charge diagnostic sensor**: New `Weekly Full Charge` diagnostic sensor on the Marstek Venus System device showing the current charge status (`Idle`, `Waiting for solar`, `Delayed (HH:MM est.)`, `Charging to 100%`, `Complete`). Attributes expose full calculation details: forecast kWh, solar T_start/T_end, energy needed, remaining solar/consumption, net solar, charge time estimate, estimated unlock time, and unlock reason.
- **Force Full Charge button**: New button on the Marstek Venus System device to trigger an immediate 100% charge on any day, bypassing the weekly schedule and delay logic. Resets automatically on day change.
- **Configurable safety margin for delay feature**: The delay safety margin (time buffer before estimated end of solar production) is now configurable in both config and options flow (10-120 minutes, default 40 min). Previously hardcoded at 40 minutes.

### Changed
- **System Charge/Discharge Power uses AC power**: The `System Charge Power` and `System Discharge Power` aggregate sensors now read from each battery's `AC Power` register instead of `Battery Power`, reflecting the actual AC-side power flow.
- **V3 Battery SOC register upgraded**: V3 batteries now read SOC from register 34002 (scale 0.1, precision 2 decimals) instead of 37005 (scale 1, precision 1 decimal), providing higher resolution readings.
- **Removed unused Charge to SOC entity**: The `charge_to_soc` number entity (register 42011) was not used by any integration logic and has been removed from both V2 and V3 definitions.
- **Translation files completed**: Added missing `apply_to_charge` field translations to EN, DE, FR and NL. Added missing `enable_weekly_full_charge_delay`, `solar_forecast_sensor` and `delay_safety_margin_min` translations to DE, FR and NL (both config and options flow).

### Fixed
- **RS485 control mode not re-enabled after reconnection**: When a battery's TCP connection was lost and re-established (e.g., WiFi drop, options flow reload), RS485 control mode was not re-enabled. The battery silently ignored all power commands until a manual restart. `async_reconnect_fresh()` now automatically re-enables RS485 after every successful reconnection, with a user-override flag to respect manual RS485 disabling via the switch entity.
- **First battery RS485 disabled after options flow reload**: On reload, the first battery attempted to reconnect before the V3 firmware released the previous TCP slot, causing the initial connection to fail. RS485 was only enabled on successful connection, leaving the first battery uncontrolled until health monitoring reconnected (without re-enabling RS485). Added a 1-second retry delay for failed initial connections.
- **Individual battery Stored Energy sensor not visible**: The `MarstekVenusStoredEnergySensor` entities were created but immediately discarded due to a `lambda entities: None` callback. Sensors are now properly registered through the sensor platform setup.
- **Consumption history not populated without predictive charging**: The daily consumption capture (needed for the delay feature's average calculation) was only scheduled when predictive charging was enabled. Now also scheduled when the weekly full charge delay is enabled.
- **Grid charging falsely triggering solar T_start detection**: `total_daily_charging_energy` includes grid charging energy, which could falsely indicate solar production start. T_start detection now only activates after 07:00 to avoid overnight grid charging interference.

## [1.2.1] - 2026-03-06

### Fixed

- **Max charge/discharge power changes from UI ignored by control loop**: Changing `Max Charge Power` or `Max Discharge Power` number entities wrote to the Modbus register but did not update the coordinator attributes used by the PD controller. The initial config flow values were used forever. Changes now take effect immediately.


## [1.2.0] - 2026-03-04

### Added
- **Solar surplus mode for excluded devices**: New `allow_solar_surplus` option in excluded device configuration. When the battery is **charging**, no adjustment is applied — the PD controller sees real grid power and naturally reduces charging to leave solar for the device. When the battery is **discharging**, full exclusion applies so the battery won't drain to power the device. Recommended for high-consumption devices like EV chargers.
- **Native config entities**: Exposed key configuration parameters as Home Assistant entities, eliminating the need to run the full Options Flow wizard for routine adjustments:
  - **PD controller number entities**: Kp, Kd, deadband, max power change, direction hysteresis, min charge/discharge power — all hot-reloadable without integration restart.
  - **Max Contracted Power number entity**: Editable from the UI when predictive charging is enabled.
  - **Weekly Full Charge Day select entity**: Pick the balancing day directly from the UI.
  - **Time Slot switches**: Enable/disable individual no-discharge time slots on the fly.
  - **Excluded Devices Config sensor**: Read-only diagnostic showing the number of excluded devices, with per-device details (sensor entity, included_in_consumption, allow_solar_surplus) as attributes.
- **Discharge Window diagnostic sensor**: Real-time sensor showing whether the system is currently inside an allowed discharge time slot. Displays "Active (Slot N)", "Inactive", or "No slots". Attributes include all slot configuration details (schedule, days, enabled, apply_to_charge, target_grid_power). Replaces the per-slot Time Slot Info sensors.
- **Battery load sharing**: Intelligent battery selection that uses the minimum number of batteries needed to keep each one operating in its optimal efficiency zone. Based on the Venus efficiency curve, batteries activate when total power exceeds 60% of combined capacity (peak efficiency ~91% at 1000-1500W). Features:
  - **Discharge priority**: Highest SOC first (drain fullest battery).
  - **Charge priority**: Lowest SOC first (fill emptiest battery).
  - **SOC hysteresis (5%)**: Active battery stays selected until another exceeds it by 5% SOC.
  - **Energy hysteresis (2.5 kWh)**: Tiebreaker uses lifetime energy with 2.5 kWh advantage for active battery, balancing long-term wear.
  - **Power hysteresis (±100W)**: Activates 2nd battery at 60% capacity threshold, deactivates at 50% to prevent ping-pong with fluctuating loads.
  - Applies to all modes: normal PD control, solar charging, and predictive grid charging.
  - **Active Batteries diagnostic sensor**: Real-time sensor showing which batteries are currently active in load sharing. Displays "Discharging: Venus 1", "Charging: Venus 2", or "Idle". Attributes include per-battery SOC, lifetime discharged/charged energy, and active battery counts. Only created for multi-battery setups.

### Improved
- **Modbus TCP connection management**: Overhauled the Modbus connection lifecycle to prevent permanent battery disconnection (especially on V3, which only accepts one TCP connection). Reconnection now creates a fresh pymodbus client instance every time — closing the old socket first (sending TCP FIN to release the battery's connection slot), then connecting with `reconnect_delay=0` to disable pymodbus's internal auto-reconnect which grew exponentially up to 300 seconds. Added coordinator-level connection health monitoring: after 3 consecutive failed poll cycles a fresh reconnection is triggered; after 5 failures, polling is suspended for 2 minutes to avoid flooding unreachable batteries. Normal 1.5s polling resumes automatically on recovery. The PD control loop now skips unreachable batteries via `coordinator.is_available` instead of writing to dead connections.
- **Automatic reconnection in Modbus retry loops**: When a `ConnectionException` or `ModbusIOException` occurs during a read or write operation, the client now immediately attempts to create a fresh TCP connection instead of retrying on the dead socket. If reconnection succeeds, the operation is retried once; if it fails, retries are aborted immediately. This dramatically reduces recovery time after WiFi drops — the integration reconnects on the first failed operation instead of waiting for 3 poll cycles.
- **Immediate unavailability detection**: The coordinator now marks a battery as unavailable (`_is_connected = False`) on the first poll cycle where all reads fail, instead of waiting for 5 consecutive failures. The control loop stops sending writes to unreachable batteries immediately, preventing log noise and wasted Modbus operations.
- **Connection error log reduction**: `ConnectionException` and `ModbusIOException` errors during read/write operations are now logged at DEBUG level instead of ERROR with full traceback. "Failed after N attempts" messages also downgraded to DEBUG. This eliminates the 60,000+ error log entries that occurred during a WiFi disconnection event.

### Changed
- **Minimum charge/discharge power moved to PD controller settings**: `min_charge_power` and `min_discharge_power` are now global PD controller parameters instead of per-time-slot settings. They apply uniformly regardless of the active time slot. Existing installations will use the default (0 = disabled) until reconfigured via Options → PD Advanced.
- **Predictive Charging switch logic inverted**: The switch is now ON when predictive charging is enabled (default) and OFF when overridden/paused. Previously, it was an "Override" switch with inverted semantics. New unique_id (`_predictive_charging`) — the old `_override_predictive_charging` entity should be manually deleted from HA.
- **Entity reorganization**: Restructured the Marstek Venus System device page for clearer HA UI layout:
  - **Controls**: Manual Mode, Predictive Charging (inverted logic), Time Slot switches, Weekly Full Charge Day select — all without `EntityCategory` so they appear in the Controls section.
  - **Diagnostic**: Discharge Window sensor (new), Predictive Charging Active binary sensor.
  - **Configuration**: PD controller parameters only (Kp, Kd, deadband, etc.).
- **Removed per-slot Time Slot Info sensors and Predictive Charging Config sensor**: Replaced by the single Discharge Window diagnostic sensor. Old entities (`*_time_slot_N_info`, `*_config_predictive_charging_slot`) should be manually deleted from HA.
- **Max charge/discharge power config flow selector**: Replaced the dropdown with only two options (800W / 2500W) with a slider ranging from 800W to 2500W in 50W increments, both in initial setup and options flow.

### Fixed
- **`write_register()` refresh never executed**: The `async_request_refresh()` call after a successful register write was dead code — it sat after `return True` inside the `async with self.lock` block and was never reached. Restructured the method so the refresh executes outside the lock after a successful write.
- **First execution ignores time slot restrictions**: After integration reload/reconfiguration, the first control cycle sent power to batteries without checking time slot restrictions. This caused a brief discharge pulse (~2.5s) even when the current day/time was outside any configured slot, which was then corrected to 0W on the next cycle. The first execution now checks `_is_operation_allowed()` before sending any power commands.
- **Charge/discharge power limits swapped**: The PD controller clamped charging power using `max_discharge_power` and vice versa. This caused charging to be limited to the discharge limit (e.g., 800W instead of 2500W) and discharge to use the charge limit. Both clamp conditions now use the correct limit for their direction.

## [1.1.1] - 2026-02-27

### Fixed
- **Incorrect time slot translations**: Fixed descriptions in English, German, French, and Dutch that incorrectly stated batteries "will NOT discharge" during slots. The correct behavior is the opposite — batteries are ALLOWED to discharge during configured slots and blocked outside them. Spanish translations were already correct.

## [1.1.0] - 2026-02-27

### Added
- **Configurable target grid power per time slot**: The PD controller can now regulate toward a user-defined grid power target instead of the fixed 0W. Each time slot includes a `target_grid_power` field (range: -500W to +500W, default: 0W). Negative values target slight export (e.g. -150W), positive values allow slight import. Outside of active time slots, the controller defaults to 0W. This enables economic optimization for tariff setups where feed-in is more valuable than self-consumption.
- **Minimum charge/discharge power per time slot**: Each time slot can now define `min_charge_power` and `min_discharge_power` thresholds (range: 0-500W, default: 0W = disabled). When the PD controller output is below the configured minimum, the controller stays idle instead of operating at inefficient low power levels. This reduces micro-cycling, unnecessary battery wear, and improves roundtrip efficiency.
- **Time slot overlap validation**: The config flow now rejects time slots that overlap with existing ones on shared days. Also prevents midnight-crossing slots (start >= end) to avoid day-ambiguity — users must create two separate slots for overnight periods instead.
- **Midnight-crossing slot runtime logic removed**: Simplified `_is_operation_allowed()` and `_get_active_slot()` to remove dead midnight-crossing code, since midnight-crossing slots are now rejected at configuration time.

## [1.0.4] - 2026-02-26

### Added
- **V3 battery support**: Version-specific Modbus register maps, entity definitions, and timing for V3 firmware.
- V3 packet correction: Automatically fixes malformed MBAP length bytes in V3 exception responses that caused pymodbus timeouts.
- Automatic reconnection in Modbus retry loops: Both read and write operations now reconnect if the TCP connection is lost mid-retry (skipped during shutdown to avoid occupying the single TCP slot).

### Changed
- Platform files (`button.py`, `number.py`, `select.py`, `switch.py`) now use coordinator's version-specific entity definitions instead of importing hardcoded V2 lists.
- `ManualModeSwitch` uses `coordinator.get_register()` instead of hardcoded register addresses, making it version-aware.
- Bumped `pymodbus` requirement from `>=3.0.0` to `>=3.5.0`.
- Version-specific Modbus timing: V2 uses 50ms, V3 uses 150ms between messages.
- RS485 control mode disable now writes the correct `command_off` value (`0x55BB`) instead of `0`, which V3 firmware rejects with Modbus Exception 3.

### Fixed
- **Race condition during reload**: Control loop and coordinator refresh continued running during `async_unload_entry`, causing "Not connected" write errors. Fixed by cancelling timers at the start of unload, adding a shutdown flag to suppress expected errors and skip operations, and reordering the unload sequence to: cancel timers → set shutdown flag → wait for in-flight ops → unload platforms → write shutdown registers → disconnect.
- **Reconfiguration fails randomly with connection error**: In-flight coordinator polls could survive the shutdown `disconnect()` and automatically reconnect via Modbus retry logic, occupying the battery's single TCP connection slot. The new `async_setup_entry` would then fail with `[Errno 111] Connect call failed`. Fixed by exiting Modbus read/write retries immediately during shutdown and adding an early exit check in the coordinator poll cycle.
- **Options flow connection validation**: Reconfiguration now temporarily closes the coordinator's active connection under lock, tests with a fresh connection, and reconnects the coordinator, instead of opening a second Modbus TCP connection (which the firmware rejects since it only supports one simultaneous connection).
- **V3 Modbus serialization**: Polling reads now acquire the coordinator lock, preventing interleaving with control loop writes on the same TCP connection. V3 firmware mishandled concurrent requests, causing transaction ID mismatches ("extra data") and written values not being applied. New `write_power_atomic()` method writes all power registers and reads feedback under a single lock acquisition.

## [1.0.3] - 2026-02-22

### Fixed
- Fix `KeyError` for `force_mode` when `data_type` is missing (PR #3 by @openschwall).

## [1.0.2] - 2026-02-20

### Fixed
- Remove redundant `_write_config_to_batteries()` call during options flow. The function opened a second Modbus TCP connection while the coordinator was still holding the first one, causing "Not connected" errors on V3 batteries. The reload already applies all configuration values via `async_setup_entry()`.
- Fix `async_close()` in Modbus client attempting to `await` the synchronous `close()` method, which caused "object NoneType can't be used in 'await' expression" errors on every reload.
- Fix "Unable to remove unknown job listener" error on reload by switching `homeassistant_started` listener from `async_listen_once` to `async_listen`. The one-time listener auto-removed itself after firing, causing `async_on_unload` to fail when trying to cancel it during reload.
- Run startup consumption backfill immediately on reload instead of waiting for `homeassistant_started` (which never fires again after boot).

## [1.0.1] - 2026-02-18

### Changed
- Remove V3-exclusive entity definitions to match V2 register footprint.
- Deleted 20 entity definitions from the V3 definition lists (sensors, binary sensors, selects, buttons) that had no equivalent in V2.
- This reduces V3 Modbus-polled registers from ~38 to ~22, which should significantly cut options flow reload time for V3 users.
