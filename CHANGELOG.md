# Changelog

## [1.1.1] - 2026-02-27

### Fixed
- **Incorrect time slot translations**: Fixed descriptions in English, German, French, and Dutch that incorrectly stated batteries "will NOT discharge" during slots. The correct behavior is the opposite — batteries are ALLOWED to discharge during configured slots and blocked outside them. Spanish translations were already correct.
- **Midnight-crossing slot runtime logic removed**: Simplified `_is_operation_allowed()` and `_get_active_slot()` to remove dead midnight-crossing code, since midnight-crossing slots are now rejected at configuration time.

## [1.1.0] - 2026-02-27

### Added
- **Configurable target grid power per time slot**: The PD controller can now regulate toward a user-defined grid power target instead of the fixed 0W. Each time slot includes a `target_grid_power` field (range: -500W to +500W, default: 0W). Negative values target slight export (e.g. -150W), positive values allow slight import. Outside of active time slots, the controller defaults to 0W. This enables economic optimization for tariff setups where feed-in is more valuable than self-consumption.
- **Minimum charge/discharge power per time slot**: Each time slot can now define `min_charge_power` and `min_discharge_power` thresholds (range: 0-500W, default: 0W = disabled). When the PD controller output is below the configured minimum, the controller stays idle instead of operating at inefficient low power levels. This reduces micro-cycling, unnecessary battery wear, and improves roundtrip efficiency.
- **Time slot overlap validation**: The config flow now rejects time slots that overlap with existing ones on shared days. Also prevents midnight-crossing slots (start >= end) to avoid day-ambiguity — users must create two separate slots for overnight periods instead.

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
