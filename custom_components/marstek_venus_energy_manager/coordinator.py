"""Data update coordinator for the Marstek Venus Energy Manager integration."""
import asyncio
import logging
from datetime import timedelta, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers import entity_registry

from .const import (
    DOMAIN,
    SCAN_INTERVAL,
    DEBUG_POLL_SENSOR_SKIPS,
    DEBUG_POLL_SENSOR_VALUES,
    CONF_ACTIVE_BALANCE_MODE_ENABLED,
    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
)
from .drivers.marstek import MarstekModbusDriver
from .drivers.base import SetpointResult
from .alarm_notifier import AlarmNotifier

_LOGGER = logging.getLogger(__name__)


class MarstekVenusDataUpdateCoordinator(DataUpdateCoordinator):
    """Manages polling for data from a single Marstek Venus battery."""

    def __init__(self, hass: HomeAssistant, name: str, host: str, port: int, consumption_sensor: str,
                 battery_version: str = "v2", slave_id: int = 1,
                 max_charge_power: int = 2500, max_discharge_power: int = 2500,
                 max_soc: int = 100, min_soc: int = 12,
                 enable_charge_hysteresis: bool = False, charge_hysteresis_percent: int = 5,
                 backup_offgrid_threshold: int = 50,
                 allow_charge: bool = True, allow_discharge: bool = True,
                 active_balance_mode_enabled: bool = False,
                 full_charge_voltage_taper_enabled: bool = DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=1.5),  # Poll every 1.5 seconds for fast response
        )
        self.name = name
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.consumption_sensor = consumption_sensor

        # Validate and store battery version
        from .const import SUPPORTED_VERSIONS, DEFAULT_VERSION
        if battery_version not in SUPPORTED_VERSIONS:
            _LOGGER.error("[%s] Unsupported battery version: %s. Defaulting to %s", name, battery_version, DEFAULT_VERSION)
            self.battery_version = DEFAULT_VERSION
        else:
            self.battery_version = battery_version

        _LOGGER.info("[%s] Initialized as %s battery", name, self.battery_version)

        self.max_charge_power = max_charge_power
        self.max_discharge_power = max_discharge_power
        self.max_soc = max_soc
        self.min_soc = min_soc
        self.enable_charge_hysteresis = enable_charge_hysteresis
        self.charge_hysteresis_percent = charge_hysteresis_percent
        self.backup_offgrid_threshold = backup_offgrid_threshold
        self.allow_charge = allow_charge
        self.allow_discharge = allow_discharge
        self.active_balance_mode_enabled = active_balance_mode_enabled
        setattr(self, CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED, full_charge_voltage_taper_enabled)
        self._hysteresis_active = False  # Tracks if battery reached max_soc (for hysteresis)
        self._hysteresis_base_soc = None  # SOC that triggered hysteresis (used as threshold base)
        self.active_balance_mode_started_ts = None
        self.active_balance_mode_run_date = None
        self.active_balance_mode_top_reached = False
        self.active_balance_mode_completed_date = None
        self.active_balance_mode_completion_reason = None
        self.active_balance_mode_saved_max_soc = None
        self.active_balance_mode_cutoff_applied = False
        self.active_balance_mode_start_delta_mv = None
        self.active_balance_mode_start_delta_source = None
        self.active_balance_mode_start_max_cell_voltage = None
        self.active_balance_mode_start_min_cell_voltage = None
        self.active_balance_mode_last_cutoff_ts = None
        self.active_balance_mode_last_cutoff_delta_mv = None
        self.active_balance_mode_last_cutoff_delta_v = None
        self.active_balance_mode_last_cutoff_source = None
        self.active_balance_mode_last_cutoff_max_cell_voltage = None
        self.active_balance_mode_last_cutoff_min_cell_voltage = None
        self.active_balance_mode_last_cutoff_soc = None
        self.active_balance_mode_wait_started_ts = None
        self.active_balance_mode_retry_voltage = None
        self._scan_counter = 0
        self.lock = asyncio.Lock()
        self._is_shutting_down = False  # Flag to suppress errors during shutdown

        # Alarm/fault notifications (owns its own previous-bit state)
        self._alarm_notifier = AlarmNotifier(hass, name)

        # Connection health monitoring
        self._consecutive_failures = 0
        self._max_failures_before_reconnect = 3   # Fresh client after 3 failed poll cycles
        self._max_failures_before_suspend = 5     # Suspend after 5 failed poll cycles
        self._is_connected = False
        self._suspension_reset_time = None         # When suspended, retry after this time

        # Timestamp-based update tracking
        self._last_update_times = {}
        self._entity_registry = None
        self.rs485_user_disabled = False  # Set by RS485 switch when user explicitly disables
        self._config_entry = None  # Set after creation to allow persisting rs485_user_disabled
        self.balance_hold = False  # Legacy BalanceMonitor hold flag; kept for persisted-state cleanup

        # Hardware I/O goes through a brand-agnostic driver. The driver owns this
        # version's register/entity definitions and its version-correct timing /
        # packet correction; the coordinator and platform setups read the
        # per-platform definition lists back from it (see the passthrough
        # properties below) instead of branching on the version string.
        # ``self.client`` is kept as a transitional alias for the two remaining
        # register-level uses: the poll loop's per-battery ``unit_id`` set and the
        # config-flow connection probe (Phase 6). Telemetry reads (incl. block
        # reads) and all writes — power, config, and now the entity-write path
        # (number/select/switch/button via ``write_control``) — route through the
        # driver. The alias falls out once the probe moves behind the driver.
        self.driver = MarstekModbusDriver(
            self.host, self.port, self.battery_version, self.slave_id,
            max_charge_power_w=self.max_charge_power,
            max_discharge_power_w=self.max_discharge_power,
        )
        self.client = self.driver.client

        # Fast key -> definition lookup so the poll loop can scale each raw value by
        # its definition's scale/precision/state_class. The driver returns raw
        # decoded telemetry and owns the register layout / block grouping (see
        # ``driver.read_groups``); presentation metadata stays coordinator-side.
        self._def_by_key = {d["key"]: d for d in self._all_definitions}

        # Log sensor count for debugging
        _LOGGER.info("[%s] Total sensors to poll: %d", self.name, len(self._all_definitions))

    @property
    def capabilities(self):
        """Static hardware traits, owned by the driver (see DriverCapabilities).

        The control + entity layers consult these instead of branching on the
        version string, keeping them device-agnostic.
        """
        return self.driver.capabilities

    # Per-platform entity definitions, owned by the driver (it loads this
    # version's register/entity set). Platform setups and the poll loop read
    # these back instead of branching on the version string. ``_all_definitions``
    # is the polled union (buttons excluded); it keeps its leading underscore for
    # backward compatibility with existing readers (e.g. sensor.py).
    @property
    def sensor_definitions(self):
        return self.driver.sensor_definitions

    @property
    def number_definitions(self):
        return self.driver.number_definitions

    @property
    def select_definitions(self):
        return self.driver.select_definitions

    @property
    def switch_definitions(self):
        return self.driver.switch_definitions

    @property
    def binary_sensor_definitions(self):
        return self.driver.binary_sensor_definitions

    @property
    def button_definitions(self):
        return self.driver.button_definitions

    @property
    def _all_definitions(self):
        return self.driver.all_definitions

    @property
    def is_available(self) -> bool:
        """Return whether the battery is currently reachable."""
        return self._is_connected and not self._is_shutting_down

    @property
    def device_key(self) -> str:
        """Stable per-battery key for entity unique_ids and device identifiers.

        Backward compatible: slave id 1 keeps the historical ``{host}_{port}``
        form so existing installs are untouched. Only non-default slave ids
        (Modbus proxy setups sharing one host:port) get the ``_{slave}`` suffix.
        """
        if self.slave_id == 1:
            return f"{self.host}_{self.port}"
        return f"{self.host}_{self.port}_{self.slave_id}"

    async def connect(self) -> bool:
        """Connect to the battery via the driver."""
        connected = await self.driver.connect()
        if connected:
            self._is_connected = True
            self._consecutive_failures = 0
        return connected

    async def disconnect(self) -> None:
        """Disconnect from the battery via the driver."""
        await self.driver.close()

    async def async_reconnect_fresh(self) -> bool:
        """Close the current connection and reconnect with a fresh client.

        Creates a brand new AsyncModbusTcpClient instance which resets all
        internal state including corrupted sockets and stuck backoff timers.
        This fixes the permanent disconnection bug where v3 batteries
        (single TCP connection) refuse new connections because they still
        hold a zombie connection from the old client.

        Returns True if reconnection succeeded.
        """
        _LOGGER.warning(
            "[%s] Creating fresh connection to %s:%s (consecutive failures: %d)",
            self.name, self.host, self.port, self._consecutive_failures
        )

        async with self.lock:
            # driver.connect() internally closes the old client and creates a new one
            connected = await self.driver.connect()

            if connected:
                self._consecutive_failures = 0
                self._is_connected = True
                self._suspension_reset_time = None
                _LOGGER.info("[%s] Fresh reconnection successful", self.name)

                # Re-enable RS485 control mode after reconnection.
                # A new TCP connection may reset the battery's RS485 state,
                # causing commands to be silently ignored.
                # Skip if the user explicitly disabled RS485 via the switch.
                # Already inside self.lock, so call the driver directly (the
                # set_rs485_control wrapper would re-acquire the lock and deadlock).
                if not self.rs485_user_disabled:
                    if await self.driver.set_rs485_control(True):
                        _LOGGER.info("[%s] RS485 control mode re-enabled after reconnection", self.name)
                    else:
                        _LOGGER.warning("[%s] Failed to re-enable RS485 after reconnection", self.name)
            else:
                self._is_connected = False
                _LOGGER.warning("[%s] Fresh reconnection failed", self.name)

            return connected

    def set_shutting_down(self, value: bool) -> None:
        """
        Set the shutdown flag to suppress error logging during integration unload.
        Propagates the flag to the Modbus client.

        Args:
            value (bool): True to suppress errors, False for normal operation.
        """
        self._is_shutting_down = value
        self.driver.set_shutting_down(value)

    def set_rs485_user_disabled(self, value: bool) -> None:
        """Set rs485_user_disabled and persist the value to config entry data."""
        self.rs485_user_disabled = value
        if self._config_entry is None:
            return
        new_data = dict(self._config_entry.data)
        batteries = [dict(b) for b in new_data.get("batteries", [])]
        for battery in batteries:
            if (battery.get("host") == self.host and battery.get("port") == self.port
                    and battery.get("slave_id", 1) == self.slave_id):
                battery["rs485_user_disabled"] = value
                break
        new_data["batteries"] = batteries
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

    def persist_battery_config(self, key: str, value) -> None:
        """Persist a per-battery config value to config_entry.data so it survives restarts."""
        if self._config_entry is None:
            return
        new_data = dict(self._config_entry.data)
        batteries = [dict(b) for b in new_data.get("batteries", [])]
        for battery in batteries:
            if (battery.get("host") == self.host and battery.get("port") == self.port
                    and battery.get("slave_id", 1) == self.slave_id):
                battery[key] = value
                break
        new_data["batteries"] = batteries
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

    def set_shadow_select(self, key: str, value: int) -> None:
        """Store a written select value to override buggy register readbacks."""
        self._shadow_selects[key] = value
        self.persist_battery_config(f"shadow_select_{key}", value)

    def get_shadow_select(self, key: str) -> int | None:
        """Return the last-written value for a shadowed select, or None."""
        return self._shadow_selects.get(key)

    async def _async_update_data(self) -> dict:
        """Update all sensors asynchronously with per-sensor interval skipping.

        Sensors disabled in Home Assistant are skipped, except dependencies which are always fetched.
        Includes connection health monitoring: tracks consecutive poll failures and
        triggers fresh reconnections when the battery becomes unreachable.
        """
        from homeassistant.util.dt import utcnow
        from homeassistant.helpers import entity_registry as er

        now = utcnow()
        updated_data = {}

        if self._is_shutting_down:
            _LOGGER.debug("[%s] Shutdown in progress, skipping poll", self.name)
            return self.data or {}

        # === CONNECTION HEALTH CHECK ===
        # If connection is suspended (too many failures), wait for cooldown
        if self._suspension_reset_time is not None:
            if now >= self._suspension_reset_time:
                _LOGGER.info("[%s] Connection suspension expired - attempting fresh reconnection", self.name)
                self._suspension_reset_time = None
                self._consecutive_failures = 0
                reconnected = await self.async_reconnect_fresh()
                if not reconnected:
                    # Suspend again for another 2 minutes
                    self._suspension_reset_time = now + timedelta(minutes=2)
                    _LOGGER.warning("[%s] Reconnection failed, suspending for another 2 minutes", self.name)
                    return self.data or {}
            else:
                _LOGGER.debug("[%s] Connection suspended - skipping poll", self.name)
                return self.data or {}

        # Get the entity registry to check for disabled entities
        if self._entity_registry is None:
            self._entity_registry = er.async_get(self.hass)

        # Collect all dependency keys from calculated sensors
        from .const import EFFICIENCY_SENSOR_DEFINITIONS, STORED_ENERGY_SENSOR_DEFINITIONS, CYCLE_SENSOR_DEFINITIONS
        all_definitions_for_deps = EFFICIENCY_SENSOR_DEFINITIONS + STORED_ENERGY_SENSOR_DEFINITIONS + CYCLE_SENSOR_DEFINITIONS
        dependency_keys_set = {dep_key for defn in all_definitions_for_deps
                            for dep_key in defn.get("dependency_keys", {}).values()
                            if dep_key}
        # Cell voltage keys are always needed by the balance monitor
        dependency_keys_set.update({"max_cell_voltage", "min_cell_voltage"})
        # Control registers must keep polling even when the user disables their
        # number entities, otherwise the control loop loses its commanded power,
        # power caps and SOC cutoffs from coordinator.data and stops driving the
        # batteries.
        dependency_keys_set.update({
            "set_charge_power", "set_discharge_power",
            "max_charge_power", "max_discharge_power",
            "force_mode",
            "charging_cutoff_capacity", "discharging_cutoff_capacity",
        })

        # Set client unit ID for this battery
        self.client.unit_id = self.slave_id

        # Track read attempts vs successes for connection health monitoring
        sensors_attempted = 0
        sensors_succeeded = 0
        sensors_skipped_interval = 0
        sensors_skipped_disabled = 0
        disabled_dependencies_fetched = 0

        # Poll the driver's read groups. Each group is one schedulable unit — a
        # contiguous register block read in a single request (issue #361) or a
        # single register — and the driver owns the register layout. The
        # coordinator only schedules per group, gates disabled entities, locks per
        # group and scales the raw result. The lock is released between groups (with
        # a yield) so a control-loop writer waiting on it is not starved during a
        # poll cycle.
        for group in self.driver.read_groups:
            interval = SCAN_INTERVAL.get(group.scan_interval)
            if interval is None:
                for key in group.keys:
                    _LOGGER.warning(
                        "[%s] '%s' has no scan_interval defined, skipping this poll",
                        self.name, key,
                    )
                continue

            # Drop disabled, non-dependency keys. Block members are all dependency
            # keys, so a block group is always read in full.
            fetch_keys = []
            for key in group.keys:
                sensor = self._def_by_key.get(key, {})
                entity_type = self._get_entity_type(sensor)
                registry_entry = None
                for unique_id in (
                    f"{self.device_key}_{key}",   # current format (post-migration)
                    f"{self.host}_{key}",         # legacy format (pre-migration)
                    f"{self.name}_{key}",         # historical legacy
                ):
                    registry_entry = self._entity_registry.async_get_entity_id(
                        entity_type, DOMAIN, unique_id
                    )
                    if registry_entry:
                        break

                entry = self._entity_registry.entities.get(registry_entry) if registry_entry else None
                is_disabled = bool(entry and (entry.disabled or entry.disabled_by is not None))
                is_dependency = key in dependency_keys_set

                if is_disabled and not is_dependency:
                    sensors_skipped_disabled += 1
                    if DEBUG_POLL_SENSOR_SKIPS:
                        _LOGGER.debug("[%s] Skipping disabled entity '%s'", self.name, sensor.get("name", key))
                    continue
                if is_disabled:
                    disabled_dependencies_fetched += 1
                    if DEBUG_POLL_SENSOR_SKIPS:
                        _LOGGER.debug("[%s] Fetching disabled dependency key '%s'", self.name, key)
                fetch_keys.append(key)

            if not fetch_keys:
                continue

            # Skip the group if it was read within its interval (the group's key
            # tuple is its stable identity for scheduling).
            last_update = self._last_update_times.get(group.keys)
            elapsed = (now - last_update).total_seconds() if last_update else None
            if elapsed is not None and elapsed < interval:
                sensors_skipped_interval += 1
                continue

            # Lock ensures reads don't interleave with control loop writes.
            sensors_attempted += 1
            try:
                async with self.lock:
                    # The driver resolves the logical keys to their registers (using
                    # a block read where the keys cover a contiguous span) and
                    # returns raw decoded values; failed/unknown keys are omitted.
                    snapshot = await self.driver.read_telemetry(fetch_keys)
                # Yield so a control writer waiting on self.lock can acquire it
                # before the loop re-enters `async with` (otherwise the tight loop
                # starves apply_power).
                await asyncio.sleep(0)
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Error reading %s: %s", self.name, list(fetch_keys), e)
                continue

            if not snapshot:
                if not self._is_shutting_down:
                    _LOGGER.warning("[%s] Failed to read %s", self.name, list(fetch_keys))
                continue

            sensors_succeeded += 1
            stored = 0
            for key, value in snapshot.items():
                sensor = self._def_by_key.get(key, {})
                # Apply scaling and rounding (not applicable to char/string sensors).
                if sensor.get("data_type") != "char":
                    if "scale" in sensor:
                        value *= sensor["scale"]
                    if "precision" in sensor:
                        value = round(value, sensor["precision"])

                # Guard against firmware noise on lifetime energy counters.
                # The battery occasionally returns a partial 32-bit read mid-update,
                # yielding a value far below the real counter (e.g. 50 kWh instead of
                # 491 kWh).  A value that is non-zero but less than 90% of the last
                # known value is physically impossible for total_increasing sensors
                # and must be discarded.  Drops to exactly 0 (daily counter reset,
                # factory reset) are still accepted.
                if (
                    sensor.get("state_class") == "total_increasing"
                    and isinstance(value, (int, float))
                    and value > 0
                ):
                    prev = self.data.get(key) if self.data else None
                    if isinstance(prev, (int, float)) and prev > 0 and value < prev * 0.9:
                        _LOGGER.debug(
                            "[%s] Discarding implausible backward jump for '%s': "
                            "%.2f -> %.2f (< 90%% of previous). Likely firmware noise.",
                            self.name, key, prev, value,
                        )
                        continue

                updated_data[key] = value
                stored += 1
                if DEBUG_POLL_SENSOR_VALUES and group.scan_interval == "high":
                    _LOGGER.debug("[%s] Updated %s: %s", self.name, key, value)

            # Only advance the group's poll clock when something was actually
            # stored, so a value rejected by the backward-jump guard is retried on
            # the next cycle rather than waiting out the interval.
            if stored:
                self._last_update_times[group.keys] = now

        # === CONNECTION HEALTH TRACKING ===
        # Only track failures when we actually attempted reads (not when all sensors
        # were simply skipped because their polling interval hasn't elapsed yet)
        if sensors_attempted == 0:
            if DEBUG_POLL_SENSOR_SKIPS:
                _LOGGER.debug("[%s] No sensors due for update this cycle", self.name)
        elif sensors_succeeded > 0:
            # At least some sensors read successfully - connection is healthy
            if self._consecutive_failures > 0:
                _LOGGER.info(
                    "[%s] Connection recovered after %d consecutive failures",
                    self.name, self._consecutive_failures
                )
            self._consecutive_failures = 0
            self._is_connected = True
        else:
            # All attempted reads failed - connection issue
            self._consecutive_failures += 1

            # Mark as unavailable immediately to stop control loop writes
            self._is_connected = False

            _LOGGER.warning(
                "[%s] All %d read attempts failed (consecutive failures: %d) - marked unavailable",
                self.name, sensors_attempted, self._consecutive_failures
            )

            if self._consecutive_failures >= self._max_failures_before_reconnect:
                # Try a fresh reconnection
                _LOGGER.warning(
                    "[%s] %d consecutive failures - attempting fresh reconnection",
                    self.name, self._consecutive_failures
                )
                await self.async_reconnect_fresh()

            if self._consecutive_failures >= self._max_failures_before_suspend:
                # Too many failures - suspend polling to avoid flooding the battery
                self._suspension_reset_time = now + timedelta(minutes=2)
                _LOGGER.error(
                    "[%s] Polling suspended after %d consecutive failures. "
                    "Will retry in 2 minutes.",
                    self.name, self._consecutive_failures
                )

        # Defensive check
        if self.data is None:
            self.data = {}

        # Update the coordinator's data
        self.data.update(updated_data)

        # Detect new alarm/fault bits and send HA notifications
        await self._alarm_notifier.check(
            self.data.get("alarm_status") or 0,
            self.data.get("fault_status") or 0,
        )

        # Sync control attributes from polled register values so that changes made
        # via the UI (number entities) survive HA restarts. The hardware register is
        # the source of truth; config_entry.data holds only the initial defaults.
        if "charging_cutoff_capacity" in self.data:
            self.max_soc = int(self.data["charging_cutoff_capacity"])
        if "discharging_cutoff_capacity" in self.data:
            self.min_soc = int(self.data["discharging_cutoff_capacity"])
        if "max_charge_power" in self.data:
            self.max_charge_power = int(self.data["max_charge_power"])
        if "max_discharge_power" in self.data:
            self.max_discharge_power = int(self.data["max_discharge_power"])

        if updated_data:
            _LOGGER.debug(
                "[%s] Poll summary: attempted=%d succeeded=%d updated=%d skipped_interval=%d "
                "skipped_disabled=%d dependency_reads=%d values=%s",
                self.name,
                sensors_attempted,
                sensors_succeeded,
                len(updated_data),
                sensors_skipped_interval,
                sensors_skipped_disabled,
                disabled_dependencies_fetched,
                updated_data,
            )

        return self.data

    def _get_entity_type(self, sensor_definition: dict) -> str:
        """Determine entity type based on sensor definition."""
        key = sensor_definition["key"]

        # Check which definition list this sensor belongs to by key
        if key in [s["key"] for s in self.sensor_definitions]:
            return "sensor"
        elif key in [s["key"] for s in self.number_definitions]:
            return "number"
        elif key in [s["key"] for s in self.select_definitions]:
            return "select"
        elif key in [s["key"] for s in self.switch_definitions]:
            return "switch"
        elif key in [s["key"] for s in self.binary_sensor_definitions]:
            return "binary_sensor"
        else:
            # Default to sensor if not found
            return "sensor"

    async def write_control(self, key: str, value: int, do_refresh: bool = True):
        """Command a single logical control to a wire value via the driver.

        Semantic entity-write entry point (number/select/switch/button): the entity
        names the logical control key and the driver resolves it to hardware. This
        wrapper adds the per-coordinator infra — lock (so a poll read cannot
        interleave), health bookkeeping and the optional immediate refresh — that
        the former register-level ``write_register`` carried.
        """
        success = False
        async with self.lock:
            try:
                success = await self.driver.write_control(key, value)
                if not success:
                    if not self._is_shutting_down:
                        _LOGGER.warning("[%s] Failed to write control %s with value %d", self.name, key, value)
                else:
                    # Successful write confirms healthy connection
                    self._consecutive_failures = 0
                    self._is_connected = True
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Exception writing control %s: %s", self.name, key, e)

        # Do refresh outside the lock to avoid deadlock
        if success and do_refresh:
            _LOGGER.debug("[%s] Write successful for control %s, triggering immediate refresh", self.name, key)
            await self.async_request_refresh()

        return success

    async def apply_power(self, net_power_w: int, read_back: bool = True) -> SetpointResult:
        """Command a signed net power (+charge / -discharge) via the driver.

        Semantic write entry point for the control layer: the driver translates
        the net power to its own wire format (Marstek: force_mode + charge/
        discharge set-points) and performs the writes — plus, on a readback cycle,
        the confirmation read — while this coordinator holds ``self.lock`` so a
        poll read cannot interleave (v3 single-slot atomicity).

        Bookkeeping that belongs to the coordinator, not the hardware driver, stays
        here: the brand-native telemetry echo is merged into ``coordinator.data``,
        and the health counters / last-failure reason are updated from the result.
        When ``read_back`` is False the set-points are applied optimistically and
        the regular poll refreshes ``battery_power``.
        """
        async with self.lock:
            try:
                result = await self.driver.apply_setpoint(net_power_w, read_back=read_back)
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.warning("[%s] Power setpoint write failed: %s", self.name, e)
                self._last_write_failure_reason = "modbus_exception"
                return SetpointResult(
                    ok=False, net_power_w=0, confirmed=False, failure_reason="modbus_exception",
                )

            if result.ok and result.failure_reason is None:
                # Clean write (write-only) or clean write+readback: merge the
                # telemetry echo and mark the connection healthy.
                if result.applied and self.data:
                    self.data.update(result.applied)
                self._consecutive_failures = 0
                self._is_connected = True
                self._last_write_failure_reason = None
            else:
                # Write failed, registers missing, or the readback timed out — no
                # data merge, no health reset; surface the reason to the tracker.
                if not self._is_shutting_down and not result.ok:
                    _LOGGER.warning(
                        "[%s] Power setpoint not applied (reason=%s)",
                        self.name, result.failure_reason,
                    )
                self._last_write_failure_reason = result.failure_reason

            return result

    async def set_rs485_control(self, enable: bool) -> bool:
        """Enable/disable RS485 control mode via the driver, holding self.lock.

        Semantic entry point for the setup re-enable, shutdown disable and the
        non-delivery wake toggle. The driver owns the toggle command values; this
        wrapper only adds the per-coordinator infra (lock + health bookkeeping),
        matching write_control. No refresh. Callers already inside self.lock
        (the reconnect re-assert) must call self.driver.set_rs485_control directly
        to avoid a deadlock.
        """
        async with self.lock:
            try:
                ok = await self.driver.set_rs485_control(enable)
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Exception toggling RS485 control: %s", self.name, e)
                return False
            if ok:
                self._consecutive_failures = 0
                self._is_connected = True
            elif not self._is_shutting_down:
                _LOGGER.warning("[%s] Failed to set RS485 control=%s", self.name, enable)
            return ok

    async def apply_config(
        self,
        *,
        max_soc_pct: float,
        min_soc_pct: float,
        max_charge_power_w: int,
        max_discharge_power_w: int,
    ) -> bool:
        """Write the one-time per-battery configuration via the driver, holding self.lock.

        Semantic entry point for the setup path (max/min SOC cut-offs + power caps).
        The driver owns which registers exist for this version and the deci-percent
        scaling; this wrapper only adds the per-coordinator infra (lock + health
        bookkeeping), matching write_control / set_rs485_control. No refresh.
        """
        async with self.lock:
            try:
                ok = await self.driver.apply_config(
                    max_soc_pct=max_soc_pct,
                    min_soc_pct=min_soc_pct,
                    max_charge_power_w=max_charge_power_w,
                    max_discharge_power_w=max_discharge_power_w,
                )
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Exception writing battery config: %s", self.name, e)
                return False
            if ok:
                self._consecutive_failures = 0
                self._is_connected = True
            elif not self._is_shutting_down:
                _LOGGER.warning("[%s] One or more battery config writes failed", self.name)
            return ok

    async def set_charge_cutoff(self, soc_pct: float) -> bool:
        """Write the hardware charge-cutoff register via the driver, holding self.lock.

        Semantic entry point for the weekly-full-charge / active-balance flows
        that temporarily raise the BMS charge ceiling to 100% and later restore
        the configured max_soc. The driver owns the register address, the
        deci-percent scaling and the settle; this wrapper only adds the
        per-coordinator infra (lock + health bookkeeping), matching write_control
        / apply_config. No refresh. Callers gate the v3 (no-register) case on
        capabilities.hardware_soc_cutoff, so a False here means the write failed.
        """
        async with self.lock:
            try:
                ok = await self.driver.set_charge_cutoff(soc_pct)
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Exception writing charge cutoff: %s", self.name, e)
                return False
            if ok:
                self._consecutive_failures = 0
                self._is_connected = True
            elif not self._is_shutting_down:
                _LOGGER.warning("[%s] Failed to write charge cutoff", self.name)
            return ok

    async def standby(self) -> bool:
        """Idle the battery for teardown via the driver, holding self.lock.

        Used on integration unload. The driver owns the zero set-points + the
        shutdown-time inter-write pacing; this wrapper only adds the lock so a
        stray poll cannot interleave. No health bookkeeping (the connection is
        about to close) and no refresh.
        """
        async with self.lock:
            try:
                return await self.driver.standby()
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Exception setting standby: %s", self.name, e)
                return False
