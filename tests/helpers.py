"""Constants and helpers shared by the Home Assistant level tests.

The config entry of these tests points at the UDP emulator (tests/fake_lamp.py) on
127.0.0.1. Its default state is: on at 50 %, static colour ff2222.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from ipaddress import IPv4Address
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.coordinator import CololightConfigEntry, CololightCoordinator
from tests import fake_lamp

# Type of the setup_integration fixture: (options=None, **data) -> the set up entry.
SetupIntegration = Callable[..., Awaitable[MockConfigEntry]]

LAMP_HOST = "127.0.0.1"  # where the emulator listens (conftest.FAKE_LAMP_HOST)
SECOND_LAMP_HOST = "127.0.0.2"  # the moved_lamp fixture
RAW_MAC = fake_lamp.MAC  # "4C11AEB1B614", as the emulator sends it
MAC = "4c:11:ae:b1:b6:14"  # RAW_MAC as stored in the config entry (also its unique id)
TITLE = "Cololight B614"
OTHER_RAW_MAC = "4C11AE000001"
OTHER_MAC = "4c:11:ae:00:00:01"

LIGHT_ID = "light.cololight_b614"
SPEED_ID = "number.cololight_b614_effect_speed"
SAVE_BUTTON_ID = "button.cololight_b614_save_as_power_on_state"

# What the network component reports in the tests (TEST-NET-1: never routed).
BROADCAST_ADDRESSES = {IPv4Address("192.0.2.255")}

# Short client timing for the config entries of the tests (seconds). The emulator answers
# within a millisecond; 0.1 s leaves room for a slow CI host without retries.
ACK_TIMEOUT = 0.1
RETRY_DELAYS = (0.01,)

INITIAL_RGB = (255, 34, 34)  # FakeLamp default mode ff 00 ff 22 22
SUNRISE = bytes.fromhex("01c10a00")  # single frame, speed byte 0x0a
TRON = (
    "93fefefe",
    "9304058b",
    "93f0b003",
    "93ff0000",
    "930087ff",
    "9300ff64",
)  # multi-frame; the last frame is shared with "Tricolor"


@dataclass
class DiscoveryMocks:
    """The network accesses of the integration that the tests replace."""

    background: AsyncMock  # __init__: LAN scan after start, then every 15 minutes
    rediscovery: AsyncMock  # coordinator: looks for a lamp that stopped answering
    config_flow: AsyncMock  # config flow: LAN scan of the "user" step
    probe: AsyncMock  # config flow: checks that a host is a Cololight


def coordinator_of(entry: CololightConfigEntry) -> CololightCoordinator:
    """The coordinator of a loaded entry."""
    return entry.runtime_data.coordinator


async def async_poll(hass: HomeAssistant, entry: CololightConfigEntry) -> None:
    """Run one polling cycle now and let the entities update."""
    await coordinator_of(entry).async_refresh()
    await hass.async_block_till_done()
