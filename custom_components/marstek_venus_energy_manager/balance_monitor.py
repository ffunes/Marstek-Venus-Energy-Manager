"""Cell balance monitor for Marstek Venus batteries."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    BALANCE_STORAGE_KEY,
    BALANCE_STORAGE_VERSION,
    BALANCE_THRESHOLD_YELLOW,
    BALANCE_THRESHOLD_ORANGE,
    BALANCE_THRESHOLD_RED,
    BALANCE_OCV_WAIT_SECONDS,
    BALANCE_ORANGE_HOLD_SECONDS,
    BALANCE_COOLDOWN_HOURS,
    BALANCE_OPPORTUNISTIC_COOLDOWN_HOURS,
    BALANCE_POWER_STABLE_POLLS,
    BALANCE_POWER_REST_THRESHOLD_W,
    BALANCE_VOLTAGE_SETTLING_THRESHOLD_V,
    BALANCE_HISTORY_MAX,
    BALANCE_RED_CONSECUTIVE_ALERT,
    BALANCE_TREND_ALERT_AVG_MV,
    WEEKDAY_MAP,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class _BatteryState:
    phase: str = "IDLE"         # IDLE | WAITING_OCV | HOLD_ORANGE
    phase_started: datetime | None = None
    stable_polls: int = 0
    prev_vmax: float | None = None


class BalanceSensorGroup:
    """Thin container holding the 5 sensor entities for one battery."""

    def __init__(self) -> None:
        self._entities: list[Any] = []

    def register(self, entity: Any) -> None:
        self._entities.append(entity)


class BalanceMonitor:
    """Manages cell-voltage balance readings for all batteries in one entry."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, controller: Any) -> None:
        self._hass = hass
        self._controller = controller
        self._store: Store = Store(
            hass,
            BALANCE_STORAGE_VERSION,
            f"{DOMAIN}.{config_entry.entry_id}.{BALANCE_STORAGE_KEY}",
        )
        self._data: dict[str, Any] = {}
        self._states: dict[str, _BatteryState] = {}
        self._sensor_groups: dict[str, BalanceSensorGroup] = {}

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted data from store."""
        stored = await self._store.async_load()
        if stored:
            self._data = stored

    async def async_restore_coordinator(self, coordinator: Any) -> None:
        """Restore state machine phase for a coordinator after HA restart."""
        host = coordinator.host
        bat = self._data.get(host, {})
        phase = bat.get("phase", "IDLE")
        phase_started = None
        if bat.get("phase_started_ts"):
            try:
                phase_started = datetime.fromisoformat(bat["phase_started_ts"])
            except ValueError:
                phase_started = None

        # stable_polls and prev_vmax are transient — reset so stale pre-shutdown
        # values don't cause a premature OCV read on the first poll after restart.
        self._states[host] = _BatteryState(
            phase=phase,
            phase_started=phase_started,
            stable_polls=0,
            prev_vmax=None,
        )

        if phase in ("WAITING_OCV", "HOLD_ORANGE"):
            coordinator.balance_hold = True
            _LOGGER.info(
                "[%s] Balance monitor: restored phase %s from store", coordinator.name, phase
            )

    # ------------------------------------------------------------------
    # Main entry point — called every coordinator poll cycle
    # ------------------------------------------------------------------

    async def async_process(self, coordinator: Any) -> None:
        """Run state machine for one battery. Called from ChargeDischargeController."""
        host = coordinator.host
        if host not in self._states:
            self._states[host] = _BatteryState()

        data = coordinator.data or {}
        soc = data.get("battery_soc")
        power = data.get("battery_power")
        vmax = data.get("max_cell_voltage")
        vmin = data.get("min_cell_voltage")

        if None in (soc, power, vmax, vmin):
            return

        state = self._states[host]
        now = datetime.now(timezone.utc)

        if state.phase == "IDLE":
            await self._process_idle(coordinator, state, soc, power, vmax, vmin, now)
        elif state.phase == "WAITING_OCV":
            await self._process_waiting_ocv(coordinator, state, soc, power, vmax, vmin, now)
        elif state.phase == "HOLD_ORANGE":
            await self._process_hold_orange(coordinator, state, vmax, vmin, soc, now)

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    async def _process_idle(
        self, coordinator, state, soc, power, vmax, vmin, now
    ) -> None:
        host = coordinator.host
        is_charge_day = self._is_weekly_charge_day()

        if is_charge_day and soc >= 100 and not self._read_recently(host, BALANCE_COOLDOWN_HOURS):
            coordinator.balance_hold = True
            state.phase = "WAITING_OCV"
            state.phase_started = now
            state.stable_polls = 0
            state.prev_vmax = vmax
            await self._persist_state(host, state)
            _LOGGER.info("[%s] Balance monitor: starting OCV wait (discharge held)", coordinator.name)
            return

        # Opportunistic — no discharge block, no threshold evaluation
        if (
            not is_charge_day
            and soc >= 100
            and abs(power) < BALANCE_POWER_REST_THRESHOLD_W
            and not self._read_recently(
                host,
                BALANCE_OPPORTUNISTIC_COOLDOWN_HOURS,
                types=("formal", "formal_followup", "opportunistic"),
            )
        ):
            delta_mv = (vmax - vmin) * 1000
            _LOGGER.debug(
                "[%s] Balance monitor: opportunistic reading %.0f mV", coordinator.name, delta_mv
            )
            await self._save_reading(host, delta_mv, vmax, vmin, soc, "opportunistic")

    async def _process_waiting_ocv(
        self, coordinator, state, soc, power, vmax, vmin, now
    ) -> None:
        host = coordinator.host

        # Cancel if charge was interrupted
        if soc < 95:
            _LOGGER.warning(
                "[%s] Balance monitor: SOC dropped to %s during OCV wait, cancelling",
                coordinator.name, soc,
            )
            coordinator.balance_hold = False
            state.phase = "IDLE"
            state.phase_started = None
            await self._persist_state(host, state)
            return

        elapsed = (now - state.phase_started).total_seconds() if state.phase_started else 0
        if elapsed < BALANCE_OCV_WAIT_SECONDS:
            return

        # After wait: require stable low power AND settling voltage
        if abs(power) < BALANCE_POWER_REST_THRESHOLD_W:
            state.stable_polls += 1
        else:
            state.stable_polls = 0

        vmax_drop = (state.prev_vmax - vmax) if state.prev_vmax is not None else 0
        voltage_settled = vmax_drop < BALANCE_VOLTAGE_SETTLING_THRESHOLD_V
        state.prev_vmax = vmax

        if state.stable_polls < BALANCE_POWER_STABLE_POLLS or not voltage_settled:
            await self._persist_state(host, state)
            return

        # Ready to read OCV
        delta_mv = (vmax - vmin) * 1000
        _LOGGER.info(
            "[%s] Balance monitor: OCV reading %.0f mV (vmax=%.4f vmin=%.4f)",
            coordinator.name, delta_mv, vmax, vmin,
        )
        status = await self._save_reading(host, delta_mv, vmax, vmin, soc, "formal", coordinator)

        if status == "orange":
            state.phase = "HOLD_ORANGE"
            state.phase_started = now
            state.stable_polls = 0
        else:
            coordinator.balance_hold = False
            state.phase = "IDLE"
            state.phase_started = None

        await self._persist_state(host, state)

    async def _process_hold_orange(
        self, coordinator, state, vmax, vmin, soc, now
    ) -> None:
        host = coordinator.host
        elapsed = (now - state.phase_started).total_seconds() if state.phase_started else 0
        if elapsed < BALANCE_ORANGE_HOLD_SECONDS:
            return

        delta_mv = (vmax - vmin) * 1000
        _LOGGER.info(
            "[%s] Balance monitor: follow-up reading after 2.5h hold: %.0f mV",
            coordinator.name, delta_mv,
        )
        await self._save_reading(host, delta_mv, vmax, vmin, soc, "formal_followup", coordinator)

        if delta_mv >= BALANCE_THRESHOLD_ORANGE:
            await self._notify(
                f"marstek_balance_persist_{host}",
                f"⚠️ Cell imbalance persists — {coordinator.name}",
                f"Delta still {delta_mv:.0f} mV after 2.5 h rest. Consider checking the battery.",
            )

        coordinator.balance_hold = False
        state.phase = "IDLE"
        state.phase_started = None
        await self._persist_state(host, state)

    # ------------------------------------------------------------------
    # Persistence and evaluation
    # ------------------------------------------------------------------

    async def _save_reading(
        self,
        host: str,
        delta_mv: float,
        vmax: float,
        vmin: float,
        soc: float,
        reading_type: str,
        coordinator: Any = None,
    ) -> str:
        bat = self._data.setdefault(
            host, {"readings": [], "consecutive_red": 0}
        )
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "delta_mV": round(delta_mv, 1),
            "vmax_V": round(vmax, 4),
            "vmin_V": round(vmin, 4),
            "soc": soc,
            "type": reading_type,
        }
        bat["readings"].append(entry)
        bat["readings"] = bat["readings"][-BALANCE_HISTORY_MAX:]

        status = "unknown"
        if reading_type in ("formal", "formal_followup") and coordinator is not None:
            status = self._evaluate(host, delta_mv, bat, coordinator)

        trend = self._trend(host)
        if reading_type in ("formal", "formal_followup") and coordinator is not None:
            self._check_trend_alert(host, coordinator.name, trend)

        await self._store.async_save(self._data)
        self._push_sensors(host, delta_mv, status, trend, entry["ts"])
        return status

    def _evaluate(self, host: str, delta_mv: float, bat: dict, coordinator: Any) -> str:
        if delta_mv < BALANCE_THRESHOLD_YELLOW:
            status = "green"
            bat["consecutive_red"] = 0
        elif delta_mv < BALANCE_THRESHOLD_ORANGE:
            status = "yellow"
            bat["consecutive_red"] = 0
        elif delta_mv < BALANCE_THRESHOLD_RED:
            status = "orange"
            bat["consecutive_red"] = 0
        else:
            status = "red"
            bat["consecutive_red"] = bat.get("consecutive_red", 0) + 1

        if status in ("orange", "red"):
            if status == "red":
                msg = f"Delta: {delta_mv:.0f} mV. High cell imbalance detected."
            else:
                msg = (
                    f"Delta: {delta_mv:.0f} mV. Moderate imbalance. "
                    "Battery will rest 2.5 h for passive balancing."
                )
            self._hass.async_create_task(
                self._notify(
                    f"marstek_balance_{host}",
                    f"⚠️ Cell imbalance — {coordinator.name}",
                    msg,
                )
            )

        if status == "red" and bat["consecutive_red"] >= BALANCE_RED_CONSECUTIVE_ALERT:
            self._hass.async_create_task(
                self._notify(
                    f"marstek_degraded_{host}",
                    f"🔴 Possible degraded cell — {coordinator.name}",
                    f"{delta_mv:.0f} mV delta for {bat['consecutive_red']} consecutive full charges. "
                    "Check battery condition.",
                )
            )

        return status

    def _trend(self, host: str) -> dict:
        readings = self._data.get(host, {}).get("readings", [])
        formal = [r for r in readings if r.get("type") in ("formal", "formal_followup")]
        if len(formal) < 2:
            return {"trend": "unknown", "avg_4w": None}

        last4 = formal[-4:]
        values = [r["delta_mV"] for r in last4]
        avg = sum(values) / len(values)
        slope = (values[-1] - values[0]) / max(len(values) - 1, 1)

        if slope > 2:
            trend = "rising"
        elif slope < -2:
            trend = "falling"
        else:
            trend = "stable"

        return {"trend": trend, "avg_4w": round(avg, 1), "slope": slope}

    def _check_trend_alert(self, host: str, name: str, trend: dict) -> None:
        if trend["trend"] == "rising" and trend["avg_4w"] is not None and trend["avg_4w"] > BALANCE_TREND_ALERT_AVG_MV:
            self._hass.async_create_task(
                self._notify(
                    f"marstek_trend_{host}",
                    f"📈 Rising imbalance trend — {name}",
                    f"Trend: +{trend['slope']:.1f} mV/reading, avg {trend['avg_4w']:.0f} mV "
                    f"over last readings.",
                )
            )

    async def _persist_state(self, host: str, state: _BatteryState) -> None:
        bat = self._data.setdefault(host, {"readings": [], "consecutive_red": 0})
        bat["phase"] = state.phase
        bat["phase_started_ts"] = (
            state.phase_started.isoformat() if state.phase_started else None
        )
        bat["stable_polls"] = state.stable_polls
        bat["prev_vmax"] = state.prev_vmax
        await self._store.async_save(self._data)

    # ------------------------------------------------------------------
    # Sensor integration
    # ------------------------------------------------------------------

    def register_sensor_group(self, host: str, group: BalanceSensorGroup) -> None:
        self._sensor_groups[host] = group

    def _push_sensors(
        self, host: str, delta_mv: float, status: str, trend: dict, last_ts: str
    ) -> None:
        group = self._sensor_groups.get(host)
        if not group:
            return
        for entity in group._entities:
            entity.on_reading(delta_mv, status, trend["trend"], trend.get("avg_4w"), last_ts)

    def get_initial_state(self, host: str) -> dict:
        """Return state derived from store — used by sensors at startup."""
        readings = self._data.get(host, {}).get("readings", [])
        formal = [r for r in readings if r.get("type") in ("formal", "formal_followup")]
        if not formal:
            return {
                "delta_mV": None,
                "status": "unknown",
                "trend": "unknown",
                "avg_4w": None,
                "last_ts": None,
            }
        last = formal[-1]
        trend = self._trend(host)
        return {
            "delta_mV": last["delta_mV"],
            "status": self._status_for_delta(last["delta_mV"]),
            "trend": trend["trend"],
            "avg_4w": trend.get("avg_4w"),
            "last_ts": last["ts"],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_weekly_charge_day(self) -> bool:
        ctrl = self._controller
        if not getattr(ctrl, "weekly_full_charge_enabled", False):
            return False
        if getattr(ctrl, "_force_full_charge", False):
            return True
        from datetime import datetime as _dt
        return _dt.now().weekday() == WEEKDAY_MAP.get(ctrl.weekly_full_charge_day, -1)

    def _read_recently(
        self,
        host: str,
        hours: float,
        types: tuple[str, ...] = ("formal", "formal_followup"),
    ) -> bool:
        readings = self._data.get(host, {}).get("readings", [])
        matching = [r for r in readings if r.get("type") in types]
        if not matching:
            return False
        try:
            last_ts = datetime.fromisoformat(matching[-1]["ts"])
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last_ts).total_seconds() < hours * 3600
        except (ValueError, KeyError):
            return False

    def _status_for_delta(self, delta_mv: float) -> str:
        if delta_mv < BALANCE_THRESHOLD_YELLOW:
            return "green"
        if delta_mv < BALANCE_THRESHOLD_ORANGE:
            return "yellow"
        if delta_mv < BALANCE_THRESHOLD_RED:
            return "orange"
        return "red"

    async def _notify(self, notification_id: str, title: str, message: str) -> None:
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": notification_id,
                "title": title,
                "message": message,
            },
        )
