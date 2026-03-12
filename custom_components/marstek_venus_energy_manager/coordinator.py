"""Data update coordinator for the Marstek Venus Energy Manager integration."""
import asyncio
import logging
from datetime import timedelta, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers import entity_registry

from .const import (
    DOMAIN,
    SENSOR_DEFINITIONS,
    SCAN_INTERVAL,
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    SWITCH_DEFINITIONS,
    BINARY_SENSOR_DEFINITIONS,
    BUTTON_DEFINITIONS,
    MESSAGE_WAIT_MS,
)
from .modbus_client import MarstekModbusClient

_LOGGER = logging.getLogger(__name__)


class MarstekVenusDataUpdateCoordinator(DataUpdateCoordinator):
    """Manages polling for data from a single Marstek Venus battery."""

    def __init__(self, hass: HomeAssistant, name: str, host: str, port: int, consumption_sensor: str,
                 battery_version: str = "v2",
                 max_charge_power: int = 2500, max_discharge_power: int = 2500,
                 max_soc: int = 100, min_soc: int = 12,
                 enable_charge_hysteresis: bool = False, charge_hysteresis_percent: int = 5) -> None:
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
        self.consumption_sensor = consumption_sensor

        # Validate and store battery version
        from .const import SUPPORTED_VERSIONS, DEFAULT_VERSION
        if battery_version not in SUPPORTED_VERSIONS:
            _LOGGER.error("[%s] Unsupported battery version: %s. Defaulting to %s", name, battery_version, DEFAULT_VERSION)
            self.battery_version = DEFAULT_VERSION
        else:
            self.battery_version = battery_version

        _LOGGER.info("[%s] Initialized as %s battery", name, self.battery_version)

        # Create Modbus client with version-specific timing and packet correction
        wait_ms = MESSAGE_WAIT_MS.get(self.battery_version, 50)
        is_v3 = self.battery_version in ("v3", "vA", "vD")
        self.client = MarstekModbusClient(host, port, message_wait_ms=wait_ms, is_v3=is_v3)

        self.max_charge_power = max_charge_power
        self.max_discharge_power = max_discharge_power
        self.max_soc = max_soc
        self.min_soc = min_soc
        self.enable_charge_hysteresis = enable_charge_hysteresis
        self.charge_hysteresis_percent = charge_hysteresis_percent
        self._hysteresis_active = False  # Tracks if battery reached max_soc (for hysteresis)
        self._scan_counter = 0
        self.lock = asyncio.Lock()
        self._is_shutting_down = False  # Flag to suppress errors during shutdown

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

        # Load version-specific definitions
        if self.battery_version == "v3":
            from .const import (
                SENSOR_DEFINITIONS_V3,
                NUMBER_DEFINITIONS_V3,
                SELECT_DEFINITIONS_V3,
                SWITCH_DEFINITIONS_V3,
                BINARY_SENSOR_DEFINITIONS_V3,
                BUTTON_DEFINITIONS_V3,
            )
            self.sensor_definitions = SENSOR_DEFINITIONS_V3
            self.number_definitions = NUMBER_DEFINITIONS_V3
            self.select_definitions = SELECT_DEFINITIONS_V3
            self.switch_definitions = SWITCH_DEFINITIONS_V3
            self.binary_sensor_definitions = BINARY_SENSOR_DEFINITIONS_V3
            self.button_definitions = BUTTON_DEFINITIONS_V3
            self._all_definitions = (
                SENSOR_DEFINITIONS_V3 +
                NUMBER_DEFINITIONS_V3 +
                SELECT_DEFINITIONS_V3 +
                SWITCH_DEFINITIONS_V3 +
                BINARY_SENSOR_DEFINITIONS_V3
            )
        elif self.battery_version in ("vA", "vD"):
            from .const import (
                SENSOR_DEFINITIONS_VA,
                NUMBER_DEFINITIONS_VA,
                NUMBER_DEFINITIONS_VD,
                SELECT_DEFINITIONS_VA,
                SELECT_DEFINITIONS_VD,
                SWITCH_DEFINITIONS_V3,
                BINARY_SENSOR_DEFINITIONS_V3,
                BUTTON_DEFINITIONS_V3,
            )
            sensor_defs = SENSOR_DEFINITIONS_VA  # identical for vA and vD
            number_defs = NUMBER_DEFINITIONS_VA if self.battery_version == "vA" else NUMBER_DEFINITIONS_VD
            select_defs = SELECT_DEFINITIONS_VA if self.battery_version == "vA" else SELECT_DEFINITIONS_VD
            self.sensor_definitions = sensor_defs
            self.number_definitions = number_defs
            self.select_definitions = select_defs
            self.switch_definitions = SWITCH_DEFINITIONS_V3
            self.binary_sensor_definitions = BINARY_SENSOR_DEFINITIONS_V3
            self.button_definitions = BUTTON_DEFINITIONS_V3
            self._all_definitions = (
                sensor_defs +
                number_defs +
                select_defs +
                SWITCH_DEFINITIONS_V3 +
                BINARY_SENSOR_DEFINITIONS_V3
            )
        else:  # v2 (default)
            self.sensor_definitions = SENSOR_DEFINITIONS
            self.number_definitions = NUMBER_DEFINITIONS
            self.select_definitions = SELECT_DEFINITIONS
            self.switch_definitions = SWITCH_DEFINITIONS
            self.binary_sensor_definitions = BINARY_SENSOR_DEFINITIONS
            self.button_definitions = BUTTON_DEFINITIONS
            self._all_definitions = (
                SENSOR_DEFINITIONS +
                NUMBER_DEFINITIONS +
                SELECT_DEFINITIONS +
                SWITCH_DEFINITIONS +
                BINARY_SENSOR_DEFINITIONS
            )

        # Log sensor count for debugging
        _LOGGER.info("[%s] Total sensors to poll: %d", self.name, len(self._all_definitions))

    @property
    def is_available(self) -> bool:
        """Return whether the battery is currently reachable."""
        return self._is_connected and not self._is_shutting_down

    async def connect(self) -> bool:
        """Connect to the Modbus client."""
        connected = await self.client.async_connect()
        if connected:
            self._is_connected = True
            self._consecutive_failures = 0
        return connected

    async def disconnect(self) -> None:
        """Disconnect from the Modbus client."""
        await self.client.async_close()

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
            # async_connect() internally closes old client and creates a new one
            connected = await self.client.async_connect()

            if connected:
                self._consecutive_failures = 0
                self._is_connected = True
                self._suspension_reset_time = None
                _LOGGER.info("[%s] Fresh reconnection successful", self.name)

                # Re-enable RS485 control mode after reconnection.
                # A new TCP connection may reset the battery's RS485 state,
                # causing commands to be silently ignored.
                # Skip if the user explicitly disabled RS485 via the switch.
                if not self.rs485_user_disabled:
                    rs485_reg = self.get_register("rs485_control")
                    if rs485_reg:
                        self.client.unit_id = 1
                        ok = await self.client.async_write_register(rs485_reg, 21930)  # 0x55AA
                        if ok:
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
        self.client.set_shutting_down(value)

    def get_register(self, key: str) -> int | None:
        """Get register address for this battery's version.

        Args:
            key: Logical register name (e.g., 'battery_soc', 'force_mode')

        Returns:
            Register address or None if not available for this version
        """
        from .const import REGISTER_MAP

        register = REGISTER_MAP.get(self.battery_version, {}).get(key)
        if register is None:
            _LOGGER.debug(
                "[%s] Register '%s' not available for %s",
                self.name, key, self.battery_version
            )
        return register

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

        _LOGGER.debug("[%s] Coordinator poll tick at %s", self.name, now.isoformat())

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
        from .const import EFFICIENCY_SENSOR_DEFINITIONS, STORED_ENERGY_SENSOR_DEFINITIONS
        all_definitions_for_deps = EFFICIENCY_SENSOR_DEFINITIONS + STORED_ENERGY_SENSOR_DEFINITIONS
        dependency_keys_set = {dep_key for defn in all_definitions_for_deps
                            for dep_key in defn.get("dependency_keys", {}).values()
                            if dep_key}

        # Set client unit ID for this battery
        self.client.unit_id = 1

        # Track read attempts vs successes for connection health monitoring
        sensors_attempted = 0
        sensors_succeeded = 0

        # Iterate over each sensor definition to poll if due
        for sensor in self._all_definitions:
            key = sensor["key"]
            
            # Determine entity type for registry lookup
            entity_type = self._get_entity_type(sensor)
            # Try both unique_id formats - the one used in entities and the one used for lookup
            unique_id_formats = [
                f"{self.host}_{sensor['key']}",  # Format used in sensor.py
                f"{self.name}_{sensor['key']}",  # Format used in coordinator lookup
            ]
            
            registry_entry = None
            for unique_id in unique_id_formats:
                registry_entry = self._entity_registry.async_get_entity_id(
                    entity_type, DOMAIN, unique_id
                )
                if registry_entry:
                    break

            # Determine if the entity is disabled in Home Assistant
            is_disabled = False
            entry = self._entity_registry.entities.get(registry_entry) if registry_entry else None
            if entry:
                is_disabled = entry.disabled or entry.disabled_by is not None

            # Check if this key is a dependency key for any calculated sensor
            is_dependency = key in dependency_keys_set

            # Skip polling if entity is disabled unless it is a dependency key
            if is_disabled:
                if is_dependency:
                    _LOGGER.debug("[%s] Fetching disabled dependency key '%s'", self.name, key)
                else:
                    _LOGGER.debug("[%s] Skipping disabled entity '%s'", self.name, sensor.get("name", key))
                continue

            # Determine polling interval for this sensor
            interval_name = sensor.get("scan_interval")
            interval = SCAN_INTERVAL.get(interval_name)

            if interval is None:
                _LOGGER.warning(
                    "[%s] %s '%s' has no scan_interval defined, skipping this poll",
                    self.name,
                    entity_type,
                    key,
                )
                continue

            # Check when this sensor was last updated and skip if within interval
            last_update = self._last_update_times.get(key)
            elapsed = (now - last_update).total_seconds() if last_update else None

            if elapsed is not None and elapsed < interval:
                _LOGGER.debug(
                    "[%s] Skipping %s '%s', last update %.1fs ago (%ds)",
                    self.name,
                    entity_type,
                    key,
                    elapsed,
                    interval,
                )
                continue

            # Attempt to read the sensor value from Modbus
            # Lock ensures reads don't interleave with control loop writes
            sensors_attempted += 1
            try:
                async with self.lock:
                    value = await self.client.async_read_register(
                        register=sensor["register"],
                        data_type=sensor.get("data_type", "uint16"),
                        count=sensor.get("count"),
                        sensor_key=key,
                    )

                if value is not None:
                    sensors_succeeded += 1
                    # Apply scaling if defined
                    if "scale" in sensor:
                        value *= sensor["scale"]
                    
                    # Apply rounding if precision is defined
                    if "precision" in sensor:
                        value = round(value, sensor["precision"])
                    
                    updated_data[key] = value
                    self._last_update_times[key] = now
                    
                    # Log high priority updates for debugging
                    if interval_name == "high":
                        _LOGGER.debug("[%s] Updated %s: %s", self.name, key, value)
                else:
                    if not self._is_shutting_down:
                        _LOGGER.warning("[%s] Failed to read %s (register %d)", self.name, key, sensor["register"])

            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Error reading register %d for %s: %s",
                                 self.name, sensor["register"], key, e)

        # === CONNECTION HEALTH TRACKING ===
        # Only track failures when we actually attempted reads (not when all sensors
        # were simply skipped because their polling interval hasn't elapsed yet)
        if sensors_attempted == 0:
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

        # Log updates for debugging
        if updated_data:
            _LOGGER.debug("[%s] Updated %d sensors: %s", self.name, len(updated_data), list(updated_data.keys()))

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

    async def write_register(self, register: int, value: int, do_refresh: bool = True):
        """Write a value to a register and optionally do an immediate refresh."""
        success = False
        async with self.lock:
            self.client.unit_id = 1

            try:
                success = await self.client.async_write_register(register, value)
                if not success:
                    if not self._is_shutting_down:
                        _LOGGER.warning("[%s] Failed to write register %d with value %d", self.name, register, value)
                else:
                    # Successful write confirms healthy connection
                    self._consecutive_failures = 0
                    self._is_connected = True
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Exception writing register %d: %s", self.name, register, e)

        # Do refresh outside the lock to avoid deadlock
        if success and do_refresh:
            _LOGGER.debug("[%s] Write successful for register %d, triggering immediate refresh", self.name, register)
            await self.async_request_refresh()

        return success

    async def async_read_power_feedback(self) -> dict | None:
        """Read power-related registers for immediate feedback after control loop write.

        Returns dict with: force_mode, set_charge_power, set_discharge_power, battery_power
        Or None if read fails.
        """
        async with self.lock:
            self.client.unit_id = 1
            try:
                # Get version-specific registers
                force_mode_reg = self.get_register("force_mode")
                set_charge_reg = self.get_register("set_charge_power")
                set_discharge_reg = self.get_register("set_discharge_power")
                battery_power_reg = self.get_register("battery_power")

                if None in [force_mode_reg, set_charge_reg, set_discharge_reg, battery_power_reg]:
                    if not self._is_shutting_down:
                        _LOGGER.error("[%s] Missing required registers for power feedback", self.name)
                    return None

                # Use version-specific data type for battery power
                power_dtype = "int16" if self.battery_version in ("v3", "vA", "vD") else "int32"

                # Read the registers we just wrote + actual power
                force_mode = await self.client.async_read_register(force_mode_reg, "uint16")
                set_charge = await self.client.async_read_register(set_charge_reg, "uint16")
                set_discharge = await self.client.async_read_register(set_discharge_reg, "uint16")
                battery_power = await self.client.async_read_register(battery_power_reg, power_dtype)

                if None in (force_mode, set_charge, set_discharge, battery_power):
                    if not self._is_shutting_down:
                        _LOGGER.error("[%s] Failed to read one or more feedback registers", self.name)
                    return None

                # Update coordinator.data with fresh values
                if self.data:
                    self.data["force_mode"] = force_mode
                    self.data["set_charge_power"] = set_charge
                    self.data["set_discharge_power"] = set_discharge
                    self.data["battery_power"] = battery_power

                return {
                    "force_mode": force_mode,
                    "set_charge_power": set_charge,
                    "set_discharge_power": set_discharge,
                    "battery_power": battery_power,
                }
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.warning("[%s] Failed to read power feedback: %s", self.name, e)
                return None

    async def write_power_atomic(
        self, discharge_power: int, charge_power: int, force_mode: int
    ) -> dict | None:
        """Write all power registers and read feedback atomically under a single lock.

        This prevents coordinator polling reads from interleaving with control loop
        writes, which causes the v3 firmware to miss or corrupt commands.

        Returns feedback dict or None if any operation fails.
        """
        async with self.lock:
            self.client.unit_id = 1

            discharge_reg = self.get_register("set_discharge_power")
            charge_reg = self.get_register("set_charge_power")
            force_reg = self.get_register("force_mode")
            battery_power_reg = self.get_register("battery_power")

            if None in [discharge_reg, charge_reg, force_reg, battery_power_reg]:
                if not self._is_shutting_down:
                    _LOGGER.error("[%s] Missing required registers for atomic power write", self.name)
                return None

            try:
                # Write all 3 registers without releasing lock
                ok1 = await self.client.async_write_register(discharge_reg, discharge_power)
                await asyncio.sleep(0.05)
                ok2 = await self.client.async_write_register(charge_reg, charge_power)
                await asyncio.sleep(0.05)
                ok3 = await self.client.async_write_register(force_reg, force_mode)

                if not (ok1 and ok2 and ok3):
                    if not self._is_shutting_down:
                        _LOGGER.warning(
                            "[%s] Atomic power write partial failure: discharge=%s, charge=%s, force=%s",
                            self.name, ok1, ok2, ok3
                        )
                    return None

                # Wait for battery to process commands
                await asyncio.sleep(0.2)

                # Read feedback within same lock (no interleaving)
                power_dtype = "int16" if self.battery_version in ("v3", "vA", "vD") else "int32"
                force_fb = await self.client.async_read_register(force_reg, "uint16")
                charge_fb = await self.client.async_read_register(charge_reg, "uint16")
                discharge_fb = await self.client.async_read_register(discharge_reg, "uint16")
                power_fb = await self.client.async_read_register(battery_power_reg, power_dtype)

                if None in (force_fb, charge_fb, discharge_fb, power_fb):
                    if not self._is_shutting_down:
                        _LOGGER.warning("[%s] Atomic power feedback read failed", self.name)
                    return None

                # Update coordinator.data with fresh values
                if self.data:
                    self.data["force_mode"] = force_fb
                    self.data["set_charge_power"] = charge_fb
                    self.data["set_discharge_power"] = discharge_fb
                    self.data["battery_power"] = power_fb

                # Successful write+read confirms healthy connection
                self._consecutive_failures = 0
                self._is_connected = True

                return {
                    "force_mode": force_fb,
                    "set_charge_power": charge_fb,
                    "set_discharge_power": discharge_fb,
                    "battery_power": power_fb,
                }
            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.warning("[%s] Atomic power write failed: %s", self.name, e)
                return None
