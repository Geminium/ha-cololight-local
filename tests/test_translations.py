"""Consistency of strings.json, the translations, services.yaml and icons.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from custom_components.cololight_local.const import DOMAIN

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
PLACEHOLDER = re.compile(r"{(\w+)}")


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def _flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


STRINGS = _load_json("strings.json")


def test_english_translation_is_strings_json() -> None:
    assert _load_json("translations/en.json") == STRINGS


def test_french_translation_matches_strings_json() -> None:
    english = _flatten(STRINGS)
    french = _flatten(_load_json("translations/fr.json"))
    assert set(french) == set(english)
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(french[key])) == set(PLACEHOLDER.findall(text)), key
        assert french[key].strip(), key


@pytest.mark.parametrize(
    "key",
    [
        *(f"config.error.{k}" for k in ("cannot_connect",)),
        *(
            f"config.abort.{k}"
            for k in (
                "already_configured",
                "already_in_progress",
                "not_cololight",
                "unique_id_mismatch",
                "reconfigure_successful",
            )
        ),
        *(f"options.error.{k}" for k in ("invalid_name", "invalid_custom_effect")),
        "options.abort.no_custom_effects",
        "selector.model.options.strip",
        "selector.model.options.hexagon",
        "selector.device.options.manual",
        "entity.number.effect_speed.name",
        "entity.button.save_state.name",
        *(
            f"exceptions.{k}.message"
            for k in (
                "communication_error",
                "command_rejected",
                "unknown_effect",
                "no_adjustable_speed",
                "invalid_custom_effect",
                "unknown_custom_color",
                "custom_mode_out_of_range",
                "invalid_effect_code",
                "no_effect_frame",
                "invalid_effect_frame",
                "effect_frame_is_colour",
                "cannot_save_unknown_palette",
            )
        ),
    ],
)
def test_keys_used_by_the_code_exist(key: str) -> None:
    assert key in _flatten(STRINGS)


@pytest.mark.parametrize(
    ("key", "placeholders"),
    [
        ("exceptions.communication_error.message", {"host"}),
        ("exceptions.command_rejected.message", {"code"}),
        ("exceptions.unknown_effect.message", {"effect"}),
        ("exceptions.no_adjustable_speed.message", set()),
        ("exceptions.invalid_custom_effect.message", {"error"}),
        ("exceptions.unknown_custom_color.message", {"color", "scheme", "colors"}),
        ("exceptions.custom_mode_out_of_range.message", {"max"}),
        ("exceptions.invalid_effect_code.message", {"error"}),
        ("exceptions.no_effect_frame.message", set()),
        ("exceptions.invalid_effect_frame.message", {"frame"}),
        ("exceptions.effect_frame_is_colour.message", {"frame"}),
        ("exceptions.cannot_save_unknown_palette.message", set()),
        ("config.step.device.description", {"host", "mac"}),
        ("config.step.discovery_confirm.description", {"host", "mac"}),
        ("config.flow_title", {"name", "host"}),
        ("options.step.add_custom_effect.description", {"modes"}),
    ],
)
def test_placeholders_given_by_the_code(key: str, placeholders: set[str]) -> None:
    assert set(PLACEHOLDER.findall(_flatten(STRINGS)[key])) == placeholders


def test_services_are_described() -> None:
    services = yaml.safe_load((PACKAGE / "services.yaml").read_text(encoding="utf-8"))
    icons = _load_json("icons.json")
    assert set(services) == set(STRINGS["services"]) == set(icons["services"])
    for name, service in services.items():
        described = STRINGS["services"][name]
        assert described["name"]
        assert described["description"]
        assert set(service.get("fields", {})) == set(described.get("fields", {})), name
        assert service["target"]["entity"] == {"integration": DOMAIN, "domain": "light"}


def test_entity_icons() -> None:
    icons = _load_json("icons.json")
    assert set(icons["entity"]) == set(STRINGS["entity"])
    for platform, entities in STRINGS["entity"].items():
        assert set(icons["entity"][platform]) == set(entities)
