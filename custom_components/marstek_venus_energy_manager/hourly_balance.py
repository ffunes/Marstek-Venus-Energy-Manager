"""Hourly net balance manager for Marstek Venus Energy Manager."""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HOURLY_BALANCE_STORAGE_KEY,
    HOURLY_BALANCE_STORAGE_VERSION,
    HOURLY_BALANCE_FORCE_RECALC_REMAINING_MIN,
    HOURLY_BALANCE_MIN_REMAINING_MIN,
    CONF_HOURLY_BALANCE_TARGET_NET_WH,
    CONF_HOURLY_BALANCE_MAX_OFFSET_W,
    CONF_HOURLY_BALANCE_DEADBAND_WH,
    CONF_HOURLY_BALANCE_HYSTERESIS_W,
    DEFAULT_HOURLY_BALANCE_TARGET_NET_WH,
    DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W,
    DEFAULT_HOURLY_BALANCE_DEADBAND_WH,
    DEFAULT_HOURLY_BALANCE_HYSTERESIS_W,
    _HOURLY_BALANCE_RAMP_IN_MIN,
    EXTERNAL_NET_BALANCE_CANDIDATES,
)

_EXTERNAL_DETECT_MAX_ATTEMPTS = 20  # ~50 s at 2.5 s/cycle

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class HourlyBalanceManager:
    """Tracks grid import/export per civil hour and adjusts setpoint offset."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, controller: Any) -> None:
        self._hass = hass
        self._config_entry = config_entry
        self._controller = controller
        self._store: Store = Store(
            hass,
            HOURLY_BALANCE_STORAGE_VERSION,
            f"{DOMAIN}.{config_entry.entry_id}.{HOURLY_BALANCE_STORAGE_KEY}",
        )

        # Accumulators for current hour
        self._current_hour: int | None = None
        self._hour_started_local: datetime | None = None
        self._imp_wh: float = 0.0
        self._exp_wh: float = 0.0
        self._last_grid_w: float | None = None
        self._last_sample_monotonic: float | None = None
        self._last_offset_w: float = 0.0

        # Internal state and save throttle
        self._last_theoretical_offset_w: float = 0.0
        self._last_block_reason: str | None = None
        self._save_counter: int = 0

        # Registered sensor entities for push updates
        self._sensors: list[Any] = []

        # External net balance sensor (auto-detected)
        self._ext_sensor: str | None = None
        self._ext_mode: str | None = None   # snapshot_kwh | snapshot_wh | direct_kwh | direct_wh | power_w | power_kw
        self._ext_snapshot: float | None = None
        self._ext_detected: bool = False
        self._ext_detect_attempts: int = 0

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted state from store."""
        stored = await self._store.async_load()
        if stored:
            # Restore current-hour accumulators only if still the same hour
            now_local = dt_util.now()
            saved_hour_iso = stored.get("hour_iso")
            if saved_hour_iso:
                try:
                    saved_hour = datetime.fromisoformat(saved_hour_iso)
                    if (saved_hour.year == now_local.year
                            and saved_hour.month == now_local.month
                            and saved_hour.day == now_local.day
                            and saved_hour.hour == now_local.hour):
                        self._imp_wh = stored.get("imp_wh", 0.0)
                        self._exp_wh = stored.get("exp_wh", 0.0)
                        self._last_offset_w = stored.get("last_offset_w", 0.0)
                        self._current_hour = now_local.hour
                        self._hour_started_local = now_local.replace(
                            minute=0, second=0, microsecond=0
                        )
                        _LOGGER.info(
                            "HourlyBalance: restored hour %s — imp=%.0fWh exp=%.0fWh",
                            saved_hour_iso, self._imp_wh, self._exp_wh,
                        )
                except ValueError:
                    pass

        _LOGGER.info("HourlyBalance: setup complete")
        await self._detect_external_sensor()

        # If we restored mid-hour data and the external sensor uses snapshots, prime the
        # snapshot so the first cycle produces the same net as the restored values instead
        # of resetting to zero.
        if (
            self._ext_sensor
            and self._ext_mode in ("snapshot_kwh", "snapshot_wh")
            and self._current_hour is not None
        ):
            state = self._hass.states.get(self._ext_sensor)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    raw = float(state.state)
                    # restored net in ext convention (positive = export to grid)
                    ext_net_wh = -(self._imp_wh - self._exp_wh)
                    scale = 1000.0 if self._ext_mode == "snapshot_kwh" else 1.0
                    self._ext_snapshot = raw - ext_net_wh / scale
                    _LOGGER.info(
                        "HourlyBalance: ext snapshot primed to %.4f to preserve %.0fWh restored net",
                        self._ext_snapshot, self._imp_wh - self._exp_wh,
                    )
                except (ValueError, TypeError):
                    pass

    async def async_unload(self) -> None:
        """Persist state to store."""
        await self._save()

    # ------------------------------------------------------------------
    # Sensor registration
    # ------------------------------------------------------------------

    def register_sensor(self, entity: Any) -> None:
        self._sensors.append(entity)

    def _push_sensors(self) -> None:
        for sensor in self._sensors:
            sensor.async_write_ha_state()

    def clear_offset(self, reset_sampling: bool = True) -> None:
        """Clear the controller offset and the manager's visible offset state."""
        self._controller.remove_setpoint_offset("hourly_balance")
        self._last_offset_w = 0.0
        self._last_theoretical_offset_w = 0.0
        self._last_block_reason = None
        if reset_sampling:
            self._last_sample_monotonic = None
            self._last_grid_w = None
        self._push_sensors()

    # ------------------------------------------------------------------
    # External sensor detection
    # ------------------------------------------------------------------

    async def _detect_external_sensor(self) -> None:
        """Try to discover an external net balance sensor from the candidates list.

        Called once at setup and lazily on the first few process cycles to
        handle sensors that aren't in the state machine yet at HA startup.
        Positive sensor value is assumed to mean net export to grid.
        """
        self._ext_detect_attempts += 1
        found_all_in_states = True

        for candidate in EXTERNAL_NET_BALANCE_CANDIDATES:
            state = self._hass.states.get(candidate)
            if state is None:
                found_all_in_states = False
                _LOGGER.debug(
                    "HourlyBalance: candidate %s not in states yet (attempt %d/%d)",
                    candidate, self._ext_detect_attempts, _EXTERNAL_DETECT_MAX_ATTEMPTS,
                )
                continue

            unit = state.attributes.get("unit_of_measurement", "")
            sc = state.attributes.get("state_class", "")
            cumulative = sc in ("total", "total_increasing")

            if unit == "kWh":
                mode = "snapshot_kwh" if cumulative else "direct_kwh"
            elif unit == "Wh":
                mode = "snapshot_wh" if cumulative else "direct_wh"
            elif unit == "W":
                mode = "power_w"
            elif unit == "kW":
                mode = "power_kw"
            else:
                _LOGGER.warning(
                    "HourlyBalance: candidate %s has unsupported unit '%s', skipping",
                    candidate, unit,
                )
                continue

            self._ext_sensor = candidate
            self._ext_mode = mode
            self._ext_detected = True
            _LOGGER.info(
                "HourlyBalance: using external sensor %s (unit=%s state_class=%s → mode=%s). "
                "Sign convention: positive = net export to grid.",
                candidate, unit, sc, mode,
            )
            return

        if found_all_in_states or self._ext_detect_attempts >= _EXTERNAL_DETECT_MAX_ATTEMPTS:
            self._ext_detected = True
            _LOGGER.info(
                "HourlyBalance: no external net balance sensor found (tried: %s), "
                "falling back to trapezoidal integration",
                EXTERNAL_NET_BALANCE_CANDIDATES,
            )

    def _read_external_net_wh(self) -> float | None:
        """Read current-hour net Wh from external sensor (positive = export to grid).

        Returns None when the sensor is unavailable; caller keeps last known values.
        For snapshot modes the first call in a new hour sets the snapshot and returns 0.
        """
        state = self._hass.states.get(self._ext_sensor)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            raw = float(state.state)
        except (ValueError, TypeError):
            return None

        if self._ext_mode == "snapshot_kwh":
            if self._ext_snapshot is None:
                self._ext_snapshot = raw
                _LOGGER.debug("HourlyBalance: ext snapshot = %.4f kWh", raw)
                return 0.0
            return (raw - self._ext_snapshot) * 1000.0
        if self._ext_mode == "snapshot_wh":
            if self._ext_snapshot is None:
                self._ext_snapshot = raw
                return 0.0
            return raw - self._ext_snapshot
        if self._ext_mode == "direct_kwh":
            return raw * 1000.0
        if self._ext_mode == "direct_wh":
            return raw
        return None  # power modes handled separately in async_process

    # ------------------------------------------------------------------
    # Main processing loop (called every PD cycle)
    # ------------------------------------------------------------------

    async def async_process(self) -> None:
        """Process one cycle. Reads grid power directly so it can run before
        the PD's deadband / stale-sensor early-returns gate the rest of the
        control loop."""
        # Feature disabled via runtime switch — clear offset and idle
        if not self._controller.hourly_balance_enabled:
            self.clear_offset()
            return

        # Edge case: manual mode — clear offset and do nothing
        if self._controller.manual_mode_enabled:
            self.clear_offset()
            return

        in_slot = self._is_in_active_slot()

        if not in_slot:
            # Reset integration so we restart clean when slot opens again
            self.clear_offset()
            return

        # Lazy detection for sensors not yet in the state machine at startup
        if not self._ext_detected and self._ext_detect_attempts < _EXTERNAL_DETECT_MAX_ATTEMPTS:
            await self._detect_external_sensor()

        # Determine integration source and read the current value.
        # _use_ext_energy = True  → external energy sensor; bypass trapezoidal, set imp/exp directly.
        # _use_ext_energy = False → power sensor (ext or consumption_sensor); trapezoidal integration.
        _use_ext_energy = (
            self._ext_sensor is not None
            and self._ext_mode not in ("power_w", "power_kw")
        )

        if _use_ext_energy:
            # Validate readability before doing anything; keep last offset if unavailable.
            ext_state = self._hass.states.get(self._ext_sensor)
            if ext_state is None or ext_state.state in ("unavailable", "unknown"):
                self._push_sensors()
                return
            grid_w = None  # not used in energy mode
        else:
            # Power source: external power sensor or consumption_sensor fallback
            if self._ext_sensor:
                ext_state = self._hass.states.get(self._ext_sensor)
                if ext_state is None or ext_state.state in ("unavailable", "unknown"):
                    grid_w = None
                else:
                    try:
                        val = float(ext_state.state)
                        if self._ext_mode == "power_kw":
                            val *= 1000.0
                        grid_w = -val  # positive export → negative in our import-positive convention
                    except (ValueError, TypeError):
                        grid_w = None
            else:
                grid_state = self._hass.states.get(self._controller.consumption_sensor)
                grid_w = self._controller._apply_meter_transform(grid_state)

            if grid_w is None:
                self._last_sample_monotonic = None
                self._last_grid_w = None
                self._push_sensors()
                return

        now_local = dt_util.now()
        now_mono = monotonic()

        # Detect hour change
        if self._current_hour != now_local.hour:
            if self._current_hour is not None:
                # Close previous hour
                net_wh = self._imp_wh - self._exp_wh
                _LOGGER.info(
                    "HourlyBalance: closed hour %s — imp=%.0fWh exp=%.0fWh net=%.0fWh",
                    self._hour_started_local.isoformat() if self._hour_started_local else None,
                    self._imp_wh,
                    self._exp_wh,
                    net_wh,
                )

            # Start new hour
            self._current_hour = now_local.hour
            self._hour_started_local = now_local.replace(minute=0, second=0, microsecond=0)
            self._imp_wh = 0.0
            self._exp_wh = 0.0
            self._last_sample_monotonic = None
            self._last_grid_w = None
            self._last_offset_w = 0.0
            self._ext_snapshot = None  # snapshot modes take a fresh reference at hour start

        # Integrate Wh — two paths depending on integration source.
        if _use_ext_energy:
            # External energy sensor: read accumulated net directly.
            # positive = net export; map to imp/exp in our import-positive convention.
            ext_net_wh = self._read_external_net_wh()
            if ext_net_wh is not None:
                self._imp_wh = max(0.0, -ext_net_wh)
                self._exp_wh = max(0.0, ext_net_wh)
            # If None (sensor momentarily unavailable), keep last known values.
        else:
            # Power source: trapezoidal rule with zero-crossing split.
            if self._last_sample_monotonic is not None and self._last_grid_w is not None:
                dt_h = (now_mono - self._last_sample_monotonic) / 3600.0
                prev_w = self._last_grid_w
                curr_w = grid_w
                if (prev_w >= 0) == (curr_w >= 0):
                    wh = (prev_w + curr_w) / 2.0 * dt_h
                    if wh >= 0:
                        self._imp_wh += wh
                    else:
                        self._exp_wh += -wh
                else:
                    frac = abs(prev_w) / (abs(prev_w) + abs(curr_w))
                    dt_first = dt_h * frac
                    dt_second = dt_h - dt_first
                    wh_first = prev_w / 2.0 * dt_first
                    wh_second = curr_w / 2.0 * dt_second
                    if wh_first >= 0:
                        self._imp_wh += wh_first
                    else:
                        self._exp_wh += -wh_first
                    if wh_second >= 0:
                        self._imp_wh += wh_second
                    else:
                        self._exp_wh += -wh_second

            self._last_sample_monotonic = now_mono
            self._last_grid_w = grid_w

        # Calculate offset
        target_net_wh = self._target_net_wh()
        net_wh = self._imp_wh - self._exp_wh
        elapsed_min = (now_local - self._hour_started_local).total_seconds() / 60.0
        remaining_min = max(0.0, 60.0 - elapsed_min)

        if remaining_min < HOURLY_BALANCE_MIN_REMAINING_MIN:
            offset_w = 0.0
        else:
            deficit_wh = target_net_wh - net_wh  # >0 means we exported too much, need to import
            deadband_wh = float(self._config_entry.data.get(
                CONF_HOURLY_BALANCE_DEADBAND_WH, DEFAULT_HOURLY_BALANCE_DEADBAND_WH
            )) * 1000.0
            if abs(deficit_wh) <= deadband_wh:
                offset_w = 0.0
            else:
                needed_avg_w = deficit_wh / (remaining_min / 60.0)
                offset_w = needed_avg_w  # positive = shift target towards import

                # Ramp-in: attenuate during the first _HOURLY_BALANCE_RAMP_IN_MIN minutes
                if elapsed_min < _HOURLY_BALANCE_RAMP_IN_MIN:
                    offset_w *= elapsed_min / _HOURLY_BALANCE_RAMP_IN_MIN

                # Saturation
                max_offset_w = self._config_entry.data.get(
                    CONF_HOURLY_BALANCE_MAX_OFFSET_W, DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W
                )
                offset_w = max(-max_offset_w, min(max_offset_w, offset_w))

        # Hysteresis (bypass near end of hour)
        if remaining_min >= HOURLY_BALANCE_FORCE_RECALC_REMAINING_MIN:
            hysteresis_w = self._config_entry.data.get(
                CONF_HOURLY_BALANCE_HYSTERESIS_W, DEFAULT_HOURLY_BALANCE_HYSTERESIS_W
            )
            if abs(offset_w - self._last_offset_w) < hysteresis_w:
                offset_w = self._last_offset_w

        # Negative offset is intentional: when the hour has net import above
        # target, the controller must discharge/export during the remaining
        # minutes to bring the hourly net balance back toward target.
        # All block reasons (solar_charge_delay, hysteresis, max_soc) only fire
        # when offset > 0 (charging direction). When blocked, keep the positive
        # offset active: charging is still rejected at hardware level, but the
        # high setpoint prevents the PD from commanding discharge to cover house
        # load — the grid supplies the house instead of depleting battery
        # headroom. The integration (imp/exp) continues tracking so the correct
        # offset will be applied once the block lifts.
        self._last_theoretical_offset_w = offset_w
        self._last_block_reason = self._get_compensation_block_reason(offset_w)
        if self._last_block_reason is not None:
            _LOGGER.debug(
                "HourlyBalance: offset %.0fW blocked by %s; keeping positive to prevent discharge",
                offset_w, self._last_block_reason,
            )

        self._controller.set_setpoint_offset("hourly_balance", offset_w)
        self._last_offset_w = offset_w

        # Throttled save (~120 cycles ≈ 5 min at 2.5 s/cycle)
        self._save_counter += 1
        if self._save_counter >= 120:
            self._save_counter = 0
            await self._save()

        self._push_sensors()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _save(self) -> None:
        data = {
            "hour_iso": self._hour_started_local.isoformat() if self._hour_started_local else None,
            "imp_wh": self._imp_wh,
            "exp_wh": self._exp_wh,
            "last_offset_w": self._last_offset_w,
        }
        await self._store.async_save(data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _target_net_wh(self) -> float:
        return float(self._config_entry.data.get(
            CONF_HOURLY_BALANCE_TARGET_NET_WH, DEFAULT_HOURLY_BALANCE_TARGET_NET_WH
        )) * 1000.0

    def _is_in_active_slot(self) -> bool:
        """Return True if we should apply hourly balance right now.

        Logic mirrors no_discharge_time_slots: if no enabled slots exist,
        return True (apply 24/7).  Otherwise return True only when current
        day+time falls inside at least one enabled slot.
        """
        all_slots = self._config_entry.data.get("no_discharge_time_slots", [])
        enabled_slots = [s for s in all_slots if s.get("enabled", True)]

        if not enabled_slots:
            return True

        now = datetime.now()
        current_time = now.time()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]

        for slot in enabled_slots:
            if current_day not in slot.get("days", []):
                continue
            try:
                start_t = dt_time.fromisoformat(slot["start_time"])
                end_t = dt_time.fromisoformat(slot["end_time"])
            except (KeyError, ValueError):
                continue
            if start_t <= current_time <= end_t:
                return True

        return False

    def _get_compensation_block_reason(self, offset: float) -> str | None:
        """Return a reason string if the positive offset is blocked, else None.

        All checks apply only when offset > 0 (charging direction). When a
        reason is returned, the caller keeps the positive offset active rather
        than zeroing it, so the PD setpoint stays high and the battery does not
        discharge to cover house load (grid supplies the house instead).
        Discharge corrections (offset < 0) are never blocked here.
        Uses _charge_delay_status (kept current by the PD cycle) to avoid
        calling _is_charge_delayed() which has side-effects.
        """
        ctrl = self._controller
        if offset > 0:
            if ctrl.charge_delay_enabled:
                delay_state = ctrl._charge_delay_status.get("state", "")
                _delay_not_blocking = {
                    "Disabled", "Charging allowed", "Skipped - Full Charge Day",
                    "Charging to setpoint",
                }
                if delay_state not in _delay_not_blocking and not delay_state.startswith("Unlocking"):
                    return "solar_charge_delay"
            if any(getattr(c, "_hysteresis_active", False) for c in ctrl.coordinators):
                return "hysteresis"
            with_data = [c for c in ctrl.coordinators if c.data]
            if with_data and all(
                c.data.get("battery_soc", 0) >= c.max_soc for c in with_data
            ):
                return "max_soc"
        return None

    def get_status_dict(self) -> dict:
        """Return a snapshot dict for sensor attributes."""
        now_local = dt_util.now()
        elapsed_min = 0.0
        remaining_min = 60.0
        if self._hour_started_local is not None:
            elapsed_min = (now_local - self._hour_started_local).total_seconds() / 60.0
            remaining_min = max(0.0, 60.0 - elapsed_min)

        offset = self._last_offset_w
        d: dict = {
            "net_kwh": round((self._exp_wh - self._imp_wh) / 1000, 3),
            "imp_wh": round(self._imp_wh, 1),
            "exp_wh": round(self._exp_wh, 1),
            "elapsed_min": round(elapsed_min, 1),
            "remaining_min": round(remaining_min, 1),
            "target_net_wh": self._target_net_wh(),
            "offset_w": round(offset, 1),
            "theoretical_offset_w": round(self._last_theoretical_offset_w, 1),
            "in_active_slot": self._is_in_active_slot(),
            "hour_iso": self._hour_started_local.isoformat() if self._hour_started_local else None,
            "charge_block_reason": self._last_block_reason,
            "source": self._ext_sensor if self._ext_sensor else "trapezoidal",
            "source_mode": self._ext_mode if self._ext_mode else "trapezoidal",
        }
        return d

    def get_state_label(self) -> str:
        """Return a string state label for the status sensor."""
        if not self._is_in_active_slot():
            return "out_of_slot"
        if self._current_hour is None:
            return "idle"

        if self._last_block_reason:
            return "compensation_stopped"

        max_offset_w = self._config_entry.data.get(
            CONF_HOURLY_BALANCE_MAX_OFFSET_W, DEFAULT_HOURLY_BALANCE_MAX_OFFSET_W
        )
        if abs(self._last_theoretical_offset_w) >= max_offset_w - 0.5:
            return "capped"

        if self._last_theoretical_offset_w != 0:
            return "compensating_import" if self._last_theoretical_offset_w > 0 else "compensating_export"
            
        return "idle"
