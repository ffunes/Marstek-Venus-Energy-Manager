"""Runtime dynamic-pricing / real-time-price engine.

``PricingManager`` owns the pricing evaluation, scheduling, control-loop handlers
and discharge-block logic extracted from ``ChargeDischargeController`` (module-8
PR3). Following the ``MaxSocChargeManager`` template, the manager owns the logic
but the runtime *state* stays on the controller by reference
(``_dynamic_pricing_schedule``, ``_dp_*``, ``_realtime_price_charging``,
``_price_based_discharge_blocked``, ``_current_price_slot_active``,
``_price_data_status``, ``_last_decision_data``) because ``sensor.py`` /
``binary_sensor.py`` read it and the PD section of the control loop consumes the
discharge block. The manager reaches all controller state and collaborators via
``self._controller``; price math goes straight to the pure ``calculations``
helpers. No persistence (no Store).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from ..const import (
    PRICE_INTEGRATION_PVPC,
    PRICE_INTEGRATION_CKW,
    PRICE_INTEGRATION_EPEX,
    PRICE_INTEGRATION_ENTSOE,
    PREDICTIVE_MODE_DYNAMIC_PRICING,
    PREDICTIVE_MODE_REALTIME_PRICE,
    NOTIFICATION_ID_PREFIX,
    SOC_REEVALUATION_THRESHOLD,
    EVENING_REEVAL_HOURS_BEFORE_TEND,
    EVENING_REEVAL_FALLBACK_HOUR,
    EVENING_DEFICIT_THRESHOLD_KWH,
)
from . import PriceSlot, DynamicPricingSchedule, calculations, notifications

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PricingManager:
    """Dynamic-pricing / real-time-price engine for one config entry."""

    def __init__(self, hass: "HomeAssistant", controller: Any) -> None:
        self._hass = hass
        self._controller = controller

    # =========================================================================
    # Startup
    # =========================================================================

    async def startup_evaluation(self) -> None:
        """Run dynamic pricing evaluation at startup if the 00:05 window was missed.

        Called once via async_create_task after integration load. Waits 15 s for
        coordinators to complete their first poll, then evaluates if today's schedule
        has not been built yet (e.g. HA restarted after 00:05).
        """
        now = datetime.now()

        # Nothing to do if we're still before the normal 00:05 window
        eval_cutoff = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if now < eval_cutoff:
            _LOGGER.debug("Dynamic pricing: startup check skipped — before 00:05 window")
            return

        # Already evaluated today (00:05 ran before the restart)
        if self._controller._dynamic_pricing_evaluated_date == now.date():
            _LOGGER.debug("Dynamic pricing: startup check skipped — already evaluated today")
            return

        # Give coordinators time to finish their first Modbus poll cycle
        await asyncio.sleep(15)

        if not self._controller.predictive_charging_enabled:
            return  # Unloaded during sleep

        coordinators_with_data = [c for c in self._controller.coordinators if c.data]
        if not coordinators_with_data:
            _LOGGER.warning(
                "Dynamic pricing: startup evaluation skipped — no coordinator data after 15 s"
            )
            return

        _LOGGER.info(
            "Dynamic pricing: running startup evaluation "
            "(restarted at %s, schedule not yet built for %s)",
            now.strftime("%H:%M"), now.date()
        )
        await self._evaluate_dynamic_pricing(extended_horizon=True)

    # =========================================================================
    # DYNAMIC PRICING: Price reading
    # =========================================================================

    def _get_price_unit(self) -> str:
        """Return the price unit label for the configured integration."""
        if self._controller.price_integration_type == PRICE_INTEGRATION_CKW:
            return "CHF/kWh"
        return "€/kWh"

    def _get_current_price(self) -> Optional[float]:
        """Return the current period price from the configured price sensor."""
        if not self._controller.price_sensor:
            return None

        price_state = self._hass.states.get(self._controller.price_sensor)
        if price_state is None:
            return None

        if self._controller.price_integration_type == PRICE_INTEGRATION_CKW:
            now = datetime.now()
            for slot in calculations.parse_ckw_prices(price_state.attributes):
                if slot.start <= now < slot.end:
                    return slot.price

        if self._controller.price_integration_type == PRICE_INTEGRATION_EPEX:
            now = datetime.now()
            for slot in calculations.parse_epex_prices(price_state.attributes):
                if slot.start <= now < slot.end:
                    return slot.price

        if self._controller.price_integration_type == PRICE_INTEGRATION_ENTSOE:
            now = datetime.now()
            for slot in calculations.parse_entsoe_prices(price_state.attributes):
                if slot.start <= now < slot.end:
                    return slot.price

        try:
            return float(price_state.state)
        except (ValueError, TypeError):
            return None

    def _parse_price_data(self, *, horizon_end=None) -> list:
        """Read price sensor and return list[PriceSlot] for remaining slots up to horizon_end.

        Dispatches to the correct parser based on price_integration_type.
        When horizon_end is None, defaults to end of current day (today 23:59:59).
        Returns empty list on error.
        """
        if not self._controller.price_sensor:
            _LOGGER.warning("Dynamic pricing: no price sensor configured")
            self._controller._price_data_status = "no_sensor"
            return []

        state = self._hass.states.get(self._controller.price_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            _LOGGER.warning("Dynamic pricing: price sensor %s unavailable", self._controller.price_sensor)
            self._controller._price_data_status = "sensor_unavailable"
            return []

        attrs = state.attributes
        if self._controller.price_integration_type == PRICE_INTEGRATION_PVPC:
            raw_slots = calculations.parse_pvpc_prices(attrs)
        elif self._controller.price_integration_type == PRICE_INTEGRATION_CKW:
            raw_slots = calculations.parse_ckw_prices(attrs)
        elif self._controller.price_integration_type == PRICE_INTEGRATION_EPEX:
            raw_slots = calculations.parse_epex_prices(attrs)
        elif self._controller.price_integration_type == PRICE_INTEGRATION_ENTSOE:
            raw_slots = calculations.parse_entsoe_prices(attrs)
        else:
            # Nordpool
            raw_slots = calculations.parse_nordpool_prices(attrs)

        if not raw_slots:
            _LOGGER.warning(
                "Dynamic pricing: no price data parsed from %s (integration=%s)",
                self._controller.price_sensor, self._controller.price_integration_type
            )
            self._controller._price_data_status = "no_slots"
            return []

        # Filter to remaining slots within the requested horizon.
        # Default (horizon_end=None) keeps today-only semantics so mid-day restarts
        # do not pull in tomorrow — callers that need cross-midnight slots pass an explicit horizon.
        now = datetime.now()
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        effective_horizon = horizon_end if horizon_end is not None else end_of_day
        filtered = [s for s in raw_slots if s.end > now and s.start <= effective_horizon]
        self._controller._price_data_status = f"ok ({len(filtered)} slots)"
        _LOGGER.info("Dynamic pricing: parsed %d slots (%d within horizon)", len(raw_slots), len(filtered))
        return filtered

    # =========================================================================
    # DYNAMIC PRICING: Scheduling helpers
    # =========================================================================

    def is_in_dynamic_pricing_slot(self) -> bool:
        """Return True if current time falls within a selected cheap slot."""
        if not self._controller._dynamic_pricing_schedule:
            return False
        now = datetime.now()
        return any(s.start <= now < s.end for s in self._controller._dynamic_pricing_schedule.selected_slots)

    def _is_dynamic_pricing_evaluation_time(self) -> bool:
        """Return True if it's 00:05 ±5 min and we haven't evaluated today."""
        now = datetime.now()
        today = now.date()

        if self._controller._dynamic_pricing_evaluated_date == today:
            return False

        eval_time = now.replace(hour=0, minute=5, second=0, microsecond=0)
        time_diff = abs((now - eval_time).total_seconds())
        return time_diff <= 5 * 60  # ±5 minutes tolerance

    # =========================================================================
    # DYNAMIC PRICING: Evaluation and notification methods
    # =========================================================================

    async def _evaluate_dynamic_pricing(self, *, extended_horizon: bool = False) -> None:
        """Main evaluation at 00:05: energy balance + prices → schedule."""
        now = datetime.now()
        today = now.date()

        _LOGGER.info("Dynamic pricing: running evaluation at %s", now.strftime("%H:%M"))

        # Step 1: Energy balance
        decision_data = await self._controller._should_activate_grid_charging()
        self._controller._last_decision_data = decision_data
        charging_needed = decision_data["should_charge"]

        # Step 2: Parse price data (always, even without deficit — for diagnostics)
        if extended_horizon:
            end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
            horizon = max(end_of_day, now + timedelta(hours=12))
        else:
            horizon = None
        slots = self._parse_price_data(horizon_end=horizon)
        if slots:
            self._controller._dp_daily_avg_price = sum(s.price for s in slots) / len(slots)
            _LOGGER.debug("Dynamic pricing: daily average price %.4f from %d slots", self._controller._dp_daily_avg_price, len(slots))
        if not slots:
            if not charging_needed:
                # No deficit + no price data: nothing to evaluate
                self._controller._dynamic_pricing_schedule = None
                self._controller._dynamic_pricing_evaluated_date = today
                self._controller._dp_eval_retry_count = 0
                _LOGGER.info("Dynamic pricing: no charging needed and no price data available")
                await self._send_dynamic_pricing_notification(decision_data=decision_data, schedule=None)
                return
            # Has deficit but no price data: retry
            self._controller._dp_eval_retry_count += 1
            _LOGGER.warning(
                "Dynamic pricing: no price data available at 00:05 (retry %d/4)",
                self._controller._dp_eval_retry_count
            )
            return  # Will retry up to 4 times (~30 min intervals via control loop)

        # Step 3: Calculate hours needed and select cheapest slots
        deficit_kwh = decision_data["energy_deficit_kwh"]
        if charging_needed:
            hours_needed = calculations.calculate_charging_hours_needed(
                deficit_kwh, self._controller.max_contracted_power, self._controller.max_charge_capacity
            )
        else:
            # No deficit — use daily consumption as reference so the number of
            # selected hours is meaningful (same basis the algorithm uses to decide)
            hours_needed = calculations.calculate_charging_hours_needed(
                decision_data["avg_consumption_kwh"], self._controller.max_contracted_power, self._controller.max_charge_capacity
            )
        selected = calculations.select_cheapest_hours(slots, hours_needed, self._controller.max_price_threshold)

        if not selected:
            self._controller._dynamic_pricing_schedule = None
            self._controller._dynamic_pricing_evaluated_date = today
            self._controller._dp_eval_retry_count = 0
            _LOGGER.warning("Dynamic pricing: no slots selected (all above threshold?)")
            await self._send_dynamic_pricing_notification(decision_data=decision_data, schedule=None)
            return

        # Step 4: Build schedule
        avg_price = sum(s.price for s in selected) / len(selected)
        effective_power_kw = min(self._controller.max_contracted_power, self._controller.max_charge_capacity) / 1000.0
        estimated_cost = avg_price * effective_power_kw * hours_needed

        schedule = DynamicPricingSchedule(
            hours_needed=hours_needed,
            selected_slots=selected,
            average_price=avg_price,
            estimated_cost=estimated_cost,
            total_available_slots=len(slots),
            evaluation_time=now,
            energy_deficit_kwh=deficit_kwh,
            charging_needed=charging_needed,
        )
        self._controller._dynamic_pricing_schedule = schedule
        # Use the date of the selected slots (tomorrow at eval time) so the midnight
        # reset only fires the day AFTER the slots — not before they can be used.
        slots_date = max(s.start.date() for s in selected) if selected else (now.date() + timedelta(days=1))
        self._controller._dynamic_pricing_evaluated_date = slots_date
        self._controller._dp_eval_retry_count = 0

        _LOGGER.info(
            "Dynamic pricing: evaluation complete — %d slots selected, %.1fh, avg=%.3f %s, charging_needed=%s",
            len(selected), hours_needed, avg_price, self._get_price_unit(), charging_needed
        )
        await self._send_dynamic_pricing_notification(decision_data=decision_data, schedule=schedule)

    async def _send_dynamic_pricing_notification(
        self,
        decision_data: dict,
        schedule: Optional[DynamicPricingSchedule]
    ) -> None:
        """Send persistent notification for dynamic pricing evaluation."""
        title, message = notifications.format_dynamic_pricing_notification(
            decision_data,
            schedule,
            unit=self._get_price_unit(),
            max_price_threshold=self._controller.max_price_threshold,
            max_contracted_power=self._controller.max_contracted_power,
            max_charge_capacity=self._controller.max_charge_capacity,
        )
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{NOTIFICATION_ID_PREFIX}predictive_charging_evaluation",
            },
        )

    async def _send_dynamic_pricing_slot_start_notification(self, slot: PriceSlot) -> None:
        """Send notification when a cheap pricing slot starts."""
        schedule = self._controller._dynamic_pricing_schedule
        if not schedule:
            return

        title, message = notifications.format_slot_start_notification(
            slot,
            schedule,
            unit=self._get_price_unit(),
            max_contracted_power=self._controller.max_contracted_power,
        )
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{NOTIFICATION_ID_PREFIX}predictive_charging_evaluation",
            },
        )

    async def _check_dp_pre_slot_reevaluation(self) -> None:
        """Re-evaluate energy balance 1 hour before each upcoming dynamic pricing slot.

        If the system already charged in an earlier slot and the battery is now
        sufficiently charged (solar + current SOC covers consumption), marks the
        next slot as skippable so it does not activate unnecessarily.
        Called every 2.5 s from the dynamic pricing control loop handler.
        """
        if not self._controller._dynamic_pricing_schedule or not self._controller._dynamic_pricing_schedule.charging_needed:
            return

        now = datetime.now()
        upcoming = [s for s in self._controller._dynamic_pricing_schedule.selected_slots if s.start > now]
        if not upcoming:
            return  # No future slots left

        next_slot = upcoming[0]

        # Only act during the ±5-minute window that is exactly 1 hour before the slot
        pre_eval_time = next_slot.start - timedelta(hours=1)
        if abs((now - pre_eval_time).total_seconds()) > 5 * 60:
            return

        # Already evaluated this slot → nothing to do
        if next_slot.start in self._controller._dp_pre_evaluated_slots:
            return

        # Skip re-evaluation if we're currently charging — the battery hasn't
        # benefited from the ongoing charge yet, so the result would be the same
        # as the original 00:05 evaluation (misleading and noisy).
        # This covers back-to-back slots where the pre-eval window of slot B
        # coincides with the active charging window of slot A.
        if self._controller._current_price_slot_active:
            return

        _LOGGER.info(
            "Dynamic pricing: running pre-slot re-evaluation for slot at %s",
            next_slot.start.strftime("%H:%M")
        )
        decision = await self._controller._should_activate_grid_charging()
        should_charge = decision["should_charge"]
        self._controller._dp_pre_evaluated_slots[next_slot.start] = should_charge

        if should_charge:
            await self._send_dp_pre_slot_reevaluation_notification(next_slot, decision)

    async def _send_dp_pre_slot_reevaluation_notification(
        self, slot: PriceSlot, decision: dict
    ) -> None:
        """Send notification when a pre-slot re-evaluation confirms charging is still needed.

        Only called when should_charge=True. Skipped slots are logged silently.
        """
        title, message = notifications.format_dp_pre_slot_reevaluation_notification(
            slot,
            decision,
            unit=self._get_price_unit(),
        )
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{NOTIFICATION_ID_PREFIX}predictive_charging_evaluation",
            },
        )

    def _is_evening_reevaluation_time(self) -> bool:
        """Return True when it's time for the late-day battery re-evaluation.

        Triggers once per day either:
        - 1.5 h before estimated T_end (when solar T_start was detected), or
        - at EVENING_REEVAL_FALLBACK_HOUR (16:00) when no T_start was seen today.

        Does not trigger after 23:00 to avoid clashing with the 00:05 evaluation.
        """
        from datetime import datetime
        now = datetime.now()

        if self._controller._dp_evening_reevaluated_date == now.date():
            return False

        now_h = now.hour + now.minute / 60.0
        if now_h >= 23.0:
            return False

        if self._controller._solar_t_start is not None:
            trigger_h = self._controller._consumption_tracker.estimate_t_end() - EVENING_REEVAL_HOURS_BEFORE_TEND
        else:
            trigger_h = EVENING_REEVAL_FALLBACK_HOUR

        return now_h >= trigger_h

    async def _evaluate_evening_recharge(self) -> None:
        """Late-day re-evaluation: charge batteries cheaply if solar fell short.

        Runs once per day around T_end - 1.5h.  Checks the current battery SOC
        against the configured max_soc and, accounting for remaining solar, decides
        whether to schedule cheap slots from now through the next 12 hours (crosses midnight when tomorrow prices are available).

        Decision flow:
        1. Batteries already at target → skip.
        2. Calculate remaining solar (actual accumulator if available, else sinusoidal).
        3. Net deficit = energy_to_full - remaining_solar_for_battery.
        4. Deficit < EVENING_DEFICIT_THRESHOLD_KWH → skip.
        5. Parse today's future price slots; select cheapest to cover the deficit.
        6. Merge into existing schedule (or create a new one).
        7. Send notification.
        """
        from datetime import datetime

        now = datetime.now()
        today = now.date()
        self._controller._dp_evening_reevaluated_date = today  # mark before any early-returns

        _LOGGER.info("Dynamic pricing: running evening re-evaluation at %s", now.strftime("%H:%M"))

        # --- Battery state ---
        coordinators_with_data = [c for c in self._controller.coordinators if c.data]
        if not coordinators_with_data:
            _LOGGER.info("Evening recharge: no battery data, skipping")
            return

        # Energy needed to bring all batteries to their max_soc
        energy_to_full_kwh = sum(
            max(0.0, (c.max_soc - (c.data.get("battery_soc", c.max_soc) or 0)) / 100.0
                * (c.data.get("battery_total_energy", 0) or 0))
            for c in coordinators_with_data
        )

        if energy_to_full_kwh <= EVENING_DEFICIT_THRESHOLD_KWH:
            _LOGGER.info(
                "Evening recharge: batteries essentially full (%.2f kWh to target), skipping",
                energy_to_full_kwh,
            )
            return

        # --- Remaining solar estimate ---
        now_h = now.hour + now.minute / 60.0
        remaining_solar_kwh = 0.0

        if self._controller.solar_forecast_sensor:
            forecast_state = self._hass.states.get(self._controller.solar_forecast_sensor)
            if forecast_state and forecast_state.state not in ("unknown", "unavailable"):
                try:
                    forecast_today = float(forecast_state.state) * 0.85
                    if self._controller.household_consumption_sensor and self._controller._solar_production_accumulator > 0:
                        remaining_solar_kwh = max(0.0, forecast_today - self._controller._solar_production_accumulator)
                    elif self._controller._solar_t_start is not None:
                        t_end = self._controller._consumption_tracker.estimate_t_end()
                        fraction_done = self._controller._consumption_tracker.get_solar_fraction_done(now_h, self._controller._solar_t_start, t_end)
                        remaining_solar_kwh = forecast_today * (1.0 - fraction_done)
                except (ValueError, TypeError):
                    pass

        # Subtract remaining house consumption from remaining solar (solar not available for battery)
        if self._controller._solar_t_start is not None:
            t_end = self._controller._consumption_tracker.estimate_t_end()
            daylight_h = max(0.0, t_end - self._controller._solar_t_start)
            hours_to_t_end = max(0.0, t_end - now_h)
            if daylight_h > 0:
                avg_consumption_kwh = self._controller._consumption_tracker.get_avg_daily_consumption()
                remaining_consumption_kwh = (avg_consumption_kwh / daylight_h) * hours_to_t_end
                remaining_solar_kwh = max(0.0, remaining_solar_kwh - remaining_consumption_kwh)

        # --- Net deficit ---
        # Apply the configurable grid-charge margin so optimistic solar forecasts
        # are hedged by booking extra cheap grid slots. Capped at energy_to_full.
        margin_factor = 1.0 + self._controller._predictive_grid_charge_margin_pct / 100.0
        evening_deficit_kwh = min(
            energy_to_full_kwh,
            max(0.0, energy_to_full_kwh - remaining_solar_kwh) * margin_factor,
        )

        if evening_deficit_kwh < EVENING_DEFICIT_THRESHOLD_KWH:
            _LOGGER.info(
                "Evening recharge: remaining solar sufficient "
                "(to_full=%.2f kWh, solar_remaining=%.2f kWh) — no action",
                energy_to_full_kwh, remaining_solar_kwh,
            )
            return

        _LOGGER.info(
            "Evening recharge: deficit %.2f kWh (to_full=%.2f, solar_remaining=%.2f) "
            "— searching for cheap slots",
            evening_deficit_kwh, energy_to_full_kwh, remaining_solar_kwh,
        )

        # --- Find cheap slots (extended horizon: now + 12h to capture cheap overnight slots) ---
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        slots = self._parse_price_data(horizon_end=max(end_of_day, now + timedelta(hours=12)))
        if not slots:
            _LOGGER.warning("Evening recharge: no price data available")
            return

        # Exclude slots already in the morning schedule
        if self._controller._dynamic_pricing_schedule:
            scheduled_starts = {s.start for s in self._controller._dynamic_pricing_schedule.selected_slots}
            slots = [s for s in slots if s.start not in scheduled_starts]

        if not slots:
            _LOGGER.info("Evening recharge: no additional slots available (all already scheduled)")
            return

        hours_needed = calculations.calculate_charging_hours_needed(
            evening_deficit_kwh, self._controller.max_contracted_power, self._controller.max_charge_capacity
        )
        selected = calculations.select_cheapest_hours(slots, hours_needed, self._controller.max_price_threshold)

        if not selected:
            _LOGGER.warning("Evening recharge: no slots below price threshold")
            return

        # --- Merge into schedule ---
        if self._controller._dynamic_pricing_schedule:
            merged = sorted(
                self._controller._dynamic_pricing_schedule.selected_slots + selected,
                key=lambda s: s.start,
            )
            self._controller._dynamic_pricing_schedule.selected_slots = merged
            self._controller._dynamic_pricing_schedule.charging_needed = True
            self._controller._dynamic_pricing_evaluated_date = max(s.start.date() for s in merged)
        else:
            avg_price = sum(s.price for s in selected) / len(selected)
            effective_power_kw = min(self._controller.max_contracted_power, self._controller.max_charge_capacity) / 1000.0
            self._controller._dynamic_pricing_schedule = DynamicPricingSchedule(
                hours_needed=hours_needed,
                selected_slots=selected,
                average_price=avg_price,
                estimated_cost=avg_price * effective_power_kw * hours_needed,
                total_available_slots=len(slots),
                evaluation_time=now,
                energy_deficit_kwh=evening_deficit_kwh,
                charging_needed=True,
            )
            self._controller._dynamic_pricing_evaluated_date = max(s.start.date() for s in selected)

        _LOGGER.info(
            "Evening recharge: scheduled %d slot(s) (%.1fh) for %.2f kWh deficit",
            len(selected), hours_needed, evening_deficit_kwh,
        )
        await self._send_evening_recharge_notification(evening_deficit_kwh, selected)

    async def _send_evening_recharge_notification(
        self, deficit_kwh: float, slots: list
    ) -> None:
        """Send notification for the evening re-evaluation result."""
        avg_soc = sum(
            (c.data.get("battery_soc", 0) or 0)
            for c in self._controller.coordinators if c.data
        ) / max(1, sum(1 for c in self._controller.coordinators if c.data))
        title, message = notifications.format_evening_recharge_notification(
            deficit_kwh,
            slots,
            unit=self._get_price_unit(),
            avg_soc=avg_soc,
        )
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{NOTIFICATION_ID_PREFIX}predictive_charging_evening_reeval",
            },
        )

    # =========================================================================
    # DYNAMIC PRICING: Control loop handler
    # =========================================================================

    async def handle_dynamic_pricing_predictive_charging(self) -> None:
        """Handle predictive charging in dynamic pricing mode (called every 2.5s)."""
        now = datetime.now()

        # Phase 1: Evaluation at 23:00
        if self._is_dynamic_pricing_evaluation_time():
            await self._evaluate_dynamic_pricing()
            return

        # Phase 2: Retry if prices weren't available at 00:05 (e.g. sensor update delay)
        if (
            self._controller._dynamic_pricing_evaluated_date != now.date()
            and self._controller._dp_eval_retry_count > 0
            and self._controller._dp_eval_retry_count < 5
            and now.hour == 0  # Only retry within the first hour of the day
        ):
            # Retry every 15 min starting from 00:05
            retry_minute = now.minute
            expected_retry_minute = 5 + self._controller._dp_eval_retry_count * 15
            if abs(retry_minute - expected_retry_minute) <= 2:
                _LOGGER.info("Dynamic pricing: retrying evaluation (attempt %d)", self._controller._dp_eval_retry_count + 1)
                await self._evaluate_dynamic_pricing()
                return

        # Phase 2.5: Pre-slot re-evaluation (1h before each upcoming slot)
        await self._check_dp_pre_slot_reevaluation()

        # Phase 2.6: Evening re-evaluation when solar is winding down
        if self._is_evening_reevaluation_time():
            await self._evaluate_evening_recharge()

        # Phase 3: Daily reset at midnight
        today = now.date()
        if self._controller._dynamic_pricing_evaluated_date is not None:
            if today > self._controller._dynamic_pricing_evaluated_date:
                _LOGGER.info("Dynamic pricing: new day — resetting schedule")
                self._controller._dynamic_pricing_schedule = None
                self._controller._dynamic_pricing_evaluated_date = None
                self._controller._current_price_slot_active = False
                self._controller._dp_eval_retry_count = 0
                self._controller._dp_pre_evaluated_slots = {}
                self._controller._dp_daily_avg_price = None
                self._controller._dp_evening_reevaluated_date = None

        # Phase 4: Check if we're in a selected cheap slot
        if self._controller._dynamic_pricing_schedule and not self._controller.predictive_charging_overridden:
            in_slot = self.is_in_dynamic_pricing_slot()

            if in_slot and not self._controller._current_price_slot_active:
                # Informational schedule only — no grid charging needed
                if not self._controller._dynamic_pricing_schedule.charging_needed:
                    _LOGGER.debug(
                        "Dynamic pricing: inside cheap slot window but charging not needed "
                        "(solar/battery sufficient) — skipping"
                    )
                    # Fall through to discharge control below (do not return early)

                # Respect charge delay: if configured and still active, hold until it unlocks
                elif self._controller.is_charge_blocked():
                    _LOGGER.info(
                        "Dynamic pricing: inside cheap slot window but charge delay is active — holding"
                    )
                    # Fall through to discharge control below (do not return early)

                else:
                    # Find which slot we're entering
                    current_slot = next(
                        (s for s in self._controller._dynamic_pricing_schedule.selected_slots if s.start <= now < s.end),
                        None
                    )

                    # Skip if pre-evaluation decided charging is no longer needed for this slot
                    if current_slot and self._controller._dp_pre_evaluated_slots.get(current_slot.start) is False:
                        _LOGGER.info(
                            "Dynamic pricing: skipping slot %s — pre-evaluation found sufficient energy",
                            current_slot.start.strftime("%H:%M")
                        )
                        # Fall through to discharge control below (do not return early)

                    else:
                        # Entering a cheap slot
                        self._controller._current_price_slot_active = True
                        self._controller._grid_charging_initialized = False
                        self._controller.grid_charging_active = True
                        if current_slot:
                            await self._send_dynamic_pricing_slot_start_notification(current_slot)
                        _LOGGER.info(
                            "Dynamic pricing: entering cheap slot %s",
                            current_slot.start.strftime("%H:%M") if current_slot else "unknown"
                        )

            elif not in_slot and self._controller._current_price_slot_active:
                # Exiting a cheap slot
                self._controller._current_price_slot_active = False
                self._controller._grid_charging_initialized = False
                self._controller.grid_charging_active = False
                self._controller.previous_power = 0
                self._controller.previous_error = 0
                _LOGGER.info("Dynamic pricing: exiting cheap slot — resuming normal control")

            if self._controller._current_price_slot_active:
                await self._controller._handle_predictive_grid_charging()
                return

        # Phase 5: Override active — resume normal PD control
        if self._controller.predictive_charging_overridden:
            if self._controller.grid_charging_active:
                self._controller.grid_charging_active = False
                self._controller._grid_charging_initialized = False
                self._controller._current_price_slot_active = False
                self._controller.first_execution = True

        # Not in a cheap slot — fall through to normal PD control (no return here)
        # Note: ``_price_based_discharge_blocked`` is computed centrally in
        # ``async_update_charge_discharge`` via ``_apply_price_discharge_block``
        # before this handler runs, so the early ``return`` at the cheap-slot path
        # above does not leave it unset for downstream enforcement.

    # =========================================================================
    # REAL-TIME PRICE: reactive charging based on current price every cycle
    # =========================================================================

    async def handle_realtime_price_predictive_charging(self) -> None:
        """Handle predictive charging in real-time price mode (called every 2.5s).

        Reads the current price every cycle and activates/deactivates grid charging
        immediately when the price crosses the threshold, with no pre-scheduling.
        If an average_price_sensor is configured its value is used as the threshold
        instead of the fixed max_price_threshold.
        """
        current_price = self._get_current_price()
        if current_price is None:
            _LOGGER.debug("Real-time price: price sensor %s unavailable", self._controller.price_sensor)
            if self._controller._realtime_price_charging:
                self._controller._realtime_price_charging = False
                self._controller.grid_charging_active = False
                self._controller._grid_charging_initialized = False
                self._controller.previous_power = 0
                self._controller.previous_error = 0
            return

        # Determine threshold: average sensor if configured, else fixed threshold
        threshold = None
        if self._controller.average_price_sensor:
            avg_state = self._hass.states.get(self._controller.average_price_sensor)
            if avg_state is not None:
                try:
                    threshold = float(avg_state.state)
                except (ValueError, TypeError):
                    pass
        if threshold is None:
            threshold = self._controller.max_price_threshold

        if threshold is None:
            _LOGGER.debug("Real-time price: no threshold configured, skipping")
            return

        # Override active — stop any active charging and do not start new
        if self._controller.predictive_charging_overridden:
            if self._controller._realtime_price_charging or self._controller.grid_charging_active:
                self._controller._realtime_price_charging = False
                self._controller.grid_charging_active = False
                self._controller._grid_charging_initialized = False
                self._controller.previous_power = 0
                self._controller.previous_error = 0
            return

        price_is_cheap = current_price <= threshold
        _LOGGER.debug(
            "Real-time price: current=%.4f threshold=%.4f cheap=%s charging=%s",
            current_price, threshold, price_is_cheap, self._controller._realtime_price_charging,
        )

        # Note: ``_price_based_discharge_blocked`` is set in
        # ``async_update_charge_discharge`` via ``_apply_price_discharge_block``
        # before this handler runs, so any early ``return`` above does not skip it.

        if price_is_cheap and not self._controller._realtime_price_charging:
            if not self._controller._is_operation_allowed(is_charging=True):
                if self._controller.charge_delay_enabled and self._controller._charge_delay_mgr.is_charge_delayed():
                    reason = "charge delay active"
                else:
                    reason = "time slot configuration"
                _LOGGER.debug(
                    "Real-time price: cheap price but charging NOT ALLOWED by %s",
                    reason,
                )
            else:
                # Evaluate whether charging is actually needed before starting
                decision_data = await self._controller._should_activate_grid_charging()
                self._controller._last_decision_data = decision_data
                if decision_data["should_charge"]:
                    self._controller._realtime_price_charging = True
                    self._controller._grid_charging_initialized = False
                    self._controller.grid_charging_active = True
                    _LOGGER.info(
                        "Real-time price: charging STARTED (price=%.4f <= threshold=%.4f)",
                        current_price, threshold,
                    )
                else:
                    _LOGGER.info(
                        "Real-time price: cheap price but charging NOT needed (sufficient energy)",
                    )

        elif not price_is_cheap and self._controller._realtime_price_charging:
            self._controller._realtime_price_charging = False
            self._controller.grid_charging_active = False
            self._controller._grid_charging_initialized = False
            self._controller.previous_power = 0
            self._controller.previous_error = 0
            _LOGGER.info(
                "Real-time price: charging STOPPED (price=%.4f > threshold=%.4f)",
                current_price, threshold,
            )

        if self._controller.grid_charging_active:
            if not self._controller._is_operation_allowed(is_charging=True):
                # Time slot ended while charging was active — stop immediately
                self._controller._realtime_price_charging = False
                self._controller.grid_charging_active = False
                self._controller._grid_charging_initialized = False
                self._controller.previous_power = 0
                self._controller.previous_error = 0
                _LOGGER.debug(
                    "Real-time price: charging stopped — outside charge time slot",
                )
                return
            await self._controller._handle_predictive_grid_charging()

    # =========================================================================
    # TIME SLOT: predictive charging handler
    # =========================================================================

    async def handle_time_slot_predictive_charging(self) -> None:
        """Handle predictive charging in time slot mode (extracted from main loop)."""
        # Check if we're in the actual time slot
        in_time_window = (
            self._controller.charging_time_slot is not None and
            self._controller._check_time_window()
        )

        if in_time_window:
            if self._controller.predictive_charging_overridden:
                _LOGGER.debug("Predictive charging overridden by user - continuing normal operation")
                if self._controller.grid_charging_active:
                    self._controller.grid_charging_active = False
                    self._controller._grid_charging_initialized = False
                    self._controller.first_execution = True
                return

            current_avg_soc = sum(c.data.get("battery_soc", 0) for c in self._controller.coordinators if c.data) / len(self._controller.coordinators)
            is_initial_eval = self._controller.last_evaluation_soc is None

            # On slot entry, wait 5 minutes before the initial evaluation so the
            # forecast sensor (which resets at midnight) has time to update.
            if is_initial_eval:
                if self._controller._slot_entry_time is None:
                    self._controller._slot_entry_time = datetime.now()
                    _LOGGER.info(
                        "Time slot entered (SOC: %.1f%%) — waiting 5 min before evaluation "
                        "to allow forecast sensor to update",
                        current_avg_soc,
                    )
                wait_elapsed_s = (datetime.now() - self._controller._slot_entry_time).total_seconds()
                if wait_elapsed_s < 5 * 60:
                    _LOGGER.debug(
                        "Predictive charging: waiting for forecast sensor (%.0f / 300 s) - normal operation continues",
                        wait_elapsed_s,
                    )
                    return

            should_reevaluate = (
                is_initial_eval or
                abs(current_avg_soc - self._controller.last_evaluation_soc) >= SOC_REEVALUATION_THRESHOLD
            )

            if should_reevaluate:
                if is_initial_eval:
                    _LOGGER.info("INITIAL evaluation of predictive grid charging (SOC: %.1f%%)", current_avg_soc)
                else:
                    _LOGGER.info("RE-EVALUATING predictive grid charging due to SOC drop (%.1f%% -> %.1f%%)",
                                self._controller.last_evaluation_soc, current_avg_soc)

                decision_data = await self._controller._should_activate_grid_charging()
                self._controller.grid_charging_active = decision_data["should_charge"]
                self._controller.last_evaluation_soc = current_avg_soc
                self._controller._last_decision_data = decision_data

                if is_initial_eval:
                    await self._send_predictive_charging_notification(
                        decision_data=decision_data
                    )

            if self._controller.grid_charging_active:
                _LOGGER.info("Predictive Grid Charging ACTIVE - target power: %dW", self._controller.max_contracted_power)
                await self._controller._handle_predictive_grid_charging()
                return
            else:
                _LOGGER.info("In predictive charging slot but charging not needed - continuing normal operation")
                return
        else:
            if self._controller.grid_charging_active or self._controller._grid_charging_initialized:
                _LOGGER.info("Exiting predictive grid charging slot - returning to normal mode")
                self._controller.grid_charging_active = False
                self._controller.last_evaluation_soc = None
                self._controller._grid_charging_initialized = False
                self._controller.error_integral = 0.0
                self._controller.previous_error = 0.0
                self._controller.sign_changes = 0
                await self._hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": f"{NOTIFICATION_ID_PREFIX}predictive_charging_evaluation"},
                )

            self._controller._slot_entry_time = None

    async def _send_predictive_charging_notification(
        self,
        decision_data: dict,
        is_daily_evaluation: bool = False,
    ) -> None:
        """Send notification about predictive charging evaluation result.

        Args:
            decision_data: Dict from _should_activate_grid_charging() with decision factors
            is_daily_evaluation: True when called from daily evaluation in automation_slots mode
        """
        # Format the notification using the pricing.notifications helper
        title, message = notifications.format_predictive_notification_message(
            decision_data,
            is_daily_evaluation,
            max_contracted_power=self._controller.max_contracted_power,
            max_charge_capacity=self._controller.max_charge_capacity,
            charging_time_slot=self._controller.charging_time_slot,
        )

        # Send the notification
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{NOTIFICATION_ID_PREFIX}predictive_charging_evaluation",
            },
        )

    # =========================================================================
    # Price-based discharge block
    # =========================================================================

    def apply_price_discharge_block(self) -> None:
        """Set ``_price_based_discharge_blocked`` from current price vs threshold.

        Centralised so the flag is set every cycle BEFORE mode dispatch — even when
        the mode handler returns early (override active, DP cheap-slot active,
        max_soc transition, etc.). Previously the flag was set inside each handler
        and any early ``return`` left it at the cycle-start ``False`` reset, letting
        PD discharge under cheap prices.
        """
        mode = self._controller.predictive_charging_mode

        if mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
            if not self._controller.dp_price_discharge_control or not self._controller.price_sensor:
                self._controller.remove_discharge_block("price_discharge")
                return
        elif mode == PREDICTIVE_MODE_REALTIME_PRICE:
            if not self._controller.rt_price_discharge_control or not self._controller.price_sensor:
                self._controller.remove_discharge_block("price_discharge")
                return
        else:
            self._controller.remove_discharge_block("price_discharge")
            return

        # Reactive per-cycle price check. DP uses the configured fixed threshold
        # when present, otherwise the daily slot average. RT keeps its explicit
        # average-sensor vs fixed-threshold behaviour.
        # DP no longer relies on selected_slots membership for the
        # discharge decision — the slot list governs grid-charging only.
        # This eliminates the post-restart and post-midnight blind windows
        # where _dynamic_pricing_schedule is None.
        threshold = None
        if mode == PREDICTIVE_MODE_DYNAMIC_PRICING:
            threshold = self._controller.max_price_threshold
            if threshold is None:
                threshold = self._controller._dp_daily_avg_price
        elif self._controller.average_price_sensor:
            avg_state = self._hass.states.get(self._controller.average_price_sensor)
            if avg_state is not None:
                try:
                    threshold = float(avg_state.state)
                except (ValueError, TypeError):
                    pass
        if threshold is None and mode == PREDICTIVE_MODE_REALTIME_PRICE:
            threshold = self._controller.max_price_threshold

        if threshold is None:
            self._controller.remove_discharge_block("price_discharge")
            return

        current_price = self._get_current_price()
        if current_price is None:
            self._controller.remove_discharge_block("price_discharge")
            return

        if current_price > threshold:
            self._controller.remove_discharge_block("price_discharge")
            self._controller._price_based_discharge_blocked = False
            return

        self._controller.set_discharge_block(
            "price_discharge",
            "price",
            {"current_price": current_price, "threshold": threshold, "mode": mode},
        )
        self._controller._price_based_discharge_blocked = True
        if self._controller._price_based_discharge_blocked:
            _LOGGER.debug(
                "Price-based discharge BLOCKED (current=%.4f <= threshold=%.4f, mode=%s)",
                current_price, threshold, mode,
            )
