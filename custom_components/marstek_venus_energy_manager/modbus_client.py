"""
Helper module for Modbus TCP communication using pymodbus.
Provides an abstraction for reading and writing registers from
a Marstek Venus battery system asynchronously.
"""

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusIOException
import asyncio
from typing import Optional

import logging

_LOGGER = logging.getLogger(__name__)


def _marstek_v3_packet_correction(sending: bool, data: bytes) -> bytes:
    """Fix malformed Modbus exception responses from Marstek v3 firmware.

    The v3 firmware incorrectly sets the MBAP length byte to 4 instead of 3
    in exception responses. This causes pymodbus to wait for an extra byte
    that never arrives, resulting in long timeouts.

    Exception response structure (9 bytes):
      [0-1] Transaction ID, [2-3] Protocol ID, [4-5] Length (should be 3),
      [6] Unit ID, [7] Function code (bit 7=1 for exception), [8] Exception code
    """
    if not sending and len(data) == 9 and data[5] == 4 and (data[7] & 0x80) == 0x80:
        return data[0:5] + b'\x03' + data[6:]
    return data


class MarstekModbusClient:
    """
    Wrapper for pymodbus AsyncModbusTcpClient with helper methods
    for async reading/writing and interpreting common data types.
    """

    def __init__(self, host: str, port: int = 502, message_wait_ms: int = 50, timeout: int = 10, is_v3: bool = False):
        """
        Initialize Modbus client with host, port, message wait time, and timeout.

        Args:
            host (str): IP address or hostname of Modbus server.
            port (int): TCP port number.
            message_wait_ms (int): Delay in ms between Modbus messages.
            timeout (int): Connection timeout in seconds.
            is_v3 (bool): If True, enable v3 firmware packet correction.
        """
        self.host = host
        self.port = port

        # Store constructor params for creating fresh client instances on reconnect
        self._host = host
        self._port = port
        self._timeout = timeout
        self._is_v3 = is_v3
        self._message_wait_ms = message_wait_ms

        # Create pymodbus async TCP client instance with auto-reconnect disabled.
        # We manage reconnection ourselves by creating fresh client instances,
        # which avoids pymodbus's internal reconnect_delay growing up to 300s.
        self.client = AsyncModbusTcpClient(
            host=host,
            port=port,
            timeout=timeout,
            reconnect_delay=0,
            reconnect_delay_max=0,
        )

        # Set v3 packet correction as attribute (compatible across all pymodbus 3.x)
        if is_v3:
            self.client.trace_packet = _marstek_v3_packet_correction

        self.client.message_wait_milliseconds = message_wait_ms
        self.unit_id = 1  # Default Unit ID
        self._is_shutting_down = False  # Flag to suppress errors during shutdown

    def set_shutting_down(self, value: bool) -> None:
        """
        Set the shutdown flag to suppress error logging during integration unload.

        Args:
            value (bool): True to suppress errors, False for normal operation.
        """
        self._is_shutting_down = value

    @property
    def connected(self) -> bool:
        """Return whether the client is currently connected."""
        return self.client is not None and self.client.connected

    async def async_connect(self) -> bool:
        """
        Connect asynchronously to the Modbus TCP server.

        Always creates a fresh AsyncModbusTcpClient instance to avoid reusing
        internal buffers/state that may be left in an inconsistent state after
        network interruptions. This also resets pymodbus's internal reconnect
        delay which can grow up to 300 seconds after repeated failures.

        Returns:
            bool: True if connection succeeded, False otherwise.
        """
        try:
            # Close and discard existing client to release the battery's
            # single TCP connection slot and avoid half-open connections
            if self.client is not None:
                try:
                    result = self.client.close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

            # Create a fresh client instance (no corrupted state, no backoff)
            self.client = AsyncModbusTcpClient(
                host=self._host,
                port=self._port,
                timeout=self._timeout,
                reconnect_delay=0,
                reconnect_delay_max=0,
            )

            # Restore v3 packet correction and timing
            if self._is_v3:
                self.client.trace_packet = _marstek_v3_packet_correction
            self.client.message_wait_milliseconds = self._message_wait_ms

            connected = await self.client.connect()

            if connected:
                await asyncio.sleep(0.2)  # Wait for connection to stabilize
                _LOGGER.info(
                    "Connected to Modbus server at %s:%s with unit %s",
                    self.host,
                    self.port,
                    self.unit_id,
                )
                return True
            else:
                if not self._is_shutting_down:
                    _LOGGER.warning(
                        "Failed to connect to Modbus server at %s:%s with unit %s",
                        self.host,
                        self.port,
                        self.unit_id,
                    )
                return False
        except Exception as e:
            if not self._is_shutting_down:
                _LOGGER.error(
                    "Exception connecting to Modbus server at %s:%s: %s",
                    self.host,
                    self.port,
                    e,
                )
            return False

    async def async_close(self) -> None:
        """
        Close the Modbus TCP connection safely (handles sync or async close).
        """
        if self.client is None:
            return
        try:
            result = self.client.close()
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            _LOGGER.debug("Error closing Modbus connection: %s", e)

    async def async_read_register(
        self,
        register: int,
        data_type: str = "uint16",
        count: Optional[int] = None,
        bit_index: Optional[int] = None,
        sensor_key: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 0.1,
    ):
        """
        Robustly read registers and interpret the data asynchronously with retries.

        Args:
            register (int): Register address to read from.
            data_type (str): Data type for interpretation, e.g. 'int16', 'int32', 'char', 'bit'.
            count (Optional[int]): Number of registers to read (default depends on data_type).
            bit_index (Optional[int]): Bit position for 'bit' data type (0-15).
            sensor_key (Optional[str]): Sensor key for logging.
            max_retries (int): Maximum number of read attempts.
            retry_delay (float): Delay in seconds between retries.

        Returns:
            int, str, bool, or None: Interpreted value or None on error.
        """

        if count is None:
            count = 2 if data_type in ["int32", "uint32"] else 1

        if not (0 <= register <= 0xFFFF):
            _LOGGER.error(
                "Invalid register address: %d (0x%04X). Must be 0-65535.",
                register,
                register,
            )
            return None

        if not (1 <= count <= 125):  # Modbus spec limit
            _LOGGER.error(
                "Invalid register count: %d. Must be between 1 and 125.",
                count,
            )
            return None

        attempt = 0
        current_retry_delay = retry_delay
        
        while attempt < max_retries:
            # Skip connection check - let pymodbus handle connection issues
            # This avoids problems with incorrect connection state reporting

            try:
                result = await asyncio.wait_for(
                    self.client.read_holding_registers(address=register, count=count),
                    timeout=self._timeout,
                )
                if result.isError():
                    if not self._is_shutting_down:
                        _LOGGER.error(
                            "Modbus read error at register %d (0x%04X) on attempt %d",
                            register,
                            register,
                            attempt + 1,
                        )
                elif not hasattr(result, "registers") or result.registers is None or len(result.registers) < count:
                    if not self._is_shutting_down:
                        _LOGGER.warning(
                            "Incomplete data received at register %d (0x%04X) on attempt %d: expected %d registers, got %s",
                            register,
                            register,
                            attempt + 1,
                            count,
                            len(result.registers) if result.registers else 0,
                        )
                else:
                    regs = result.registers
                    _LOGGER.debug(
                        "Requesting register %d (0x%04X) for sensor '%s' (type: %s, count: %s)",
                        register,
                        register,
                        sensor_key or 'unknown',
                        data_type,
                        count,
                    )
                    _LOGGER.debug("Received data from register %d (0x%04X): %s", register, register, regs)
                    _LOGGER.debug("Raw value for register %d (0x%04X): %s", register, register, regs[0] if regs else None)

                    if data_type == "int16":
                        val = regs[0]
                        return val - 0x10000 if val >= 0x8000 else val

                    elif data_type == "uint16":
                        return regs[0]

                    elif data_type == "int32":
                        if len(regs) < 2:
                            _LOGGER.warning(
                                "Expected 2 registers for int32 at register %d (0x%04X), got %s",
                                register,
                                register,
                                len(regs),
                            )
                            return None
                        val = (regs[0] << 16) | regs[1]
                        return val - 0x100000000 if val >= 0x80000000 else val

                    elif data_type == "uint32":
                        if len(regs) < 2:
                            _LOGGER.warning(
                                "Expected 2 registers for uint32 at register %d (0x%04X), got %s",
                                register,
                                register,
                                len(regs),
                            )
                            return None
                        return (regs[0] << 16) | regs[1]

                    elif data_type == "uint48":
                        if len(regs) < 3:
                            _LOGGER.warning(
                                "Expected 3 registers for uint48 at register %d (0x%04X), got %s",
                                register,
                                register,
                                len(regs),
                            )
                            return None
                        return (regs[0] << 32) | (regs[1] << 16) | regs[2]

                    elif data_type == "uint64":
                        if len(regs) < 4:
                            _LOGGER.warning(
                                "Expected 4 registers for uint64 at register %d (0x%04X), got %s",
                                register,
                                register,
                                len(regs),
                            )
                            return None
                        return (regs[0] << 48) | (regs[1] << 32) | (regs[2] << 16) | regs[3]

                    elif data_type == "char":
                        byte_array = bytearray()
                        for reg in regs:
                            byte_array.append((reg >> 8) & 0xFF)
                            byte_array.append(reg & 0xFF)
                        return byte_array.decode("ascii", errors="ignore").rstrip('\x00')

                    elif data_type == "bit":
                        if bit_index is None or not (0 <= bit_index < 16):
                            raise ValueError("bit_index must be between 0 and 15 for bit data_type")
                        reg_val = regs[0]
                        return bool((reg_val >> bit_index) & 1)

                    else:
                        raise ValueError(f"Unsupported data_type: {data_type}")

            except (ConnectionException, ModbusIOException, asyncio.TimeoutError):
                if self._is_shutting_down:
                    return None
                # Connection is dead or unresponsive — try to create a fresh connection
                _LOGGER.debug("Connection lost during read of register %d (0x%04X), attempting reconnect", register)
                reconnected = await self.async_connect()
                if not reconnected:
                    _LOGGER.debug("Reconnect failed for register %d (0x%04X) read - aborting", register, register)
                    return None
                # Fresh connection established — retry the read once more
                _LOGGER.info("Reconnected successfully, retrying read of register %d (0x%04X)", register, register)
                attempt += 1  # Count reconnect as an attempt to prevent infinite loops
                continue

            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.exception("Exception during Modbus read at register %d (0x%04X) on attempt %d: %s", register, register, attempt + 1, e)

            # During shutdown, don't retry or reconnect - exit immediately to release the connection
            if self._is_shutting_down:
                return None

            attempt += 1
            if attempt < max_retries:
                # Exponential backoff with jitter
                jitter = current_retry_delay * 0.1 * (0.5 - asyncio.get_event_loop().time() % 1)
                await asyncio.sleep(current_retry_delay + jitter)
                current_retry_delay = min(current_retry_delay * 2, 5.0)  # Cap at 5 seconds

        _LOGGER.debug(
            "Failed to read register %d (0x%04X) after %d attempts",
            register,
            register,
            max_retries,
        )
        return None

    async def async_write_register(self, register: int, value: int, max_retries: int = 3, retry_delay: float = 0.1) -> bool:
        """
        Write a single value to a Modbus holding register asynchronously.

        Args:
            register (int): Register address to write to.
            value (int): Value to write.

        Returns:
            bool: True if write was successful, False otherwise.
        """
        attempt = 0
        current_retry_delay = retry_delay
        
        while attempt < max_retries:
            # Skip connection check for write operations too
            # Let pymodbus handle connection issues

            try:
                _LOGGER.debug("Writing value %s to register %d (0x%04X)", value, register, register)
                result = await asyncio.wait_for(
                    self.client.write_register(address=register, value=value),
                    timeout=self._timeout,
                )
                return not result.isError()

            except (ConnectionException, ModbusIOException, asyncio.TimeoutError):
                if self._is_shutting_down:
                    return False
                # Connection is dead or unresponsive — try to create a fresh connection
                _LOGGER.debug("Connection lost during write to register %d (0x%04X), attempting reconnect", register)
                reconnected = await self.async_connect()
                if not reconnected:
                    _LOGGER.debug("Reconnect failed for register %d (0x%04X) write - aborting", register, register)
                    return False
                # Fresh connection established — retry the write once more
                _LOGGER.info("Reconnected successfully, retrying write to register %d (0x%04X)", register, register)
                attempt += 1  # Count reconnect as an attempt to prevent infinite loops
                continue

            except Exception as e:
                if not self._is_shutting_down:
                    _LOGGER.exception("Exception during modbus write at register %d (0x%04X) on attempt %d: %s", register, register, attempt + 1, e)

            # During shutdown, don't retry or reconnect - exit immediately to release the connection
            if self._is_shutting_down:
                return False

            attempt += 1
            if attempt < max_retries:
                # Exponential backoff with jitter
                jitter = current_retry_delay * 0.1 * (0.5 - asyncio.get_event_loop().time() % 1)
                await asyncio.sleep(current_retry_delay + jitter)
                current_retry_delay = min(current_retry_delay * 2, 5.0)  # Cap at 5 seconds

        _LOGGER.debug(
            "Failed to write register %d (0x%04X) after %d attempts",
            register,
            register,
            max_retries,
        )
        return False
