"""Polling, availability, rediscovery and the deferred save (coordinator.py)."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGB_COLOR
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.cololight_local.client import DiscoveredDevice
from custom_components.cololight_local.const import (
    CONF_CUSTOM_EFFECTS,
    CONF_HIDDEN_EFFECTS,
    CONF_SAVE_AS_DEFAULT,
    CONF_SAVE_DELAY,
    DISCOVERY_TIMEOUT,
)
from custom_components.cololight_local.coordinator import CololightData
from custom_components.cololight_local.effects import STRIP_DYNAMIC_EFFECTS
from custom_components.cololight_local.protocol import ModeState, PowerState
from tests.fake_lamp import FakeLamp, Received
from tests.helpers import (
    BROADCAST_ADDRESSES,
    LAMP_HOST,
    LIGHT_ID,
    OTHER_RAW_MAC,
    RAW_MAC,
    SAVE_BUTTON_ID,
    SECOND_LAMP_HOST,
    SPEED_ID,
    SUNRISE,
    DiscoveryMocks,
    SetupIntegration,
    async_poll,
    coordinator_of,
)

SAVE_OPTIONS = {CONF_SAVE_AS_DEFAULT: True, CONF_SAVE_DELAY: 30, CONF_SCAN_INTERVAL: 300}


def _saves(lamp: FakeLamp) -> list[tuple[int | None, str]]:
    """(element, data) of every EEPROM write (op 07) the lamp received."""
    return [(r.element, r.data.hex()) for r in lamp.received if r.op == 0x07]


def _reads(lamp: FakeLamp) -> list[Received]:
    return [r for r in lamp.received if r.op == 0x03]


async def _turn_on(hass: HomeAssistant, **data: object) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT_ID, **data}, blocking=True
    )


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


# ---------------------------------------------------------------------- polling


async def test_poll_reads_power_and_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    fake_lamp.power = bytes.fromhex("cf28")  # on, 40 %
    fake_lamp.mode = bytes.fromhex("ff0000ff00")  # green
    fake_lamp.received.clear()

    # The scheduled poll (every 10 s by default).
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert [(r.op, r.element) for r in fake_lamp.received] == [(0x03, 0x01), (0x03, 0x02)]
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 102
    assert state.attributes[ATTR_RGB_COLOR] == (0, 255, 0)
    assert coordinator.data == CololightData(
        power=PowerState(on=True, brightness=40), mode=ModeState(bytes.fromhex("0000ff00"))
    )
    assert (coordinator.last_brightness, coordinator.last_rgb) == (40, (0, 255, 0))

    # Off and running an effect: the last brightness and colour are kept.
    fake_lamp.power = bytes.fromhex("ce1e")
    fake_lamp.mode = b"\xff" + SUNRISE
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).state == STATE_OFF
    assert (coordinator.last_brightness, coordinator.last_rgb) == (40, (0, 255, 0))


async def test_failed_polls_keep_state_then_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    fake_lamp_port: int,
    mock_discovery: DiscoveryMocks,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = init_integration
    coordinator = coordinator_of(entry)
    fake_lamp.crashed = True
    caplog.set_level(logging.DEBUG, logger="custom_components.cololight_local")

    # 1st lost poll: previous state kept, entities stay available, no rediscovery yet.
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 1
    assert coordinator.last_update_success
    assert hass.states.get(LIGHT_ID).state == STATE_ON
    mock_discovery.rediscovery.assert_not_awaited()
    assert "poll failed (1 in a row), keeping the previous state" in caplog.text

    # 2nd: still available; the lamp is looked for on the LAN by its MAC.
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 2
    assert coordinator.last_update_success
    assert hass.states.get(LIGHT_ID).state == STATE_ON
    mock_discovery.rediscovery.assert_awaited_once_with(
        BROADCAST_ADDRESSES, timeout=DISCOVERY_TIMEOUT, port=fake_lamp_port
    )

    # 3rd: unavailable.
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 3
    assert not coordinator.last_update_success
    for entity_id in (LIGHT_ID, SPEED_ID, SAVE_BUTTON_ID):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert mock_discovery.rediscovery.await_count == 2
    assert "The Cololight at 127.0.0.1 did not answer" in caplog.text

    # Further failures keep looking for the lamp, every 4th failed poll only.
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 4
    assert mock_discovery.rediscovery.await_count == 3
    for _ in range(3):
        await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 7
    assert mock_discovery.rediscovery.await_count == 3
    await async_poll(hass, entry)
    assert mock_discovery.rediscovery.await_count == 4

    # It answers again: available at once, counter reset.
    fake_lamp.crashed = False
    fake_lamp.power = bytes.fromhex("ce1e")
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 0
    assert coordinator.last_update_success
    assert hass.states.get(LIGHT_ID).state == STATE_OFF
    assert hass.states.get(SAVE_BUTTON_ID).state != STATE_UNAVAILABLE


async def test_one_lost_reply_is_retried_within_the_poll(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    fake_lamp.drop_next = 1
    fake_lamp.power = bytes.fromhex("cf0a")
    await async_poll(hass, init_integration)
    assert coordinator.consecutive_failures == 0
    assert coordinator.data.power == PowerState(on=True, brightness=10)


async def test_command_success_restores_availability(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    fake_lamp.crashed = True
    for _ in range(3):
        await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).state == STATE_UNAVAILABLE

    fake_lamp.crashed = False
    await coordinator.async_turn_off()
    await hass.async_block_till_done()
    assert coordinator.consecutive_failures == 0
    assert hass.states.get(LIGHT_ID).state == STATE_OFF


# ---------------------------------------------------------------------- rediscovery


async def test_rediscovery_follows_the_lamp_to_its_new_address(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = init_integration
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    fake_lamp.crashed = True
    moved_lamp.power = bytes.fromhex("cf28")
    moved_lamp.mode = bytes.fromhex("ff000000ff")
    mock_discovery.rediscovery.return_value = [
        DiscoveredDevice(host="192.0.2.20", mac=OTHER_RAW_MAC),  # another lamp
        DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC),
    ]

    await async_poll(hass, entry)  # 1st failure: no rediscovery yet
    assert entry.data[CONF_HOST] == LAMP_HOST
    await async_poll(hass, entry)  # 2nd failure: found at 127.0.0.2

    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert runtime.client.host == SECOND_LAMP_HOST
    assert entry.runtime_data is runtime  # followed without reloading the entry
    assert coordinator.consecutive_failures == 0
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_BRIGHTNESS] == 102
    assert state.attributes[ATTR_RGB_COLOR] == (0, 0, 255)
    assert "moved from 127.0.0.1 to 127.0.0.2" in caplog.text

    # The next polls go to the new address only.
    fake_lamp.received.clear()
    moved_lamp.received.clear()
    await async_poll(hass, entry)
    assert len(_reads(moved_lamp)) == 2
    assert fake_lamp.received == []


@pytest.mark.parametrize(
    "found",
    [
        [],
        [DiscoveredDevice(host="127.0.0.1", mac=RAW_MAC)],  # same address: nothing to follow
        [DiscoveredDevice(host="192.0.2.20", mac=OTHER_RAW_MAC)],  # another lamp
    ],
)
async def test_rediscovery_without_new_address(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
    found: list[DiscoveredDevice],
) -> None:
    entry = init_integration
    fake_lamp.crashed = True
    mock_discovery.rediscovery.return_value = found
    for _ in range(3):
        await async_poll(hass, entry)
    assert entry.data[CONF_HOST] == LAMP_HOST
    assert entry.runtime_data.client.host == LAMP_HOST
    assert hass.states.get(LIGHT_ID).state == STATE_UNAVAILABLE


async def test_rediscovery_at_the_same_address_reads_the_lamp_again(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
) -> None:
    """The lamp answers the broadcast at its address (it just finished booting): read it
    again at once instead of declaring it unavailable."""
    entry = init_integration
    coordinator = coordinator_of(entry)
    fake_lamp.crashed = True
    calls = 0

    async def discover(*args: object, **kwargs: object) -> list[DiscoveredDevice]:
        nonlocal calls
        calls += 1
        if calls == 2:  # booted during the broadcast of the 3rd failed cycle
            fake_lamp.crashed = False
        return [DiscoveredDevice(host=LAMP_HOST, mac=RAW_MAC)]

    mock_discovery.rediscovery.side_effect = discover
    await async_poll(hass, entry)
    await async_poll(hass, entry)  # answered the broadcast, not the read that follows
    assert coordinator.consecutive_failures == 2
    fake_lamp.power = bytes.fromhex("cf28")
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 0
    assert coordinator.last_update_success
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 102
    assert entry.data[CONF_HOST] == LAMP_HOST


async def test_another_lamp_at_the_address_is_a_failed_poll(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
) -> None:
    """Two lamps swapped their addresses: the other one is not taken for this one."""
    entry = init_integration
    coordinator = coordinator_of(entry)
    fake_lamp.mac = OTHER_RAW_MAC  # another lamp now answers at 127.0.0.1...
    fake_lamp.mode = bytes.fromhex("ff000000ff")
    moved_lamp.mode = bytes.fromhex("ff0000ff00")  # ...and this one moved to 127.0.0.2
    mock_discovery.rediscovery.return_value = [
        DiscoveredDevice(host=LAMP_HOST, mac=OTHER_RAW_MAC),
        DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC),
    ]
    fake_lamp.received.clear()
    await async_poll(hass, entry)
    assert coordinator.consecutive_failures == 1
    assert len(fake_lamp.received) == 1  # refused at once, no retry
    assert hass.states.get(LIGHT_ID).attributes[ATTR_RGB_COLOR] == (255, 34, 34)  # kept

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT_ID}, blocking=True)
    assert err.value.translation_key == "communication_error"

    await async_poll(hass, entry)  # 2nd failure: found by its MAC at 127.0.0.2
    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert coordinator.consecutive_failures == 0
    assert hass.states.get(LIGHT_ID).attributes[ATTR_RGB_COLOR] == (0, 255, 0)


async def test_rediscovery_network_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
) -> None:
    fake_lamp.crashed = True
    mock_discovery.rediscovery.side_effect = OSError("network is unreachable")
    await async_poll(hass, init_integration)
    await async_poll(hass, init_integration)
    assert coordinator_of(init_integration).consecutive_failures == 2
    assert hass.states.get(LIGHT_ID).state == STATE_ON
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).state == STATE_UNAVAILABLE


async def test_rediscovered_address_does_not_answer(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
) -> None:
    """The lamp answered the broadcast from a new address but not the reads that follow."""
    entry = init_integration
    fake_lamp.crashed = True
    moved_lamp.crashed = True
    mock_discovery.rediscovery.return_value = [DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC)]
    await async_poll(hass, entry)
    await async_poll(hass, entry)
    # The address is followed, the previous state is kept.
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST
    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert _reads(moved_lamp)
    assert coordinator_of(entry).consecutive_failures == 2
    assert hass.states.get(LIGHT_ID).state == STATE_ON


# ---------------------------------------------------------------------- deferred save (op 07)


async def test_save_as_default_is_debounced(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
) -> None:
    await setup_integration(options=SAVE_OPTIONS)

    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    await _tick(hass, freezer, 20)
    assert _saves(fake_lamp) == []

    # Another change restarts the delay: nothing at 30 s after the first change...
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    await _tick(hass, freezer, 20)
    assert _saves(fake_lamp) == []

    # ...but once, 30 s after the last one: mode first, then power.
    await _tick(hass, freezer, 15)
    assert _saves(fake_lamp) == [(0x02, "ff" + SUNRISE.hex()), (0x01, "cf64")]
    assert fake_lamp.saved_mode == b"\xff" + SUNRISE
    assert fake_lamp.saved_power == bytes.fromhex("cf64")

    await _tick(hass, freezer, 120)
    assert len(_saves(fake_lamp)) == 2


async def test_save_as_default_writes_nothing_while_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
) -> None:
    """Turning off changes nothing that is stored (the power state never is): no EEPROM
    write while the lamp is off. The colour set before is stored after the next turn on."""
    await setup_integration(options=SAVE_OPTIONS)
    saved_power = fake_lamp.saved_power
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    await hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT_ID}, blocking=True)
    await _tick(hass, freezer, 31)
    assert _saves(fake_lamp) == []
    assert fake_lamp.saved_power == saved_power

    await _turn_on(hass)
    await _tick(hass, freezer, 31)
    assert _saves(fake_lamp) == [(0x02, "ff000000ff"), (0x01, "cf32")]


async def test_save_as_default_skips_an_unchanged_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
) -> None:
    """An on/off routine that changes nothing else writes the EEPROM once."""
    await setup_integration(options=SAVE_OPTIONS)
    for _ in range(3):
        await hass.services.async_call(
            LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT_ID}, blocking=True
        )
        await _turn_on(hass)
        await _tick(hass, freezer, 31)
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 128})  # 50 %, as already saved
    await _tick(hass, freezer, 31)
    assert _saves(fake_lamp) == [(0x02, "ff00ff2222"), (0x01, "cf32")]

    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})  # a real change is stored
    await _tick(hass, freezer, 31)
    assert _saves(fake_lamp)[2:] == [(0x02, "ff00ff2222"), (0x01, "cf64")]


async def test_save_as_default_after_an_explicit_save(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
) -> None:
    """The button always writes; the automatic save then has nothing new to store."""
    await setup_integration(options=SAVE_OPTIONS)
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: SAVE_BUTTON_ID}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: SAVE_BUTTON_ID}, blocking=True
    )
    await _tick(hass, freezer, 31)
    assert _saves(fake_lamp) == [(0x02, "ff00ff2222"), (0x01, "cf64")] * 2


async def test_save_as_default_of_an_unidentified_palette(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Never a lone palette frame: only the brightness is stored, with a warning."""
    entry = await setup_integration(options=SAVE_OPTIONS)
    fake_lamp.mode = bytes.fromhex("ff9300ff64")  # Tron or Tricolor, started from the app
    await async_poll(hass, entry)
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    await _tick(hass, freezer, 31)
    assert _saves(fake_lamp) == [(0x01, "cf64")]
    assert "the running palette effect is not identified" in caplog.text


async def test_deferred_save_waiting_for_a_command_is_dropped(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    """The delay ends while a palette upload is in flight: the state it would store is
    already outdated, so it stores nothing (the command restarted the delay)."""
    await setup_integration(options=SAVE_OPTIONS)
    await _turn_on(hass, **{ATTR_RGB_COLOR: (255, 0, 0)})
    fake_lamp.delay = 0.03
    task = asyncio.create_task(_turn_on(hass, **{ATTR_EFFECT: "Innocence"}))
    while not any(r.data == bytes.fromhex("ff93fefefe") for r in fake_lamp.received):
        await asyncio.sleep(0.005)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))  # the delay ends
    await task
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _saves(fake_lamp) == []

    # 30 s after the effect, the effect is stored.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    innocence = STRIP_DYNAMIC_EFFECTS["Innocence"].frames
    assert _saves(fake_lamp) == [*((0x02, f"ff{frame.hex()}") for frame in innocence), (0x01, "cf32")]


async def test_deferred_save_waiting_for_the_lamp_is_cancelled_on_unload(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    """Unloading cancels a save that already waits for the lamp; the closed client never
    opens a socket again."""
    entry = await setup_integration(options=SAVE_OPTIONS)
    client = entry.runtime_data.client
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    fake_lamp.crashed = True
    command = asyncio.create_task(
        hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT_ID}, blocking=True)
    )
    await asyncio.sleep(0.02)  # the command waits for an acknowledgement
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))  # the save waits
    assert await hass.config_entries.async_unload(entry.entry_id)
    fake_lamp.crashed = False
    with pytest.raises(HomeAssistantError):
        await command
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _saves(fake_lamp) == []
    assert client._transport is None


# ---------------------------------------------------------------------- concurrent callers


async def test_command_during_a_poll_publishes_what_the_poll_read(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """A brightness change waiting for a poll must not publish the colour it saw before."""
    coordinator = coordinator_of(init_integration)
    fake_lamp.mode = bytes.fromhex("ff000000ff")  # changed in the app
    fake_lamp.delay = 0.03
    poll = asyncio.create_task(coordinator.async_refresh())
    await asyncio.sleep(0.01)  # the poll is waiting for the lamp
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    await poll
    await hass.async_block_till_done()
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_RGB_COLOR] == (0, 0, 255)
    assert state.attributes[ATTR_BRIGHTNESS] == 255


async def test_brightness_during_a_speed_change_publishes_the_new_speed(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The light and the number are separate callers: their commands run one at a time."""
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    fake_lamp.delay = 0.03
    speed = asyncio.create_task(
        hass.services.async_call(
            "number", "set_value", {ATTR_ENTITY_ID: SPEED_ID, "value": 30}, blocking=True
        )
    )
    await asyncio.sleep(0.01)  # the speed change is waiting for the lamp
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    await speed
    await hass.async_block_till_done()
    assert fake_lamp.mode_code == bytes.fromhex("01c10200")
    assert hass.states.get(LIGHT_ID).attributes["effect_code"] == "01c10200"
    assert float(hass.states.get(SPEED_ID).state) == 30


async def test_save_as_default_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _saves(fake_lamp) == []


async def test_save_as_default_failure_is_logged(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_integration(options=SAVE_OPTIONS)
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    fake_lamp.crashed = True
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [r.op for r in fake_lamp.received if r.op == 0x07]  # it tried
    assert "could not store the state as power-on state" in caplog.text
    assert fake_lamp.saved_mode == bytes.fromhex("ff00ff2222")  # unchanged


async def test_pending_save_is_cancelled_on_unload(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    entry = await setup_integration(options=SAVE_OPTIONS)
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    assert await hass.config_entries.async_unload(entry.entry_id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _saves(fake_lamp) == []


async def test_pending_save_is_cancelled_on_shutdown(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    entry = await setup_integration(options=SAVE_OPTIONS)
    coordinator = coordinator_of(entry)
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    assert coordinator._save_unsub is not None
    await coordinator.async_shutdown()
    assert coordinator._save_unsub is None


# ---------------------------------------------------------------------- effects of the entry


async def test_effects_from_options(hass: HomeAssistant, setup_integration: SetupIntegration) -> None:
    entry = await setup_integration(
        options={
            CONF_HIDDEN_EFFECTS: ["Sunrise", "Tron"],
            CONF_CUSTOM_EFFECTS: {
                "Mine": {"code": "05b40c10"},
                "Pensieve": {"code": "05b50c10"},  # overrides the built-in of the same name
                "Bad hex": {"code": "zz"},
                "Too short": {"code": "0102"},
                "Colour": {"code": "00ff0000"},
                "No code": {"scheme": "Mood"},
            },
        }
    )
    coordinator = coordinator_of(entry)
    assert "Sunrise" not in coordinator.effects
    assert "Tron" not in coordinator.effects
    assert "Sunrise" in coordinator.all_effects  # still recognised when the lamp runs it
    assert coordinator.effects["Mine"].frames == (bytes.fromhex("05b40c10"),)
    assert coordinator.effects["Pensieve"].frames == (bytes.fromhex("05b50c10"),)
    for name in ("Bad hex", "Too short", "Colour", "No code"):
        assert name not in coordinator.effects
