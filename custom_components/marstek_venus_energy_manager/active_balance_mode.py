"""Active balance mode for Marstek Venus.

Owns the scheduled per-battery active balancing run:
- State machine: PRE_TOP_CHARGE -> CHARGE -> WAIT_MEASURE ->
  DISCHARGE / FINAL_DISCHARGE.
- Adaptive charge-resume voltage with BMS-rejection detection.
- Temporary max_soc / hardware cutoff override so PD can drive the battery
  to 100% during the pre-top run-up.
- Persistent notifications on start / completion.

Per-battery persistent state lives on the coordinator (active_balance_mode_*
attributes) for backward compatibility with sensors, switches and the
restore code in async_setup_entry. The manager owns only the in-memory
cross-cycle dicts.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_BALANCE_ADAPTIVE_MIN_RESUME_CELL_VOLTAGE,
    ACTIVE_BALANCE_ADAPTIVE_RESUME_STEP_V,
    ACTIVE_BALANCE_CHARGE_POWER_W,
    ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE,
    ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE,
    ACTIVE_BALANCE_DISCHARGE_POWER_W,
    ACTIVE_BALANCE_DISCHARGE_STOP_CELL_VOLTAGE,
    ACTIVE_BALANCE_FINAL_DISCHARGE_STOP_CELL_VOLTAGE,
    ACTIVE_BALANCE_MEASURE_WAIT_SECONDS,
    ACTIVE_BALANCE_MODE_TARGET_DELTA_V,
    CONF_ACTIVE_BALANCE_MODE_ENABLED,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ActiveBalanceModeManager:
    """Manages per-battery scheduled active balance mode."""

    def __init__(self, hass: "HomeAssistant", controller) -> None:
        self._hass = hass
        self._controller = controller
        self._active_balance_mode_phases: dict = {}
        self._active_balance_charge_resume_targets: dict = {}
        self._active_balance_mode_status: dict[str, dict] = {}
        # Restore in-memory phase from persisted coordinator attrs.
        for coordinator in controller.coordinators:
            saved_phase = getattr(coordinator, "active_balance_mode_phase", None)
            if (
                getattr(coordinator, "active_balance_mode_started_ts", None)
                and saved_phase
                in {
                    "PRE_TOP_CHARGE",
                    "CHARGE",
                    "WAIT_MEASURE",
                    "DISCHARGE",
                    "FINAL_DISCHARGE",
                    "HOLD",
                    # legacy phase labels (pre power-name removal)
                    "CHARGE_50W",
                    "DISCHARGE_25W",
                    "FINAL_DISCHARGE_25W",
                }
            ):
                legacy_map = {
                    "CHARGE_50W": "CHARGE",
                    "HOLD": "CHARGE",
                    "DISCHARGE_25W": "DISCHARGE",
                    "FINAL_DISCHARGE_25W": "FINAL_DISCHARGE",
                }
                self._active_balance_mode_phases[coordinator] = legacy_map.get(
                    saved_phase,
                    saved_phase,
                )

    def _active_balance_charge_resume_target(self, coordinator) -> float:
        """Return the current adaptive cell voltage where charge should be retried."""
        return self._active_balance_charge_resume_targets.get(
            coordinator,
            ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE,
        )

    def _reset_active_balance_charge_resume_target(self, coordinator) -> None:
        """Reset adaptive retry voltage for a battery leaving active balancing."""
        self._active_balance_charge_resume_targets.pop(coordinator, None)

    def _lower_active_balance_charge_resume_target(
        self,
        coordinator,
        vmax_f: float,
    ) -> float:
        """Lower the charge retry point after the BMS rejects charge.

        Steps the retry voltage down by ``ACTIVE_BALANCE_ADAPTIVE_RESUME_STEP_V``,
        but also forces it strictly below the voltage at which the charge was
        rejected. Without the vmax-relative bound a BMS that refuses charge at a
        low resting voltage (e.g. SOC-100 full lockout at vmax ~3.48 V) leaves the
        DISCHARGE target (min(retry, stop)) at or above the current vmax, so the
        escape discharge never runs and the run ping-pongs between CHARGE and
        DISCHARGE forever. Bounding by vmax guarantees a real discharge that drops
        SOC off the lockout so the next charge is accepted. In the original
        high-vmax OVP case (rejection near the stop voltage) the current-step
        bound still dominates, so behaviour there is unchanged.
        """
        current = self._active_balance_charge_resume_target(coordinator)
        next_target = round(
            max(
                ACTIVE_BALANCE_ADAPTIVE_MIN_RESUME_CELL_VOLTAGE,
                min(
                    current - ACTIVE_BALANCE_ADAPTIVE_RESUME_STEP_V,
                    vmax_f - ACTIVE_BALANCE_ADAPTIVE_RESUME_STEP_V,
                ),
            ),
            3,
        )
        if next_target != current:
            self._active_balance_charge_resume_targets[coordinator] = next_target
            _LOGGER.info(
                "%s: active balance charge rejected at vmax=%.3f V; "
                "lowering retry point to %.3f V",
                coordinator.name,
                vmax_f,
                next_target,
            )
        return next_target

    def _active_balance_charge_rejected_detected(
        self,
        coordinator,
        phase: str,
    ) -> bool:
        """Return True when the BMS rejects a charge command but delivers no charge.

        Two BMS OVP failure modes are covered:
        - BMS keeps inv_state=2 (Charge mode) while delivering 0W after OVP cut.
        - BMS reverts both force_mode and set_charge_power registers; intent is
          tracked via coordinator._ab_charge_cmd_active set at end of each cycle.
        """
        if phase not in {"CHARGE", "HOLD"}:
            return False
        data = coordinator.data or {}
        power = data.get("battery_power")
        inv_state = data.get("inverter_state")
        force_mode = data.get("force_mode")
        set_charge_power = data.get("set_charge_power")
        try:
            force_mode_value = int(float(force_mode)) if force_mode is not None else None
            charge_was_requested = (
                force_mode_value == 1
                or (
                    set_charge_power is not None
                    and float(set_charge_power) > 0
                )
                or getattr(coordinator, "_ab_charge_cmd_active", False)
            )
            return (
                charge_was_requested
                and power is not None
                and abs(float(power)) <= 10
                and inv_state in {1, 2}
            )
        except (TypeError, ValueError):
            return False

    def _active_balance_mode_delta_v(self, coordinator) -> float | None:
        """Return current cell delta in V for the scheduled active balance mode."""
        data = coordinator.data or {}
        vmax = data.get("max_cell_voltage")
        vmin = data.get("min_cell_voltage")
        if vmax is None or vmin is None:
            return None
        try:
            return float(vmax) - float(vmin)
        except (TypeError, ValueError):
            return None

    def _active_balance_mode_cell_values(self, coordinator) -> tuple[float | None, float | None, float | None]:
        """Return current vmax/vmin/delta values for active-balance notifications."""
        data = coordinator.data or {}
        vmax = data.get("max_cell_voltage")
        vmin = data.get("min_cell_voltage")
        if vmax is None or vmin is None:
            return None, None, None
        try:
            vmax_f = float(vmax)
            vmin_f = float(vmin)
        except (TypeError, ValueError):
            return None, None, None
        return vmax_f, vmin_f, vmax_f - vmin_f

    async def _record_active_balance_mode_measurement(
        self,
        coordinator,
        details: dict,
        source: str = "measurement_3.58V",
    ) -> None:
        """Store the latest balance measurement for result notifications.

        ``source`` distinguishes a normal 3.58 V top measurement from one taken
        when the BMS cut charge before reaching the 3.58 V stop voltage.
        """
        final_delta = details.get("delta_V")
        if final_delta is None:
            return
        data = coordinator.data or {}
        cutoff_ts = dt_util.now().isoformat()
        coordinator.active_balance_mode_last_cutoff_ts = cutoff_ts
        coordinator.active_balance_mode_last_cutoff_delta_v = final_delta
        coordinator.active_balance_mode_last_cutoff_delta_mv = final_delta
        coordinator.active_balance_mode_last_cutoff_source = source
        coordinator.active_balance_mode_last_cutoff_max_cell_voltage = details.get("max_cell_voltage")
        coordinator.active_balance_mode_last_cutoff_min_cell_voltage = details.get("min_cell_voltage")
        coordinator.active_balance_mode_last_cutoff_soc = data.get("battery_soc")
        self._controller._persist_battery_runtime_config(
            coordinator,
            {
                "active_balance_mode_last_cutoff_ts": cutoff_ts,
                "active_balance_mode_last_cutoff_delta_v": final_delta,
                "active_balance_mode_last_cutoff_delta_mv": final_delta,
                "active_balance_mode_last_cutoff_source": source,
                "active_balance_mode_last_cutoff_max_cell_voltage": details.get("max_cell_voltage"),
                "active_balance_mode_last_cutoff_min_cell_voltage": details.get("min_cell_voltage"),
                "active_balance_mode_last_cutoff_soc": data.get("battery_soc"),
            },
        )
        monitor = getattr(self._controller, "_balance_monitor", None)
        if monitor is not None:
            await monitor.async_record_active_balance_measurement(
                coordinator,
                details.get("max_cell_voltage"),
                details.get("min_cell_voltage"),
                data.get("battery_soc"),
                getattr(coordinator, "active_balance_mode_phase", None),
            )

    def _active_balance_mode_last_recorded_delta_v(self, coordinator) -> tuple[float | None, str]:
        """Return the last official 3.58 V balance measurement, else instant delta."""
        delta, _vmax, _vmin, source = self._active_balance_mode_initial_snapshot(coordinator)
        return delta, source

    def _active_balance_mode_initial_snapshot(
        self, coordinator
    ) -> tuple[float | None, float | None, float | None, str]:
        """Return (delta_V, vmax_V, vmin_V, source) for the start notification.

        Prefers the last official 3.58 V balance measurement stored by the
        BalanceMonitor so the start figures match a real cutoff reading.
        Falls back to the current instant cell values if no measurement is
        available (e.g. first ever run with empty history).
        """
        monitor = getattr(self._controller, "_balance_monitor", None)
        if monitor is not None:
            readings = monitor.get_recent_readings(coordinator.device_key, limit=1)
            if readings:
                last = readings[-1]
                try:
                    delta_mv = float(last.get("delta_mV"))
                    vmax = float(last.get("vmax_V"))
                    vmin = float(last.get("vmin_V"))
                except (TypeError, ValueError):
                    delta_mv = None
                    vmax = None
                    vmin = None
                if delta_mv is not None and vmax is not None and vmin is not None:
                    ts = last.get("ts")
                    source = f"measurement_3.58V ({ts})" if ts else "measurement_3.58V"
                    return delta_mv / 1000.0, vmax, vmin, source
        vmax_f, vmin_f, delta_v = self._active_balance_mode_cell_values(coordinator)
        return delta_v, vmax_f, vmin_f, "instant"

    def _format_active_balance_value(self, value, unit: str, decimals: int = 1) -> str:
        """Format optional numeric values for active-balance notifications."""
        if value is None:
            return "n/a"
        try:
            return f"{float(value):.{decimals}f} {unit}"
        except (TypeError, ValueError):
            return "n/a"

    def _format_delta_mv(self, value_v) -> str:
        """Format a delta stored in volts as mV, matching the Cell Delta sensor."""
        if value_v is None:
            return "n/a"
        try:
            return f"{float(value_v) * 1000:.0f} mV"
        except (TypeError, ValueError):
            return "n/a"

    def _active_balance_notification_id(
        self,
        coordinator,
        kind: str,
        started_ts: str | None = None,
        reason: str | None = None,
    ) -> str:
        """Build a per-run persistent notification ID for active balance events."""

        def _sanitize(value: object) -> str:
            text = str(value)
            cleaned = "".join(ch if ch.isalnum() else "_" for ch in text)
            return cleaned.strip("_") or "unknown"

        parts = [
            "marstek_active_balance_mode",
            kind,
            coordinator.device_key,
        ]
        if started_ts:
            parts.append(started_ts)
        if reason:
            parts.append(reason)
        return "_".join(_sanitize(part) for part in parts)

    async def _dismiss_persistent_notification(self, notification_id: str) -> None:
        """Dismiss a persistent notification if it exists."""
        try:
            await self._hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": notification_id},
            )
        except Exception as err:
            _LOGGER.debug(
                "Failed to dismiss persistent notification %s: %s",
                notification_id,
                err,
            )

    async def _dismiss_legacy_active_balance_notifications(self, coordinator) -> None:
        """Dismiss pre per-run active-balance notification IDs."""
        await self._dismiss_persistent_notification(
            f"marstek_active_balance_mode_start_{coordinator.device_key}"
        )
        await self._dismiss_persistent_notification(
            f"marstek_active_balance_mode_result_{coordinator.device_key}"
        )

    async def _notify_active_balance_mode_started(
        self,
        coordinator,
        started_ts: str,
    ) -> None:
        """Send a persistent notification when a scheduled balance run starts."""
        start_delta = getattr(coordinator, "active_balance_mode_start_delta_mv", None)
        message = "\n".join(
            [
                f"📊 Initial delta: {self._format_delta_mv(start_delta)}",
                f"🎯 Runs until delta ≤ {ACTIVE_BALANCE_MODE_TARGET_DELTA_V * 1000:.0f} mV "
                f"or you stop it.",
                "🚫 Battery paused from normal control while balancing.",
            ]
        )
        try:
            await self._dismiss_legacy_active_balance_notifications(coordinator)
            await self._hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"🔋 Active balancing started - {coordinator.name}",
                    "message": message,
                    "notification_id": self._active_balance_notification_id(
                        coordinator,
                        "start",
                        started_ts,
                    ),
                },
            )
        except Exception as err:
            _LOGGER.warning(
                "%s: failed to create active balance start notification: %s",
                coordinator.name,
                err,
            )

    async def _notify_active_balance_mode_completed(
        self,
        coordinator,
        reason: str,
        started_ts: str | None,
        elapsed_h: float | None,
    ) -> None:
        """Send a persistent notification with the scheduled balance result."""
        reason_text = {
            "delta_reasonable": "Delta within reasonable range",
            "final_discharge_complete": "Delta within range and final discharge complete",
            "disabled": "Stopped by user",
        }.get(reason, reason)

        final_delta = getattr(coordinator, "active_balance_mode_last_cutoff_delta_v", None)
        if final_delta is None:
            final_delta = getattr(coordinator, "active_balance_mode_last_cutoff_delta_mv", None)
        if final_delta is None:
            monitor = getattr(self._controller, "_balance_monitor", None)
            if monitor is not None:
                readings = monitor.get_recent_readings(coordinator.device_key, limit=1)
                if readings:
                    try:
                        final_delta = float(readings[-1].get("delta_mV")) / 1000.0
                    except (TypeError, ValueError):
                        final_delta = None
        start_delta = getattr(coordinator, "active_balance_mode_start_delta_mv", None)
        improvement = None
        if start_delta is not None and final_delta is not None:
            try:
                improvement = float(start_delta) - float(final_delta)
            except (TypeError, ValueError):
                improvement = None

        message = "\n".join(
            [
                f"✅ {reason_text}",
                f"📊 Delta: {self._format_delta_mv(start_delta)} → "
                f"{self._format_delta_mv(final_delta)} "
                f"(improvement {self._format_delta_mv(improvement)})",
                f"⏱️ Duration: {self._format_active_balance_value(elapsed_h, 'h', 2)}",
            ]
        )
        try:
            await self._dismiss_legacy_active_balance_notifications(coordinator)
            if started_ts:
                await self._dismiss_persistent_notification(
                    self._active_balance_notification_id(
                        coordinator,
                        "start",
                        started_ts,
                    )
                )
            await self._hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"✅ Active balancing finished - {coordinator.name}",
                    "message": message,
                    "notification_id": self._active_balance_notification_id(
                        coordinator,
                        "result",
                        started_ts,
                        reason,
                    ),
                },
            )
        except Exception as err:
            _LOGGER.warning(
                "%s: failed to create active balance result notification: %s",
                coordinator.name,
                err,
            )

    def _is_active_balance_mode_running(self, coordinator) -> bool:
        """Return True when active balance mode owns this battery's power control.

        The active-balance handler owns the pre-top run-up too, because it sends
        an explicit max-charge command to this battery while PD keeps managing
        the rest of the system.
        """
        return bool(
            getattr(coordinator, "active_balance_mode_started_ts", None)
            or coordinator in self._active_balance_mode_phases
        )

    def _active_balance_mode_started(self, coordinator) -> bool:
        """Return True when an active-balance run is in progress (any phase)."""
        return bool(getattr(coordinator, "active_balance_mode_started_ts", None))

    def get_active_balance_mode_status(self) -> dict:
        """Return diagnostic status for the per-battery active balance mode."""
        return dict(self._active_balance_mode_status)

    async def _apply_active_balance_mode_cutoff(self, coordinator) -> None:
        """Temporarily raise the hardware charge cutoff and software max_soc to 100%.

        Bumps both:
          * Hardware register (v2 only): so the BMS itself allows charging to 100%.
          * Software ``coordinator.max_soc``: so the PD loop is allowed to drive
            this battery to the top during the pre-top run-up. Without this PD
            would cap charge at the user's configured max_soc (e.g. 80%) and
            never reach the 3.45 V balancing window.

        Both originals are saved on the coordinator and restored on completion.
        """
        if getattr(coordinator, "active_balance_mode_cutoff_applied", False):
            return

        if self._controller._is_backup_function_active(coordinator):
            _LOGGER.debug(
                "%s: skipping active balance mode cutoff write because backup is active",
                coordinator.name,
            )
            return

        updates = {}
        if getattr(coordinator, "active_balance_mode_saved_max_soc", None) is None:
            coordinator.active_balance_mode_saved_max_soc = coordinator.max_soc
            updates["active_balance_mode_saved_max_soc"] = coordinator.max_soc

        # Bump software max_soc unconditionally so PD can charge to 100% during
        # the pre-top run-up. Hardware register write below is v2-only.
        coordinator.max_soc = 100

        cutoff_reg = coordinator.get_register("charging_cutoff_capacity")
        if cutoff_reg is None:
            coordinator.active_balance_mode_cutoff_applied = True
            _LOGGER.info(
                "%s: active balance mode raised software max_soc to 100%% "
                "(v3 — no hardware cutoff register)",
                coordinator.name,
            )
        else:
            try:
                await coordinator.write_register(cutoff_reg, 1000, do_refresh=False)
                await asyncio.sleep(0.1)
                coordinator.active_balance_mode_cutoff_applied = True
                _LOGGER.info(
                    "%s: active balance mode raised software max_soc and hardware "
                    "charging cutoff to 100%%",
                    coordinator.name,
                )
            except Exception as err:
                _LOGGER.error(
                    "%s: failed to set active balance mode hardware cutoff: %s",
                    coordinator.name,
                    err,
                )

        if updates:
            self._controller._persist_battery_runtime_config(coordinator, updates)

    async def _restore_active_balance_mode_cutoff(self, coordinator) -> None:
        """Restore the hardware charge cutoff and software max_soc saved before balance mode."""
        saved_max_soc = getattr(coordinator, "active_balance_mode_saved_max_soc", None)
        if saved_max_soc is None:
            coordinator.active_balance_mode_cutoff_applied = False
            return

        # Restore software max_soc first so PD respects the original limit on the
        # next cycle, regardless of whether the hardware write succeeds.
        coordinator.max_soc = saved_max_soc

        cutoff_reg = coordinator.get_register("charging_cutoff_capacity")
        if cutoff_reg is not None and not self._controller._is_backup_function_active(coordinator):
            try:
                await coordinator.write_register(
                    cutoff_reg,
                    int(saved_max_soc / 0.1),
                    do_refresh=False,
                )
                await asyncio.sleep(0.1)
                _LOGGER.info(
                    "%s: active balance mode restored software max_soc and hardware "
                    "charging cutoff to %d%%",
                    coordinator.name,
                    saved_max_soc,
                )
            except Exception as err:
                _LOGGER.error(
                    "%s: failed to restore active balance mode hardware cutoff: %s",
                    coordinator.name,
                    err,
                )
        else:
            _LOGGER.info(
                "%s: active balance mode restored software max_soc to %d%%",
                coordinator.name,
                saved_max_soc,
            )

        coordinator.active_balance_mode_saved_max_soc = None
        coordinator.active_balance_mode_cutoff_applied = False
        self._controller._persist_battery_runtime_config(
            coordinator,
            {"active_balance_mode_saved_max_soc": None},
        )

    async def _complete_active_balance_mode(
        self,
        coordinator,
        reason: str,
        today: str,
        mark_completed: bool = True,
    ) -> None:
        """Stop and mark one scheduled active-balance run complete."""
        started_ts = getattr(coordinator, "active_balance_mode_started_ts", None)
        elapsed_h = None
        if started_ts:
            try:
                elapsed_h = max(
                    0.0,
                    (dt_util.now() - datetime.fromisoformat(started_ts)).total_seconds() / 3600,
                )
            except (TypeError, ValueError):
                elapsed_h = None

        if started_ts:
            await self._notify_active_balance_mode_completed(
                coordinator,
                reason,
                started_ts,
                elapsed_h,
            )
        else:
            await self._dismiss_legacy_active_balance_notifications(coordinator)

        self._active_balance_mode_phases.pop(coordinator, None)
        self._reset_active_balance_charge_resume_target(coordinator)
        await self._restore_active_balance_mode_cutoff(coordinator)
        coordinator.active_balance_mode_started_ts = None
        coordinator.active_balance_mode_run_date = None
        coordinator.active_balance_mode_phase = None
        coordinator.active_balance_mode_wait_started_ts = None
        coordinator.active_balance_mode_retry_voltage = None
        coordinator.active_balance_mode_top_reached = False
        coordinator.active_balance_mode_completed_date = today if mark_completed else None
        coordinator.active_balance_mode_completion_reason = reason
        coordinator.active_balance_mode_start_delta_mv = None
        coordinator.active_balance_mode_start_delta_source = None
        coordinator.active_balance_mode_start_max_cell_voltage = None
        coordinator.active_balance_mode_start_min_cell_voltage = None
        coordinator.active_balance_mode_last_cutoff_ts = None
        coordinator.active_balance_mode_last_cutoff_delta_v = None
        coordinator.active_balance_mode_last_cutoff_delta_mv = None
        coordinator.active_balance_mode_last_cutoff_source = None
        coordinator.active_balance_mode_last_cutoff_max_cell_voltage = None
        coordinator.active_balance_mode_last_cutoff_min_cell_voltage = None
        coordinator.active_balance_mode_last_cutoff_soc = None
        persist_updates: dict = {
            "active_balance_mode_started_ts": None,
            "active_balance_mode_run_date": None,
            "active_balance_mode_phase": None,
            "active_balance_mode_wait_started_ts": None,
            "active_balance_mode_retry_voltage": None,
            "active_balance_mode_top_reached": False,
            "active_balance_mode_completed_date": today if mark_completed else None,
            "active_balance_mode_completion_reason": reason,
            "active_balance_mode_start_delta_mv": None,
            "active_balance_mode_start_delta_source": None,
            "active_balance_mode_start_max_cell_voltage": None,
            "active_balance_mode_start_min_cell_voltage": None,
            "active_balance_mode_last_cutoff_ts": None,
            "active_balance_mode_last_cutoff_delta_v": None,
            "active_balance_mode_last_cutoff_delta_mv": None,
            "active_balance_mode_last_cutoff_source": None,
            "active_balance_mode_last_cutoff_max_cell_voltage": None,
            "active_balance_mode_last_cutoff_min_cell_voltage": None,
            "active_balance_mode_last_cutoff_soc": None,
        }
        if mark_completed:
            coordinator.active_balance_mode_enabled = False
            persist_updates[CONF_ACTIVE_BALANCE_MODE_ENABLED] = False
        self._controller._persist_battery_runtime_config(coordinator, persist_updates)
        await self._controller._set_battery_power(coordinator, 0, 0)
        _LOGGER.info("%s: active balance mode completed (%s)", coordinator.name, reason)

    async def _handle_active_balance_mode(self) -> None:
        """Run per-battery active balancing while leaving PD to other batteries."""
        now = dt_util.now()
        today = now.date().isoformat()
        statuses: dict[str, dict] = {}

        for coordinator in self._controller.coordinators:
            enabled = bool(getattr(coordinator, "active_balance_mode_enabled", False))
            started_ts = getattr(coordinator, "active_balance_mode_started_ts", None)

            if not enabled:
                if self._active_balance_mode_started(coordinator):
                    await self._complete_active_balance_mode(
                        coordinator,
                        "disabled",
                        today,
                        mark_completed=False,
                    )
                statuses[coordinator.name] = {"enabled": False, "state": "disabled"}
                continue

            if not started_ts:
                started_ts = now.isoformat()
                coordinator.active_balance_mode_started_ts = started_ts
                coordinator.active_balance_mode_run_date = today
                coordinator.active_balance_mode_phase = "PRE_TOP_CHARGE"
                coordinator.active_balance_mode_top_reached = False
                coordinator.active_balance_mode_completed_date = None
                coordinator.active_balance_mode_completion_reason = None
                coordinator.active_balance_mode_wait_started_ts = None
                coordinator.active_balance_mode_retry_voltage = None
                coordinator.active_balance_mode_last_cutoff_ts = None
                coordinator.active_balance_mode_last_cutoff_delta_v = None
                coordinator.active_balance_mode_last_cutoff_delta_mv = None
                coordinator.active_balance_mode_last_cutoff_source = None
                coordinator.active_balance_mode_last_cutoff_max_cell_voltage = None
                coordinator.active_balance_mode_last_cutoff_min_cell_voltage = None
                coordinator.active_balance_mode_last_cutoff_soc = None
                start_delta, start_vmax, start_vmin, start_delta_source = (
                    self._active_balance_mode_initial_snapshot(coordinator)
                )
                coordinator.active_balance_mode_start_delta_mv = start_delta
                coordinator.active_balance_mode_start_delta_source = start_delta_source
                coordinator.active_balance_mode_start_max_cell_voltage = start_vmax
                coordinator.active_balance_mode_start_min_cell_voltage = start_vmin
                self._controller._persist_battery_runtime_config(
                    coordinator,
                    {
                        "active_balance_mode_started_ts": started_ts,
                        "active_balance_mode_run_date": today,
                        "active_balance_mode_phase": "PRE_TOP_CHARGE",
                        "active_balance_mode_top_reached": False,
                        "active_balance_mode_completed_date": None,
                        "active_balance_mode_completion_reason": None,
                        "active_balance_mode_wait_started_ts": None,
                        "active_balance_mode_retry_voltage": None,
                        "active_balance_mode_last_cutoff_ts": None,
                        "active_balance_mode_last_cutoff_delta_v": None,
                        "active_balance_mode_last_cutoff_delta_mv": None,
                        "active_balance_mode_last_cutoff_source": None,
                        "active_balance_mode_last_cutoff_max_cell_voltage": None,
                        "active_balance_mode_last_cutoff_min_cell_voltage": None,
                        "active_balance_mode_last_cutoff_soc": None,
                        "active_balance_mode_start_delta_mv": coordinator.active_balance_mode_start_delta_mv,
                        "active_balance_mode_start_delta_source": coordinator.active_balance_mode_start_delta_source,
                        "active_balance_mode_start_max_cell_voltage": start_vmax,
                        "active_balance_mode_start_min_cell_voltage": start_vmin,
                    },
                )
                _LOGGER.info("%s: active balance mode started", coordinator.name)
                await self._notify_active_balance_mode_started(coordinator, started_ts)

            await self._apply_active_balance_mode_cutoff(coordinator)

            try:
                started = datetime.fromisoformat(str(started_ts))
            except (TypeError, ValueError):
                started = now
                started_ts = started.isoformat()
                coordinator.active_balance_mode_started_ts = started_ts
                self._controller._persist_battery_runtime_config(
                    coordinator,
                    {"active_balance_mode_started_ts": started_ts},
                )

            elapsed_s = max(0.0, (now - started).total_seconds())
            data_now = coordinator.data or {}
            soc_now = data_now.get("battery_soc")
            vmax_now = data_now.get("max_cell_voltage")
            vmin_now = data_now.get("min_cell_voltage")
            delta_v = self._active_balance_mode_delta_v(coordinator)

            top_reached = bool(getattr(coordinator, "active_balance_mode_top_reached", False))
            if not top_reached:
                try:
                    vmax_high = (
                        vmax_now is not None
                        and float(vmax_now) >= ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE
                    )
                except (TypeError, ValueError):
                    vmax_high = False
                try:
                    soc_f = float(soc_now) if soc_now is not None else None
                except (TypeError, ValueError):
                    soc_f = None
                # A near-full pack reports SOC ~100% while the resting max-cell
                # voltage can still sit below the resume threshold. In that state
                # the BMS refuses the high-power pre-top charge (delivers ~0 W in
                # Standby), so vmax never climbs to
                # ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE and PRE_TOP_CHARGE
                # would hammer max_charge_power forever. Treat near-full SOC, or a
                # charge the BMS is rejecting at high SOC, as "top reached" and
                # hand off to the low-power CHARGE phase whose 95 W trickle the
                # BMS still accepts.
                soc_at_top = soc_f is not None and soc_f >= 99
                pre_top_charge_stalled = (
                    soc_f is not None
                    and soc_f >= 95
                    and self._active_balance_charge_rejected_detected(coordinator, "CHARGE")
                )
                if vmax_high or soc_at_top or pre_top_charge_stalled:
                    top_reached = True
                    coordinator.active_balance_mode_top_reached = True
                    coordinator.active_balance_mode_phase = "CHARGE"
                    self._active_balance_mode_phases[coordinator] = "CHARGE"
                    self._controller._persist_battery_runtime_config(
                        coordinator,
                        {
                            "active_balance_mode_top_reached": True,
                            "active_balance_mode_phase": "CHARGE",
                        },
                    )
                    _LOGGER.info(
                        "%s: active balance mode reached top-balance zone "
                        "(soc=%s, vmax=%s, vmax_high=%s, soc_at_top=%s, "
                        "charge_stalled=%s)",
                        coordinator.name,
                        soc_now,
                        vmax_now,
                        vmax_high,
                        soc_at_top,
                        pre_top_charge_stalled,
                    )

            if not top_reached:
                charge_power = int(getattr(coordinator, "max_charge_power", 0) or 0)
                await self._controller._set_battery_power(
                    coordinator,
                    charge_power,
                    0,
                    ignore_charge_blockers={
                        "charge_delay",
                        "time_slot_charge",
                        "max_soc",
                        "charge_hysteresis",
                        "normal_balance_pause",
                        "user_battery_charge_disabled",
                        "ev_pause",
                    },
                )
                statuses[coordinator.name] = {
                    "enabled": True,
                    "state": "pre_top_charge",
                    "phase": "pre_top_charge",
                    "elapsed_h": round(elapsed_s / 3600, 2),
                    "max_cell_voltage": round(float(vmax_now), 3) if vmax_now is not None else None,
                    "soc": soc_now,
                    "delta_V": round(delta_v, 4) if delta_v is not None else None,
                    "trigger_vmax": ACTIVE_BALANCE_CHARGE_RESUME_CELL_VOLTAGE,
                    "charge_w": charge_power,
                }
                continue

            try:
                vmax_f = float(vmax_now)
                vmin_f = float(vmin_now)
            except (TypeError, ValueError):
                statuses[coordinator.name] = {
                    "enabled": True,
                    "state": "waiting_for_cell_voltage",
                    "elapsed_h": round(elapsed_s / 3600, 2),
                }
                await self._controller._set_battery_power(coordinator, 0, 0)
                continue

            phase = (
                self._active_balance_mode_phases.get(coordinator)
                or getattr(coordinator, "active_balance_mode_phase", None)
                or "CHARGE"
            )
            legacy_phase_map = {
                "CHARGE_50W": "CHARGE",
                "HOLD": "CHARGE",
                "DISCHARGE_25W": "DISCHARGE",
                "FINAL_DISCHARGE_25W": "FINAL_DISCHARGE",
            }
            phase = legacy_phase_map.get(phase, phase)
            previous_phase = self._active_balance_mode_phases.get(coordinator)
            charge_power = 0
            discharge_power = 0
            delta_v = round(vmax_f - vmin_f, 4)
            retry_voltage = getattr(coordinator, "active_balance_mode_retry_voltage", None)
            if retry_voltage is None:
                retry_voltage = self._active_balance_charge_resume_target(coordinator)
            charge_rejected = self._active_balance_charge_rejected_detected(
                coordinator,
                "CHARGE" if phase in {"CHARGE", "WAIT_MEASURE"} else phase,
            )
            # Only treat as a real BMS rejection when we are still below the
            # configured stop voltage. At/above it the cutoff is the expected
            # end-of-charge signal and must transition us into WAIT_MEASURE,
            # not into DISCHARGE (which would skip the delta evaluation).
            if charge_rejected and vmax_f < ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE:
                # BMS cut charge before the 3.58 V top. Rejection detection
                # requires ~0 W, so cells are already at rest: record the
                # achieved delta as a real measurement before stepping the retry
                # point down and dropping into the escape discharge.
                await self._record_active_balance_mode_measurement(
                    coordinator,
                    {
                        "delta_V": delta_v,
                        "max_cell_voltage": round(vmax_f, 3),
                        "min_cell_voltage": round(vmin_f, 3),
                    },
                    source="bms_cut_below_stop",
                )
                retry_voltage = self._lower_active_balance_charge_resume_target(coordinator, vmax_f)
                coordinator.active_balance_mode_retry_voltage = retry_voltage
                phase = "DISCHARGE"

            if phase == "CHARGE":
                if vmax_f >= ACTIVE_BALANCE_CHARGE_STOP_CELL_VOLTAGE:
                    phase = "WAIT_MEASURE"
                    coordinator.active_balance_mode_wait_started_ts = now.isoformat()
                    # Reached the 3.58 V top: clear any ratcheted-down retry so
                    # the next run-up starts from the default resume voltage.
                    coordinator.active_balance_mode_retry_voltage = None
                    self._reset_active_balance_charge_resume_target(coordinator)
                else:
                    charge_power = ACTIVE_BALANCE_CHARGE_POWER_W
            elif phase == "WAIT_MEASURE":
                wait_started_ts = getattr(coordinator, "active_balance_mode_wait_started_ts", None)
                if not wait_started_ts:
                    wait_started_ts = now.isoformat()
                    coordinator.active_balance_mode_wait_started_ts = wait_started_ts
                try:
                    wait_started = datetime.fromisoformat(str(wait_started_ts))
                    wait_elapsed = max(0.0, (now - wait_started).total_seconds())
                except (TypeError, ValueError):
                    wait_elapsed = 0.0
                if wait_elapsed >= ACTIVE_BALANCE_MEASURE_WAIT_SECONDS:
                    await self._record_active_balance_mode_measurement(
                        coordinator,
                        {
                            "delta_V": delta_v,
                            "max_cell_voltage": round(vmax_f, 3),
                            "min_cell_voltage": round(vmin_f, 3),
                        },
                    )
                    coordinator.active_balance_mode_wait_started_ts = None
                    if delta_v <= ACTIVE_BALANCE_MODE_TARGET_DELTA_V:
                        phase = "FINAL_DISCHARGE"
                    else:
                        phase = "DISCHARGE"
            elif phase == "DISCHARGE":
                target_voltage = min(float(retry_voltage), ACTIVE_BALANCE_DISCHARGE_STOP_CELL_VOLTAGE)
                if vmax_f > target_voltage:
                    discharge_power = ACTIVE_BALANCE_DISCHARGE_POWER_W
                else:
                    # Keep the ratcheted-down retry voltage so a repeated BMS
                    # rejection steps it lower on the next charge attempt (down
                    # to the 3.40 V floor). It is reset only when the 3.58 V top
                    # is reached (WAIT_MEASURE) or the run completes.
                    phase = "CHARGE"
                    charge_power = ACTIVE_BALANCE_CHARGE_POWER_W
            elif phase == "FINAL_DISCHARGE":
                if vmax_f > ACTIVE_BALANCE_FINAL_DISCHARGE_STOP_CELL_VOLTAGE:
                    discharge_power = ACTIVE_BALANCE_DISCHARGE_POWER_W
                else:
                    await self._complete_active_balance_mode(
                        coordinator,
                        "final_discharge_complete",
                        today,
                        mark_completed=True,
                    )
                    statuses[coordinator.name] = {
                        "enabled": False,
                        "state": "complete",
                        "elapsed_h": round(elapsed_s / 3600, 2),
                        "delta_V": delta_v,
                        "completion_reason": "final_discharge_complete",
                    }
                    continue
            else:
                phase = "CHARGE"
                charge_power = ACTIVE_BALANCE_CHARGE_POWER_W

            self._active_balance_mode_phases[coordinator] = phase
            if getattr(coordinator, "active_balance_mode_phase", None) != phase:
                coordinator.active_balance_mode_phase = phase
            self._controller._persist_battery_runtime_config(
                coordinator,
                {
                    "active_balance_mode_phase": phase,
                    "active_balance_mode_wait_started_ts": getattr(
                        coordinator,
                        "active_balance_mode_wait_started_ts",
                        None,
                    ),
                    "active_balance_mode_retry_voltage": getattr(
                        coordinator,
                        "active_balance_mode_retry_voltage",
                        None,
                    ),
                },
            )

            coordinator._ab_charge_cmd_active = charge_power > 0
            await self._controller._set_battery_power(
                coordinator,
                charge_power,
                discharge_power,
                ignore_charge_blockers={
                    "charge_delay",
                    "time_slot_charge",
                    "max_soc",
                    "charge_hysteresis",
                    "normal_balance_pause",
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
            statuses[coordinator.name] = {
                "enabled": True,
                "state": "active",
                "phase": phase.lower(),
                "started": started_ts,
                "elapsed_h": round(elapsed_s / 3600, 2),
                "target_delta_V": ACTIVE_BALANCE_MODE_TARGET_DELTA_V,
                "delta_reasonable": delta_v <= ACTIVE_BALANCE_MODE_TARGET_DELTA_V,
                "delta_V": delta_v,
                "max_cell_voltage": round(vmax_f, 3),
                "min_cell_voltage": round(vmin_f, 3),
                "charge_w": charge_power,
                "discharge_w": discharge_power,
                "charge_rejected": charge_rejected,
                "charge_retry_voltage": round(float(retry_voltage), 3),
            }
            if previous_phase != phase:
                _LOGGER.info(
                    "%s: active balance mode phase changed %s -> %s",
                    coordinator.name,
                    previous_phase or "none",
                    phase,
                )

        self._active_balance_mode_status = statuses

    def _active_balance_overrides_delay(self) -> bool:
        """Return True when any battery has the scheduled active balance mode enabled.

        Active balance sends direct battery commands in both pre-top and top
        phases, so charge delay must not block those explicit commands.
        """
        return any(
            bool(getattr(c, "active_balance_mode_enabled", False))
            for c in self._controller.coordinators
        )
