"""Consumption history, energy accumulators and solar timing for Marstek Venus.

Owns:
- Persistent stores for consumption history, household/solar accumulators and solar T_start
- Daily 23:55 (local) capture of battery discharge or household consumption
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

        # Transient state (not exposed to sensors)
        self._household_last_accumulation_time: Optional[float] = None
        self._solar_last_accumulation_time: Optional[float] = None
        self._grid_at_min_soc_save_counter: int = 0
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
        if not self._controller.household_consumption_sensor:
            return
        ctrl = self._controller
        asyncio.create_task(self._accumulator_store.async_save({
            "date": ctrl._household_accumulator_date.isoformat() if ctrl._household_accumulator_date else None,
            "household_kwh": round(ctrl._household_energy_accumulator, 4),
            "solar_kwh": round(ctrl._solar_production_accumulator, 4),
        }))

    async def load_accumulators(self) -> None:
        """Restore household and solar accumulators from storage (today's values only)."""
        if not self._controller.household_consumption_sensor:
            return
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
        """Get dynamic base consumption from 7-day average of daily discharge.

        Uses the daily discharging energy sensor which resets every 24 hours.
        Daily values are automatically captured at 23:55 by scheduled task.
        This method performs opportunistic backfill from history if needed.
        """
        ctrl = self._controller
        today = date.today()
        entity_id = "sensor.marstek_venus_system_daily_discharging_energy"

        # OPPORTUNISTIC BACKFILL: Replace default entries with real data from HA history
        # This recovers real data after restarts or when defaults were pre-populated
        real_data_dates = {
            d for d, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        }
        if len(real_data_dates) < 7:
            for days_ago in range(1, 8):  # Look back 7 days (excluding today)
                past_date = today - timedelta(days=days_ago)
                if past_date not in real_data_dates:
                    if ctrl.household_consumption_sensor:
                        value = await self.backfill_household_from_history(past_date)
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
                    else:
                        await self.capture_from_history(entity_id, past_date)
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

    async def capture_from_history(self, entity_id: str, target_date: date) -> None:
        """Capture daily consumption from HA history for a specific date.

        Gets the maximum value from the target date (final reading before reset).
        Also queries the grid-at-min-soc sensor and sums both values to get the
        full daily consumption estimate (battery discharge + unmet demand).
        """
        ctrl = self._controller

        try:
            from homeassistant.components.recorder import history
        except ImportError:
            _LOGGER.warning("Recorder history module not available for backfill")
            return

        local_tz = dt_util.get_time_zone(self._hass.config.time_zone) or dt_util.UTC
        start_time = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=local_tz)
        end_time = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=local_tz)

        _LOGGER.debug(
            "Backfill attempt: entity=%s, date=%s, range=%s to %s",
            entity_id, target_date, start_time, end_time,
        )

        try:
            from homeassistant.components.recorder import get_instance
            recorder_instance = get_instance(self._hass)
            states = await recorder_instance.async_add_executor_job(
                history.state_changes_during_period,
                self._hass,
                start_time,
                end_time,
                entity_id,
            )

            if entity_id not in states or len(states[entity_id]) == 0:
                _LOGGER.debug("No history found for %s on %s", entity_id, target_date)
                return

            # Find the maximum value (final reading before reset)
            max_value = 0.0
            state_count = 0
            for state in states[entity_id]:
                state_count += 1
                if state.state not in ['unknown', 'unavailable']:
                    try:
                        value = float(state.state)
                        max_value = max(max_value, value)
                    except (ValueError, TypeError):
                        continue

            _LOGGER.debug(
                "Backfill query result: %d states found, max_value=%.2f for %s on %s",
                state_count, max_value, entity_id, target_date,
            )

            # Also query the grid-at-min-soc sensor for this date and add it
            grid_min_soc_entity_id = "sensor.marstek_venus_system_daily_grid_at_min_soc_energy"
            grid_min_soc_value = 0.0
            try:
                grid_states = await recorder_instance.async_add_executor_job(
                    history.state_changes_during_period,
                    self._hass,
                    start_time,
                    end_time,
                    grid_min_soc_entity_id,
                )
                if grid_min_soc_entity_id in grid_states:
                    for state in grid_states[grid_min_soc_entity_id]:
                        if state.state not in ['unknown', 'unavailable']:
                            try:
                                grid_min_soc_value = max(grid_min_soc_value, float(state.state))
                            except (ValueError, TypeError):
                                continue
            except Exception as grid_err:
                _LOGGER.debug(
                    "Could not query grid-at-min-soc history for %s: %s", target_date, grid_err
                )

            total_value = round(max_value + grid_min_soc_value, 2)
            if grid_min_soc_value > 0:
                _LOGGER.debug(
                    "Backfill grid-at-min-soc for %s: +%.3f kWh → total=%.3f kWh",
                    target_date, grid_min_soc_value, total_value,
                )

            if total_value >= 1.5:
                # Replace existing entry for this date (including defaults) or append
                replaced = False
                for i, (d, c) in enumerate(ctrl._daily_consumption_history):
                    if d == target_date:
                        ctrl._daily_consumption_history[i] = (target_date, total_value)
                        replaced = True
                        break
                if not replaced:
                    ctrl._daily_consumption_history.append((target_date, total_value))

                _LOGGER.info(
                    "Captured daily consumption from history: %.1f kWh for %s (%s, history: %d days)",
                    total_value, target_date,
                    "replaced default" if replaced else "new entry",
                    len(ctrl._daily_consumption_history),
                )

                # Cleanup: keep only the 7 most recent entries
                ctrl._daily_consumption_history.sort(key=lambda x: x[0])
                ctrl._daily_consumption_history = ctrl._daily_consumption_history[-7:]
        except Exception as e:
            _LOGGER.error("Failed to capture from history for %s on %s: %s", entity_id, target_date, e)

    async def backfill_household_from_history(self, target_date: date) -> Optional[float]:
        """Integrate household power sensor history for target_date → kWh.

        Only counts time intervals that fall OUTSIDE the charging_time_slot
        (the solar+battery window). Returns None if no usable data was found.
        """
        ctrl = self._controller

        if not ctrl.household_consumption_sensor:
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
                ctrl.household_consumption_sensor,
            )
        except Exception as e:
            _LOGGER.error("Household backfill query failed for %s: %s", target_date, e)
            return None

        entity_states = states_map.get(ctrl.household_consumption_sensor, [])
        if not entity_states:
            _LOGGER.debug("No household sensor history for %s", target_date)
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

        entity_id = "sensor.marstek_venus_system_daily_discharging_energy"
        today = date.today()

        _LOGGER.info(
            "Startup backfill: attempting to replace defaults with real data "
            "(current history: %d entries, %d real)",
            len(ctrl._daily_consumption_history),
            sum(1 for _, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH),
        )

        if not ctrl.household_consumption_sensor:
            # Battery discharge method: also capture today's running total from coordinators
            coordinators_with_data = [c for c in ctrl.coordinators if c.data]
            if coordinators_with_data:
                today_value = round(sum(
                    c.data.get("total_daily_discharging_energy", 0)
                    for c in coordinators_with_data
                ) + ctrl._daily_grid_at_min_soc_kwh, 2)
                if today_value >= 1.5:
                    for i, (d, c) in enumerate(ctrl._daily_consumption_history):
                        if d == today:
                            if c == DEFAULT_BASE_CONSUMPTION_KWH:
                                ctrl._daily_consumption_history[i] = (today, today_value)
                                _LOGGER.info(
                                    "Startup backfill: replaced today's default with current value: %.2f kWh",
                                    today_value,
                                )
                            break

        # Try to backfill past days from recorder history
        real_data_dates = {
            d for d, c in ctrl._daily_consumption_history if c != DEFAULT_BASE_CONSUMPTION_KWH
        }
        backfill_count = 0
        for days_ago in range(1, 8):
            past_date = today - timedelta(days=days_ago)
            if past_date not in real_data_dates:
                if ctrl.household_consumption_sensor:
                    value = await self.backfill_household_from_history(past_date)
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
                else:
                    await self.capture_from_history(entity_id, past_date)
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
        """Scheduled task to capture daily battery consumption.

        Runs daily at 23:55 to capture the day's accumulated discharge energy
        before the sensor resets at midnight. This ensures we always have
        historical data for predictive charging calculations.

        Reads directly from coordinator data (Modbus registers) to avoid
        dependency on entity_id naming.

        Args:
            now: Timestamp from scheduler (unused, for compatibility)
        """
        ctrl = self._controller

        if not ctrl.predictive_charging_enabled:
            return

        today = date.today()

        # --- BIFURCATION: household sensor vs battery discharge estimation ---
        if ctrl.household_consumption_sensor:
            current_value = round(ctrl._household_energy_accumulator, 2)
            if current_value < 1.5:
                _LOGGER.warning(
                    "Daily consumption capture: household accumulator too low (%.2f kWh), skipping",
                    current_value,
                )
                return
        else:
            coordinators_with_data = [c for c in ctrl.coordinators if c.data]
            if not coordinators_with_data:
                _LOGGER.warning("Daily consumption capture: no coordinators with data available")
                return

            current_value = None  # assigned in try block below

        try:
            if not ctrl.household_consumption_sensor:
                current_value = round(sum(
                    c.data.get("total_daily_discharging_energy", 0)
                    for c in coordinators_with_data
                ) + ctrl._daily_grid_at_min_soc_kwh, 2)

            if current_value < 1.5:
                _LOGGER.warning(
                    "Daily consumption capture: value too low (%.2f kWh), skipping",
                    current_value,
                )
                return

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
        if ctrl._is_weekly_full_charge_active():
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
        if not ctrl.household_consumption_sensor:
            return

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

    async def accumulate_household_consumption(self) -> None:
        """Integrate household power sensor → kWh accumulator (called every control cycle).

        Only accumulates during the solar+battery window (outside charging_time_slot).
        Uses monotonic time to avoid issues with system clock changes.
        """
        ctrl = self._controller

        if not ctrl.household_consumption_sensor:
            return

        if not self.is_in_consumption_window():
            # Outside measurement window — pause accumulation but don't reset timer
            self._household_last_accumulation_time = None
            return

        state = self._hass.states.get(ctrl.household_consumption_sensor)
        if state is None or state.state in ('unknown', 'unavailable'):
            if state is None:
                _LOGGER.warning(
                    "Household consumption sensor %s not found",
                    ctrl.household_consumption_sensor,
                )
            return

        try:
            power_w = float(state.state)
        except (ValueError, TypeError):
            return

        unit = state.attributes.get("unit_of_measurement", "W")
        power_kw = power_w / 1000.0 if unit == "W" else power_w

        # Adjust for excluded devices: remove power the battery doesn't cover and
        # add power the battery covers that isn't visible to the home sensor.
        power_kw += ctrl._excluded_devices_consumption_delta_kw()

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

    async def maybe_save_grid_at_min_soc_history(self) -> None:
        """Persist consumption history every ~5 min during grid-at-min-soc accumulation.

        Called from the PD control loop when accumulating grid imports while SOC
        is pinned to min_soc. Throttles writes to once every ~120 cycles
        (~5 min at 2.5 s/cycle).
        """
        self._grid_at_min_soc_save_counter += 1
        if self._grid_at_min_soc_save_counter >= 120:
            self._grid_at_min_soc_save_counter = 0
            await self.save_consumption_history()
