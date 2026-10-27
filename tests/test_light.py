"""The light entity (light.py), end to end through the emulator."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    EFFECT_OFF,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache_with_extra_data

from custom_components.cololight_local.const import (
    CONF_CUSTOM_EFFECTS,
    CONF_HIDDEN_EFFECTS,
    DOMAIN,
    UNKNOWN_PALETTE_EFFECT,
)
from custom_components.cololight_local.effects import (
    DEFAULT_EFFECTS,
    STRIP_DYNAMIC_EFFECTS,
    custom_effect_code,
)
from tests.fake_lamp import FakeLamp
from tests.helpers import INITIAL_RGB, LIGHT_ID, SUNRISE, TRON, SetupIntegration, async_poll, coordinator_of


def _writes(lamp: FakeLamp) -> list[tuple[int | None, str]]:
    """(element, data) of every volatile write (op 04) the lamp received."""
    return [(r.element, r.data.hex()) for r in lamp.received if r.op == 0x04]


async def _turn_on(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT_ID, **data}, blocking=True
    )


async def _turn_off(hass: HomeAssistant) -> None:
    await hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT_ID}, blocking=True)


# ---------------------------------------------------------------------- state


async def test_static_colour_state(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 128  # 50 %
    assert state.attributes[ATTR_RGB_COLOR] == INITIAL_RGB
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.RGB
    assert state.attributes[ATTR_SUPPORTED_COLOR_MODES] == [ColorMode.RGB]
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == LightEntityFeature.EFFECT
    assert state.attributes[ATTR_EFFECT] == EFFECT_OFF
    assert "effect_code" not in state.attributes
    assert "effect_speed" not in state.attributes
    assert state.attributes["friendly_name"] == "Cololight B614"


async def test_effect_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.mode = b"\xff" + SUNRISE
    await async_poll(hass, init_integration)
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_ON
    # While an effect runs only the brightness is adjustable.
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.BRIGHTNESS
    assert state.attributes[ATTR_RGB_COLOR] is None
    assert state.attributes[ATTR_BRIGHTNESS] == 128
    assert state.attributes[ATTR_EFFECT] == "Sunrise"
    assert state.attributes["effect_code"] == SUNRISE.hex()
    assert state.attributes["effect_speed"] == 22  # 32 - 0x0a


async def test_palette_effect_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """A palette effect has no speed; its last frame alone is ambiguous after a restart."""
    fake_lamp.mode = bytes.fromhex("ff9300ff64")  # last frame of Tron and of Tricolor
    await async_poll(hass, init_integration)
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_EFFECT] == UNKNOWN_PALETTE_EFFECT
    assert state.attributes["effect_code"] == "9300ff64"
    assert "effect_speed" not in state.attributes

    fake_lamp.mode = bytes.fromhex("ff93ff0091")  # last frame of Graffiti only
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Graffiti"


async def test_unknown_single_frame_effect_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.mode = bytes.fromhex("ff05b40c10")
    await async_poll(hass, init_integration)
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_EFFECT] == "Effect 05b40c10"
    assert state.attributes["effect_speed"] == 32 - 0x0C


async def test_off_state(hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp) -> None:
    fake_lamp.power = bytes.fromhex("ce1e")
    await async_poll(hass, init_integration)
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_OFF
    assert state.attributes.get(ATTR_BRIGHTNESS) is None


async def test_effect_list(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    effect_list = hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]
    assert effect_list[0] == EFFECT_OFF
    assert effect_list[1:] == [*DEFAULT_EFFECTS, *STRIP_DYNAMIC_EFFECTS]


async def test_effect_list_hexagon(hass: HomeAssistant, setup_integration: SetupIntegration) -> None:
    await setup_integration(**{CONF_MODEL: "hexagon"})
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST] == [EFFECT_OFF, *DEFAULT_EFFECTS]


async def test_effect_list_with_hidden_and_custom_effects(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    code = custom_effect_code("strip", "Mood", "Red", 20, 3).hex()
    await setup_integration(
        options={
            CONF_HIDDEN_EFFECTS: ["Sunrise"],
            CONF_CUSTOM_EFFECTS: {
                "Red mood": {"scheme": "Mood", "color": "Red", "speed": 20, "mode": 3, "code": code}
            },
        }
    )
    effect_list = hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]
    assert effect_list[0] == EFFECT_OFF
    assert "Sunrise" not in effect_list
    assert effect_list[-1] == "Red mood"

    # A custom effect is started and recognised by its name.
    await _turn_on(hass, **{ATTR_EFFECT: "Red mood"})
    assert fake_lamp.mode_code.hex() == code
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Red mood"

    # A hidden effect can still be started by name, and is still recognised.
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    assert fake_lamp.mode_code == SUNRISE
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Sunrise"


# ---------------------------------------------------------------------- turn on / off


@pytest.mark.parametrize(("brightness", "pct"), [(255, 100), (128, 50), (1, 1), (3, 1), (64, 25)])
async def test_turn_on_brightness(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    brightness: int,
    pct: int,
) -> None:
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_BRIGHTNESS: brightness})
    assert _writes(fake_lamp) == [(0x01, f"cf{pct:02x}")]
    assert hass.states.get(LIGHT_ID).attributes[ATTR_BRIGHTNESS] == round(pct * 255 / 100)
    assert coordinator_of(init_integration).last_brightness == pct


async def test_turn_on_colour(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 128, 255)})
    # A colour change keeps the brightness: no power write while on.
    assert _writes(fake_lamp) == [(0x02, "ff000080ff")]
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_RGB_COLOR] == (0, 128, 255)
    assert state.attributes[ATTR_BRIGHTNESS] == 128
    assert coordinator_of(init_integration).last_rgb == (0, 128, 255)

    # Other colour formats are converted by Home Assistant.
    await _turn_on(hass, **{ATTR_HS_COLOR: (120, 100)})
    assert fake_lamp.mode_code == bytes.fromhex("0000ff00")


async def test_turn_on_colour_and_brightness(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 255, 0), ATTR_BRIGHTNESS: 255})
    assert _writes(fake_lamp) == [(0x02, "ff0000ff00"), (0x01, "cf64")]  # mode first


async def test_turn_on_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    assert _writes(fake_lamp) == [(0x02, "ff" + SUNRISE.hex())]
    assert coordinator.last_effect == "Sunrise"
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_EFFECT] == "Sunrise"
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.BRIGHTNESS

    # Effect "off": back to the last static colour.
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: EFFECT_OFF})
    assert _writes(fake_lamp) == [(0x02, "ff00ff2222")]
    assert coordinator.last_effect is None
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_EFFECT] == EFFECT_OFF
    assert state.attributes[ATTR_RGB_COLOR] == INITIAL_RGB


async def test_turn_on_raw_effect_name(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The name shown for an unknown frame ("Effect xxxxxxxx") can be sent back."""
    coordinator = coordinator_of(init_integration)
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: "Effect 05b40c10"})
    assert _writes(fake_lamp) == [(0x02, "ff05b40c10")]
    assert coordinator.last_effect is None
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Effect 05b40c10"


@pytest.mark.parametrize("effect", ["Disco", "Effect 05b40c1", "Effect 05B40C10", "effect 05b40c10"])
async def test_turn_on_unknown_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp, effect: str
) -> None:
    fake_lamp.received.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _turn_on(hass, **{ATTR_EFFECT: effect})
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "unknown_effect"
    assert err.value.translation_placeholders == {"effect": effect}
    assert fake_lamp.received == []


async def test_turn_on_raw_effect_starting_with_00(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """00 selects a static colour: refused before anything is sent."""
    fake_lamp.received.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _turn_on(hass, **{ATTR_EFFECT: "Effect 00ff0000"})
    assert err.value.translation_key == "effect_frame_is_colour"
    assert err.value.translation_placeholders == {"frame": "00ff0000"}
    assert fake_lamp.received == []


async def test_turn_on_effect_off_with_a_colour(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """Effect "off" with a colour (what a scene sends) sets that colour, not the last one."""
    coordinator = coordinator_of(init_integration)
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: EFFECT_OFF, ATTR_RGB_COLOR: (10, 20, 30)})
    assert _writes(fake_lamp) == [(0x02, "ff000a141e")]
    assert coordinator.last_effect is None
    assert coordinator.last_rgb == (10, 20, 30)
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_RGB_COLOR] == (10, 20, 30)
    assert state.attributes[ATTR_EFFECT] == EFFECT_OFF


async def test_turn_on_when_off_sends_mode_then_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _turn_off(hass)
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    # Mode first, then power at the last brightness (50 %).
    assert _writes(fake_lamp) == [(0x02, "ff" + SUNRISE.hex()), (0x01, "cf32")]
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 128


async def test_turn_on_when_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _turn_off(hass)
    fake_lamp.received.clear()
    await _turn_on(hass)
    assert _writes(fake_lamp) == [(0x01, "cf32")]  # last brightness, mode unchanged
    assert hass.states.get(LIGHT_ID).state == STATE_ON

    await _turn_off(hass)
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 26})
    assert _writes(fake_lamp) == [(0x01, "cf0a")]


async def test_turn_on_when_on_without_change(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.received.clear()
    await _turn_on(hass)
    assert _writes(fake_lamp) == []


async def test_turn_off(hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp) -> None:
    fake_lamp.received.clear()
    await _turn_off(hass)
    assert _writes(fake_lamp) == [(0x01, "ce1e")]
    assert not fake_lamp.is_on
    assert hass.states.get(LIGHT_ID).state == STATE_OFF
    assert coordinator_of(init_integration).last_brightness == 50


async def test_state_comes_from_the_acknowledgement(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The entity shows what the lamp acknowledged, not what was asked, with no extra read."""
    original_handle = fake_lamp._handle

    def _handle(op: int, element: int | None, data: bytes) -> bytes:
        if op == 0x04 and element == 0x01:
            data = bytes.fromhex("cf14")  # the lamp applies 20 % whatever was asked
        return original_handle(op, element, data)

    fake_lamp._handle = _handle  # type: ignore[method-assign]
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    assert [r.op for r in fake_lamp.received] == [0x04]
    assert hass.states.get(LIGHT_ID).attributes[ATTR_BRIGHTNESS] == 51


# ---------------------------------------------------------------------- multi-frame effects


async def test_multi_frame_effect_identified_by_what_was_sent(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: "Tron"})
    assert _writes(fake_lamp) == [(0x02, f"ff{frame}") for frame in TRON]
    assert fake_lamp.mode_code.hex() == TRON[-1]
    # Tron and Tricolor end with the same frame: the effect sent last decides.
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Tron"
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Tron"
    assert hass.states.get(LIGHT_ID).attributes["effect_code"] == TRON[-1]

    await _turn_on(hass, **{ATTR_EFFECT: "Tricolor"})
    assert fake_lamp.mode_code.hex() == TRON[-1]
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Tricolor"


# ---------------------------------------------------------------------- failures


async def test_command_failure_raises_and_logs(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_lamp.crashed = True
    fake_lamp.received.clear()
    with pytest.raises(HomeAssistantError) as err:
        await _turn_off(hass)
    assert not isinstance(err.value, ServiceValidationError)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "communication_error"
    assert err.value.translation_placeholders == {"host": "127.0.0.1"}
    assert str(err.value).startswith("The Cololight at 127.0.0.1 did not answer")
    assert len(fake_lamp.received) == 4  # 1 attempt + 3 retries
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name.startswith("custom_")]
    assert len(warnings) == 1
    assert "could not turn off" in warnings[0].getMessage()
    assert "after 4 attempts" in warnings[0].getMessage()
    # The state is not guessed.
    assert hass.states.get(LIGHT_ID).state == STATE_ON


async def test_partial_failure_publishes_what_was_acknowledged(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The colour was acknowledged, then the lamp stopped answering before the power."""
    await _turn_off(hass)
    fake_lamp.drop_filter = lambda request: request.element == 0x01
    with pytest.raises(HomeAssistantError):
        await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_OFF
    assert coordinator_of(init_integration).data.mode.rgb == (0, 0, 255)


async def test_rejected_command(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_lamp._handle = lambda op, element, data: bytes([0x01, 0x43])  # type: ignore[method-assign]
    with pytest.raises(HomeAssistantError) as err:
        await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    assert err.value.translation_key == "command_rejected"
    assert err.value.translation_placeholders == {"code": "0x43"}
    assert "rejected the request to set the colour (error code 0x43)" in caplog.text


async def test_brightness_when_off_uses_the_last_one(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    await _turn_off(hass)
    light = hass.data[LIGHT_DOMAIN].get_entity(LIGHT_ID)
    assert light is not None
    assert light.brightness == 128


async def test_reported_brightness_out_of_range(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The lamp accepts and reports 0 and 101 % (set by another client)."""
    coordinator = coordinator_of(init_integration)
    fake_lamp.power = bytes.fromhex("cf65")  # 101 %
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_BRIGHTNESS] == 255
    assert coordinator.last_brightness == 100  # never more than the integration sends

    fake_lamp.power = bytes.fromhex("cf00")  # on at 0 %
    await async_poll(hass, init_integration)
    state = hass.states.get(LIGHT_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 1
    # Turning on "on at 0 %" restores the last brightness.
    fake_lamp.received.clear()
    await _turn_on(hass)
    assert _writes(fake_lamp) == [(0x01, "cf64")]
    assert hass.states.get(LIGHT_ID).attributes[ATTR_BRIGHTNESS] == 255


# ---------------------------------------------------------------------- name of a palette effect


async def test_colour_from_home_assistant_forgets_the_palette(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """Tron, then a colour, then the app starts Tricolor (same last frame): not "Tron"."""
    coordinator = coordinator_of(init_integration)
    await _turn_on(hass, **{ATTR_EFFECT: "Tron"})
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    assert coordinator.last_effect is None
    fake_lamp.mode = bytes.fromhex("ff" + TRON[-1])
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == UNKNOWN_PALETTE_EFFECT


async def test_other_mode_seen_by_a_poll_forgets_the_palette(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    await _turn_on(hass, **{ATTR_EFFECT: "Tron"})
    fake_lamp.mode = b"\xff" + SUNRISE  # changed in the app
    await async_poll(hass, init_integration)
    assert coordinator.last_effect is None
    fake_lamp.mode = bytes.fromhex("ff" + TRON[-1])
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == UNKNOWN_PALETTE_EFFECT


async def test_effect_name_kept_across_speed_changes_and_polls(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """80s Club and Unicorns differ by their speed only: the effect sent decides."""
    coordinator = coordinator_of(init_integration)
    await _turn_on(hass, **{ATTR_EFFECT: "Unicorns"})
    await coordinator.async_set_effect_speed(20)  # 049a0c00: "80s Club" or "Unicorns"
    await async_poll(hass, init_integration)
    assert coordinator.last_effect == "Unicorns"
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Unicorns"


# ---------------------------------------------------------------------- state kept across reloads


async def test_last_values_survive_a_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The lamp does not report its brightness while off, nor its colour during an effect."""
    entry = init_integration
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 26, ATTR_RGB_COLOR: (0, 0, 255)})
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    await _turn_off(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 20})  # reloads
    await hass.async_block_till_done()
    coordinator = coordinator_of(entry)
    assert (coordinator.last_brightness, coordinator.last_rgb) == (10, (0, 0, 255))

    fake_lamp.received.clear()
    await _turn_on(hass)
    assert _writes(fake_lamp) == [(0x01, "cf0a")]  # 10 %, not 100 %
    await _turn_on(hass, **{ATTR_EFFECT: EFFECT_OFF})
    assert fake_lamp.mode_code == bytes.fromhex("000000ff")  # blue, not white


async def test_palette_name_survives_a_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    entry = init_integration
    await _turn_on(hass, **{ATTR_EFFECT: "Tricolor"})
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 20})
    await hass.async_block_till_done()
    assert coordinator_of(entry).last_effect == "Tricolor"
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Tricolor"


async def test_last_values_restored_after_a_restart(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    fake_lamp.power = bytes.fromhex("ce1e")
    fake_lamp.mode = bytes.fromhex("ff" + TRON[-1])
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(LIGHT_ID, STATE_OFF),
                {"last_brightness": 10, "last_rgb": [0, 0, 255], "last_effect": "Tron"},
            )
        ],
    )
    entry = await setup_integration()
    coordinator = coordinator_of(entry)
    assert (coordinator.last_brightness, coordinator.last_rgb, coordinator.last_effect) == (
        10,
        (0, 0, 255),
        "Tron",
    )
    assert hass.states.get(LIGHT_ID).attributes.get(ATTR_BRIGHTNESS) is None  # off
    fake_lamp.received.clear()
    await _turn_on(hass)
    assert _writes(fake_lamp) == [(0x01, "cf0a")]
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Tron"


@pytest.mark.parametrize(
    "extra",
    [
        {"last_brightness": 10, "last_rgb": [0, 0, 255], "last_effect": "Tron"},  # lamp knows better
        {"last_brightness": "x", "last_rgb": [0, 0, 255]},
        {"last_rgb": [0, 0, 255]},
        {"last_brightness": 10, "last_rgb": [0, 0]},
        {"last_brightness": 0, "last_rgb": [0, 0, 999], "last_effect": 5},
        {"last_brightness": 10, "last_rgb": [0, 0, 255], "last_effect": "Not an effect"},
    ],
)
async def test_restored_values_are_checked(
    hass: HomeAssistant, setup_integration: SetupIntegration, extra: dict[str, Any]
) -> None:
    """Values read from the lamp win; malformed or stale stored values are ignored."""
    mock_restore_cache_with_extra_data(hass, [(State(LIGHT_ID, STATE_ON), extra)])
    entry = await setup_integration()  # the lamp is on at 50 %, colour ff2222
    coordinator = coordinator_of(entry)
    assert (coordinator.last_brightness, coordinator.last_rgb, coordinator.last_effect) == (
        50,
        INITIAL_RGB,
        None,
    )


async def test_stored_values_ignored_when_out_of_range(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    fake_lamp.power = bytes.fromhex("ce1e")
    fake_lamp.mode = b"\xff" + SUNRISE
    mock_restore_cache_with_extra_data(
        hass,
        [(State(LIGHT_ID, STATE_OFF), {"last_brightness": 0, "last_rgb": [0, 0, 999], "last_effect": "Tron"})],
    )
    entry = await setup_integration()
    coordinator = coordinator_of(entry)
    assert (coordinator.last_brightness, coordinator.last_rgb, coordinator.last_effect) == (
        100,
        (255, 255, 255),
        None,  # Tron is not what the lamp runs
    )
