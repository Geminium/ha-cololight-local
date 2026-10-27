"""Scenes and snapshots (scene.create / scene.turn_on / scene.apply) restoring the lamp.

Home Assistant restores a light by calling light.turn_on with its brightness and effect,
plus the colour of its colour mode (homeassistant/components/light/reproduce_state.py):
a static colour therefore comes back as effect "off" together with rgb_color. Scenes of
several domains are applied in parallel: the light and the speed number at the same time.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGB_COLOR
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.const import UNKNOWN_PALETTE_EFFECT
from tests.fake_lamp import FakeLamp
from tests.helpers import LIGHT_ID, SPEED_ID, SUNRISE, async_poll, coordinator_of

SNAPSHOT_ID = "scene.before"
SNOW = bytes.fromhex("058908c0")  # single frame, speed byte 0x08
RED_ALERT = bytes.fromhex("06a90100")


@pytest.fixture(autouse=True)
async def scene_component(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "scene", {})


def _writes(lamp: FakeLamp) -> list[tuple[int | None, str]]:
    return [(r.element, r.data.hex()) for r in lamp.received if r.op == 0x04]


async def _turn_on(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT_ID, **data}, blocking=True
    )


async def _snapshot(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "scene", "create", {"scene_id": "before", "snapshot_entities": [LIGHT_ID]}, blocking=True
    )


async def _restore(hass: HomeAssistant) -> None:
    await hass.services.async_call("scene", "turn_on", {ATTR_ENTITY_ID: SNAPSHOT_ID}, blocking=True)


async def _apply(hass: HomeAssistant, entities: dict[str, Any]) -> None:
    await hass.services.async_call("scene", "apply", {"entities": entities}, blocking=True)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------- static colour


async def test_snapshot_restores_a_static_colour(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 255, 0)})
    await _snapshot(hass)
    await _turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255)})
    fake_lamp.received.clear()

    await _restore(hass)
    # Effect "off" + the snapshot's colour, then its brightness (50 %).
    assert _writes(fake_lamp) == [(0x02, "ff0000ff00"), (0x01, "cf32")]
    assert fake_lamp.mode_code == bytes.fromhex("0000ff00")
    assert hass.states.get(LIGHT_ID).attributes[ATTR_RGB_COLOR] == (0, 255, 0)


async def test_scene_of_a_static_colour_stops_an_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """A scene saved in the editor stores effect "off" with the colour."""
    await _turn_on(hass, **{ATTR_EFFECT: "Sunrise"})
    fake_lamp.received.clear()
    await _apply(
        hass,
        {
            LIGHT_ID: {
                "state": "on",
                "color_mode": "rgb",
                "rgb_color": [0, 255, 0],
                "effect": "off",
                "brightness": 204,
            }
        },
    )
    assert _writes(fake_lamp) == [(0x02, "ff0000ff00"), (0x01, "cf50")]
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_RGB_COLOR] == (0, 255, 0)
    assert state.attributes[ATTR_EFFECT] == "off"


# ---------------------------------------------------------------------- unidentified palette


async def test_snapshot_of_an_unidentified_palette_restores_the_brightness(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The palette still runs: only the brightness changes, nothing fails."""
    fake_lamp.mode = bytes.fromhex("ff9300ff64")  # Tron or Tricolor, started from the app
    await async_poll(hass, init_integration)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == UNKNOWN_PALETTE_EFFECT
    await _snapshot(hass)
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    fake_lamp.received.clear()

    await _restore(hass)
    assert _writes(fake_lamp) == [(0x01, "cf32")]
    assert fake_lamp.mode == bytes.fromhex("ff9300ff64")
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_EFFECT] == UNKNOWN_PALETTE_EFFECT
    assert state.attributes[ATTR_BRIGHTNESS] == 128


async def test_snapshot_of_an_unidentified_palette_after_an_alert(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The doorbell example of the user guide: the restore must not fail.

    The palette's frames are unknown, so it cannot come back: the alert keeps running,
    but the brightness and power of the snapshot are restored, and a warning says why.
    """
    fake_lamp.mode = bytes.fromhex("ff9300ff64")
    await async_poll(hass, init_integration)
    await _snapshot(hass)
    await _turn_on(hass, **{ATTR_EFFECT: "Red alert", ATTR_BRIGHTNESS: 255})
    fake_lamp.received.clear()

    await _restore(hass)
    assert _writes(fake_lamp) == [(0x01, "cf32")]
    assert fake_lamp.mode_code == RED_ALERT
    assert "an unidentified palette effect cannot be started again" in caplog.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name.startswith("custom_")]
    assert len(warnings) == 1


async def test_turn_on_unidentified_palette_while_off_turns_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.mode = bytes.fromhex("ff9300ff64")
    fake_lamp.power = bytes.fromhex("ce1e")
    await async_poll(hass, init_integration)
    fake_lamp.received.clear()
    await _turn_on(hass, **{ATTR_EFFECT: UNKNOWN_PALETTE_EFFECT})
    assert _writes(fake_lamp) == [(0x01, "cf32")]
    assert hass.states.get(LIGHT_ID).state == "on"


# ---------------------------------------------------------------------- light and speed together


async def _start_snow(hass: HomeAssistant, entry: MockConfigEntry, lamp: FakeLamp) -> None:
    lamp.mode = b"\xff" + SNOW
    await async_poll(hass, entry)
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Snow"
    lamp.delay = 0.02  # the two calls overlap
    lamp.received.clear()


def _assert_state_matches_the_lamp(hass: HomeAssistant, lamp: FakeLamp) -> None:
    state = hass.states.get(LIGHT_ID)
    assert state.attributes["effect_code"] == lamp.mode_code.hex()
    speed = 32 - lamp.mode_code[2]
    assert float(hass.states.get(SPEED_ID).state) == speed


async def test_scene_with_the_light_before_the_speed(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The speed applies to the effect of the scene, and the state matches the lamp."""
    await _start_snow(hass, init_integration, fake_lamp)
    await _apply(hass, {LIGHT_ID: {"state": "on", "effect": "Sunrise"}, SPEED_ID: {"state": "10"}})
    assert _writes(fake_lamp) == [(0x02, "ff" + SUNRISE.hex()), (0x02, "ff01c11600")]
    assert fake_lamp.mode_code == bytes.fromhex("01c11600")
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Sunrise"
    _assert_state_matches_the_lamp(hass, fake_lamp)
    assert coordinator_of(init_integration).last_effect == "Sunrise"


async def test_scene_with_the_speed_before_the_light(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The speed reaches the running effect first: the scene's effect then starts at its
    own speed (documented), but the state shown still matches the lamp."""
    await _start_snow(hass, init_integration, fake_lamp)
    await _apply(hass, {SPEED_ID: {"state": "10"}, LIGHT_ID: {"state": "on", "effect": "Sunrise"}})
    assert fake_lamp.mode_code == SUNRISE
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Sunrise"
    _assert_state_matches_the_lamp(hass, fake_lamp)
