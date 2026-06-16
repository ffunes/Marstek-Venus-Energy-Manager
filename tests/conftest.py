"""Shared pytest configuration for the Marstek Venus Energy Manager test suite.

The Home Assistant test harness comes from ``pytest-homeassistant-custom-component``.
Nothing here talks to real hardware.

Note: tests that use the full in-process ``hass`` fixture build a Home Assistant
event loop. On Windows that loop needs a local socketpair which ``pytest-socket``
(bundled with the HA plugin) blocks, so full integration-level tests are expected
to run in CI on Linux. The unit-level tests in this suite are deliberately written
without the ``hass`` fixture so they run everywhere, including a Windows dev box.

To opt a future test into loading the integration, request the
``enable_custom_integrations`` fixture provided by the plugin.
"""
from __future__ import annotations

from custom_components.marstek_venus_energy_manager.drivers import DriverCapabilities


class FakeCoordinator:
    """Test double pinned to the real coordinator's public surface.

    Every key in ``_DEFAULTS`` mirrors a real ``MarstekVenusDataUpdateCoordinator``
    attribute or property (``is_available`` and ``device_key`` are properties
    there, the rest are instance attributes). The constructor rejects any keyword
    outside that set, so a test cannot invent ``available=`` to match a production
    typo — the real attribute is ``is_available``. That was the interface-drift
    hole: ``SimpleNamespace`` happily *wrote* the bogus name, so the later read
    succeeded and the test went green while production crashed.

    Reading an attribute that was never set raises ``AttributeError`` for free
    (ordinary class), so a production read of a wrong name fails the test too.
    This is intentionally *not* ``__slots__``: production attaches private runtime
    state onto the live coordinator (``_pd_write_count``, ``_hysteresis_active``,
    …) by assignment, and the fake must allow that exactly as the real object does.
    """

    _DEFAULTS = {
        "name": "test",
        "host": "1.2.3.4",
        "port": 502,
        "slave_id": 1,
        "battery_version": "v2",
        "data": None,
        "is_available": True,
        "device_key": "1.2.3.4_502",
        "max_charge_power": 0,
        "max_discharge_power": 0,
        "max_soc": 80,
        "min_soc": 10,
        "rs485_user_disabled": False,
        "balance_hold": False,
        "apply_power": None,
        "set_charge_cutoff": None,
        "write_control": None,
    }

    def __init__(self, **kw):
        unknown = set(kw) - set(self._DEFAULTS)
        if unknown:
            raise AttributeError(
                f"FakeCoordinator: unknown coordinator attribute(s) {sorted(unknown)}; "
                "the real coordinator does not expose them (interface drift guard)"
            )
        for key, default in self._DEFAULTS.items():
            setattr(self, key, kw.get(key, default))

    @property
    def capabilities(self) -> DriverCapabilities:
        """Mirror the real coordinator's driver-owned capabilities.

        The real ``coordinator.capabilities`` proxies the Marstek driver, which
        derives these from the version's register map + entity definitions. The
        fake reproduces that derivation from ``battery_version`` so capability
        consumers can be unit-tested without a live driver.
        """
        v3_family = self.battery_version in ("v3", "vA", "vD")
        has_pv = self.battery_version in ("vA", "vD")
        return DriverCapabilities(
            hardware_soc_cutoff=not v3_family,
            has_force_mode=True,
            push_telemetry=False,
            max_charge_power_w=self.max_charge_power,
            max_discharge_power_w=self.max_discharge_power,
            has_mppt_pv=has_pv,
            has_alarm_registers=self.battery_version == "v2",
            has_rs485_control=True,
        )
