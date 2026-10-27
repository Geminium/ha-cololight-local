"""Effect speed of a Cololight lamp."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant

from .coordinator import CololightConfigEntry, CololightCoordinator
from .effects import SPEED_MAX, SPEED_MIN, effect_speed
from .entity import CololightEntity

if TYPE_CHECKING:
    # Typing only: this name does not exist in Home Assistant 2025.2 (minimum supported).
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CololightConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the effect speed number."""
    async_add_entities([CololightEffectSpeed(entry.runtime_data.coordinator)])


class CololightEffectSpeed(CololightEntity, NumberEntity):
    """Speed of the running effect: 0 (slowest) to 32 (fastest).

    Unavailable while a static colour or a palette effect (no speed byte) is shown.
    """

    _attr_translation_key = "effect_speed"
    _attr_native_min_value = SPEED_MIN
    _attr_native_max_value = SPEED_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: CololightCoordinator) -> None:
        super().__init__(coordinator, "effect_speed")

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> int | None:
        return effect_speed(self.coordinator.data.mode.code)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_effect_speed(round(value))
