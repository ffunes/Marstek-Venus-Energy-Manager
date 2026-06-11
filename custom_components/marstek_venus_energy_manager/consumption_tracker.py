"""Consumption history, energy accumulators and solar timing for Marstek Venus.

Owns:
- Persistent stores for consumption history, household/solar accumulators and solar T_start
- Daily 23:55 (local) capture of home consumption (household sensor or derived)
- Startup backfill from recorder history
- Real-time accumulation of household consumption and solar production
- Solar T_start detection plus astronomical sunrise/T_end estimation

Reads/writes the controller's existing public attributes for backward
compatibility with sensors and binary_sensors that read those attrs directly:
    _daily_consumption_history, _daily_grid_at_min_soc_kwh, _grid_at_min_soc_sensor,
    _household_energy_accumulator, _household_accumulator_date,
    _solar_production_accumulator, _solar_accumulator_date, _solar_t_start.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, time as dt_time, timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any, Optional

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DEFAULT_BASE_CONSUMPTION_KWH, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class ConsumptionTracker:
    """Manages consumption history, accumulators and solar timing."""

    def __init__(
        self,
        hass: "HomeAssistant",
        config_entry: "ConfigEntry",
        controller: Any,
    ) -> None:
        self._hass = hass
        self._controller = controller
        self._config_entry = config_entry

        # Persistent stores
        self._consumption_store: Store = Store(
            hass, 1, f"{DOMAIN}_consumption_history"
        )
        self._solar_t_start_store: Store = Store(
            hass, 1, f"{DOMAIN}.{config_entry.entry_id}.solar_t_start"
        )
        self._accumulator_store: Store = Store(
            hass, 1, f"{DOMAIN}.{config_entry.entry_id}.accumulators"
        )
        self._daily_energy_store: Store = Store(
            hass, 1, f"{DOMAIN}.{config_entry.entry_id}.daily_energy"
        )

        # Transient state (not exposed to sensors)
        self._household_last_accumulation_time: Optional[float] = None
        self._solar_last_accumulation_time: Optional[float] = None
        self._daily_solar_last_time: Optional[float] = None
        self._daily_home_last_time: Optional[float] = None
        self._daily_grid_last_time: Optional[float] = None
        # Previous power sample (kW) for trapezoidal integration of the daily totals
        self._daily_solar_last_power_kw: Optional[float] = None
        self._daily_home_last_power_kw: Optional[float] = None
        self._daily_grid_last_power_kw: Optional[float] = None
        self._grid_at_min_soc_last_save_mono: float = 0.0
        self._accumulator_last_save_monotonic: float = 0.0
        self._solar_noon_cache: Optional[tuple[date, float]] = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save_consumption_history(self) -> None:
        """Persist consumption history to disk via HA Store."""
        try:
            data = {
                "history": [
                    (d.isoformat(), c)
                    for d, c in self._controller._daily_consumption_history
                ],
                "grid_at_min_soc_kwh": self._controller._daily_grid_at_min_soc_kwh,
            }
            await self._consumption_store.async_save(data)
        except Exception as e:
            _LOGGER.error("Failed to save consumption history: %s", e)

    async def load_consumption_history(self) -> bool:
        """Load consumption history from HA Store. Returns True if data was loaded."""
        try:
            data = await self._consumption_store.async_load()
            if data and "history" in data and data["history"]:
                self._controller._daily_consumption_history = [
                    (date.fromisoformat(date_str), round(consumption, 2))
                    for date_str, consumption in data["history"]
                ]
                if "grid_at_min_soc_kwh" in data:
                    self._controller._daily_grid_at_min_soc_kwh = round(
                        float(data["grid_at_min_soc_kwh"]), 2
                    )
                    _LOGGER.info(
                        "Loaded grid-at-min-soc accumulator from store: %.2f kWh",
                        self._controller._daily_grid_at_min_soc_kwh,
                    )
                history = self._controller._daily_consumption_history
                _LOGGER.info(
                    "Loaded consumption history from store: %d days (oldest: %s, newest: %s)",
                    len(history),
                    history[0][0] if history else "N/A",
                    history[-1][0] if history else "N/A",
                )
                return True
            _LOGGER.debug("No consumption history found in store")
            return False
        except Exception as e:
            _LOGGER.warning("Failed to load consumption history from store: %s", e)
            return False

    def save_solar_t_start(self) -> None:
        """Fire-and-forget: persist solar_t_start alongside today's date."""
        asyncio.create_task(self._solar_t_start_store.async_save({
            "date": date.today().isoformat(),
            "t_start": self._controller._solar_t_start,
        }))

    async def load_solar_t_start(self) -> None:
        """Restore solar_t_start from storage if it was captured today."""
        try:
            data = await self._solar_t_start_store.async_load()
            if not data:
                return
            if data.get("date") == date.today().isoformat() and data.get("t_start") is not None:
                self._controller._solar_t_start = data["t_start"]
                _LOGGER.info(
                    "Charge Delay: Restored solar T_start=%.2fh from storage (HA restart)",
                    self._controller._solar_t_start,
                )
        except Exception as e:
            _LOGGER.error("Charge Delay: Failed to load solar T_start from storage: %s", e)

    def save_accumulators(self) -> None:
        """Fire-and-forget: persist household and solar accumulators to storage."""
        asyncio.create_task(self.async_save_accumulators())

    async def async_save_accumulators(self) -> None:
        """Await-able persist of household and solar accumulators (used on unload).

        Saved whether or not a dedicated household sensor exists: with none, the
        household accumulator holds the derived home-consumption total.
        """
        ctrl = self._controller
        try:
            await self._accumulator_store.async_save({
                "date": ctrl._household_accumulator_date.isoformat() if ctrl._household_accumulator_date else None,
                "household_kwh": round(ctrl._household_energy_accumulator, 4),
                "solar_kwh": round(ctrl._solar_production_accumulator, 4),
            })
        except Exception as e:
            _LOGGER.error("Failed to save accumulators: %s", e)

    async def load_accumulators(self) -> None:
        """Restore household and solar accumulators from storage (today's values only)."""
        try:
            data = await self._accumulator_store.async_load()
            if not data:
                return
            stored_date_str = data.get("date")
            if not stored_date_str or stored_date_str != date.today().isoformat():
                return
            today = date.today()
            ctrl = self._controller
            ctrl._household_energy_accumulator = float(data.get("household_kwh", 0.0))
            ctrl._household_accumulator_date = today
            ctrl._solar_production_accumulator = float(data.get("solar_kwh", 0.0))
            ctrl._solar_accumulator_date = today
            _LOGGER.info(
                "Restored accumulators from storage: household=%.2f kWh, solar=%.2f kWh",
                ctrl._household_energy_accumulator, ctrl._solar_production_accumulator,
            )
        except Exception as e:
            _LOGGER.warning("Failed to load accumulators from storage: %s", e)

    def save_daily_energy(self) -> None:
        """Fire-and-forget: persist the exact daily solar/home/grid energy totals."""
        asyncio.create_task(self.async_save_daily_energy())

    async def async_save_daily_energy(self) -> None:
        """Await-able persist of the daily energy totals (used on unload)."""
        ctrl = self._controller
        # The grid meter (consumption_sensor) is always configured, so this always
        # has something worth saving (import/export); the date is keyed to today.
        try:
            await self._daily_energy_store.async_save({
                "date": date.today().isoformat(),
                "solar_kwh": round(ctrl._daily_solar_energy_kwh, 4),
                "home_kwh": round(ctrl._daily_home_energy_kwh, 4),
                "grid_import_kwh": round(ctrl._daily_grid_import_energy_kwh, 4),
                "grid_export_kwh": round(ctrl._daily_grid_export_energy_kwh, 4),
            })
        except Exception as e:
            _LOGGER.error("Failed to save daily energy: %s", e)

    async def load_daily_energy(self) -> None:
        """Restore the daily solar/home/grid energy totals (today's values only)."""
        ctrl = self._controller
        try:
            data = await self._daily_energy_store.async_load()
            if not data or data.get("date") != date.today().isoformat():
                return
            today = date.today()
            ctrl._daily_solar_energy_kwh = float(data.get("solar_kwh", 0.0))
            ctrl._daily_solar_energy_date = today
            ctrl._daily_home_energy_kwh = float(data.get("home_kwh", 0.0))
            ctrl._daily_home_energy_date = today
            ctrl._daily_grid_import_energy_kwh = float(data.get("grid_import_kwh", 0.0))
            ctrl._daily_grid_export_energy_kwh = float(data.get("grid_export_kwh", 0.0))
            ctrl._daily_grid_energy_date = today
            _LOGGER.info(
                "Restored daily energy totals from storage: solar=%.2f kWh, home=%.2f kWh, "
                "grid import=%.2f kWh, grid export=%.2f kWh",
                ctrl._daily_solar_energy_kwh, ctrl._daily_home_energy_kwh,
                ctrl._daily_grid_import_energy_kwh, ctrl._daily_grid_export_energy_kwh,
            )
        except Exception as e:
            _LOGGER.warning("Failed to load daily energy from storage: %s", e)

    # ------------------------------------------------------------------
    # Exact daily energy totals (real power sensors, full day)
    # ------------------------------------------------------------------

    def handle_daily_energy_reset(self) -> None:
        """Reset the exact daily solar/home totals at local-midnight rollover."""
        ctrl = self._controller
        today = date.today()
        if ctrl._daily_solar_energy_date != today:
            if ctrl._daily_solar_energy_date is not None:
                _LOGGER.info(
                    "Daily solar energy reset (was %.2f kWh for %s)",
                    ctrl._daily_solar_energy_kwh, ctrl._daily_solar_energy_date,
                )
            ctrl._daily_solar_energy_kwh = 0.0
            self._daily_solar_last_time = None
            self._daily_solar_last_power_kw = None
            ctrl._daily_solar_energy_date = today
        if ctrl._daily_home_energy_date != today:
            if ctrl._daily_home_energy_date is not None:
                _LOGGER.info(
                    "Daily home energy reset (was %.2f kWh for %s)",
                    ctrl._daily_home_energy_kwh, ctrl._daily_home_energy_date,
                )
            ctrl._daily_home_energy_kwh = 0.0
            self._daily_home_last_time = None
            self._daily_home_last_power_kw = None
            ctrl._daily_home_energy_date = today
        if ctrl._daily_grid_energy_date != today:
            if ctrl._daily_grid_energy_date is not None:
                _LOGGER.info(
                    "Daily grid energy reset (import=%.2f export=%.2f kWh for %s)",
                    ctrl._daily_grid_import_energy_kwh,
                    ctrl._daily_grid_export_energy_kwh,
                    ctrl._daily_grid_energy_date,
                )
            ctrl._daily_grid_import_energy_kwh = 0.0
            ctrl._daily_grid_export_energy_kwh = 0.0
            self._daily_grid_last_time = None
            self._daily_grid_last_power_kw = None
            ctrl._daily_grid_energy_date = today

    def _read_power_kw(self, entity_id: str) -> Optional[float]:
        """Read a power entity and return its value in kW, or None if unusable."""
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        unit = state.attributes.get("unit_of_measurement", "W")
        return value if unit == "kW" else value / 1000.0

    async def accumulate_daily_solar_energy(self) -> None:
        """Integrate the real solar production power sensor → exact daily kWh.

        Trapezoidal rule: averages the previous and current sample so a ramping
        production curve is not systematically miscounted (left-Riemann bias).
        """
        ctrl = self._controller
        if not ctrl.solar_production_sensor:
            return
        power_kw = self._read_power_kw(ctrl.solar_production_sensor)
        if power_kw is None:
            self._daily_solar_last_time = None
            self._daily_solar_last_power_kw = None
            return
        power_kw = max(0.0, power_kw)
        now = monotonic()
        if self._daily_solar_last_time is not None and self._daily_solar_last_power_kw is not None:
            dt_hours = (now - self._daily_solar_last_time) / 3600.0
            if dt_hours > 0:
                avg_kw = (self._daily_solar_last_power_kw + power_kw) / 2.0
                ctrl._daily_solar_energy_kwh += avg_kw * dt_hours
        self._daily_solar_last_time = now
        self._daily_solar_last_power_kw = power_kw

    def _derive_home_power_kw(self) -> Optional[float]:
        """Derive instantaneous home consumption (kW) from grid + battery AC + solar.

        Mirrors the aggregate Home Consumption power sensor (home = grid +
        sum(ac_power) + external_solar) so the daily energy total integrates
        exactly what the dashboard power flow shows. Used when no dedicated
        household_consumption_sensor is configured.
        """
        ctrl = self._controller
        if not ctrl.consumption_sensor:
            return None
        grid_kw = self._read_power_kw(ctrl.consumption_sensor)
        if grid_kw is None:
            return None
        total_kw = grid_kw
        for coordinator in ctrl.coordinators:
            if coordinator.data:
                ac = coordinator.data.get("ac_power")
                if ac is not None:
                    total_kw += ac / 1000.0
        if ctrl.solar_production_sensor:
            solar_kw = self._read_power_kw(ctrl.solar_production_sensor)
            if solar_kw is not None:
                total_kw += solar_kw
        return max(0.0, total_kw)

    async def accumulate_daily_home_energy(self) -> None:
        """Integrate household consumption power → exact daily kWh.

        Prefers the user's dedicated household_consumption_sensor; when none is
        configured, derives the same value the power-flow dashboard shows from
        grid + battery AC + solar. Trapezoidal rule averages the previous and
        current sample so a ramping load curve is not systematically miscounted
        (left-Riemann bias).
        """
        ctrl = self._controller
        if ctrl.use_household_consumption_sensor:
            power_kw = self._read_power_kw(ctrl.household_consumption_sensor)
        else:
            power_kw = self._derive_home_power_kw()
        if power_kw is None:
            self._daily_home_last_time = None
            self._daily_home_last_power_kw = None
            return
        power_kw = max(0.0, power_kw)
        now = monotonic()
        if self._daily_home_last_time is not None and self._daily_home_last_power_kw is not None:
            dt_hours = (now - self._daily_home_last_time) / 3600.0
            if dt_hours > 0:
                avg_kw = (self._daily_home_last_power_kw + power_kw) / 2.0
                ctrl._daily_home_energy_kwh += avg_kw * dt_hours
        self._daily_home_last_time = now
        self._daily_home_last_power_kw = power_kw

    async def accumulate_daily_grid_energy(self) -> None:
        """Integrate the net grid meter → exact daily import/export kWh.

        Sign convention of the consumption sensor: positive = importing from the
        grid, negative = exporting to it. Each half integrates separately so the
        panel can show both totals.
        """
        ctrl = self._controller
        # Use the same meter transform as the PD loop so a user-inverted meter
        # (meter_inverted) keeps the +import / -export convention; otherwise the
        # import and export totals would be swapped.
        grid_w = ctrl._apply_meter_transform(self._hass.states.get(ctrl.consumption_sensor))
        if grid_w is None:
            self._daily_grid_last_time = None
            self._daily_grid_last_power_kw = None
            return
        power_kw = grid_w / 1000.0
        now = monotonic()
        # Trapezoidal rule with zero-crossing split: when the meter sign flips
        # between samples (import↔export), the interval is split at the crossing so
        # each half is booked to the correct side instead of misclassifying the
        # whole interval by the start sample's sign.
        if self._daily_grid_last_time is not None and self._daily_grid_last_power_kw is not None:
            dt_hours = (now - self._daily_grid_last_time) / 3600.0
            if dt_hours > 0:
                prev_kw = self._daily_grid_last_power_kw
                curr_kw = power_kw
                if (prev_kw >= 0) == (curr_kw >= 0):
                    kwh = (prev_kw + curr_kw) / 2.0 * dt_hours
                    if kwh >= 0:
                        ctrl._daily_grid_import_energy_kwh += kwh
                    else:
                        ctrl._daily_grid_export_energy_kwh += -kwh
                else:
                    frac = abs(prev_kw) / (abs(prev_kw) + abs(curr_kw))
                    dt_first = dt_hours * frac
                    dt_second = dt_hours - dt_first
                    kwh_first = prev_kw / 2.0 * dt_first
                    kwh_second = curr_kw / 2.0 * dt_second
                    if kwh_first >= 0:
                        ctrl._daily_grid_import_energy_kwh += kwh_first
                    else:
                        ctrl._daily_grid_export_energy_kwh += -kwh_first
                    if kwh_second >= 0:
                        ctrl._daily_grid_import_energy_kwh += kwh_second
                    else:
                        ctrl._daily_grid_export_energy_kwh += -kwh_second
        self._daily_grid_last_time = now
        self._daily_grid_last_power_kw = power_kw

    # ------------------------------------------------------------------
    # Consumption history queries
    # ------------------------------------------------------------------

    def get_avg_daily_consumption(self) -> float:
        """Get average daily consumption from history, with fallback."""
        history = self._controller._daily_consumption_history
        if history:
            total = sum(c for _, c in history)
            return total / len(history)
        return DEFAULT_BASE_CONSUMPTION_KWH

    async def get_dynamic_base_consumption(self) -> float:
        """Get dynamic base consumption from the 7-day average of daily home consumption.

        Daily values are captured at 23:55 from the windowed home-energy
        accumulator; this method opportunistically backfills missing days from
        the Home Consumption sensor's recorder history.
        """
        ctrl = self._controller
        today = date.today()

        # OPPORTUNISTIC BACKFILL: Replace default entries with real data from HA history
        # This recovers real data after restarts or when defaults were pre-populated
        real_data_dates = {
            d for d, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        }
        if len(real_data_dates) < 7:
            for days_ago in range(1, 8):  # Look back 7 days (excluding today)
                past_date = today - timedelta(days=days_ago)
                if past_date not in real_data_dates:
                    value = await self.backfill_home_from_history(past_date)
                    if value is not None and value >= 1.5:
                        replaced = False
                        for i, (d, c) in enumerate(ctrl._daily_consumption_history):
                            if d == past_date:
                                ctrl._daily_consumption_history[i] = (past_date, value)
                                replaced = True
                                break
                        if not replaced:
                            ctrl._daily_consumption_history.append((past_date, value))
                        ctrl._daily_consumption_history.sort(key=lambda x: x[0])
                        ctrl._daily_consumption_history = ctrl._daily_consumption_history[-7:]
                    await asyncio.sleep(0.1)  # Small delay between history queries

        # Calculate average from history
        if len(ctrl._daily_consumption_history) == 0:
            _LOGGER.warning(
                "No consumption history, using fallback: %.1f kWh",
                DEFAULT_BASE_CONSUMPTION_KWH,
            )
            return DEFAULT_BASE_CONSUMPTION_KWH

        total = sum(consumption for _, consumption in ctrl._daily_consumption_history)
        average = total / len(ctrl._daily_consumption_history)

        if average <= 0:
            _LOGGER.warning(
                "Average consumption is 0, using fallback: %.1f kWh",
                DEFAULT_BASE_CONSUMPTION_KWH,
            )
            return DEFAULT_BASE_CONSUMPTION_KWH

        real_count = sum(
            1 for _, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        )
        source = "household sensor" if ctrl.household_consumption_sensor else "battery discharge + grid"
        _LOGGER.info(
            "Dynamic base consumption: %.1f kWh (avg of %d days, %d real + %d defaults, source: %s)",
            average, len(ctrl._daily_consumption_history),
            real_count, len(ctrl._daily_consumption_history) - real_count,
            source,
        )

        return average

    def _home_consumption_entity_id(self) -> Optional[str]:
        """Resolve the aggregate Home Consumption power sensor's entity_id.

        That sensor already encapsulates "household sensor if configured, else
        derived (grid + battery AC + solar)", so its recorder history is the
        single source for backfilling daily home consumption.
        """
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(self._hass)
        return ent_reg.async_get_entity_id(
            "sensor", DOMAIN, "marstek_venus_system_system_home_consumption"
        )

    async def backfill_home_from_history(self, target_date: date) -> Optional[float]:
        """Integrate home power history for target_date → kWh.

        Integrates the aggregate Home Consumption sensor, which already resolves to
        the household sensor or the derived value (grid + battery AC + solar) per the
        active precedence. Only counts time intervals that fall OUTSIDE the
        charging_time_slot (the solar+battery window). Returns None if no usable data.
        """
        ctrl = self._controller

        source_entity = self._home_consumption_entity_id()
        if not source_entity:
            return None

        # Skip days that are not covered by the charging slot (battery doesn't operate those days)
        if ctrl.charging_time_slot:
            day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            if day_names[target_date.weekday()] not in ctrl.charging_time_slot.get("days", []):
                _LOGGER.debug("Household backfill: skipping %s (not a slot day)", target_date)
                return None

        try:
            from homeassistant.components.recorder import history, get_instance
        except ImportError:
            _LOGGER.warning("Recorder not available for household backfill")
            return None

        local_tz = dt_util.get_time_zone(self._hass.config.time_zone) or dt_util.UTC
        start_time = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)
        end_time = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=local_tz)

        # Parse charging_time_slot boundaries (if configured)
        slot_start: Optional[dt_time] = None
        slot_end: Optional[dt_time] = None
        if ctrl.charging_time_slot:
            try:
                slot_start = dt_time.fromisoformat(ctrl.charging_time_slot["start_time"])
                slot_end = dt_time.fromisoformat(ctrl.charging_time_slot["end_time"])
            except Exception:
                pass

        def _in_consumption_window(ts: datetime) -> bool:
            """True when ts is outside the charging_time_slot."""
            if slot_start is None or slot_end is None:
                return True
            t = ts.time().replace(tzinfo=None)
            if slot_start <= slot_end:
                in_slot = slot_start <= t <= slot_end
            else:
                in_slot = t >= slot_start or t <= slot_end
            return not in_slot

        try:
            recorder_instance = get_instance(self._hass)
            states_map = await recorder_instance.async_add_executor_job(
                history.state_changes_during_period,
                self._hass,
                start_time,
                end_time,
                source_entity,
            )
        except Exception as e:
            _LOGGER.error("Home consumption backfill query failed for %s: %s", target_date, e)
            return None

        entity_states = states_map.get(source_entity, [])
        if not entity_states:
            _LOGGER.debug("No home consumption history for %s", target_date)
            return None

        # Integrate power × dt over the consumption window
        energy_kwh = 0.0
        prev_ts: Optional[datetime] = None
        prev_kw: Optional[float] = None

        for state in entity_states:
            if state.state in ('unknown', 'unavailable'):
                prev_ts = None
                prev_kw = None
                continue
            try:
                power_w = float(state.state)
            except (ValueError, TypeError):
                prev_ts = None
                prev_kw = None
                continue

            unit = state.attributes.get("unit_of_measurement", "W")
            power_kw = power_w / 1000.0 if unit == "W" else power_w
            ts = state.last_updated

            if prev_ts is not None and prev_kw is not None:
                # Use the midpoint timestamp to decide if interval is in consumption window
                mid_ts = prev_ts + (ts - prev_ts) / 2
                if _in_consumption_window(mid_ts):
                    dt_hours = (ts - prev_ts).total_seconds() / 3600.0
                    energy_kwh += max(0.0, prev_kw) * dt_hours

            prev_ts = ts
            prev_kw = power_kw

        # Apply excluded-device adjustment using historical power data for each device.
        # Mirrors the real-time logic in _excluded_devices_consumption_delta_kw():
        #   included_in_consumption=True  → device is in home sensor but battery skips it → subtract
        #   included_in_consumption=False → device not in home sensor but battery covers it → add
        excluded_devices = self._config_entry.data.get("excluded_devices", [])
        for device in excluded_devices:
            if device.get("ev_charger_no_telemetry", False):
                continue
            power_sensor = device.get("power_sensor")
            if not power_sensor:
                continue
            try:
                dev_states_map = await recorder_instance.async_add_executor_job(
                    history.state_changes_during_period,
                    self._hass,
                    start_time,
                    end_time,
                    power_sensor,
                )
            except Exception as e:
                _LOGGER.debug(
                    "Excluded device backfill query failed for %s on %s: %s",
                    power_sensor, target_date, e,
                )
                continue

            dev_states = dev_states_map.get(power_sensor, [])
            if not dev_states:
                continue

            dev_kwh = 0.0
            prev_ts = None
            prev_kw = None
            for dev_state in dev_states:
                if dev_state.state in ('unknown', 'unavailable'):
                    prev_ts = None
                    prev_kw = None
                    continue
                try:
                    dev_w = float(dev_state.state)
                except (ValueError, TypeError):
                    prev_ts = None
                    prev_kw = None
                    continue
                dev_unit = dev_state.attributes.get("unit_of_measurement", "W")
                dev_kw = dev_w / 1000.0 if dev_unit == "W" else dev_w
                ts = dev_state.last_updated
                if prev_ts is not None and prev_kw is not None:
                    mid_ts = prev_ts + (ts - prev_ts) / 2
                    if _in_consumption_window(mid_ts):
                        dt_hours = (ts - prev_ts).total_seconds() / 3600.0
                        dev_kwh += max(0.0, prev_kw) * dt_hours
                prev_ts = ts
                prev_kw = dev_kw

            if device.get("included_in_consumption", True):
                energy_kwh -= dev_kwh
            else:
                energy_kwh += dev_kwh

        energy_kwh = max(0.0, energy_kwh)

        if energy_kwh <= 0:
            _LOGGER.debug("Household backfill for %s: no energy accumulated", target_date)
            return None

        result = round(energy_kwh, 2)
        _LOGGER.debug("Household backfill for %s: %.2f kWh", target_date, result)
        return result

    async def startup_backfill_consumption(self) -> None:
        """Run backfill from recorder history shortly after startup.

        Called once after a delay to give the recorder and coordinators time
        to initialize. Replaces default entries with real historical data.
        """
        ctrl = self._controller

        if not ctrl.predictive_charging_enabled:
            return

        today = date.today()

        _LOGGER.info(
            "Startup backfill: attempting to replace defaults with real data "
            "(current history: %d entries, %d real)",
            len(ctrl._daily_consumption_history),
            sum(1 for _, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH),
        )

        # Try to backfill past days from recorder history
        real_data_dates = {
            d for d, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        }
        backfill_count = 0
        for days_ago in range(1, 8):
            past_date = today - timedelta(days=days_ago)
            if past_date not in real_data_dates:
                value = await self.backfill_home_from_history(past_date)
                if value is not None and value >= 1.5:
                    replaced = False
                    for i, (d, c) in enumerate(ctrl._daily_consumption_history):
                        if d == past_date:
                            ctrl._daily_consumption_history[i] = (past_date, value)
                            replaced = True
                            break
                    if not replaced:
                        ctrl._daily_consumption_history.append((past_date, value))
                    ctrl._daily_consumption_history.sort(key=lambda x: x[0])
                    ctrl._daily_consumption_history = ctrl._daily_consumption_history[-7:]
                await asyncio.sleep(0.1)
                backfill_count += 1

        # Fill any remaining gaps in the 7-day window so we always have 7 entries.
        # Use the average of real entries as the gap value; fall back to
        # DEFAULT_BASE_CONSUMPTION_KWH only if there are no real entries at all.
        real_values = [
            c for _, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        ]
        gap_value = (
            round(sum(real_values) / len(real_values), 2) if real_values
            else DEFAULT_BASE_CONSUMPTION_KWH
        )
        existing_dates = {d for d, _ in ctrl._daily_consumption_history}
        for days_ago in range(1, 8):
            past_date = today - timedelta(days=days_ago)
            if past_date not in existing_dates:
                ctrl._daily_consumption_history.append((past_date, gap_value))
                _LOGGER.info(
                    "Startup backfill: no data found for %s, inserted %.2f kWh (%s)",
                    past_date, gap_value,
                    "avg of real days" if real_values else "default fallback",
                )
        ctrl._daily_consumption_history.sort(key=lambda x: x[0])
        ctrl._daily_consumption_history = ctrl._daily_consumption_history[-7:]

        real_after = sum(
            1 for _, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        )
        _LOGGER.info(
            "Startup backfill complete: attempted %d days, now %d real entries out of %d total",
            backfill_count, real_after, len(ctrl._daily_consumption_history),
        )

        # Persist updated history to disk
        await self.save_consumption_history()

    def initialize_history_with_defaults(self) -> None:
        """Initialize consumption history with default values for the past 7 days.

        This provides an immediate 7-day average on first use, using the fallback
        consumption value. Real data will gradually replace these estimates as days pass.

        Only initializes if history is completely empty (first-time setup).
        """
        ctrl = self._controller

        if len(ctrl._daily_consumption_history) > 0:
            return

        _LOGGER.info(
            "Initializing consumption history with default values (%.1f kWh per day)",
            DEFAULT_BASE_CONSUMPTION_KWH,
        )

        today = date.today()

        # Pre-populate with 7 days of fallback values (6 days ago through today)
        for days_ago in range(6, -1, -1):
            past_date = today - timedelta(days=days_ago)
            ctrl._daily_consumption_history.append((past_date, DEFAULT_BASE_CONSUMPTION_KWH))

        _LOGGER.info(
            "Pre-populated consumption history with %d days of default values",
            len(ctrl._daily_consumption_history),
        )

    async def capture_daily_consumption(self, now=None) -> None:
        """Scheduled task to capture daily home consumption.

        Runs daily at 23:55 to snapshot the windowed home-energy accumulator
        into the 7-day history before it resets at midnight, so predictive
        charging always has historical data.

        Args:
            now: Timestamp from scheduler (unused, for compatibility)
        """
        ctrl = self._controller

        if not ctrl.predictive_charging_enabled:
            return

        today = date.today()

        # Consumption comes from the windowed home-energy accumulator, which
        # integrates the household sensor when configured, otherwise the derived
        # home power (grid + battery AC + solar). Both measure the same quantity:
        # total home load during the solar+battery window.
        current_value = round(ctrl._household_energy_accumulator, 2)
        if current_value < 1.5:
            _LOGGER.info(
                "Daily consumption capture: accumulator low (%.2f kWh) — skipping. "
                "Today's value will be recovered from recorder history on the next "
                "predictive-charging cycle.",
                current_value,
            )
            return

        try:
            has_today = any(d == today for d, _ in ctrl._daily_consumption_history)

            if has_today:
                ctrl._daily_consumption_history = [
                    (d, current_value if d == today else c)
                    for d, c in ctrl._daily_consumption_history
                ]
                _LOGGER.info(
                    "Daily consumption capture: UPDATED today's value: %.2f kWh (%d days in history)",
                    current_value, len(ctrl._daily_consumption_history),
                )
            else:
                ctrl._daily_consumption_history.append((today, current_value))
                _LOGGER.info(
                    "Daily consumption capture: CAPTURED today's value: %.2f kWh (%d days in history)",
                    current_value, len(ctrl._daily_consumption_history),
                )

                ctrl._daily_consumption_history.sort(key=lambda x: x[0])
                ctrl._daily_consumption_history = ctrl._daily_consumption_history[-7:]

            await self.save_consumption_history()

        except (ValueError, TypeError) as e:
            _LOGGER.error("Daily consumption capture: Failed to parse sensor value: %s", e)

    async def reset_daily_grid_at_min_soc(self, _now=None) -> None:
        """Reset the daily grid-at-min-soc accumulator at midnight."""
        ctrl = self._controller
        _LOGGER.debug(
            "Daily reset: clearing grid-at-min-soc accumulator (was %.3f kWh)",
            ctrl._daily_grid_at_min_soc_kwh,
        )
        ctrl._daily_grid_at_min_soc_kwh = 0.0
        if ctrl._grid_at_min_soc_sensor:
            ctrl._grid_at_min_soc_sensor.async_write_ha_state()
        await self.save_consumption_history()

    # ------------------------------------------------------------------
    # Solar timing
    # ------------------------------------------------------------------

    def calculate_solar_noon(self) -> float:
        """Calculate local solar noon from HA longitude and timezone.

        Returns solar noon as a float hour (e.g. 13.25 = 13:15).
        Cached per day (recalculated when date changes to handle DST transitions).
        """
        from zoneinfo import ZoneInfo

        today = datetime.now().date()
        if self._solar_noon_cache is not None and self._solar_noon_cache[0] == today:
            return self._solar_noon_cache[1]

        tz = ZoneInfo(self._hass.config.time_zone)
        utc_offset = datetime.now(tz).utcoffset().total_seconds() / 3600
        solar_noon = 12.0 - (self._hass.config.longitude / 15.0) + utc_offset
        self._solar_noon_cache = (today, solar_noon)
        _LOGGER.info(
            "Weekly Full Charge Delay: Solar noon calculated at %.2fh (longitude=%.2f, UTC offset=%.1f)",
            solar_noon, self._hass.config.longitude, utc_offset,
        )
        return solar_noon

    def calculate_sunrise(self) -> Optional[float]:
        """Estimate local sunrise time from HA latitude/longitude and day of year.

        Uses the standard solar declination + hour-angle formula.
        Returns sunrise as a float hour (e.g. 7.5 = 07:30), or None if the
        sun never rises today (polar night) or if HA location is not configured.
        """
        try:
            latitude = self._hass.config.latitude
            if latitude is None:
                return None

            day_of_year = datetime.now().timetuple().tm_yday
            lat_rad = math.radians(latitude)

            # Solar declination (degrees → radians)
            declination_rad = math.radians(
                -23.45 * math.cos(math.radians(360 / 365 * (day_of_year + 10)))
            )

            # Hour angle at sunrise: cos(H) = -tan(lat) * tan(dec)
            cos_h = -math.tan(lat_rad) * math.tan(declination_rad)
            if cos_h < -1 or cos_h > 1:
                return None  # Polar day / polar night

            hour_angle_deg = math.degrees(math.acos(cos_h))
            solar_noon = self.calculate_solar_noon()
            return solar_noon - hour_angle_deg / 15.0
        except Exception:  # noqa: BLE001
            return None

    def detect_solar_t_start(self) -> None:
        """Detect start of solar production via grid sensor and battery state.

        Primary: sets controller._solar_t_start when grid_power <= 0 while batteries
        are not discharging, indicating solar is covering the full house load.

        Fallback: if the primary condition hasn't fired within 30 min after the
        astronomically estimated sunrise (high-consumption day where grid power
        never reaches zero), uses the estimated sunrise as t_start so the
        sinusoidal energy model can still run.

        Only checks after 7:00 to avoid false triggers from overnight grid charging.
        """
        ctrl = self._controller

        if ctrl._solar_t_start is not None:
            return  # Already detected today

        now = datetime.now()
        if now.hour < 7:
            return  # Too early, any export is likely from nocturnal grid charging

        now_h = now.hour + now.minute / 60.0

        # --- Primary: grid ≤ 0 and batteries not discharging ---
        grid_state = self._hass.states.get(ctrl.consumption_sensor)
        grid_power = ctrl._apply_meter_transform(grid_state)
        if grid_power is not None and grid_power <= 0:
            total_battery_power = sum(
                (c.data.get("battery_power", 0) or 0)
                for c in ctrl.coordinators if c.data
            )
            if total_battery_power <= 0:
                ctrl._solar_t_start = now_h
                self.save_solar_t_start()
                t_end = self.estimate_t_end()
                _LOGGER.info(
                    "Charge Delay: Solar T_start detected via grid=%.0fW, battery=%.0fW "
                    "at %.2fh, estimated T_end=%.2fh",
                    grid_power, total_battery_power, ctrl._solar_t_start, t_end,
                )
                return

        # --- Fallback: astronomical sunrise + 30 min buffer ---
        estimated_sunrise = self.calculate_sunrise()
        if estimated_sunrise is not None and now_h >= estimated_sunrise + 0.5:
            ctrl._solar_t_start = estimated_sunrise
            self.save_solar_t_start()
            t_end = self.estimate_t_end()
            _LOGGER.info(
                "Charge Delay: Solar T_start set via astronomical sunrise fallback "
                "(estimated=%.2fh, now=%.2fh, T_end=%.2fh)",
                estimated_sunrise, now_h, t_end,
            )

    def estimate_t_end(self) -> float:
        """Estimate end of solar production by symmetry around solar noon.

        Returns T_end as a float hour. Dynamically extends if batteries
        are still charging beyond the estimated T_end.
        """
        ctrl = self._controller
        solar_noon = self.calculate_solar_noon()
        t_end = 2 * solar_noon - ctrl._solar_t_start

        # Dynamic extension: if current time is past T_end but batteries still charging
        now = datetime.now()
        now_h = now.hour + now.minute / 60.0
        if now_h > t_end:
            any_charging = any(
                (c.data.get("battery_power", 0) or 0) > 0
                for c in ctrl.coordinators if c.data
            )
            if any_charging:
                extended_t_end = now_h + 1.0
                _LOGGER.debug(
                    "Weekly Full Charge Delay: Extended T_end from %.2fh to %.2fh (active production)",
                    t_end, extended_t_end,
                )
                return extended_t_end

        return t_end

    @staticmethod
    def h_to_hhmm(h: Optional[float]) -> Optional[str]:
        """Convert decimal hours to HH:MM string."""
        if h is None:
            return None
        hours = int(h)
        minutes = int((h - hours) * 60)
        return f"{hours:02d}:{minutes:02d}"

    @staticmethod
    def get_solar_fraction_done(now_h: float, t_start: float, t_end: float) -> float:
        """Calculate cumulative fraction of daily solar energy produced by now.

        Uses sinusoidal model: F(t) = [1 - cos(π × (t - t_start) / (t_end - t_start))] / 2
        Returns value clamped to [0, 1].
        """
        if t_end <= t_start:
            return 1.0  # Invalid window, assume all produced

        if now_h <= t_start:
            return 0.0
        if now_h >= t_end:
            return 1.0

        progress = (now_h - t_start) / (t_end - t_start)
        fraction = (1.0 - math.cos(math.pi * progress)) / 2.0
        return max(0.0, min(1.0, fraction))

    def get_today_target_soc(self) -> int:
        """Get today's charge target SOC.

        On weekly full charge day → 100.
        Otherwise → average max_soc across batteries.
        """
        ctrl = self._controller
        if ctrl._weekly_charge_mgr.is_active():
            return 100

        if ctrl.coordinators:
            return round(sum(c.max_soc for c in ctrl.coordinators) / len(ctrl.coordinators))
        return 100

    # ------------------------------------------------------------------
    # Real-time accumulation (called from control loop)
    # ------------------------------------------------------------------

    def handle_accumulator_daily_reset(self) -> None:
        """Reset household and solar accumulators on day rollover.

        Compares each accumulator date against today; if changed, resets the
        accumulator value and clears the corresponding last-accumulation
        timestamp so the next sample doesn't integrate over the reset gap.
        """
        ctrl = self._controller

        today = date.today()
        if ctrl._household_accumulator_date != today:
            if ctrl._household_accumulator_date is not None:
                _LOGGER.info(
                    "Household accumulator daily reset (was %.2f kWh for %s)",
                    ctrl._household_energy_accumulator,
                    ctrl._household_accumulator_date,
                )
            ctrl._household_energy_accumulator = 0.0
            self._household_last_accumulation_time = None
            ctrl._household_accumulator_date = today
        if ctrl._solar_accumulator_date != today:
            if ctrl._solar_accumulator_date is not None:
                _LOGGER.info(
                    "Solar production accumulator daily reset (was %.2f kWh for %s)",
                    ctrl._solar_production_accumulator,
                    ctrl._solar_accumulator_date,
                )
            ctrl._solar_production_accumulator = 0.0
            self._solar_last_accumulation_time = None
            ctrl._solar_accumulator_date = today

    def is_in_consumption_window(self) -> bool:
        """Return True when we are OUTSIDE the charging_time_slot (solar+battery window).

        If no charging_time_slot is configured, the consumption window is 24 h.
        On days NOT covered by the slot, the battery is not in use → return False.
        On days covered by the slot, return True only during the hours outside the slot.
        """
        ctrl = self._controller
        if not ctrl.charging_time_slot:
            return True

        now = datetime.now()
        current_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]

        # Battery only operates on days covered by the charging slot
        if current_day not in ctrl.charging_time_slot["days"]:
            return False

        return not ctrl._check_time_window()

    def get_consumption_window_hours_per_day(self) -> float:
        """Total daily duration (hours) of the window over which avg_consumption is measured.

        Mirrors is_in_consumption_window: 24h if no charging_time_slot, otherwise
        24h minus the slot duration. Used to prorate avg_consumption against the
        portion of the day still ahead in the charge-delay energy balance check.
        """
        slot = self._controller.charging_time_slot
        if not slot:
            return 24.0
        try:
            start = dt_time.fromisoformat(slot["start_time"])
            end = dt_time.fromisoformat(slot["end_time"])
        except Exception:
            return 24.0
        start_h = start.hour + start.minute / 60.0
        end_h = end.hour + end.minute / 60.0
        slot_h = (end_h - start_h) % 24
        return max(0.0, 24.0 - slot_h)

    def consumption_window_hours_in_range(self, from_h: float, to_h: float) -> float:
        """Hours within [from_h, to_h] that fall OUTSIDE the charging_time_slot.

        from_h/to_h are hours of the same day in [0, 24]. Returns 0 when the
        range is empty. When no slot is configured, returns the full range.
        """
        if to_h <= from_h:
            return 0.0
        slot = self._controller.charging_time_slot
        if not slot:
            return to_h - from_h
        try:
            s = dt_time.fromisoformat(slot["start_time"])
            e = dt_time.fromisoformat(slot["end_time"])
        except Exception:
            return to_h - from_h
        s_h = s.hour + s.minute / 60.0
        e_h = e.hour + e.minute / 60.0
        intervals = [(s_h, e_h)] if s_h <= e_h else [(s_h, 24.0), (0.0, e_h)]
        overlap = sum(
            max(0.0, min(to_h, b) - max(from_h, a))
            for a, b in intervals
        )
        return max(0.0, (to_h - from_h) - overlap)

    async def accumulate_household_consumption(self) -> None:
        """Integrate home power → kWh accumulator (called every control cycle).

        Prefers the dedicated household_consumption_sensor; when none is configured,
        derives the same home power the dashboard shows (grid + battery AC + solar)
        so installs without a household sensor still get an accurate consumption
        estimate for predictive charging. Only accumulates during the solar+battery
        window (outside charging_time_slot). Uses monotonic time to avoid issues
        with system clock changes.
        """
        ctrl = self._controller

        if not self.is_in_consumption_window():
            # Outside measurement window — pause accumulation but don't reset timer
            self._household_last_accumulation_time = None
            return

        if ctrl.use_household_consumption_sensor:
            power_kw = self._read_power_kw(ctrl.household_consumption_sensor)
        else:
            power_kw = self._derive_home_power_kw()
        if power_kw is None:
            return

        # Adjust for excluded devices: remove power the battery doesn't cover and
        # add power the battery covers that isn't visible to the home sensor.
        power_kw += ctrl._external_loads.consumption_delta_kw()

        now = monotonic()
        if self._household_last_accumulation_time is not None:
            dt_hours = (now - self._household_last_accumulation_time) / 3600.0
            ctrl._household_energy_accumulator += max(0.0, power_kw) * dt_hours
        self._household_last_accumulation_time = now

    async def accumulate_solar_production(self) -> None:
        """Integrate real-time solar production → kWh accumulator (called every control cycle).

        Solar_W = House_W + Battery_Net_W - Grid_W

        Requires household_consumption_sensor. Grid power comes from consumption_sensor.
        Battery net power (positive = charging) is read from coordinator data.
        Uses monotonic time to avoid issues with system clock changes.
        """
        ctrl = self._controller

        if not ctrl.household_consumption_sensor:
            return

        # Read house power
        house_state = self._hass.states.get(ctrl.household_consumption_sensor)
        if house_state is None or house_state.state in ("unknown", "unavailable"):
            self._solar_last_accumulation_time = None
            return
        try:
            house_w = float(house_state.state)
        except (ValueError, TypeError):
            self._solar_last_accumulation_time = None
            return
        if house_state.attributes.get("unit_of_measurement", "W") == "kW":
            house_w *= 1000.0

        # Read grid power (positive = import, negative = export)
        grid_state = self._hass.states.get(ctrl.consumption_sensor)
        grid_w = ctrl._apply_meter_transform(grid_state)
        if grid_w is None:
            self._solar_last_accumulation_time = None
            return

        # Battery net power (positive = charging)
        battery_net_w = sum(
            (c.data.get("battery_power", 0) or 0)
            for c in ctrl.coordinators if c.data
        )

        solar_w = max(0.0, house_w + battery_net_w - grid_w)

        now = monotonic()
        if self._solar_last_accumulation_time is not None:
            dt_hours = (now - self._solar_last_accumulation_time) / 3600.0
            ctrl._solar_production_accumulator += (solar_w / 1000.0) * dt_hours
        self._solar_last_accumulation_time = now

    # ------------------------------------------------------------------
    # Throttle helpers used by the control loop
    # ------------------------------------------------------------------

    def maybe_save_accumulators(self) -> None:
        """Persist accumulators every 5 min (called every cycle)."""
        now_mono = monotonic()
        if now_mono - self._accumulator_last_save_monotonic >= 300:
            self._accumulator_last_save_monotonic = now_mono
            self.save_accumulators()
            self.save_daily_energy()

    async def maybe_save_grid_at_min_soc_history(self) -> None:
        """Persist consumption history every ~5 min during grid-at-min-soc accumulation.

        Called from the PD control loop when accumulating grid imports while SOC
        is pinned to min_soc. Throttles writes to once every ~5 min. Uses elapsed
        monotonic time, not a cycle count, because the control loop is event-driven
        (variable cadence) — a count would fire faster or slower with the sensor rate.
        """
        now_mono = monotonic()
        if now_mono - self._grid_at_min_soc_last_save_mono >= 300:
            self._grid_at_min_soc_last_save_mono = now_mono
            await self.save_consumption_history()

    async def async_save_all(self) -> None:
        """Await every throttled persistence store at once.

        Called on unload so a reload does not revert the TOTAL_INCREASING daily
        energy sensors (consumption history + grid-at-min-soc, daily solar/home/
        grid totals, household/solar accumulators) to the last throttled (~5 min)
        save, which would step their values backwards and spam the HA log.
        """
        await self.save_consumption_history()
        await self.async_save_accumulators()
        await self.async_save_daily_energy()
