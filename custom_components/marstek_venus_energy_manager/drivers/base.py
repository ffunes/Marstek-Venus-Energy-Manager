"""Brand-agnostic battery driver contract.

This is the seam between the control layer (coordinator + ChargeDischargeController)
and the hardware. It is deliberately *semantic*, not register-shaped: the only
operations it exposes are "give me a telemetry snapshot" and "deliver this net
power". A Modbus/register battery (Marstek) and an MQTT/property battery (Zendure)
can both sit behind it because neither register addresses nor MQTT topics appear
in the contract.

Two model differences the contract reconciles:

* **Poll vs push.** Marstek is polled every ~1.5 s; Zendure pushes telemetry over
  MQTT. :meth:`BatteryDriver.read_telemetry` is a *pull* of the latest known
  state — a push-based driver caches the last message and returns it, so the
  coordinator's poll loop is unchanged.
* **Control semantics.** Marstek wants ``force_mode`` + separate charge/discharge
  set-point registers; Zendure wants an input/output limit. The control loop
  speaks a single signed *net power* (+charge / -discharge) via
  :meth:`BatteryDriver.apply_setpoint`; each driver translates to its own wire
  format internally.

Nothing imports this module yet — it defines the target contract. It is filled
in incrementally; see ``docs/plans/driver_abstraction.md`` for the phase plan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DriverCapabilities:
    """Static, brand/model-specific traits the control layer branches on.

    Replaces the ``if self.battery_version in ("v3", "vA", "vD")`` checks that are
    currently scattered through the coordinator and control loop. A driver reports
    its capabilities once; callers consult them instead of hard-coding versions.
    """

    # True if the hardware enforces SOC charge/discharge cut-offs itself. When
    # False the control layer must enforce min/max SOC in software (Marstek v3/vA/vD
    # have no cut-off registers; v2 does).
    hardware_soc_cutoff: bool

    # True if the hardware supports a distinct force/charge/discharge mode command
    # (Marstek force_mode). A driver that only takes a signed power limit reports
    # False and ignores the ``mode`` hint in apply_setpoint.
    has_force_mode: bool

    # Telemetry arrives by push (MQTT) rather than poll (Modbus). The coordinator
    # uses this to decide whether read_telemetry is a live read or a cache read.
    push_telemetry: bool

    # Inclusive power envelope the hardware accepts, in watts (per battery unit).
    max_charge_power_w: int
    max_discharge_power_w: int

    # True if the hardware has DC-coupled PV / MPPT inputs (Marstek Venus D/A).
    # The control layer uses this to decide whether the unit contributes solar
    # production and needs DC-plane efficiency integration. AC-only models report
    # False.
    has_mppt_pv: bool

    # True if the hardware exposes alarm/fault status registers (Marstek v2 only).
    # Gates the system alarm sensor.
    has_alarm_registers: bool

    # True if external (RS485/Modbus) control mode can be toggled on this hardware.
    has_rs485_control: bool


@dataclass(frozen=True)
class SetpointResult:
    """Outcome of an :meth:`BatteryDriver.apply_setpoint` call.

    ``net_power_w`` is the commanded signed power that was actually applied
    (+charge / -discharge), clamped to the driver's envelope. ``confirmed`` is
    True only when the driver read the command back from the hardware and it
    matched; a write-only fast path returns the optimistic command with
    ``confirmed=False``.
    """

    ok: bool
    net_power_w: int
    confirmed: bool
    # Brief machine-readable reason when ``ok`` is False (e.g. "write_failed",
    # "not_connected", "feedback_timeout"). None on success.
    failure_reason: Optional[str] = None
    # Measured delivered power (signed W, +charge / -discharge) read back from the
    # hardware on a confirmation cycle; None on the write-only fast path
    # (``read_back=False``). Universal telemetry the control layer uses for
    # non-delivery detection — independent of any register/property layout.
    battery_power_w: Optional[int] = None
    # Brand-native state echo for the coordinator's telemetry cache
    # (``coordinator.data``). The coordinator merges this verbatim so it need not
    # know the keys: Marstek returns ``force_mode`` + ``set_charge_power`` +
    # ``set_discharge_power`` (plus ``battery_power`` on a readback cycle). None
    # only when the command failed before anything was applied.
    applied: Optional[dict] = None


# Telemetry is a flat mapping of logical sensor key -> decoded value, exactly the
# shape the coordinator already stores in ``coordinator.data`` today (e.g.
# {"battery_soc": 47, "battery_power": -612, ...}). Kept as a plain dict so the
# existing sensor/aggregate layers need no change.
TelemetrySnapshot = dict


@dataclass(frozen=True)
class ReadGroup:
    """A schedulable unit of telemetry the coordinator polls as one request.

    The driver groups its telemetry keys so the coordinator can schedule, gate and
    lock *per group* without knowing the register layout: a Modbus driver collapses
    a contiguous register span into one block group (read in a single request) and
    exposes every other key as its own singleton group; a push driver can expose a
    single group of everything it caches. ``scan_interval`` is the poll-cadence
    name the coordinator maps to seconds (None means the group is misconfigured and
    is skipped with a warning); ``keys`` are the logical telemetry keys read
    together — passed verbatim to :meth:`BatteryDriver.read_telemetry` — and double
    as the group's stable identity for per-group poll scheduling.
    """

    scan_interval: Optional[str]
    keys: tuple[str, ...]


class BatteryDriver(ABC):
    """Abstract hardware driver for a single physical battery.

    One instance per battery (per coordinator). Owns its transport and connection
    state. All methods are async because every real transport (Modbus TCP, MQTT)
    is I/O bound.
    """

    # --- identity -----------------------------------------------------------

    @property
    @abstractmethod
    def capabilities(self) -> DriverCapabilities:
        """Static traits of this battery (see :class:`DriverCapabilities`)."""

    # --- connection lifecycle ----------------------------------------------

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the driver currently holds a live link to the hardware."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish the link. Return True on success. Idempotent / re-callable."""

    @abstractmethod
    async def close(self) -> None:
        """Tear the link down and release any single-slot resource (e.g. the v3
        TCP slot). Safe to call when already closed."""

    @abstractmethod
    def set_shutting_down(self, value: bool) -> None:
        """Suppress error logging during integration unload / HA shutdown."""

    # --- telemetry (read) ---------------------------------------------------

    @property
    @abstractmethod
    def read_groups(self) -> list[ReadGroup]:
        """Telemetry keys grouped into schedulable poll units (see :class:`ReadGroup`).

        The coordinator iterates these to schedule, gate and lock per group rather
        than branching on register layout. A polled Modbus driver returns one group
        per contiguous register block (read in a single request) plus a singleton
        group per remaining key; a push driver may return a single group of its
        cached state.
        """

    @abstractmethod
    async def read_telemetry(self, keys: Optional[list[str]] = None) -> TelemetrySnapshot:
        """Return the latest decoded telemetry as a logical-key -> value mapping.

        ``keys`` optionally restricts the read to the given logical keys (used by
        the coordinator to honour per-sensor poll intervals and skip disabled
        entities); None means "everything this driver knows". A polled driver
        reads the hardware now; a push driver returns its cached last state.
        Missing/failed values are omitted rather than set to None.
        """

    # --- control (write) ----------------------------------------------------

    @abstractmethod
    async def apply_setpoint(
        self,
        net_power_w: int,
        *,
        mode_hint: Optional[str] = None,
        read_back: bool = True,
    ) -> SetpointResult:
        """Command a signed net power: +charge / -discharge, 0 = idle/hold.

        The driver translates to its own wire format (Marstek: force_mode +
        charge/discharge registers; Zendure: input/output limit). ``mode_hint``
        is an optional control-layer intent ("charge"/"discharge"/"idle") that
        drivers with an explicit mode command may use; sign of ``net_power_w`` is
        authoritative. ``read_back=False`` skips confirmation to cut bus traffic
        (result carries ``confirmed=False``).
        """

    @abstractmethod
    async def write_control(self, key: str, value: int) -> bool:
        """Command a single logical control to a wire value.

        Generic entity-write path for the user-facing number/select/switch/button
        entities: the entity names a logical control *key* (e.g. ``force_mode``,
        ``rs485_control_mode``, a select option's underlying value) and supplies the
        already-encoded wire value; the driver resolves the key to its own wire
        detail (Marstek: the register address). This keeps the platform code
        register-free so a non-Modbus brand whose definitions carry no "register"
        does not break here. Returns True if the write was accepted, False if this
        driver has no control for the key or the write failed.
        """
