"""Light entity of a Cololight lamp, plus the integration's entity services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import voluptuous as vol
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    EFFECT_OFF,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import (
    ATTR_CODE,
    ATTR_COLOR,
    ATTR_EFFECT_CODE,
    ATTR_EFFECT_SPEED,
    ATTR_MODE,
    ATTR_SCHEME,
    ATTR_SPEED,
    DEFAULT_CUSTOM_SPEED,
    MAX_CUSTOM_MODE,
    MIN_CUSTOM_MODE,
    SERVICE_SAVE_STATE,
    SERVICE_SET_CUSTOM_EFFECT,
    SERVICE_SET_EFFECT_CODE,
)
from .coordinator import CololightConfigEntry, CololightCoordinator, validation_error
from .effects import CUSTOM_SCHEMES, SPEED_MAX, SPEED_MIN, effect_speed
from .entity import CololightEntity

if TYPE_CHECKING:
    # Typing only: this name does not exist in Home Assistant 2025.2 (minimum supported).
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

PARALLEL_UPDATES = 1

_FRAME_RE = re.compile(r"[0-9a-fA-F]{8}")

SET_CUSTOM_EFFECT_SCHEMA: dict[vol.Marker, Any] = {
    vol.Required(ATTR_SCHEME): vol.In(list(CUSTOM_SCHEMES)),
    vol.Required(ATTR_COLOR): cv.string,
    vol.Optional(ATTR_SPEED, default=DEFAULT_CUSTOM_SPEED): vol.All(
        vol.Coerce(int), vol.Range(min=SPEED_MIN, max=SPEED_MAX)
    ),
    vol.Optional(ATTR_MODE, default=MIN_CUSTOM_MODE): vol.All(
        vol.Coerce(int), vol.Range(min=MIN_CUSTOM_MODE, max=MAX_CUSTOM_MODE)
    ),
}
SET_EFFECT_CODE_SCHEMA: dict[vol.Marker, Any] = {vol.Required(ATTR_CODE): cv.string}


def parse_effect_code(text: str) -> list[bytes]:
    """Parse frames written as 8 hex digits, separated by spaces or commas.

    Raises ServiceValidationError when no frame is given, when a frame is malformed, or
    when it starts with 00 (a static colour).
    """
    parts = [part for part in re.split(r"[\s,]+", text.strip()) if part]
    if not parts:
        raise validation_error("no_effect_frame")
    frames: list[bytes] = []
    for part in parts:
        if not _FRAME_RE.fullmatch(part):
            raise validation_error("invalid_effect_frame", frame=part)
        frame = bytes.fromhex(part)
        if frame[0] == 0x00:
            raise validation_error("effect_frame_is_colour", frame=part)
        frames.append(frame)
    return frames


@dataclass(frozen=True, slots=True)
class CololightExtraStoredData(ExtraStoredData):
    """What the light keeps across restarts and reloads.

    The lamp does not report its brightness while off nor its colour while an effect
    runs, and it reports a palette effect by its last frame only.
    """

    last_brightness: int
    last_rgb: tuple[int, int, int]
    last_effect: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_brightness": self.last_brightness,
            "last_rgb": list(self.last_rgb),
            "last_effect": self.last_effect,
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> Self | None:
        """Read what was stored; None if it is malformed."""
        try:
            brightness = int(restored["last_brightness"])
            red, green, blue = (int(c) for c in restored["last_rgb"])
            effect = restored.get("last_effect")
        except (KeyError, TypeError, ValueError):
            return None
        return cls(brightness, (red, green, blue), effect if isinstance(effect, str) else None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CololightConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light and register the entity services."""
    async_add_entities([CololightLight(entry.runtime_data.coordinator)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_SAVE_STATE, None, "async_service_save_state")
    platform.async_register_entity_service(
        SERVICE_SET_CUSTOM_EFFECT, SET_CUSTOM_EFFECT_SCHEMA, "async_service_set_custom_effect"
    )
    platform.async_register_entity_service(
        SERVICE_SET_EFFECT_CODE, SET_EFFECT_CODE_SCHEMA, "async_service_set_effect_code"
    )


class CololightLight(CololightEntity, LightEntity, RestoreEntity):
    """The lamp itself: on/off, brightness, static colour and effects."""

    _attr_name = None
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, coordinator: CololightCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_supported_color_modes = {ColorMode.RGB}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is not None and (
            restored := CololightExtraStoredData.from_dict(extra.as_dict())
        ) is not None:
            self.coordinator.async_restore(restored.last_brightness, restored.last_rgb, restored.last_effect)

    @property
    def extra_restore_state_data(self) -> CololightExtraStoredData:
        coordinator = self.coordinator
        return CololightExtraStoredData(coordinator.last_brightness, coordinator.last_rgb, coordinator.last_effect)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.power.on

    @property
    def brightness(self) -> int | None:
        power = self.coordinator.data.power
        pct = power.brightness
        if not power.on or pct is None:
            pct = self.coordinator.last_brightness  # the lamp does not report it when off
        # The lamp accepts and reports 0 and 101 %: keep Home Assistant's 1-255 range.
        return max(1, min(255, round(pct * 255 / 100)))

    @property
    def color_mode(self) -> ColorMode:
        # While an effect runs only the brightness can be adjusted (allowed by Home Assistant).
        return ColorMode.RGB if self.coordinator.data.mode.is_color else ColorMode.BRIGHTNESS

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self.coordinator.data.mode.rgb

    @property
    def effect(self) -> str | None:
        if self.coordinator.data.mode.is_color:
            return EFFECT_OFF
        return self.coordinator.current_effect_name()

    @property
    def effect_list(self) -> list[str]:
        return [EFFECT_OFF, *self.coordinator.effects]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        mode = self.coordinator.data.mode
        if mode.is_color:
            return None
        attributes: dict[str, Any] = {ATTR_EFFECT_CODE: mode.code.hex()}
        if (speed := effect_speed(mode.code)) is not None:
            attributes[ATTR_EFFECT_SPEED] = speed
        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)
        await self.coordinator.async_turn_on(
            brightness_pct=None if brightness is None else max(1, round(brightness * 100 / 255)),
            rgb=kwargs.get(ATTR_RGB_COLOR),
            effect=kwargs.get(ATTR_EFFECT),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_turn_off()

    # ------------------------------------------------------------------ services

    async def async_service_save_state(self) -> None:
        """Service save_state."""
        await self.coordinator.async_save_state()

    async def async_service_set_custom_effect(self, scheme: str, color: str, speed: int, mode: int) -> None:
        """Service set_custom_effect."""
        await self.coordinator.async_set_custom_effect(scheme, color, speed, mode)

    async def async_service_set_effect_code(self, code: str) -> None:
        """Service set_effect_code."""
        await self.coordinator.async_set_effect_code(parse_effect_code(code))
