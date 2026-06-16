"""Contract test: keep ``FakeCoordinator`` honest against the real coordinator.

The unit suite mocks the coordinator with ``FakeCoordinator`` (conftest). A mock is
only as good as its fidelity to the real interface: ``coordinator.available`` once
passed green against a ``SimpleNamespace`` while crashing in production because the
real attribute is ``is_available``. This test pins the class-level names the fake
mirrors (properties + methods) to the real coordinator, so a rename there fails the
suite instead of silently drifting.

Instance attributes set in ``__init__`` (data, battery_version, max_charge_power,
…) are not visible at class level and are not checked here; constructing a real
coordinator needs hass/pymodbus and is out of scope for the Windows unit suite.
"""
from __future__ import annotations

from custom_components.marstek_venus_energy_manager.coordinator import (
    MarstekVenusDataUpdateCoordinator,
)
from tests.conftest import FakeCoordinator


# Subset of FakeCoordinator.__slots__ that the real coordinator exposes at class
# level (properties + methods). The bug that motivated this guard was exactly
# `is_available` vs `available`.
CLASS_LEVEL_NAMES = (
    "is_available", "device_key", "apply_power", "capabilities", "set_charge_cutoff",
    "write_control",
)


def test_class_level_names_exist_on_real_coordinator():
    for name in CLASS_LEVEL_NAMES:
        assert hasattr(MarstekVenusDataUpdateCoordinator, name), (
            f"FakeCoordinator mirrors {name!r}, but the real coordinator no longer "
            f"exposes it — rename the slot and every test mock together."
        )


def test_constructor_rejects_unknown_attribute():
    # The exact interface-drift hole: a test must not be able to set `available=`
    # (the real attribute is `is_available`) to mirror a production typo.
    try:
        FakeCoordinator(available=False)
    except AttributeError:
        pass
    else:
        raise AssertionError("FakeCoordinator must reject constructor kwarg 'available'")


def test_reading_unset_attribute_raises():
    # A production read of a wrong name (never set on the fake) must raise inside
    # the test rather than returning a silent mock value.
    coord = FakeCoordinator()
    try:
        coord.available
    except AttributeError:
        pass
    else:
        raise AssertionError("FakeCoordinator must not expose attribute 'available'")
