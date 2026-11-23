"""Fixtures for KWB Comfort 4 tests."""

from __future__ import annotations

import pytest

from .fake_kwb import gerald_like

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def kwb(socket_enabled):
    server = gerald_like()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture(autouse=True)
def fast_requests(monkeypatch):
    monkeypatch.setattr("custom_components.kwb_comfort4.const.DEFAULT_REQUEST_DELAY", 0)
    monkeypatch.setattr("custom_components.kwb_comfort4.coordinator.DEFAULT_REQUEST_DELAY", 0)
    monkeypatch.setattr("custom_components.kwb_comfort4.config_flow.DEFAULT_REQUEST_DELAY", 0)
    monkeypatch.setattr("custom_components.kwb_comfort4.coordinator.PROBE_DELAY", 0)
