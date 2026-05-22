"""Weekly full charge management for Marstek Venus.

Owns:
- Day-based activation logic (is_active)
- Persistence of completion / registers-written across HA restarts
- Hardware register (44000) writes to allow charging to 100% on v2 batteries
- Completion detection (all batteries at 100%) and register restore
- Mid-charge abort handling when day or feature flag changes

Reads/writes the controller's existing public attributes for backward
compatibility with sensors, switches and the balance monitor that read
those attrs directly.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .const import (
    ACTIVE_BALANCE_CHARGE_POWER_W,
    ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE,
    ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE,
    ACTIVE_BALANCE_DISCHARGE_POWER_W,
    ACTIVE_BALANCE_BMS_CUTOFF_DISCHARGE_CELL_VOLTAGE,
    ACTIVE_BALANCE_DISCHARGE_START_CELL_VOLTAGE,
    ACTIVE_BALANCE_DISCHARGE_STOP_CELL_VOLTAGE,
    ACTIVE_BALANCE_HOLD_CHARGE_POWER_W,
    ACTIVE_BALANCE_HOLD_CHARGE_STOP_CELL_VOLTAGE,
    ACTIVE_BALANCE_WEEKLY_SECONDS,
    DOMAIN,
    WEEKDAY_MAP,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Inverter state raw value for "Standby" (BMS has cut off, no active charge/discharge).
_INVERTER_STATE_STANDBY = 1
# Battery power below this (W) is treated as "not charging" for BMS-cutoff detection.
_BMS_CUTOFF_POWER_W = 10
# Consecutive update cycles (~2 s each) of BMS-cutoff conditions required before
# declaring completion at 99%.  5 × 2 s = 10 s is enough to outlast the Modbus
# response delay after writing registers, but fast enough to react to a real cutoff.
_BMS_CUTOFF_REQUIRED_CYCLES = 5


class WeeklyFullChargeManager:
    """Manages weekly full charge state, persistence and register writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        controller: Any,
    ) -> None:
        self._hass = hass
        self._controller = controller
        # Bundled store: weekly charge flags + delay_unlocked + solar_t_start.
        # Format preserved for backward-compat with existing user installs.
        self._store = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.weekly_charge_state")
        # Per-battery debounce counter for BMS-cutoff detection (in-memory only).
        self._bms_cutoff_counts: dict[str, int] = {}
        self._balance_phases: dict[str, str] = {}
        self._balance_started_ts: str | None = None

    @property
    def store(self) -> Store:
        """Expose the underlying Store (for legacy attribute compatibility)."""
        return self._store

    def tick_bms_cutoff(self) -> None:
        """Update per-battery BMS-cutoff counters for the current cycle.

        Must be called exactly once per update cycle, unconditionally, at the
        top of handle_registers() before any early returns.  Both
        handle_registers() and _get_available_batteries() then query
        is_battery_full() as a read-only state check.
        """
        ctrl = self._controller
        for c in ctrl.coordinators:
            if not c.data:
                self._bms_cutoff_counts[c.name] = 0
                continue
            soc = c.data.get("battery_soc", 0)
            if soc >= 99:
                power = c.data.get("battery_power", None)
                inv_state = c.data.get("inverter_state", None)
                cutoff = (
                    power is not None
                    and inv_state is not None
                    and power <= _BMS_CUTOFF_POWER_W
                    and inv_state == _INVERTER_STATE_STANDBY
                )
                if cutoff:
                    count = self._bms_cutoff_counts.get(c.name, 0) + 1
                    self._bms_cutoff_counts[c.name] = count
                    if count == 1:
                        _LOGGER.info(
                            "%s: SOC %d%%, power=%.1fW, inverter=Standby — "
                            "possible BMS cutoff, confirming (%d/%d cycles)",
                            c.name, soc, power, count, _BMS_CUTOFF_REQUIRED_CYCLES,
                        )
                    elif count == _BMS_CUTOFF_REQUIRED_CYCLES:
                        _LOGGER.info(
                            "%s: BMS cutoff confirmed at %d%% (%d cycles at ≤%.0fW + Standby)",
                            c.name, soc, count, _BMS_CUTOFF_POWER_W,
                        )
                else:
                    if self._bms_cutoff_counts.get(c.name, 0) > 0:
                        _LOGGER.debug(
                            "%s: BMS cutoff condition cleared (power=%.1fW, inv_state=%s) — "
                            "resetting counter",
                            c.name, power or 0, inv_state,
                        )
                    self._bms_cutoff_counts[c.name] = 0
            else:
                self._bms_cutoff_counts[c.name] = 0

    def is_battery_full(self, coordinator: Any) -> bool:
        """Return True if this battery counts as fully charged.

        Read-only: does not modify _bms_cutoff_counts (tick_bms_cutoff() does).
        Used by both handle_registers() (weekly completion) and
        _get_available_batteries() (normal max_soc=100% case).
        """
        if not coordinator.data:
            return False
        soc = coordinator.data.get("battery_soc", 0)
        if soc >= 100:
            return True
        if soc >= 99:
            return self._bms_cutoff_counts.get(coordinator.name, 0) >= _BMS_CUTOFF_REQUIRED_CYCLES
        return False

    def is_active(self) -> bool:
        """Check if weekly full charge is currently active.

        Returns True if:
        - Feature is enabled
        - Today is the selected day
        - NOT all batteries have reached 100% yet

        Also handles day boundary transitions to reset the flag.
        """
        ctrl = self._controller
        if not ctrl.weekly_full_charge_enabled:
            return False

        now = datetime.now()
        current_weekday = now.weekday()
        target_weekday = WEEKDAY_MAP[ctrl.weekly_full_charge_day]

        # Handle day boundary transitions
        if ctrl.last_checked_weekday is not None and ctrl.last_checked_weekday != current_weekday:
            # Day changed - check if we're exiting the target day
            if ctrl.last_checked_weekday == target_weekday and current_weekday != target_weekday:
                # Just exited the target day - reset flags for next week
                _LOGGER.info("Weekly Full Charge: Exited %s, resetting flags for next week",
                            ctrl.weekly_full_charge_day.upper())
                ctrl.weekly_full_charge_complete = False
                ctrl.weekly_full_charge_top_reached = False
                ctrl.weekly_full_charge_registers_written = False
                ctrl._force_full_charge = False
                self._balance_phases.clear()
                self._balance_started_ts = None
                ctrl._weekly_charge_status["state"] = "Idle"
                ctrl._weekly_charge_status.pop("completion_reason", None)
                ctrl._weekly_charge_status.pop("active_balancing", None)
                ctrl._weekly_charge_status.pop("active_balance_elapsed_h", None)
                ctrl._weekly_charge_status.pop("active_balance_target_h", None)
                # Save the cleared state asynchronously (don't await to avoid blocking)
                asyncio.create_task(self.save_state())

        ctrl.last_checked_weekday = current_weekday

        # Check if we're on the target day and haven't completed yet
        is_target_day = current_weekday == target_weekday

        # Force full charge button overrides the day check
        if ctrl._force_full_charge:
            if ctrl.weekly_full_charge_complete:
                return False
            return True

        if not is_target_day:
            return False

        if ctrl.weekly_full_charge_complete:
            _LOGGER.debug("Weekly Full Charge: On target day but already completed - using normal max_soc")
            return False

        # Active: on target day and not yet complete
        return True

    async def load_state(self) -> None:
        """Load persisted weekly charge state from storage.

        This ensures that if Home Assistant is reloaded after the weekly charge
        completes, the system remembers not to restart the charging process.
        """
        ctrl = self._controller
        if not ctrl.weekly_full_charge_enabled:
            return

        try:
            data = await self._store.async_load()
            if data is None:
                _LOGGER.debug("Weekly Full Charge: No persisted state found")
                return

            today_iso = date.today().isoformat()
            stored_date = data.get("date")

            # Only restore state if saved on the same calendar date (prevents last week's
            # completion from being incorrectly restored on the same weekday next week)
            if stored_date == today_iso:
                ctrl.weekly_full_charge_complete = data.get("complete", False)
                ctrl.weekly_full_charge_top_reached = data.get("top_reached", False)
                ctrl.weekly_full_charge_registers_written = data.get("registers_written", False)
                self._balance_phases = data.get("balance_phases", {}) or {}
                self._balance_started_ts = data.get("balance_started_ts")
                # Restore visible status so the sensor reflects the correct state immediately.
                # (handle_registers() will also correct it on the next tick, but this avoids
                # a transient "Idle" flash and is correct for the "Complete" case too.)
                saved_state = data.get("state")
                if saved_state:
                    ctrl._weekly_charge_status["state"] = saved_state
                # Restore delay state
                ctrl._charge_delay_unlocked = data.get("delay_unlocked", False)
                ctrl._solar_t_start = data.get("solar_t_start")
                _LOGGER.info(
                    "Weekly Full Charge: Restored state - complete=%s, top_reached=%s, "
                    "registers_written=%s, delay_unlocked=%s",
                    ctrl.weekly_full_charge_complete,
                    ctrl.weekly_full_charge_top_reached,
                    ctrl.weekly_full_charge_registers_written,
                    ctrl._charge_delay_unlocked,
                )
            else:
                _LOGGER.debug("Weekly Full Charge: Stored state is from %s, today is %s - ignoring",
                              stored_date, today_iso)

        except Exception as e:
            _LOGGER.error("Weekly Full Charge: Failed to load persisted state: %s", e)

    async def save_state(self) -> None:
        """Save weekly charge state to persistent storage."""
        ctrl = self._controller
        if not ctrl.weekly_full_charge_enabled:
            return

        try:
            now = datetime.now()
            data = {
                "complete": ctrl.weekly_full_charge_complete,
                "top_reached": ctrl.weekly_full_charge_top_reached,
                "registers_written": ctrl.weekly_full_charge_registers_written,
                "state": ctrl._weekly_charge_status.get("state", "Idle"),
                "balance_started_ts": self._balance_started_ts,
                "balance_phases": dict(self._balance_phases),
                "date": date.today().isoformat(),
                "timestamp": now.isoformat(),
                # Delay state (bundled in the same store for legacy reasons)
                "delay_unlocked": ctrl._charge_delay_unlocked,
                "solar_t_start": ctrl._solar_t_start,
            }
            await self._store.async_save(data)
            _LOGGER.debug("Weekly Full Charge: Saved state to storage")
        except Exception as e:
            _LOGGER.error("Weekly Full Charge: Failed to save state: %s", e)

    async def handle_registers(self) -> None:
        """Manage weekly full charge register writes and completion detection.

        Runs independently of control mode (predictive/normal) to ensure
        hardware registers are properly configured when weekly charge is active.

        Responsibilities:
        - Write register 44000 to 100% on first activation (v2 only)
        - Detect completion (all batteries at 100% or BMS cutoff at 99%)
        - Restore register 44000 to configured max_soc when complete
        - Re-enable hysteresis after completion
        """
        ctrl = self._controller

        # Always tick BMS-cutoff counters unconditionally — _get_available_batteries()
        # reads is_battery_full() later in the same cycle for the normal max_soc=100% case.
        self.tick_bms_cutoff()

        # Mid-charge abort: day changed (or feature disabled) while registers were already at 100%.
        # Restore hardware cutoff to max_soc before anything else.
        if ctrl._weekly_charge_needs_restore:
            _LOGGER.info("Weekly Full Charge: Restoring hardware cutoff registers after mid-charge abort")
            for coordinator in ctrl.coordinators:
                if ctrl._is_active_balance_mode_running(coordinator):
                    continue
                cutoff_reg = coordinator.get_register("charging_cutoff_capacity")
                if ctrl._is_backup_function_active(coordinator):
                    continue
                if cutoff_reg is None:
                    _LOGGER.debug("%s: No hardware cutoff register to restore (v3 battery)", coordinator.name)
                    continue
                try:
                    # Use the saved value captured before writing 100%; fall back to current max_soc
                    # only if no saved value exists (e.g. HA restarted mid-charge).
                    original_max_soc = ctrl._weekly_charge_saved_max_soc.get(
                        coordinator.name, coordinator.max_soc
                    )
                    max_soc_value = int(original_max_soc / 0.1)
                    await coordinator.write_register(cutoff_reg, max_soc_value, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.info("%s: Restored hardware cutoff to %d%% after mid-charge abort",
                                 coordinator.name, original_max_soc)
                except Exception as e:
                    _LOGGER.error("%s: Failed to restore charging cutoff register: %s", coordinator.name, e)
            ctrl._weekly_charge_saved_max_soc.clear()
            ctrl._weekly_charge_needs_restore = False
            ctrl.weekly_full_charge_top_reached = False
            self._balance_phases.clear()
            self._balance_started_ts = None
            ctrl._weekly_charge_status["state"] = "Idle"
            ctrl._weekly_charge_status.pop("active_balancing", None)
            ctrl._weekly_charge_status.pop("completion_reason", None)
            ctrl._weekly_charge_status.pop("active_balance_elapsed_h", None)
            ctrl._weekly_charge_status.pop("active_balance_target_h", None)

        if not ctrl.weekly_full_charge_enabled and not ctrl._force_full_charge:
            return
        if not self.is_active():
            return

        # Check if unified charge delay is active - if so, don't write registers yet
        # Skip delay logic when force button was pressed
        if (ctrl.charge_delay_enabled and not ctrl._charge_delay_unlocked
                and not ctrl._force_full_charge and not ctrl._balance_monitor_overrides_delay()):
            return  # Delay is handled by _is_charge_delayed() in _is_operation_allowed()

        # Write register 44000 to 100% on first activation (v2 only - v3 uses software enforcement).
        # Also re-write after HA restart: registers_written may be True (from persisted state)
        # but async_setup_entry wrote max_soc back to the hardware register.  The empty
        # _weekly_charge_saved_max_soc dict is a reliable proxy for "not yet applied this
        # session" because it is in-memory only and starts empty on every restart.
        need_write = (not ctrl.weekly_full_charge_registers_written
                      or not ctrl._weekly_charge_saved_max_soc)
        if need_write:
            is_restart_reapply = ctrl.weekly_full_charge_registers_written
            if is_restart_reapply:
                _LOGGER.info("Weekly Full Charge: Re-applying 100%% cutoff after HA restart")
            else:
                _LOGGER.info("Weekly Full Charge: Activating for compatible batteries")
            for coordinator in ctrl.coordinators:
                if ctrl._is_active_balance_mode_running(coordinator):
                    continue
                cutoff_reg = coordinator.get_register("charging_cutoff_capacity")

                if ctrl._is_backup_function_active(coordinator):
                    _LOGGER.debug("%s: Skipping weekly full charge - backup function is active", coordinator.name)
                    continue

                if cutoff_reg is None:
                    _LOGGER.debug(
                        "%s: Weekly full charge - no hardware cutoff register (v3 battery). "
                        "Using software enforcement to 100%%.",
                        coordinator.name
                    )
                    # v3 batteries: mark as verified so the restart-proxy check doesn't
                    # loop forever when all coordinators are v3.
                    ctrl._weekly_charge_saved_max_soc[coordinator.name] = coordinator.max_soc
                    continue

                # v2 batteries: write hardware register
                try:
                    # Save original max_soc before overwriting the hardware register
                    ctrl._weekly_charge_saved_max_soc[coordinator.name] = coordinator.max_soc
                    # Write 1000 to register 44000 (100% = 1000 in register scale)
                    await coordinator.write_register(cutoff_reg, 1000, do_refresh=False)
                    await asyncio.sleep(0.1)
                    _LOGGER.debug("%s: Set hardware charging cutoff to 100%% (saved original max_soc=%d%%)",
                                  coordinator.name, coordinator.max_soc)
                except Exception as e:
                    _LOGGER.error("%s: Failed to write charging cutoff register: %s", coordinator.name, e)

            ctrl.weekly_full_charge_registers_written = True
            ctrl._weekly_charge_status["state"] = "Charging to 100%"
            ctrl._weekly_charge_status.pop("completion_reason", None)
            ctrl._weekly_charge_status.pop("active_balancing", None)
            ctrl._weekly_charge_status.pop("active_balance_elapsed_h", None)
            ctrl._weekly_charge_status.pop("active_balance_target_h", None)
            # Persist state so that the next restart can restore both registers_written
            # and the status field immediately.
            asyncio.create_task(self.save_state())

        # Check if all batteries reached the top. This starts active cell
        # balancing; completion is handled after the cells converge.
        batteries_with_data = [
            c
            for c in ctrl.coordinators
            if c.data and not ctrl._is_active_balance_mode_running(c)
        ]
        all_batteries_full = bool(batteries_with_data) and all(
            self.is_battery_full(c)
            for c in batteries_with_data
        )

        if (
            all_batteries_full
            and not ctrl.weekly_full_charge_complete
            and not ctrl.weekly_full_charge_top_reached
        ):
            ctrl.weekly_full_charge_top_reached = True
            self._balance_started_ts = datetime.now().isoformat()
            self._balance_phases = {
                c.host: "HOLD"
                for c in ctrl.coordinators
                if c.data and not ctrl._is_active_balance_mode_running(c)
            }
            ctrl._weekly_charge_status["state"] = "Active balancing"
            ctrl._weekly_charge_status.pop("completion_reason", None)
            self._bms_cutoff_counts.clear()
            _LOGGER.info(
                "Weekly Full Charge: all batteries reached the top - starting active cell balancing"
            )
            await self.save_state()

    def _weekly_balance_elapsed_seconds(self) -> float:
        """Return elapsed seconds since weekly active balancing started."""
        if not self._balance_started_ts:
            return 0.0
        try:
            started = datetime.fromisoformat(self._balance_started_ts)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, (datetime.now() - started).total_seconds())

    async def handle_active_balancing(self) -> bool:
        """Run active top-balancing micro-cycles after the weekly charge reaches 100%.

        Returns True when this manager took over the control loop for this cycle.
        """
        ctrl = self._controller
        if (
            not ctrl.weekly_full_charge_enabled
            and not ctrl._force_full_charge
        ):
            return False
        if (
            ctrl.weekly_full_charge_complete
            or not ctrl.weekly_full_charge_top_reached
            or not self.is_active()
        ):
            return False

        elapsed = self._weekly_balance_elapsed_seconds()
        if elapsed >= ACTIVE_BALANCE_WEEKLY_SECONDS:
            await self._complete_weekly_charge("active_balance_4h_complete")
            return True

        missing_cell_data = False
        status: dict[str, dict[str, Any]] = {}

        for coordinator in ctrl.coordinators:
            data = coordinator.data or {}
            if ctrl._is_active_balance_mode_running(coordinator):
                continue
            if not data:
                continue

            vmax = data.get("max_cell_voltage")
            vmin = data.get("min_cell_voltage")
            if vmax is None or vmin is None:
                missing_cell_data = True
                status[coordinator.name] = {
                    "phase": "waiting_for_cell_voltage",
                    "charge_w": 0,
                    "discharge_w": 0,
                }
                await ctrl._set_battery_power(coordinator, 0, 0)
                continue

            try:
                vmax_f = float(vmax)
                vmin_f = float(vmin)
            except (TypeError, ValueError):
                missing_cell_data = True
                status[coordinator.name] = {
                    "phase": "waiting_for_cell_voltage",
                    "charge_w": 0,
                    "discharge_w": 0,
                }
                await ctrl._set_battery_power(coordinator, 0, 0)
                continue

            delta_mv = (vmax_f - vmin_f) * 1000
            previous_phase = self._balance_phases.get(coordinator.host, "HOLD")
            phase = previous_phase
            charge_power = 0
            discharge_power = 0
            soc = data.get("battery_soc")
            power = data.get("battery_power")
            inv_state = data.get("inverter_state")
            try:
                bms_cutoff = (
                    vmax_f >= ACTIVE_BALANCE_BMS_CUTOFF_DISCHARGE_CELL_VOLTAGE
                    and phase in {"CHARGE", "HOLD"}
                    and soc is not None
                    and float(soc) >= 95
                    and power is not None
                    and abs(float(power)) <= 10
                    and inv_state == _INVERTER_STATE_STANDBY
                )
            except (TypeError, ValueError):
                bms_cutoff = False
            try:
                bms_full_lockout = (
                    vmax_f > ACTIVE_BALANCE_DISCHARGE_STOP_CELL_VOLTAGE
                    and phase == "HOLD"
                    and soc is not None
                    and float(soc) >= 99
                    and power is not None
                    and abs(float(power)) <= 10
                    and inv_state == _INVERTER_STATE_STANDBY
                )
            except (TypeError, ValueError):
                bms_full_lockout = False

            if phase == "DISCHARGE" and vmax_f > ACTIVE_BALANCE_DISCHARGE_STOP_CELL_VOLTAGE:
                discharge_power = ACTIVE_BALANCE_DISCHARGE_POWER_W
            elif (
                vmax_f >= ACTIVE_BALANCE_DISCHARGE_START_CELL_VOLTAGE
                or bms_cutoff
                or bms_full_lockout
            ):
                phase = "DISCHARGE"
                discharge_power = ACTIVE_BALANCE_DISCHARGE_POWER_W
            elif phase == "CHARGE" and vmax_f < ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE:
                charge_power = ACTIVE_BALANCE_CHARGE_POWER_W
            elif vmax_f <= ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE:
                phase = "CHARGE"
                charge_power = ACTIVE_BALANCE_CHARGE_POWER_W
            elif vmax_f < ACTIVE_BALANCE_HOLD_CHARGE_STOP_CELL_VOLTAGE:
                # HOLD zone: keep 30W charge until vmax reaches HOLD_CHARGE_STOP (3.59 V).
                # Covers vmax dropping back below CHARGE_STOP (3.53 V) after the BMS rejects
                # the hold charge — otherwise the controller would stall at 0 W until vmax
                # relaxed all the way to CHARGE_RESUME (3.45 V).
                phase = "HOLD"
                charge_power = ACTIVE_BALANCE_HOLD_CHARGE_POWER_W
            else:
                # 3.59 V <= vmax < 3.62 V: idle window before DISCHARGE_START kicks in.
                phase = "HOLD"

            self._balance_phases[coordinator.host] = phase
            status[coordinator.name] = {
                "phase": phase.lower(),
                "max_cell_voltage": round(vmax_f, 3),
                "min_cell_voltage": round(vmin_f, 3),
                "delta_mV": round(delta_mv, 1),
                "charge_w": charge_power,
                "discharge_w": discharge_power,
                "bms_cutoff": bms_cutoff,
                "bms_full_lockout": bms_full_lockout,
            }

            await ctrl._set_battery_power(
                coordinator,
                charge_power,
                discharge_power,
                ignore_charge_blockers={
                    "charge_delay",
                    "time_slot_charge",
                    "max_soc",
                    "charge_hysteresis",
                    "normal_balance_pause",
                    "normal_balance_daily_limit",
                    "user_battery_charge_disabled",
                    "ev_pause",
                },
                ignore_discharge_blockers={
                    "time_slot_discharge",
                    "price_discharge",
                    "min_soc",
                    "user_battery_discharge_disabled",
                    "ev_pause",
                    "ev_charging",
                },
            )

            if (
                phase == "DISCHARGE"
                and previous_phase in {"CHARGE", "HOLD"}
                and getattr(ctrl, "_balance_monitor", None) is not None
            ):
                await ctrl._balance_monitor.async_record_active_balance_transition(
                    coordinator,
                    vmax_f,
                    vmin_f,
                    soc,
                    previous_phase,
                    phase,
                )

        ctrl._weekly_charge_status["state"] = "Active balancing"
        ctrl._weekly_charge_status["active_balancing"] = status
        ctrl._weekly_charge_status["active_balance_elapsed_h"] = round(elapsed / 3600, 2)
        ctrl._weekly_charge_status["active_balance_target_h"] = round(
            ACTIVE_BALANCE_WEEKLY_SECONDS / 3600,
            2,
        )

        if missing_cell_data:
            _LOGGER.warning(
                "Weekly Full Charge: cell-voltage data unavailable during active balancing; "
                "holding output at 0W for affected batteries until data returns or 4h elapse"
            )

        await self.save_state()
        return True

    async def _complete_weekly_charge(self, reason: str) -> None:
        """Mark weekly full charge complete and restore configured limits."""
        ctrl = self._controller
        _LOGGER.info("Weekly Full Charge: Complete (%s) - reverting to configured limits", reason)
        ctrl.weekly_full_charge_complete = True
        ctrl.weekly_full_charge_top_reached = False
        ctrl._weekly_charge_status["state"] = "Complete"
        ctrl._weekly_charge_status["completion_reason"] = reason
        ctrl._weekly_charge_status.pop("active_balancing", None)
        ctrl._weekly_charge_status.pop("active_balance_elapsed_h", None)
        ctrl._weekly_charge_status.pop("active_balance_target_h", None)
        self._bms_cutoff_counts.clear()
        self._balance_phases.clear()
        self._balance_started_ts = None

        for coordinator in ctrl.coordinators:
            if ctrl._is_active_balance_mode_running(coordinator):
                continue
            await ctrl._set_battery_power(coordinator, 0, 0)

        # Restore register 44000 to original max_soc values (v2 only).
        for coordinator in ctrl.coordinators:
            if ctrl._is_active_balance_mode_running(coordinator):
                continue
            cutoff_reg = coordinator.get_register("charging_cutoff_capacity")

            if ctrl._is_backup_function_active(coordinator):
                _LOGGER.debug("%s: Skipping cutoff restore - backup function is active", coordinator.name)
                continue

            if cutoff_reg is None:
                _LOGGER.debug("%s: No hardware cutoff register to restore (v3 battery)", coordinator.name)
                continue

            try:
                original_max_soc = ctrl._weekly_charge_saved_max_soc.get(
                    coordinator.name, coordinator.max_soc
                )
                max_soc_value = int(original_max_soc / 0.1)
                await coordinator.write_register(cutoff_reg, max_soc_value, do_refresh=False)
                await asyncio.sleep(0.1)
                _LOGGER.debug("%s: Restored hardware cutoff to %d%% (reg=%d)",
                              coordinator.name, original_max_soc, max_soc_value)
            except Exception as e:
                _LOGGER.error("%s: Failed to restore charging cutoff register: %s", coordinator.name, e)

        ctrl._weekly_charge_saved_max_soc.clear()

        # Re-enable hysteresis for batteries that have it configured.
        for coordinator in ctrl.coordinators:
            if ctrl._is_active_balance_mode_running(coordinator):
                continue
            if coordinator.enable_charge_hysteresis:
                coordinator._hysteresis_active = True
                current_soc = coordinator.data.get("battery_soc", 100) if coordinator.data else 100
                coordinator._hysteresis_base_soc = current_soc
                _LOGGER.debug(
                    "%s: Re-enabled hysteresis after weekly full charge (base SOC: %.1f%%)",
                    coordinator.name,
                    coordinator._hysteresis_base_soc,
                )

        await self.save_state()

    def get_active_balance_status(self) -> dict[str, Any]:
        """Return diagnostics for the current weekly active-balancing phase."""
        return {
            "active": self._controller.weekly_full_charge_top_reached,
            "started": self._balance_started_ts,
            "elapsed_h": round(self._weekly_balance_elapsed_seconds() / 3600, 2),
            "target_h": round(ACTIVE_BALANCE_WEEKLY_SECONDS / 3600, 2),
            "phases": dict(self._balance_phases),
            "batteries": dict(self._controller._weekly_charge_status.get("active_balancing", {})),
        }
