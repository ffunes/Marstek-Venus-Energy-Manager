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

    def record_non_delivery(self, coordinator, commanded: float, actual: float) -> None:
        """Record a non-delivery cycle and exclude after threshold consecutive fails."""
        info = self.batteries.setdefault(
            coordinator,
            {"fail_count": 0, "excluded_at": None, "cooldown_minutes": self._initial_cooldown_min},
        )
        info["fail_count"] += 1
        _LOGGER.debug(
            "[%s] Not delivering power: commanded=%dW, actual=%dW (fail %d/%d)",
            coordinator.name, int(commanded), int(actual),
            info["fail_count"], self._fail_threshold,
        )
        if info["fail_count"] >= self._fail_threshold and info["excluded_at"] is None:
            info["excluded_at"] = dt_util.utcnow()
            _LOGGER.warning(
                "[%s] Battery is not delivering power after %d consecutive cycles "
                "(commanded=%dW, actual=%dW). Excluding from pool for %d minutes.",
                coordinator.name, self._fail_threshold,
                int(commanded), int(actual), info["cooldown_minutes"],
            )

    def clear(self, coordinator) -> None:
        """Mark a battery as healthy (delivering power) and reset its exclusion state."""
        info = self.batteries.get(coordinator)
        if info:
            was_excluded = info["excluded_at"] is not None
            info["fail_count"] = 0
            info["excluded_at"] = None
            info["cooldown_minutes"] = self._initial_cooldown_min
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
