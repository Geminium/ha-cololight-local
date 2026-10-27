"""The "save as power-on state" button (button.py): op 07 writes."""

from __future__ import annotations

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.light import ATTR_EFFECT, ATTR_RGB_COLOR
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_SCAN_INTERVAL,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.effects import STRIP_DYNAMIC_EFFECTS
from tests.fake_lamp import FakeLamp
from tests.helpers import LIGHT_ID, SAVE_BUTTON_ID, SUNRISE, TRON, async_poll


def _saves(lamp: FakeLamp) -> list[tuple[int | None, str]]:
    return [(r.element, r.data.hex()) for r in lamp.received if r.op == 0x07]


async def _press(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: SAVE_BUTTON_ID}, blocking=True
    )


async def _light(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(LIGHT_DOMAIN, service, {ATTR_ENTITY_ID: LIGHT_ID, **data}, blocking=True)


async def test_press_saves_colour_and_brightness(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.saved_power = bytes.fromhex("cf64")
    fake_lamp.saved_mode = bytes.fromhex("ff00ffffff")
    assert hass.states.get(SAVE_BUTTON_ID).state == STATE_UNKNOWN
    await _press(hass)
    assert _saves(fake_lamp) == [(0x02, "ff00ff2222"), (0x01, "cf32")]
    assert fake_lamp.saved_mode == bytes.fromhex("ff00ff2222")
    assert fake_lamp.saved_power == bytes.fromhex("cf32")
    assert hass.states.get(SAVE_BUTTON_ID).state != STATE_UNKNOWN  # time of the last press

    # The lamp boots with it after a power cut.
    fake_lamp.power = bytes.fromhex("ce1e")
    fake_lamp.power_cycle()
    assert (fake_lamp.power, fake_lamp.mode) == (bytes.fromhex("cf32"), bytes.fromhex("ff00ff2222"))


async def test_press_when_off_does_not_store_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _light(hass, SERVICE_TURN_OFF)
    await _press(hass)
    assert _saves(fake_lamp) == [(0x02, "ff00ff2222")]


async def test_press_after_single_frame_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Sunrise"})
    await _press(hass)
    assert _saves(fake_lamp) == [(0x02, "ff" + SUNRISE.hex()), (0x01, "cf32")]


async def test_press_after_multi_frame_effect_sends_every_frame(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The lamp only reports the last frame of a palette effect: all frames are stored."""
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Tron"})
    await _press(hass)
    assert _saves(fake_lamp) == [*((0x02, f"ff{frame}") for frame in TRON), (0x01, "cf32")]


async def test_press_after_multi_frame_effect_when_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Tron"})
    await _light(hass, SERVICE_TURN_OFF)
    await _press(hass)
    assert _saves(fake_lamp) == [(0x02, f"ff{frame}") for frame in TRON]


async def test_press_after_effect_changed_by_the_app(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The palette effect sent by Home Assistant is no longer running: store what runs."""
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Tron"})
    fake_lamp.mode = b"\xff" + SUNRISE
    await async_poll(hass, init_integration)
    await _press(hass)
    assert _saves(fake_lamp) == [(0x02, "ff" + SUNRISE.hex()), (0x01, "cf32")]


async def test_press_with_a_palette_started_from_the_app(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """Graffiti's last frame is unique: the effect is identified, and all its frames stored."""
    fake_lamp.mode = bytes.fromhex("ff93ff0091")
    await async_poll(hass, init_integration)
    await _press(hass)
    graffiti = STRIP_DYNAMIC_EFFECTS["Graffiti"].frames
    assert _saves(fake_lamp) == [*((0x02, f"ff{frame.hex()}") for frame in graffiti), (0x01, "cf32")]


async def test_press_with_an_unidentified_palette_stores_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """Never a lone palette frame: the press fails and says why."""
    fake_lamp.mode = bytes.fromhex("ff" + TRON[-1])  # Tron or Tricolor, started from the app
    await async_poll(hass, init_integration)
    with pytest.raises(HomeAssistantError) as err:
        await _press(hass)
    assert err.value.translation_key == "cannot_save_unknown_palette"
    assert _saves(fake_lamp) == []


async def test_press_after_the_app_started_the_twin_palette(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """Tron, a colour, then Tricolor from the app (same last frame): Tron is not stored."""
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Tron"})
    await _light(hass, SERVICE_TURN_ON, **{ATTR_RGB_COLOR: (0, 0, 255)})
    fake_lamp.mode = bytes.fromhex("ff" + TRON[-1])
    await async_poll(hass, init_integration)
    with pytest.raises(HomeAssistantError):
        await _press(hass)
    assert _saves(fake_lamp) == []


async def test_press_after_a_reload_with_a_palette_running(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The name of the palette sent before the reload is kept: all its frames are stored."""
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Tron"})
    hass.config_entries.async_update_entry(init_integration, options={CONF_SCAN_INTERVAL: 20})
    await hass.async_block_till_done()
    await _press(hass)
    assert _saves(fake_lamp) == [*((0x02, f"ff{frame}") for frame in TRON), (0x01, "cf32")]


async def test_press_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.crashed = True
    with pytest.raises(HomeAssistantError) as err:
        await _press(hass)
    assert err.value.translation_key == "communication_error"
    assert fake_lamp.saved_mode == bytes.fromhex("ff00ff2222")


async def test_press_failure_of_multi_frame_save(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _light(hass, SERVICE_TURN_ON, **{ATTR_EFFECT: "Tron"})
    fake_lamp.drop_filter = lambda request: request.op == 0x07 and request.element == 0x01
    with pytest.raises(HomeAssistantError):
        await _press(hass)
    assert len([s for s in _saves(fake_lamp) if s[0] == 0x02]) == len(TRON)
