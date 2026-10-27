"""Entity services of the integration: save_state, set_custom_effect, set_effect_code."""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous as vol
from homeassistant.components.light import ATTR_EFFECT
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.const import (
    DOMAIN,
    SERVICE_SAVE_STATE,
    SERVICE_SET_CUSTOM_EFFECT,
    SERVICE_SET_EFFECT_CODE,
)
from custom_components.cololight_local.effects import custom_effect_code
from tests.fake_lamp import FakeLamp
from tests.helpers import LIGHT_ID, SetupIntegration, async_poll, coordinator_of


def _writes(lamp: FakeLamp, op: int = 0x04) -> list[tuple[int | None, str]]:
    return [(r.element, r.data.hex()) for r in lamp.received if r.op == op]


async def _call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(DOMAIN, service, {ATTR_ENTITY_ID: LIGHT_ID, **data}, blocking=True)


async def test_services_are_registered(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    for service in (SERVICE_SAVE_STATE, SERVICE_SET_CUSTOM_EFFECT, SERVICE_SET_EFFECT_CODE):
        assert hass.services.has_service(DOMAIN, service)


# ---------------------------------------------------------------------- save_state


async def test_save_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _call(hass, SERVICE_SAVE_STATE)
    assert _writes(fake_lamp, 0x07) == [(0x02, "ff00ff2222"), (0x01, "cf32")]


async def test_save_state_with_an_unidentified_palette(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.mode = bytes.fromhex("ff9300ff64")
    await async_poll(hass, init_integration)
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, SERVICE_SAVE_STATE)
    assert err.value.translation_key == "cannot_save_unknown_palette"
    assert _writes(fake_lamp, 0x07) == []


async def test_save_state_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.crashed = True
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, SERVICE_SAVE_STATE)
    assert err.value.translation_key == "communication_error"


# ---------------------------------------------------------------------- set_custom_effect


async def test_set_custom_effect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT_ID, ATTR_EFFECT: "Sunrise"}, blocking=True
    )
    fake_lamp.received.clear()
    await _call(hass, SERVICE_SET_CUSTOM_EFFECT, scheme="Mood", color="Red", speed=20, mode=3)
    code = custom_effect_code("strip", "Mood", "Red", 20, 3)
    assert _writes(fake_lamp) == [(0x02, "ff" + code.hex())]
    assert coordinator.last_effect is None
    state = hass.states.get(LIGHT_ID)
    assert state.attributes[ATTR_EFFECT] == f"Effect {code.hex()}"
    assert state.attributes["effect_code"] == code.hex()
    assert state.attributes["effect_speed"] == 20


async def test_set_custom_effect_defaults(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await _call(hass, SERVICE_SET_CUSTOM_EFFECT, scheme="Scene", color="Birthday")
    assert fake_lamp.mode_code == custom_effect_code("strip", "Scene", "Birthday", 16, 1)


async def test_set_custom_effect_keeps_the_lamp_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    await hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT_ID}, blocking=True)
    fake_lamp.received.clear()
    await _call(hass, SERVICE_SET_CUSTOM_EFFECT, scheme="Mood", color="Red")
    assert [element for element, _ in _writes(fake_lamp)] == [0x02]
    assert hass.states.get(LIGHT_ID).state == STATE_OFF


async def test_set_custom_effect_hexagon_modes(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    await setup_integration(**{CONF_MODEL: "hexagon"})
    await _call(hass, SERVICE_SET_CUSTOM_EFFECT, scheme="Mood", color="Red", mode=20)
    assert fake_lamp.mode_code == custom_effect_code("hexagon", "Mood", "Red", 16, 20)


MOOD_COLORS = "Red · Orange · Yellow · Green · Grass · Azure · Blue · Pink · Gold · Color · True Color"


@pytest.mark.parametrize(
    ("data", "key", "placeholders"),
    [
        (  # not a colour of this scheme
            {"scheme": "Mood", "color": "Purple"},
            "unknown_custom_color",
            {"color": "Purple", "scheme": "Mood", "colors": MOOD_COLORS},
        ),
        (  # colours are case-sensitive
            {"scheme": "Mood", "color": "red"},
            "unknown_custom_color",
            {"color": "red", "scheme": "Mood", "colors": MOOD_COLORS},
        ),
        (  # gap in the table
            {"scheme": "Selected", "color": ""},
            "unknown_custom_color",
            {"color": "", "scheme": "Selected", "colors": "Savasana · Sunrise · Unicorns"},
        ),
        (  # the strip has 13 modes
            {"scheme": "Mood", "color": "Red", "mode": 14},
            "custom_mode_out_of_range",
            {"max": "13"},
        ),
    ],
)
async def test_set_custom_effect_invalid(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    data: dict[str, Any],
    key: str,
    placeholders: dict[str, str],
) -> None:
    """The error tells what is wrong, with the valid values (shown in the user's language)."""
    fake_lamp.received.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_SET_CUSTOM_EFFECT, **data)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == key
    assert err.value.translation_placeholders == placeholders
    assert fake_lamp.received == []


async def test_set_custom_effect_other_invalid_values(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    """Values the action's schema already refuses still give an error from the coordinator."""
    coordinator = coordinator_of(init_integration)
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_set_custom_effect("Mood", "Red", 40, 1)
    assert err.value.translation_key == "invalid_custom_effect"
    assert err.value.translation_placeholders == {"error": "speed must be 0-32"}
    fake_lamp.received.clear()
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_set_effect_code([bytes.fromhex("01c10a")])
    assert err.value.translation_key == "invalid_effect_code"
    assert fake_lamp.received == []


@pytest.mark.parametrize(
    "data",
    [
        {"scheme": "Disco", "color": "Red"},
        {"color": "Red"},
        {"scheme": "Mood"},
        {"scheme": "Mood", "color": "Red", "speed": 33},
        {"scheme": "Mood", "color": "Red", "mode": 0},
        {"scheme": "Mood", "color": "Red", "mode": 28},
    ],
)
async def test_set_custom_effect_schema(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp, data: dict[str, Any]
) -> None:
    fake_lamp.received.clear()
    with pytest.raises(vol.Invalid):
        await _call(hass, SERVICE_SET_CUSTOM_EFFECT, **data)
    assert fake_lamp.received == []


async def test_set_custom_effect_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.crashed = True
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, SERVICE_SET_CUSTOM_EFFECT, scheme="Mood", color="Red")
    assert err.value.translation_key == "communication_error"


# ---------------------------------------------------------------------- set_effect_code


async def test_set_effect_code(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    coordinator = coordinator_of(init_integration)
    coordinator.last_effect = "Sunrise"
    fake_lamp.received.clear()
    await _call(hass, SERVICE_SET_EFFECT_CODE, code="049a0000")
    assert _writes(fake_lamp) == [(0x02, "ff049a0000")]
    assert coordinator.last_effect is None
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT] == "80s Club"


async def test_set_effect_code_several_frames(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.received.clear()
    await _call(hass, SERVICE_SET_EFFECT_CODE, code=" 93FEFEFE, 9304058b  93f0b003,93ff0000 ")
    assert _writes(fake_lamp) == [
        (0x02, "ff93fefefe"),
        (0x02, "ff9304058b"),
        (0x02, "ff93f0b003"),
        (0x02, "ff93ff0000"),
    ]
    assert fake_lamp.mode_code == bytes.fromhex("93ff0000")


@pytest.mark.parametrize(
    ("code", "key", "placeholders"),
    [
        ("", "no_effect_frame", None),
        (" , ", "no_effect_frame", None),
        ("049a00", "invalid_effect_frame", {"frame": "049a00"}),
        ("049a00000", "invalid_effect_frame", {"frame": "049a00000"}),
        ("xyz12345", "invalid_effect_frame", {"frame": "xyz12345"}),
        ("00ff0000", "effect_frame_is_colour", {"frame": "00ff0000"}),
        ("049a0000 00000000", "effect_frame_is_colour", {"frame": "00000000"}),
    ],
)
async def test_set_effect_code_invalid(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp: FakeLamp,
    code: str,
    key: str,
    placeholders: dict[str, str] | None,
) -> None:
    fake_lamp.received.clear()
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_SET_EFFECT_CODE, code=code)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == key
    assert err.value.translation_placeholders == placeholders
    assert fake_lamp.received == []


async def test_set_effect_code_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.crashed = True
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, SERVICE_SET_EFFECT_CODE, code="049a0000")
    assert err.value.translation_key == "communication_error"


async def test_services_work_after_a_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    hass.config_entries.async_update_entry(init_integration, options={CONF_SCAN_INTERVAL: 20})
    await hass.async_block_till_done()
    fake_lamp.received.clear()
    await _call(hass, SERVICE_SET_EFFECT_CODE, code="049a0000")
    assert _writes(fake_lamp) == [(0x02, "ff049a0000")]
