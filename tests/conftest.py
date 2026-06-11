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
