"""Diagnostics of the Cololight (local) integration."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant

from .coordinator import CololightConfigEntry

TO_REDACT = {CONF_HOST, CONF_MAC}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CololightConfigEntry
) -> dict[str, Any]:
    """Entry configuration, last state, failure counters and client statistics."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "power": None if data is None else {"on": data.power.on, "brightness": data.power.brightness},
            "mode_code": None if data is None else data.mode.code.hex(),
            "effect": None if data is None else coordinator.current_effect_name(),
            "consecutive_failures": coordinator.consecutive_failures,
            "last_effect": coordinator.last_effect,
            "last_update_success": coordinator.last_update_success,
            "update_interval": None
            if coordinator.update_interval is None
            else coordinator.update_interval.total_seconds(),
        },
        "client": dataclasses.asdict(entry.runtime_data.client.stats),
    }
