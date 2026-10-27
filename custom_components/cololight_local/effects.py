"""Cololight effect tables and helpers.

Pure Python, no Home Assistant import. The tables come from pycololight
(MIT, (c) 2021 BazaJayGee66); the speed semantics were verified on a real strip:
in a frame ``A B C D`` the speed byte C ranges from 0x00 (fastest) to 0x20 (slowest),
except for the "mode 2" family (A == 0x02) whose speed sits in byte B.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .protocol import MULTI_FRAME_PREFIX

SPEED_MIN = 0  # slowest
SPEED_MAX = 32  # fastest
_SPEED_BYTE_SLOWEST = 0x20
_MODE2_SPEED_BYTES = (0x13, 0x0B, 0x03)  # the only three speeds of the mode 2 family


class Model(StrEnum):
    """Supported devices."""

    STRIP = "strip"
    HEXAGON = "hexagon"


@dataclass(frozen=True, slots=True)
class Effect:
    """A named effect: one frame, or several sent in order (palette upload)."""

    name: str
    frames: tuple[bytes, ...]

    @property
    def is_multi_frame(self) -> bool:
        return len(self.frames) > 1


def _fx(name: str, *frames: str) -> Effect:
    return Effect(name, tuple(bytes.fromhex(f) for f in frames))


DEFAULT_EFFECTS: dict[str, Effect] = {
    e.name: e
    for e in (
        _fx("80s Club", "049a0000"),
        _fx("Cherry Blossom", "04940800"),
        _fx("Cocktail Parade", "05bd0690"),
        _fx("Instagrammer", "03bc0190"),
        _fx("Pensieve", "04c40600"),
        _fx("Savasana", "04970400"),
        _fx("Sunrise", "01c10a00"),
        _fx("The Circus", "04810130"),
        _fx("Unicorns", "049a0e00"),
        _fx("Christmas", "068b0900"),
        _fx("Rainbow Flow", "03810690"),
        _fx("Music Mode", "07bd0990"),
    )
}

STRIP_DYNAMIC_EFFECTS: dict[str, Effect] = {
    e.name: e
    for e in (
        _fx("Graffiti", "93fefefe", "9305088c", "93f0a003", "93fa00ff", "93ffaf00", "9300c3ff", "93ff0091"),
        _fx("Color train", "069a0d00"),
        _fx("Snow", "058908c0"),
        _fx("White link", "06a20e00"),
        _fx("Tron", "93fefefe", "9304058b", "93f0b003", "93ff0000", "930087ff", "9300ff64"),
        _fx("Urban beauty", "93fefefe", "930304b4", "93f04000", "93ff00c3", "9300ffc3"),
        _fx("Cyberpunk", "93fefefe", "9303052c", "93f0a801", "93ff00d2", "9300c3ff"),
        _fx("Tropic affair", "93fefefe", "93050713", "93f08003", "9319ff00", "93fff000", "93ff9b00", "93ff0000"),
        _fx("Go by", "93fefefe", "93030448", "93f06000", "93ff0000", "9300faff"),
        _fx("Break dance", "93fefefe", "9303048c", "93f0b003", "936400ff", "93ff8700"),
        _fx("Children park", "93fefefe", "93050896", "93f0a602", "93ff00b4", "93b900ff", "9300aaff", "93ffeb00"),
        _fx("Thunder", "93fefefe", "9303064a", "93f0a582", "930037ff", "93ffffff"),
        _fx("Red meteor", "93fefefe", "93020237", "93f04800", "93ff0000"),
        _fx("Green meteor", "93fefefe", "93020246", "93f04800", "9300ff0f"),
        _fx("Blue meteor", "93fefefe", "9302027d", "93f04800", "930046ff"),
        _fx("Forest", "93fefefe", "9303045a", "93f01580", "9332ff00", "93ffa500"),
        _fx("Cherry lake", "93fefefe", "9303050d", "93f01680", "93ff738e", "9304ff84"),
        _fx("World cup", "93fefefe", "9304057f", "93f02200", "930037ff", "93ffe100", "930089ce"),
        _fx("Sunset", "93fefefe", "930404dd", "93f00500", "936400ff", "93ff0000", "93ff8700"),
        _fx("Tide", "93fefefe", "93040775", "93f09a82", "930050ff", "933d98ff", "9395b2ff"),
        _fx("Lilac", "93fefefe", "930407f8", "93f00800", "93fdb7ff", "93cb34ff", "93d977ff"),
        _fx("Witch hut", "93fefefe", "93030381", "93f02500", "936900ff", "9300ff05"),
        _fx("Cranberry", "93fefefe", "93030388", "93f01580", "93ff0000", "9300ff05"),
        _fx("Tricolor", "93fefefe", "93040563", "93f08803", "93ff0000", "930087ff", "9300ff64"),
        _fx("Color star", "05810cc0"),
        _fx("Lover", "05ba0150"),
        _fx("Treasure", "06bb0330"),
        _fx("Heavy traffic", "06a01d00"),
        _fx("Weird story", "06900e00"),
        _fx("Green field", "06950160"),
        _fx("Seaman", "06960100"),
        _fx("Purple link", "069e0e00"),
        _fx("Blue link", "069d0e00"),
        _fx("Orange star", "05870f70"),
        _fx("Green star", "05820f70"),
        _fx("Red star", "05860f70"),
        _fx("Dusk", "06920f00"),
        _fx("Innocence", "93fefefe", "93060c28", "93f01300", "935ab4ff", "93ff7878", "93a9ffac", "93d696ff", "93fff477"),
        _fx("Red alert", "06a90100"),
        _fx("Blue alert", "06a70100"),
    )
}

# Custom effects: colour scheme -> (base palette byte, colours by index). Empty names are gaps.
CUSTOM_SCHEMES: dict[str, tuple[int, tuple[str, ...]]] = {
    "Breath": (128, ("Red, Green, Blue", "Rainbow", "Green", "Azure", "Blue", "Purple", "Red",
                     "Orange", "Yellow", "White", "Green, Blue")),
    "Shadow": (138, ("Red, Yellow", "Red, Green", "Red, Purple", "Red, Blue", "Green, Yellow",
                     "Green, Azure", "Green, Blue", "Blue, Azure", "Blue, Purple", "Yellow, White",
                     "Red, White", "Green, White", "Azure, White", "Blue, White", "Purple, White")),
    "Flash": (153, ("Red, Green, Blue", "Rainbow", "Green", "Azure", "Blue", "Purple", "Red",
                    "Orange", "Yellow", "White")),
    "Flicker": (163, ("Red, Green, Blue", "Rainbow", "Green", "Azure", "Blue", "Purple", "Red",
                      "Orange", "Yellow", "White")),
    "Scene": (173, ("Birthday", "Girlfriends", "Friends", "Workmates", "Family", "Lover")),
    "Mood": (179, ("Red", "Orange", "Yellow", "Green", "Grass", "Azure", "Blue", "Pink", "Gold",
                   "Color", "True Color")),
    "Selected": (191, ("Savasana", "", "Sunrise", "", "Unicorns")),
}

# Custom effect modes (pictures in pycololight's MODES.md): mode number -> (byte A, byte D).
HEXAGON_MODES: tuple[tuple[int, int], ...] = (
    (0x01, 0x00), (0x02, 0x00), (0x05, 0x10), (0x05, 0x30), (0x05, 0x40), (0x05, 0x50),
    (0x05, 0x70), (0x05, 0x80), (0x05, 0x90), (0x05, 0xA0), (0x05, 0xB0), (0x05, 0xC0),
    (0x05, 0x00), (0x05, 0x20), (0x05, 0x30), (0x06, 0x00), (0x06, 0x10), (0x06, 0x20),
    (0x06, 0x30), (0x06, 0x50), (0x05, 0xF0), (0x05, 0x10), (0x05, 0x40), (0x05, 0x50),
    (0x06, 0x60), (0x06, 0x70), (0x06, 0x80),
)
STRIP_MODES: tuple[tuple[int, int], ...] = (
    (0x01, 0x00), (0x02, 0x00), (0x05, 0x10), (0x05, 0x30), (0x05, 0x40), (0x05, 0x50),
    (0x05, 0x70), (0x05, 0xC0), (0x05, 0xF0), (0x05, 0x10), (0x06, 0x00), (0x06, 0x30),
    (0x06, 0x60),
)
# Modes whose palette byte is 128 lower (it distinguishes modes sharing the same A, D).
_LOWER_MODES: dict[Model, frozenset[int]] = {
    Model.HEXAGON: frozenset({13, 14, 15, 22, 23, 24}),
    Model.STRIP: frozenset({10}),
}


def effects_for_model(model: Model | str) -> dict[str, Effect]:
    """Built-in effects of a model, in display order."""
    if Model(model) is Model.STRIP:
        return {**DEFAULT_EFFECTS, **STRIP_DYNAMIC_EFFECTS}
    return dict(DEFAULT_EFFECTS)


def modes_for_model(model: Model | str) -> tuple[tuple[int, int], ...]:
    return STRIP_MODES if Model(model) is Model.STRIP else HEXAGON_MODES


def scheme_colors(scheme: str) -> list[str]:
    """Selectable colours of a custom effect scheme."""
    return [c for c in CUSTOM_SCHEMES[scheme][1] if c]


def _speed_index(code: bytes) -> int | None:
    """Index of the speed byte in a single effect frame, None if it has none."""
    if len(code) != 4 or code[0] in (0x00, MULTI_FRAME_PREFIX):
        return None
    return 1 if code[0] == 0x02 else 2


def effect_speed(code: bytes) -> int | None:
    """Speed of a single-frame effect, 0 (slowest) to 32 (fastest); None if not applicable."""
    idx = _speed_index(code)
    if idx is None:
        return None
    return SPEED_MAX - min(code[idx], _SPEED_BYTE_SLOWEST)


def with_speed(code: bytes, speed: int) -> bytes:
    """Return ``code`` with its speed replaced (0 slowest .. 32 fastest)."""
    idx = _speed_index(code)
    if idx is None:
        raise ValueError(f"effect {code.hex()} has no adjustable speed")
    if not SPEED_MIN <= speed <= SPEED_MAX:
        raise ValueError(f"speed must be {SPEED_MIN}-{SPEED_MAX}")
    target = SPEED_MAX - int(speed)
    if code[0] == 0x02:
        target = min(_MODE2_SPEED_BYTES, key=lambda b: abs(b - target))
    out = bytearray(code)
    out[idx] = target
    return bytes(out)


def custom_effect_code(model: Model | str, scheme: str, color: str, speed: int, mode: int) -> bytes:
    """Build the frame of a custom effect (scheme/colour/speed/mode, as in the official app)."""
    if scheme not in CUSTOM_SCHEMES:
        raise ValueError(f"unknown scheme {scheme!r}")
    base, colors = CUSTOM_SCHEMES[scheme]
    if not color or color not in colors:
        raise ValueError(f"unknown colour {color!r} for scheme {scheme!r}")
    modes = modes_for_model(model)
    if not 1 <= mode <= len(modes):
        raise ValueError(f"mode must be 1-{len(modes)}")
    if not SPEED_MIN <= speed <= SPEED_MAX:
        raise ValueError(f"speed must be {SPEED_MIN}-{SPEED_MAX}")
    palette = base + colors.index(color)
    if mode in _LOWER_MODES[Model(model)]:
        palette -= 128
    a, d = modes[mode - 1]
    if a == 0x02:
        return with_speed(bytes([a, 0x13, palette, d]), speed)
    return with_speed(bytes([a, palette, 0x00, d]), speed)


def identify_effect(code: bytes, effects: Mapping[str, Effect], last_sent: str | None = None) -> str | None:
    """Name the effect whose frame the lamp reports, or None if it cannot be told.

    ``last_sent`` (the effect this integration sent last) breaks ties: multi-frame
    effects are only reported by their last frame, and several effects differ only
    by their speed (e.g. "80s Club" and "Unicorns").
    """
    code = bytes(code)
    if code[0] == MULTI_FRAME_PREFIX:
        matches = [n for n, e in effects.items() if e.is_multi_frame and e.frames[-1] == code]
    else:
        matches = [n for n, e in effects.items() if e.frames == (code,)]
        if not matches and (idx := _speed_index(code)) is not None:
            def masked(c: bytes) -> bytes:
                return c[:idx] + b"\x00" + c[idx + 1 :]

            matches = [
                n for n, e in effects.items()
                if not e.is_multi_frame and _speed_index(e.frames[0]) == idx
                and masked(e.frames[0]) == masked(code)
            ]
    if len(matches) == 1:
        return matches[0]
    if last_sent in matches:
        return last_sent
    return None
