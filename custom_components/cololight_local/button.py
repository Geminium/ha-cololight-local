"""Button storing the current state of a Cololight lamp as its power-on state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .coordinator import CololightConfigEntry, CololightCoordinator
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
    """Set up the save button."""
    async_add_entities([CololightSaveStateButton(entry.runtime_data.coordinator)])


class CololightSaveStateButton(CololightEntity, ButtonEntity):
    """Write the current colour/effect and brightness to the lamp's EEPROM (op 07)."""

    _attr_translation_key = "save_state"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: CololightCoordinator) -> None:
        super().__init__(coordinator, "save_state")

    async def async_press(self) -> None:
        await self.coordinator.async_save_state()
