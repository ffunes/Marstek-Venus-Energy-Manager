"""Alarm and fault notifications for Marstek Venus batteries.

Detects newly-set bits in the alarm_status / fault_status registers and
emits Home Assistant persistent notifications. State (previous bitmasks)
is owned by this module so the coordinator no longer carries it.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import ALARM_BIT_DESCRIPTIONS, FAULT_BIT_DESCRIPTIONS

_LOGGER = logging.getLogger(__name__)


def _active_labels(value: int, descriptions: dict) -> list[str]:
    return [descriptions[b] for b in range(32) if (value & (1 << b)) and b in descriptions]


class AlarmNotifier:
    """Tracks alarm/fault bitmask deltas and dispatches HA notifications."""

    def __init__(self, hass: HomeAssistant, device_name: str) -> None:
        self._hass = hass
        self._device_name = device_name
        self._previous_alarm_status: int = 0
        self._previous_fault_status: int = 0

    async def check(self, alarm_status: int, fault_status: int) -> None:
        """Detect newly-set alarm/fault bits and notify, or dismiss if all cleared."""
        new_alarm_bits = alarm_status & ~self._previous_alarm_status
        new_fault_bits = fault_status & ~self._previous_fault_status
        all_cleared = (
            (self._previous_alarm_status or self._previous_fault_status)
            and alarm_status == 0
            and fault_status == 0
        )

        if new_fault_bits or new_alarm_bits:
            await self._send(alarm_status, fault_status, new_alarm_bits, new_fault_bits)
        elif all_cleared:
            await self._hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": f"battery_alarm_{self._device_name}"},
            )

        self._previous_alarm_status = alarm_status
        self._previous_fault_status = fault_status

    async def _send(
        self,
        alarm_status: int,
        fault_status: int,
        new_alarm_bits: int,
        new_fault_bits: int,
    ) -> None:
        is_fault = bool(fault_status)
        header_emoji = "🚨" if is_fault else "⚠️"
        severity = "Fault" if is_fault else "Warning"

        sections: list[str] = []
        sections.append(f"{header_emoji} {'Fault' if is_fault else 'Warning'} detected on {self._device_name}")
        sections.append("")

        if new_fault_bits:
            new_faults = _active_labels(new_fault_bits, FAULT_BIT_DESCRIPTIONS)
            sections.append(f"🆕 New faults:")
            for label in new_faults:
                sections.append(f"  🔴 {label}")

        if new_alarm_bits:
            new_alarms = _active_labels(new_alarm_bits, ALARM_BIT_DESCRIPTIONS)
            sections.append(f"🆕 New alarms:")
            for label in new_alarms:
                sections.append(f"  🟡 {label}")

        all_faults = _active_labels(fault_status, FAULT_BIT_DESCRIPTIONS)
        all_alarms = _active_labels(alarm_status, ALARM_BIT_DESCRIPTIONS)
        extra_faults = [l for l in all_faults if l not in _active_labels(new_fault_bits, FAULT_BIT_DESCRIPTIONS)]
        extra_alarms = [l for l in all_alarms if l not in _active_labels(new_alarm_bits, ALARM_BIT_DESCRIPTIONS)]

        if extra_faults or extra_alarms:
            sections.append("")
            sections.append("⚡ Also active:")
            for label in extra_faults:
                sections.append(f"  🔴 {label}")
            for label in extra_alarms:
                sections.append(f"  🟡 {label}")

        message = "\n".join(sections)
        title = f"{header_emoji} Battery {severity}: {self._device_name}"

        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"battery_alarm_{self._device_name}",
            },
        )
        log_conditions = ", ".join(all_faults + all_alarms)
        _LOGGER.warning("[%s] Battery %s — %s", self._device_name, severity.lower(), log_conditions)
