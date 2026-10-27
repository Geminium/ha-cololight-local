"""Tests of the effect tables and helpers (custom_components/cololight_local/effects.py).

Frames tagged "real" were acknowledged and read back by the real strip on 2026-10-25
(``logs/cololight-20261025.jsonl``, labels ``H8-*`` and ``custom-*``).
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from custom_components.cololight_local.effects import (
    CUSTOM_SCHEMES,
    DEFAULT_EFFECTS,
    HEXAGON_MODES,
    SPEED_MAX,
    SPEED_MIN,
    STRIP_DYNAMIC_EFFECTS,
    STRIP_MODES,
    Effect,
    Model,
    custom_effect_code,
    effect_speed,
    effects_for_model,
    identify_effect,
    modes_for_model,
    scheme_colors,
    with_speed,
)
from custom_components.cololight_local.protocol import MULTI_FRAME_PREFIX, effect_data

STRIP_EFFECTS = effects_for_model(Model.STRIP)
HEXAGON_EFFECTS = effects_for_model(Model.HEXAGON)


def _h(code: str) -> bytes:
    return bytes.fromhex(code)


# ------------------------------------------------------------------ tables


def test_table_sizes() -> None:
    assert len(DEFAULT_EFFECTS) == 12
    assert len(STRIP_DYNAMIC_EFFECTS) == 40
    assert sum(e.is_multi_frame for e in STRIP_DYNAMIC_EFFECTS.values()) == 22
    assert not any(e.is_multi_frame for e in DEFAULT_EFFECTS.values())
    assert not set(DEFAULT_EFFECTS) & set(STRIP_DYNAMIC_EFFECTS)


def test_table_keys_match_names() -> None:
    for table in (DEFAULT_EFFECTS, STRIP_DYNAMIC_EFFECTS):
        for name, effect in table.items():
            assert effect.name == name


def test_every_frame_is_a_valid_effect_frame() -> None:
    for effect in STRIP_EFFECTS.values():
        assert effect.frames
        for frame in effect.frames:
            assert isinstance(frame, bytes)
            assert len(frame) == 4
            effect_data(frame)  # raises on a static-colour prefix or a wrong length
        if effect.is_multi_frame:
            assert all(f[0] == MULTI_FRAME_PREFIX for f in effect.frames)
            assert effect.frames[0] == _h("93fefefe")  # every palette upload starts with it
        else:
            assert effect.frames[0][0] not in (0x00, MULTI_FRAME_PREFIX)


def test_single_frame_codes_are_unique() -> None:
    codes = [e.frames[0] for e in STRIP_EFFECTS.values() if not e.is_multi_frame]
    assert len(codes) == len(set(codes)) == 30


@pytest.mark.parametrize(
    ("name", "code"),
    [
        # the 12 default effects, read back by the real strip (label H8-*)
        ("80s Club", "049a0000"),
        ("Cherry Blossom", "04940800"),
        ("Cocktail Parade", "05bd0690"),
        ("Instagrammer", "03bc0190"),
        ("Pensieve", "04c40600"),
        ("Savasana", "04970400"),
        ("Sunrise", "01c10a00"),
        ("The Circus", "04810130"),
        ("Unicorns", "049a0e00"),
        ("Christmas", "068b0900"),
        ("Rainbow Flow", "03810690"),
        ("Music Mode", "07bd0990"),
        # single-frame dynamic effects tested on the strip
        ("Color train", "069a0d00"),
        ("Snow", "058908c0"),
        ("Lover", "05ba0150"),
        ("Red alert", "06a90100"),
    ],
)
def test_real_single_frames(name: str, code: str) -> None:
    assert STRIP_EFFECTS[name].frames == (_h(code),)


@pytest.mark.parametrize(
    ("name", "frames"),
    [
        # every frame acknowledged one by one by the real strip (label H8-*)
        ("Tron", "93fefefe 9304058b 93f0b003 93ff0000 930087ff 9300ff64"),
        ("Red meteor", "93fefefe 93020237 93f04800 93ff0000"),
        ("Innocence", "93fefefe 93060c28 93f01300 935ab4ff 93ff7878 93a9ffac 93d696ff 93fff477"),
    ],
)
def test_real_multi_frames(name: str, frames: str) -> None:
    assert STRIP_EFFECTS[name].frames == tuple(_h(f) for f in frames.split())


def test_effect_dataclass() -> None:
    single = Effect("x", (_h("01c10a00"),))
    multi = Effect("y", (_h("93fefefe"), _h("9300ff64")))
    assert not single.is_multi_frame
    assert multi.is_multi_frame
    assert single == Effect("x", (_h("01c10a00"),))
    with pytest.raises(AttributeError):
        single.name = "z"  # type: ignore[misc]


# ------------------------------------------------------------------ effects_for_model / modes


def test_effects_for_strip() -> None:
    effects = effects_for_model(Model.STRIP)
    assert len(effects) == 52
    assert list(effects) == [*DEFAULT_EFFECTS, *STRIP_DYNAMIC_EFFECTS]  # display order


def test_effects_for_hexagon() -> None:
    effects = effects_for_model(Model.HEXAGON)
    assert list(effects) == list(DEFAULT_EFFECTS)
    assert not any(e.is_multi_frame for e in effects.values())


def test_effects_for_model_accepts_strings() -> None:
    assert effects_for_model("strip") == STRIP_EFFECTS
    assert effects_for_model("hexagon") == HEXAGON_EFFECTS


def test_effects_for_model_returns_a_copy() -> None:
    for model in Model:
        effects = effects_for_model(model)
        effects.pop("Sunrise")
        effects["mine"] = Effect("mine", (_h("01c10000"),))
    assert "Sunrise" in DEFAULT_EFFECTS
    assert "mine" not in DEFAULT_EFFECTS
    assert "mine" not in STRIP_DYNAMIC_EFFECTS
    assert len(effects_for_model(Model.STRIP)) == 52


def test_unknown_model() -> None:
    with pytest.raises(ValueError, match="bulb"):
        effects_for_model("bulb")
    with pytest.raises(ValueError, match="bulb"):
        modes_for_model("bulb")


def test_modes_for_model() -> None:
    assert modes_for_model(Model.STRIP) is STRIP_MODES
    assert modes_for_model("hexagon") is HEXAGON_MODES
    assert len(STRIP_MODES) == 13
    assert len(HEXAGON_MODES) == 27


def test_model_values() -> None:
    assert [m.value for m in Model] == ["strip", "hexagon"]


# ------------------------------------------------------------------ schemes


def test_scheme_colors() -> None:
    assert scheme_colors("Selected") == ["Savasana", "Sunrise", "Unicorns"]  # gaps removed
    assert scheme_colors("Breath")[0] == "Red, Green, Blue"
    assert len(scheme_colors("Breath")) == 11
    assert len(scheme_colors("Shadow")) == 15
    assert len(scheme_colors("Scene")) == 6
    with pytest.raises(KeyError):
        scheme_colors("Nope")


def test_scheme_palette_bytes_fit_in_a_byte() -> None:
    assert set(CUSTOM_SCHEMES) == {"Breath", "Shadow", "Flash", "Flicker", "Scene", "Mood", "Selected"}
    for base, colors in CUSTOM_SCHEMES.values():
        assert base >= 128
        assert base + len(colors) - 1 <= 0xFF


# ------------------------------------------------------------------ speed


def test_speed_bounds() -> None:
    assert (SPEED_MIN, SPEED_MAX) == (0, 32)


@pytest.mark.parametrize(
    ("code", "speed"),
    [
        ("01c10a00", 22),  # Sunrise as shipped
        ("01c10000", 32),  # byte 0x00 = fastest (verified visually)
        ("01c12000", 0),  # byte 0x20 = slowest (verified visually)
        ("01c13000", 0),  # beyond 0x20: clamped to the slowest
        ("01c1ff00", 0),
        ("05bd0690", 26),
        ("020b8d00", 21),  # mode 2 family: speed in byte B
        ("02138d00", 13),
        ("02038d00", 29),
    ],
)
def test_effect_speed(code: str, speed: int) -> None:
    assert effect_speed(_h(code)) == speed


@pytest.mark.parametrize("code", ["00ff0000", "9300ff64", "93fefefe", "01c10a", "01c10a0000", ""])
def test_effect_speed_not_applicable(code: str) -> None:
    assert effect_speed(_h(code)) is None


@pytest.mark.parametrize(
    ("speed", "byte"), [(0, 0x20), (1, 0x1F), (16, 0x10), (22, 0x0A), (31, 0x01), (32, 0x00)]
)
def test_with_speed(speed: int, byte: int) -> None:
    assert with_speed(_h("01c10a00"), speed) == bytes([0x01, 0xC1, byte, 0x00])


def test_with_speed_round_trip_keeps_other_bytes() -> None:
    for name, effect in STRIP_EFFECTS.items():
        if effect.is_multi_frame:
            continue
        code = effect.frames[0]
        for speed in range(SPEED_MIN, SPEED_MAX + 1):
            new = with_speed(code, speed)
            assert effect_speed(new) == speed, name
            assert (new[0], new[1], new[3]) == (code[0], code[1], code[3]), name


@pytest.mark.parametrize(
    ("speed", "byte"),
    [
        (0, 0x13),
        (13, 0x13),
        (17, 0x13),
        (18, 0x0B),
        (21, 0x0B),
        (25, 0x0B),
        (26, 0x03),
        (29, 0x03),
        (32, 0x03),
    ],
)
def test_with_speed_mode2_quantisation(speed: int, byte: int) -> None:
    """The mode 2 family only knows three speeds (bytes 0x13, 0x0b, 0x03), stored in byte B."""
    assert with_speed(_h("020b8d00"), speed) == bytes([0x02, byte, 0x8D, 0x00])


def test_with_speed_mode2_is_stable() -> None:
    for speed in range(SPEED_MIN, SPEED_MAX + 1):
        code = with_speed(_h("02138d00"), speed)
        assert code[1] in (0x13, 0x0B, 0x03)
        current = effect_speed(code)
        assert current is not None
        assert with_speed(code, current) == code


@pytest.mark.parametrize("speed", [-1, 33, 100])
def test_with_speed_out_of_range(speed: int) -> None:
    with pytest.raises(ValueError, match="speed must be 0-32"):
        with_speed(_h("01c10a00"), speed)


@pytest.mark.parametrize("code", ["00ff0000", "9300ff64", "01c10a"])
def test_with_speed_no_adjustable_speed(code: str) -> None:
    with pytest.raises(ValueError, match="no adjustable speed"):
        with_speed(_h(code), 10)


# ------------------------------------------------------------------ custom effects


@pytest.mark.parametrize(
    ("scheme", "color", "speed", "mode", "code"),
    [
        # Frames built by the probe tool and acknowledged/read back by the real strip.
        # The tool used pycololight's speed scale (byte = 33 - speed, 1..32), ours is
        # byte = 32 - speed (0..32): tool speed 16 = our 15, 32 = 31, 8 = 7.
        ("Breath", "Red", 15, 1, "01861100"),
        ("Flash", "Rainbow", 31, 3, "059a0110"),
        ("Mood", "Blue", 7, 11, "06b91900"),
        # mode 2: speed byte B (one of 3 values), palette byte C
        ("Shadow", "Red, Blue", 21, 2, "020b8d00"),
    ],
)
def test_custom_effect_matches_real_frames(scheme: str, color: str, speed: int, mode: int, code: str) -> None:
    assert custom_effect_code(Model.STRIP, scheme, color, speed, mode) == _h(code)


def test_custom_effect_layout() -> None:
    # A = mode byte, B = palette (scheme base + colour index), C = speed, D = mode byte
    assert custom_effect_code("strip", "Breath", "Red, Green, Blue", 32, 1) == _h("01800000")
    assert custom_effect_code("strip", "Selected", "Unicorns", 0, 1) == _h("01c32000")  # 191 + 4
    assert custom_effect_code("strip", "Mood", "True Color", 16, 13) == _h("06bd1060")  # 179 + 10


def test_custom_effect_mode2_byte_order() -> None:
    code = custom_effect_code(Model.STRIP, "Breath", "Red", 32, 2)
    assert code == _h("02038600")  # speed in B, palette in C
    assert custom_effect_code(Model.HEXAGON, "Breath", "Red", 0, 2) == _h("02138600")
    assert effect_speed(code) == 29


def test_custom_effect_strip_lower_mode() -> None:
    """Strip modes 3 and 10 share bytes A/D: mode 10 lowers the palette byte by 128."""
    assert STRIP_MODES[2] == STRIP_MODES[9] == (0x05, 0x10)
    assert custom_effect_code("strip", "Breath", "Red", 32, 3) == _h("05860010")
    assert custom_effect_code("strip", "Breath", "Red", 32, 10) == _h("05060010")


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        (1, "01860000"),
        (4, "05860030"),
        (12, "058600c0"),
        (13, "05060000"),  # lower
        (14, "05060020"),  # lower
        (15, "05060030"),  # lower, same A/D as mode 4
        (16, "06860000"),
        (21, "058600f0"),
        (22, "05060010"),  # lower, same A/D as mode 3
        (23, "05060040"),  # lower, same A/D as mode 5
        (24, "05060050"),  # lower, same A/D as mode 6
        (27, "06860080"),
    ],
)
def test_custom_effect_hexagon_modes(mode: int, code: str) -> None:
    assert custom_effect_code(Model.HEXAGON, "Breath", "Red", 32, mode) == _h(code)


@pytest.mark.parametrize("model", list(Model))
def test_custom_effect_modes_are_distinct(model: Model) -> None:
    """Thanks to the lower modes, every mode of a model yields a different frame."""
    modes = modes_for_model(model)
    codes = {custom_effect_code(model, "Flash", "Blue", 10, m) for m in range(1, len(modes) + 1)}
    assert len(codes) == len(modes)


def test_custom_effect_all_combinations_are_valid_frames() -> None:
    for model in Model:
        for scheme in CUSTOM_SCHEMES:
            for color in scheme_colors(scheme):
                for mode in range(1, len(modes_for_model(model)) + 1):
                    code = custom_effect_code(model, scheme, color, 16, mode)
                    effect_data(code)
                    assert effect_speed(code) is not None


@pytest.mark.parametrize(
    ("model", "scheme", "color", "speed", "mode", "message"),
    [
        ("strip", "Nope", "Red", 16, 1, "unknown scheme"),
        ("strip", "Breath", "Pink", 16, 1, "unknown colour"),
        ("strip", "Selected", "", 16, 1, "unknown colour"),  # the gaps of the table are not colours
        ("strip", "Breath", "Red", 16, 0, "mode must be 1-13"),
        ("strip", "Breath", "Red", 16, 14, "mode must be 1-13"),
        ("hexagon", "Breath", "Red", 16, 28, "mode must be 1-27"),
        ("strip", "Breath", "Red", -1, 1, "speed must be 0-32"),
        ("strip", "Breath", "Red", 33, 1, "speed must be 0-32"),
        ("bulb", "Breath", "Red", 16, 1, "bulb"),
    ],
)
def test_custom_effect_errors(
    model: str, scheme: str, color: str, speed: int, mode: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        custom_effect_code(model, scheme, color, speed, mode)


def test_custom_effect_hexagon_accepts_high_modes() -> None:
    assert custom_effect_code("hexagon", "Breath", "Red", 16, 27)[0] == 0x06


# ------------------------------------------------------------------ identify_effect


@pytest.mark.parametrize("name", [n for n, e in STRIP_EFFECTS.items() if not e.is_multi_frame])
def test_identify_every_single_frame_effect(name: str) -> None:
    assert identify_effect(STRIP_EFFECTS[name].frames[0], STRIP_EFFECTS) == name


def test_identify_speed_masked() -> None:
    # Sunrise is 01c10a00; the user changed its speed
    assert identify_effect(_h("01c11500"), STRIP_EFFECTS) == "Sunrise"
    assert identify_effect(with_speed(_h("069a0d00"), 0), STRIP_EFFECTS) == "Color train"


def test_identify_speed_masked_mode2_custom_effect() -> None:
    effects = {**STRIP_EFFECTS, "Mine": Effect("Mine", (_h("020b8d00"),))}
    assert identify_effect(_h("02138d00"), effects) == "Mine"  # speed byte is B for mode 2


def test_identify_mask_needs_the_same_speed_position() -> None:
    effects = {"m2": Effect("m2", (_h("02c10a00"),))}
    # same bytes except A: different family, not the same effect
    assert identify_effect(_h("01c10a00"), effects) is None


def test_identify_80s_club_vs_unicorns() -> None:
    """049a0000 and 049a0e00 differ only by their speed byte."""
    # exact codes are unambiguous, whatever was sent last
    assert identify_effect(_h("049a0000"), STRIP_EFFECTS) == "80s Club"
    assert identify_effect(_h("049a0e00"), STRIP_EFFECTS) == "Unicorns"
    assert identify_effect(_h("049a0000"), STRIP_EFFECTS, "Unicorns") == "80s Club"
    # once the speed changed, only the hint can tell them apart
    changed = _h("049a0500")
    assert identify_effect(changed, STRIP_EFFECTS) is None
    assert identify_effect(changed, STRIP_EFFECTS, "Unicorns") == "Unicorns"
    assert identify_effect(changed, STRIP_EFFECTS, "80s Club") == "80s Club"
    assert identify_effect(changed, STRIP_EFFECTS, "Sunrise") is None  # hint not among the candidates
    assert identify_effect(changed, HEXAGON_EFFECTS, "Unicorns") == "Unicorns"


def test_80s_club_and_unicorns_are_the_only_speed_ambiguity() -> None:
    groups: dict[bytes, set[str]] = defaultdict(set)
    for name, effect in STRIP_EFFECTS.items():
        if not effect.is_multi_frame:
            code = effect.frames[0]
            groups[with_speed(code, SPEED_MIN)].add(name)
    assert [g for g in groups.values() if len(g) > 1] == [{"80s Club", "Unicorns"}]


def test_identify_multi_frame_last_frame() -> None:
    # unique last frame: no hint needed
    assert identify_effect(_h("93fff477"), STRIP_EFFECTS) == "Innocence"
    assert identify_effect(_h("93fff477"), STRIP_EFFECTS, "Sunrise") == "Innocence"
    # a multi-frame effect is never matched against single-frame tables
    assert identify_effect(_h("93fff477"), HEXAGON_EFFECTS) is None


def test_identify_tron_vs_tricolor() -> None:
    """Both end with 9300ff64 (real read-back after Tron): only the hint can tell."""
    last = _h("9300ff64")
    assert STRIP_EFFECTS["Tron"].frames[-1] == STRIP_EFFECTS["Tricolor"].frames[-1] == last
    assert identify_effect(last, STRIP_EFFECTS) is None
    assert identify_effect(last, STRIP_EFFECTS, "Tron") == "Tron"
    assert identify_effect(last, STRIP_EFFECTS, "Tricolor") == "Tricolor"
    assert identify_effect(last, STRIP_EFFECTS, "Innocence") is None
    assert identify_effect(bytearray(last), STRIP_EFFECTS, "Tron") == "Tron"


def test_identify_not_last_frame() -> None:
    """A frame that is not the last one of any effect (e.g. upload interrupted)."""
    assert identify_effect(_h("93fefefe"), STRIP_EFFECTS) is None
    assert identify_effect(_h("93fefefe"), STRIP_EFFECTS, "Tron") is None
    assert identify_effect(_h("9304058b"), STRIP_EFFECTS, "Tron") is None


def test_ambiguous_last_frames() -> None:
    groups: dict[bytes, set[str]] = defaultdict(set)
    for name, effect in STRIP_EFFECTS.items():
        if effect.is_multi_frame:
            groups[effect.frames[-1]].add(name)
    ambiguous = sorted(sorted(g) for g in groups.values() if len(g) > 1)
    assert ambiguous == [
        ["Break dance", "Sunset"],
        ["Cranberry", "Witch hut"],
        ["Red meteor", "Tropic affair"],
        ["Tricolor", "Tron"],
    ]


@pytest.mark.parametrize("name", [n for n, e in STRIP_EFFECTS.items() if e.is_multi_frame])
def test_identify_every_multi_frame_effect_with_hint(name: str) -> None:
    assert identify_effect(STRIP_EFFECTS[name].frames[-1], STRIP_EFFECTS, name) == name


def test_identify_static_colour_and_unknown() -> None:
    assert identify_effect(_h("00ff2222"), STRIP_EFFECTS) is None
    assert identify_effect(_h("00ff2222"), STRIP_EFFECTS, "Sunrise") is None
    assert identify_effect(_h("07c10a00"), STRIP_EFFECTS) is None  # no known effect in that family
    assert identify_effect(_h("01c10a00"), {}) is None


def test_identify_duplicate_exact_codes() -> None:
    """A user effect with the same frame as a built-in one: ambiguous without a hint."""
    effects = {**STRIP_EFFECTS, "Mine": Effect("Mine", (_h("049a0000"),))}
    assert identify_effect(_h("049a0000"), effects) is None
    assert identify_effect(_h("049a0000"), effects, "Mine") == "Mine"
    assert identify_effect(_h("049a0000"), effects, "80s Club") == "80s Club"


def test_identify_custom_effects() -> None:
    code = custom_effect_code("strip", "Mood", "Blue", 7, 11)
    effects = {**STRIP_EFFECTS, "Blue mood": Effect("Blue mood", (code,))}
    assert identify_effect(code, effects) == "Blue mood"
    assert identify_effect(with_speed(code, 30), effects) == "Blue mood"
