"""The effect speed number (number.py)."""

from __future__ import annotations

import pytest
from homeassistant.components.light import ATTR_EFFECT
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_MODE,
    ATTR_STEP,
    ATTR_VALUE,
    SERVICE_SET_VALUE,
    NumberMode,
)
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.const import DOMAIN
from custom_components.cololight_local.effects import custom_effect_code
from tests.fake_lamp import FakeLamp
from tests.helpers import LIGHT_ID, SPEED_ID, SUNRISE, TRON, async_poll, coordinator_of


async def _set_speed(hass: HomeAssistant, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: SPEED_ID, ATTR_VALUE: value}, blocking=True
    )


async def _start_effect(hass: HomeAssistant, effect: str) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT_ID, ATTR_EFFECT: effect}, blocking=True
    )


async def test_unavailable_without_adjustable_speed(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    # Static colour.
    assert hass.states.get(SPEED_ID).state == STATE_UNAVAILABLE
    # Palette (multi-frame) effect: no speed byte.
    fake_lamp.mode = bytes.fromhex("ff" + TRON[-1])
    await async_poll(hass, init_integration)
    assert hass.states.get(SPEED_ID).state == STATE_UNAVAILABLE


async def test_speed_of_the_running_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.mode = b"\xff" + SUNRISE
    await async_poll(hass, init_integration)
    state = hass.states.get(SPEED_ID)
    assert float(state.state) == 22  # 32 - 0x0a
    assert state.attributes[ATTR_MIN] == 0
    assert state.attributes[ATTR_MAX] == 32
    assert state.attributes[ATTR_STEP] == 1
    assert state.attributes[ATTR_MODE] == NumberMode.SLIDER
    assert state.attributes["friendly_name"] == "Cololight B614 Effect speed"


async def test_set_speed(hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp) -> None:
    await _start_effect(hass, "Sunrise")
    fake_lamp.received.clear()

    await _set_speed(hass, 30)
    assert [(r.op, r.data.hex()) for r in fake_lamp.received] == [(0x04, "ff01c10200")]
    assert float(hass.states.get(SPEED_ID).state) == 30
    # Still the same effect, at another speed.
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "Sunrise"
    assert coordinator_of(init_integration).last_effect == "Sunrise"

    await _set_speed(hass, 0)
    assert fake_lamp.mode_code == bytes.fromhex("01c12000")
    assert float(hass.states.get(SPEED_ID).state) == 0


async def test_set_speed_of_mode_2_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """The "mode 2" family only has three speeds, held in byte B."""
    fake_lamp.mode = b"\xff" + custom_effect_code("strip", "Breath", "Red", 16, 2)
    await async_poll(hass, init_integration)
    assert float(hass.states.get(SPEED_ID).state) == 13  # 32 - 0x13
    await _set_speed(hass, 30)
    assert fake_lamp.mode_code[1] == 0x03
    assert float(hass.states.get(SPEED_ID).state) == 29


async def test_set_speed_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _start_effect(hass, "Sunrise")
    fake_lamp.crashed = True
    with pytest.raises(HomeAssistantError) as err:
        await _set_speed(hass, 10)
    assert err.value.translation_key == "communication_error"
    assert float(hass.states.get(SPEED_ID).state) == 22


@pytest.mark.parametrize("speed", [10, 40])
async def test_set_speed_refused(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp, speed: int
) -> None:
    """No effect with a speed is running (colour) or the speed is out of range."""
    coordinator = coordinator_of(init_integration)
    if speed == 40:
        await _start_effect(hass, "Sunrise")
    fake_lamp.received.clear()
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_set_effect_speed(speed)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "no_adjustable_speed"
    assert fake_lamp.received == []
