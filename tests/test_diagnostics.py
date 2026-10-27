"""Diagnostics (diagnostics.py): content and redaction."""

from __future__ import annotations

from homeassistant.components.light import ATTR_EFFECT
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.cololight_local.const import CONF_SAVE_AS_DEFAULT
from custom_components.cololight_local.diagnostics import async_get_config_entry_diagnostics
from tests.fake_lamp import FakeLamp
from tests.helpers import LIGHT_ID, MAC, SetupIntegration, async_poll

REDACTED = "**REDACTED**"


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: SetupIntegration,
    fake_lamp_port: int,
) -> None:
    entry = await setup_integration(options={CONF_SAVE_AS_DEFAULT: True})
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT_ID, ATTR_EFFECT: "Sunrise"}, blocking=True
    )
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"] == {
        "data": {"host": REDACTED, "mac": REDACTED, "port": fake_lamp_port, "model": "strip"},
        "options": {CONF_SAVE_AS_DEFAULT: True},
    }
    assert diagnostics["coordinator"] == {
        "power": {"on": True, "brightness": 50},
        "mode_code": "01c10a00",
        "effect": "Sunrise",
        "consecutive_failures": 0,
        "last_effect": "Sunrise",
        "last_update_success": True,
        "update_interval": 10.0,
    }
    client = diagnostics["client"]
    assert client["requests"] == 3  # first poll (2 reads) + the effect
    assert client["datagrams_sent"] == 3
    assert client["timeouts"] == 0
    assert len(client["rtts"]) == 3
    assert "127.0.0.1" not in str(diagnostics)
    assert MAC not in str(diagnostics).lower()


async def test_diagnostics_after_failures(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_lamp: FakeLamp
) -> None:
    fake_lamp.crashed = True
    for _ in range(3):
        await async_poll(hass, init_integration)
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    assert diagnostics["coordinator"]["consecutive_failures"] == 3
    assert diagnostics["coordinator"]["last_update_success"] is False
    assert diagnostics["coordinator"]["mode_code"] == "00ff2222"  # last known state
    assert diagnostics["coordinator"]["effect"] is None
    assert diagnostics["client"]["timeouts"] == 3
