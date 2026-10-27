"""Constants of the Cololight (local) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from .effects import Model
from .protocol import PORT

DOMAIN: Final = "cololight_local"
MANUFACTURER: Final = "LifeSmart"
MODEL_NAMES: Final[dict[Model, str]] = {
    Model.STRIP: "Cololight Strip",
    Model.HEXAGON: "Cololight Hexagon",
}

# ---------------------------------------------------------------- entry data
# CONF_HOST, CONF_MAC, CONF_MODEL, CONF_PORT come from homeassistant.const.
DEFAULT_PORT: Final = PORT  # not asked in the UI; tests point it at the emulator
DEFAULT_MODEL: Final = Model.STRIP

# ---------------------------------------------------------------- options
CONF_SAVE_AS_DEFAULT: Final = "save_as_default"
CONF_SAVE_DELAY: Final = "save_delay"
CONF_HIDDEN_EFFECTS: Final = "hidden_effects"
CONF_CUSTOM_EFFECTS: Final = "custom_effects"
# CONF_SCAN_INTERVAL comes from homeassistant.const.

DEFAULT_SCAN_INTERVAL: Final = 10  # seconds
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 300
DEFAULT_SAVE_AS_DEFAULT: Final = False
DEFAULT_SAVE_DELAY: Final = 30  # seconds the state must stay unchanged before op 07
MIN_SAVE_DELAY: Final = 10
MAX_SAVE_DELAY: Final = 600

# Keys of one custom effect stored in options[CONF_CUSTOM_EFFECTS][name]
CUSTOM_SCHEME: Final = "scheme"
CUSTOM_COLOR: Final = "color"
CUSTOM_SPEED: Final = "speed"
CUSTOM_MODE: Final = "mode"
CUSTOM_CODE: Final = "code"  # 8 hex digits, precomputed with custom_effect_code()

# ---------------------------------------------------------------- polling / discovery
MAX_CONSECUTIVE_FAILURES: Final = 3  # failed polls before the entities become unavailable
REDISCOVERY_AFTER_FAILURES: Final = 2  # failed polls before looking for the lamp by MAC
# Once the entities are unavailable, keep looking only every N failed polls (about once a
# minute with the default interval) instead of broadcasting at every poll.
REDISCOVERY_EVERY_FAILURES: Final = 4
DISCOVERY_TIMEOUT: Final = 2.0  # seconds of listening after the broadcast
DISCOVERY_INTERVAL: Final = timedelta(minutes=15)

# ---------------------------------------------------------------- state defaults
DEFAULT_BRIGHTNESS_PCT: Final = 100
DEFAULT_RGB: Final = (255, 255, 255)
UNKNOWN_PALETTE_EFFECT: Final = "Unknown palette effect"
UNKNOWN_EFFECT_PREFIX: Final = "Effect "  # followed by the 8 hex digits of the frame

# ---------------------------------------------------------------- services
SERVICE_SAVE_STATE: Final = "save_state"
SERVICE_SET_CUSTOM_EFFECT: Final = "set_custom_effect"
SERVICE_SET_EFFECT_CODE: Final = "set_effect_code"

ATTR_SCHEME: Final = "scheme"
ATTR_COLOR: Final = "color"
ATTR_SPEED: Final = "speed"
ATTR_MODE: Final = "mode"
ATTR_CODE: Final = "code"
ATTR_EFFECT_CODE: Final = "effect_code"
ATTR_EFFECT_SPEED: Final = "effect_speed"

DEFAULT_CUSTOM_SPEED: Final = 16
MIN_CUSTOM_MODE: Final = 1
MAX_CUSTOM_MODE: Final = 27  # hexagon; the strip has 13 (checked against the model)
