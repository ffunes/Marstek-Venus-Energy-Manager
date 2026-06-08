"""Non-responsive battery tracking for Marstek Venus.

Excludes batteries that ACK power commands but fail to deliver power
(e.g. firmware glitch, BMS lockout). Excluded batteries are retried after
a cooldown that doubles each cycle, capped.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class NonResponsiveTracker:
    """Track per-battery non-delivery events and gate exclusion via cooldown."""

    def __init__(
        self,
        fail_threshold: int = 3,
        initial_cooldown_min: int = 5,
        cooldown_cap_min: int = 5,
    ) -> None:
        self._fail_threshold = fail_threshold
        self._initial_cooldown_min = initial_cooldown_min
        self._cooldown_cap_min = cooldown_cap_min
        # coordinator -> {"fail_count": int, "excluded_at": datetime|None, "cooldown_minutes": int}
        self.batteries: dict[Any, dict] = {}

    def is_excluded(self, coordinator) -> bool:
        """Return True if the battery is currently in non-responsive cooldown.

        When the cooldown expires, the battery is allowed one retry window:
        fail_count is reset and the next cooldown duration is doubled (capped).
        """
        info = self.batteries.get(coordinator)
        if not info or info["excluded_at"] is None:
            return False
        elapsed_min = (dt_util.utcnow() - info["excluded_at"]).total_seconds() / 60
        if elapsed_min >= info["cooldown_minutes"]:
            _LOGGER.info(
                "[%s] Non-responsive cooldown expired (%d min) - retrying battery",
                coordinator.name, info["cooldown_minutes"],
            )
            info["excluded_at"] = None
            info["fail_count"] = 0
            info["cooldown_minutes"] = min(
                info["cooldown_minutes"] * 2, self._cooldown_cap_min
            )
            return False
        return True

    def _record_fail(
        self, coordinator, reason: str, detail: str,
        *, retry_attempted: bool = False,
    ) -> bool:
        """Increment the fail counter for a battery and exclude after threshold.

        ``reason`` is a stable category string surfaced on the diagnostic sensor:
        ``non_delivery`` (ACK ok, awake, ~0 W out), ``standby_no_delivery`` (ACK ok
        but the inverter sits in standby), ``modbus_write_failed`` /
        ``modbus_exception`` (register write failed), ``feedback_timeout`` (write
        accepted but the readback never followed) or ``ack_mismatch`` (readback did
        not match the command).

        Returns True only on the call that crosses the threshold and excludes the
        battery, so the caller can fire a one-shot wake nudge at that moment.
        """
        info = self.batteries.setdefault(
            coordinator,
            {"fail_count": 0, "excluded_at": None, "cooldown_minutes": self._initial_cooldown_min},
        )
        info["fail_count"] += 1
        info["reason"] = reason
        info["retry_attempted"] = retry_attempted
        _LOGGER.debug(
            "[%s] %s (fail %d/%d, reason=%s, retry=%s)",
            coordinator.name, detail, info["fail_count"], self._fail_threshold,
            reason, retry_attempted,
        )
        if info["fail_count"] >= self._fail_threshold and info["excluded_at"] is None:
            info["excluded_at"] = dt_util.utcnow()
            _LOGGER.warning(
                "[%s] Non-responsive after %d consecutive cycles (reason=%s, "
                "retry_attempted=%s) — %s. Excluding from pool for %d minutes.",
                coordinator.name, self._fail_threshold, reason,
                retry_attempted, detail, info["cooldown_minutes"],
            )
            return True
        return False

    def record_non_delivery(
        self, coordinator, commanded: float, actual: float,
        *, reason: str = "non_delivery", retry_attempted: bool = False,
    ) -> bool:
        """Record a cycle where the battery ACK'd but delivered ~0 W.

        Returns True on the call that just excluded the battery.
        """
        return self._record_fail(
            coordinator, reason,
            f"ACK ok but not delivering power: commanded={int(commanded)}W, actual={int(actual)}W",
            retry_attempted=retry_attempted,
        )

    def record_comm_failure(
        self, coordinator, reason: str, *, retry_attempted: bool = True,
    ) -> bool:
        """Record a cycle where the write or its feedback failed at the Modbus level.

        Returns True on the call that just excluded the battery.
        """
        return self._record_fail(
            coordinator, reason, "Power write/feedback did not complete",
            retry_attempted=retry_attempted,
        )

    def set_wake_attempted(self, coordinator, value: bool) -> None:
        """Flag whether a wake nudge was sent at the moment of exclusion."""
        info = self.batteries.get(coordinator)
        if info:
            info["wake_attempted"] = value

    def clear(self, coordinator) -> None:
        """Mark a battery as healthy (delivering power) and reset its exclusion state."""
        info = self.batteries.get(coordinator)
        if info:
            was_excluded = info["excluded_at"] is not None
            info["fail_count"] = 0
            info["excluded_at"] = None
            info["cooldown_minutes"] = self._initial_cooldown_min
            info["reason"] = None
            info["retry_attempted"] = False
            info["wake_attempted"] = False
            if was_excluded:
                _LOGGER.info(
                    "[%s] Battery is delivering power again - returned to pool",
                    coordinator.name,
                )

    def excluded_names(self) -> list[str]:
        """Return names of batteries currently excluded due to non-responsive behavior."""
        now = dt_util.utcnow()
        return [
            c.name
            for c, info in self.batteries.items()
            if info.get("excluded_at") is not None
            and (now - info["excluded_at"]).total_seconds() / 60 < info["cooldown_minutes"]
        ]
