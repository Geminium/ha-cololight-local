"""Shared test fixtures.

* Every test runs with custom integrations enabled, so that Home Assistant can load
  ``custom_components/cololight_local`` (pytest-homeassistant-custom-component).
* ``fake_lamp`` / ``fake_lamp_port``: the UDP emulator of the lamp (tests/fake_lamp.py)
  listening on 127.0.0.1 with a random free port. Tests never talk to a real lamp:
  point the client (or a config entry: ``host="127.0.0.1"``, ``port=fake_lamp_port``)
  at the emulator.

Sockets: the Home Assistant test plugin blocks socket creation in every test
(pytest-socket ``disable_socket(allow_unix_socket=True)``) and restricts ``connect()``
to 127.0.0.1 (``socket_allow_hosts(["127.0.0.1"])``). The emulator and the client need
real UDP sockets, so ``fake_lamp_server`` requests pytest-socket's ``socket_enabled``
fixture, which re-enables socket creation for that test only. ``connect()`` stays
restricted to 127.0.0.1, but ``sendto()`` on an unconnected socket is not checked:
discovery tests must only target loopback addresses. A test needing another loopback
address (e.g. a second lamp on 127.0.0.2) can widen the list with
``pytest_socket.socket_allow_hosts([...])``, see ``allow_second_loopback`` in
tests/test_client.py.

Home Assistant layer (test_config_flow.py, test_init.py, test_light.py...):

* ``mock_discovery`` (autouse): the LAN scans of the integration (background discovery,
  rediscovery by MAC, config flow scan) and the config flow probe are mocked in every
  test, and the network component reports a TEST-NET broadcast address: no broadcast
  and no probe can reach the real network. Tests set return values on the mocks.
* ``mock_config_entry``: a config entry pointing at the emulator. ``setup_integration``
  adds and sets it up (optionally with options or other data), with short client
  timeouts; ``init_integration`` is the loaded entry with default options.
* ``moved_lamp``: a second emulator with the same MAC on 127.0.0.2 (same port), as if
  the lamp had moved to another address. Tests using 127.0.0.2 request
  ``second_loopback``, which skips them where that address is not routed (macOS).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.client import CololightTimeout
from custom_components.cololight_local.const import DOMAIN
from tests.fake_lamp import FakeLamp
from tests.helpers import (
    ACK_TIMEOUT,
    BROADCAST_ADDRESSES,
    MAC,
    RETRY_DELAYS,
    SECOND_LAMP_HOST,
    TITLE,
    DiscoveryMocks,
    SetupIntegration,
)

FAKE_LAMP_HOST = "127.0.0.1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load the integrations of custom_components/."""


@pytest.fixture
async def fake_lamp_server(socket_enabled: None) -> AsyncGenerator[tuple[FakeLamp, int]]:
    """Run a FakeLamp on 127.0.0.1 (random free port) and yield ``(lamp, port)``."""
    lamp = FakeLamp()
    _host, port = await lamp.start(FAKE_LAMP_HOST)
    try:
        yield lamp, port
    finally:
        if lamp.delay:
            # Let delayed replies go out: the Home Assistant test plugin fails a test
            # that leaves timers behind.
            await asyncio.sleep(lamp.delay + 0.05)
        await lamp.stop()


@pytest.fixture
def fake_lamp(fake_lamp_server: tuple[FakeLamp, int]) -> FakeLamp:
    """The running emulator (set ``drop_next``, ``delay``, ``crashed``... on it)."""
    return fake_lamp_server[0]


@pytest.fixture
def fake_lamp_port(fake_lamp_server: tuple[FakeLamp, int]) -> int:
    """UDP port of the running emulator (its host is always 127.0.0.1)."""
    return fake_lamp_server[1]


# ---------------------------------------------------------------------- Home Assistant layer


@pytest.fixture(autouse=True)
def mock_discovery() -> Generator[DiscoveryMocks]:
    """Replace every LAN scan and probe of the integration (see the module docstring)."""
    mocks = DiscoveryMocks(
        background=AsyncMock(return_value=[]),
        rediscovery=AsyncMock(return_value=[]),
        config_flow=AsyncMock(return_value=[]),
        probe=AsyncMock(side_effect=CololightTimeout("no lamp answers in the tests")),
    )
    with (
        patch(
            "homeassistant.components.network.async_get_ipv4_broadcast_addresses",
            AsyncMock(return_value=set(BROADCAST_ADDRESSES)),
        ),
        patch("custom_components.cololight_local.async_discover", mocks.background),
        patch("custom_components.cololight_local.coordinator.async_discover", mocks.rediscovery),
        patch("custom_components.cololight_local.config_flow.async_discover", mocks.config_flow),
        patch("custom_components.cololight_local.config_flow.async_probe", mocks.probe),
    ):
        yield mocks


@pytest.fixture
def fast_client() -> Generator[None]:
    """Short acknowledgement timeout and retry delays for the clients of config entries."""
    with (
        patch("custom_components.cololight_local.ACK_TIMEOUT", ACK_TIMEOUT),
        patch("custom_components.cololight_local.RETRY_DELAYS", RETRY_DELAYS),
    ):
        yield


@pytest.fixture
def mock_config_entry(fake_lamp_port: int) -> MockConfigEntry:
    """A config entry of the emulator (strip, default options), not added to hass."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title=TITLE,
        data={CONF_HOST: FAKE_LAMP_HOST, CONF_PORT: fake_lamp_port, CONF_MAC: MAC, CONF_MODEL: "strip"},
    )


@pytest.fixture
def setup_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fast_client: None
) -> SetupIntegration:
    """Add ``mock_config_entry`` (with ``options`` / extra ``data``) and set it up."""

    async def _setup(options: dict[str, Any] | None = None, **data: Any) -> MockConfigEntry:
        mock_config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            mock_config_entry, data={**mock_config_entry.data, **data}, options=options or {}
        )
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        return mock_config_entry

    return _setup


@pytest.fixture
async def init_integration(setup_integration: SetupIntegration) -> MockConfigEntry:
    """The emulator's config entry, loaded with the default options."""
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.LOADED
    return entry


@pytest.fixture
def second_loopback(socket_enabled: None) -> None:
    """Skip the test when 127.0.0.2 cannot be used (macOS only routes 127.0.0.1 by default)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind((SECOND_LAMP_HOST, 0))
    except OSError as err:
        pytest.skip(f"{SECOND_LAMP_HOST} is not usable ({err}); on macOS: sudo ifconfig lo0 alias 127.0.0.2")
    finally:
        probe.close()


@pytest.fixture
async def moved_lamp(
    fake_lamp: FakeLamp, fake_lamp_port: int, second_loopback: None
) -> AsyncGenerator[FakeLamp]:
    """The same lamp (same MAC) answering on 127.0.0.2, same port: it "moved"."""
    pytest_socket.socket_allow_hosts([FAKE_LAMP_HOST, SECOND_LAMP_HOST])
    lamp = FakeLamp(mac=fake_lamp.mac)
    await lamp.start(SECOND_LAMP_HOST, fake_lamp_port)
    try:
        yield lamp
    finally:
        await lamp.stop()
        pytest_socket.socket_allow_hosts([FAKE_LAMP_HOST])
