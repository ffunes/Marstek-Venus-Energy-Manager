# Changelog

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
