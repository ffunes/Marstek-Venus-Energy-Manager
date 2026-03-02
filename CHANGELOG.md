# Changelog

## [1.2.0] - 2026-03-02

### Added
- **Solar surplus mode for excluded devices**: New `allow_solar_surplus` option in excluded device configuration. When enabled, the battery will not charge to compensate for the device's consumption when it is running on solar surplus. The adjustment is capped to real grid import (`min(device_power, max(0, grid_import))`), so if the device runs entirely on solar the battery stays idle, and if it partially draws from the grid the battery only ignores the grid portion. Recommended for high-consumption devices like EV chargers.
- **Native config entities**: Exposed key configuration parameters as Home Assistant entities, eliminating the need to run the full Options Flow wizard for routine adjustments:
  - **PD controller number entities**: Kp, Kd, deadband, max power change, direction hysteresis, min charge/discharge power — all hot-reloadable without integration restart.
  - **Max Contracted Power number entity**: Editable from the UI when predictive charging is enabled.
  - **Weekly Full Charge Day select entity**: Pick the balancing day directly from the UI.
  - **Time Slot switches**: Enable/disable individual no-discharge time slots on the fly.
  - **Excluded Devices Config sensor**: Read-only diagnostic showing the number of excluded devices, with per-device details (sensor entity, included_in_consumption, allow_solar_surplus) as attributes.
- **Discharge Window diagnostic sensor**: Real-time sensor showing whether the system is currently inside an allowed discharge time slot. Displays "Active (Slot N)", "Inactive", or "No slots". Attributes include all slot configuration details (schedule, days, enabled, apply_to_charge, target_grid_power). Replaces the per-slot Time Slot Info sensors.

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
