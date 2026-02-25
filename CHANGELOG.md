# Changelog

## [1.0.4b7] - 2026-02-25

### Fixed
- **Reconfiguration fails randomly with connection error**: When the user saved options, the in-flight coordinator poll (which takes ~5-6s for V3) would survive the shutdown `disconnect()` call and automatically reconnect via the Modbus retry logic, occupying the battery's single TCP connection slot. The new `async_setup_entry` would then fail with `[Errno 111] Connect call failed`. Fixed by:
  - Modbus client read/write retries now exit immediately when `_is_shutting_down` is set, preventing reconnection attempts that would steal the TCP slot.
  - Coordinator poll now checks the shutdown flag at the start of each cycle and returns early with cached data.

## [1.0.4b6] - 2026-02-24

### Fixed
- **V3 shutdown hangs on RS485 disable**: The shutdown sequence wrote `0` to register 42000 to disable RS485 control mode, but the firmware only accepts `0x55BB` (21947). The invalid value caused a Modbus Exception 3 (Illegal Data Value) with 40s+ timeout, blocking integration reload. Now writes the correct `command_off` value (0x55BB).
- **V3 work mode manipulation removed**: Removed V3-specific code that set `user_work_mode` to Manual (0) on setup and restored to Auto (1) on shutdown via register 43000. V3 batteries operate the same as V2 and do not require work mode changes. This also eliminates the state conflict that caused the RS485 disable to fail during shutdown.

### Removed
- `Working Mode` select entity for V3 batteries (was exposed as Manual / Anti-Feed / Trade Mode). The register is not needed for integration control.
- `user_work_mode` entry from V3 register map (set to `None`, matching V2).

## [1.0.4b5] - 2026-02-24

### Fixed
- **V3 RS485 Control Mode switch missing**: Restored `RS485 Control Mode` switch definition in `SWITCH_DEFINITIONS_V3`. The switch had been incorrectly removed, preventing V3 users from toggling RS485 control mode via the UI.
- **Options flow connection validation**: Changed how battery connections are validated during reconfiguration. Instead of opening a second Modbus TCP connection (which the firmware rejects since it only supports one simultaneous connection), the options flow now temporarily closes the coordinator's active connection under lock, tests with a fresh connection, and reconnects the coordinator. Polling and control loop pause transparently during the test.
- Added delay after closing connections in options flow test to allow firmware to release the connection slot before reconnecting.
- Added diagnostic logging to options flow connection test for troubleshooting connection issues.

## [1.0.4b2] - 2026-02-23

### Added
- **V3 battery support**: Version-specific Modbus register maps, entity definitions, and timing for V3 firmware.
- V3 packet correction: Automatically fixes malformed MBAP length bytes in V3 exception responses that caused pymodbus timeouts.
- V3 Working Mode (`user_work_mode` register 43000): Set to Manual on setup, restored to Auto on shutdown.
- `Working Mode` select entity for V3 batteries (Manual / Anti-Feed / Trade Mode).
- Automatic reconnection in Modbus retry loops: Both read and write operations now reconnect if the TCP connection is lost mid-retry.

### Changed
- Platform files (`button.py`, `number.py`, `select.py`, `switch.py`) now use coordinator's version-specific entity definitions instead of importing hardcoded V2 lists.
- `ManualModeSwitch` uses `coordinator.get_register()` instead of hardcoded register addresses, making it version-aware.
- Bumped `pymodbus` requirement from `>=3.0.0` to `>=3.5.0`.
- Version-specific Modbus timing: V2 uses 50ms, V3 uses 150ms between messages.

### Fixed
- **Race condition during reload**: The control loop (every 2.0s) and coordinator refresh (every 1.5s) continued running during `async_unload_entry`, causing "Not connected" write errors on registers 42020/42010. Fixed by storing the `async_track_time_interval` unsub callbacks and cancelling them at the start of unload, before closing the connection.
- Added shutdown guard in `async_update_charge_discharge` to skip all operations when coordinators are shutting down.
- Reordered `async_unload_entry` to: cancel timers → set shutdown flag → wait for in-flight ops → unload platforms → write shutdown registers → disconnect.
- Suppressed expected Modbus write errors during shutdown (respects `_is_shutting_down` flag).
- **V3 Modbus serialization**: Polling reads in `_async_update_data` now acquire the coordinator lock, preventing interleaving with control loop writes on the same TCP connection. V3 firmware mishandled concurrent requests, causing transaction ID mismatches ("extra data") and written values not being applied (e.g., write 2025W → readback 2010W).
- New `write_power_atomic()` method: writes all three power registers (discharge, charge, force mode) and reads feedback under a single lock acquisition, eliminating polling interleaving between writes.

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
