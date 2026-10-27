# Cololight (local) – Home Assistant integration design (contract)

Audience: the developers/agents building `custom_components/cololight_local`.
Ground truth for the device: `docs/findings.md` (measured on a real strip). Read it first.

## 0. Status of the code base

DONE and tested against the emulator and the real lamp – do not rewrite, only fix real bugs
(and say so explicitly in your report):

| File | Role |
|---|---|
| `custom_components/cololight_local/protocol.py` | frame codec, `PowerState`, `ModeState`, `DeviceState`, `CololightError`, `ProtocolError`, `format_mac()` |
| `custom_components/cololight_local/effects.py` | `Model`, `Effect`, effect tables, `effects_for_model()`, `custom_effect_code()`, `effect_speed()`, `with_speed()`, `identify_effect()`, `CUSTOM_SCHEMES`, `scheme_colors()`, `modes_for_model()`, `SPEED_MIN/MAX` |
| `custom_components/cololight_local/client.py` | `CololightClient` (async UDP, retries, ACK checking), `CololightTimeout`, `CololightConnectionError`, `CololightRejected`, `ClientStats`, `async_discover()`, `async_probe()`, `DiscoveredDevice` |
| `tests/fake_lamp.py` | UDP emulator of the lamp (`FakeLamp`), with packet loss, delay, crash, power cycle |

These three modules must stay free of Home Assistant imports (they are also used by CLI tools
on plain Python 3.12).

## 1. Identity

- Domain: **`cololight_local`** (the old community integration uses `cololight`; both can coexist).
- Name: **Cololight (local)**. Manufacturer: LifeSmart.
- `manifest.json`: `"config_flow": true`, `"iot_class": "local_polling"`, `"integration_type": "device"`,
  `"dependencies": ["network"]`, `"requirements": []`, `"version": "1.0.0"`,
  `"loggers": ["custom_components.cololight_local"]`, `"codeowners": []`,
  `"dhcp": [{"registered_devices": true}, {"macaddress": "4C11AE*"}]`,
  documentation / issue_tracker: `https://github.com/Geminium/ha-cololight-local` (placeholder, documented).
- Minimum Home Assistant: **2025.2.0**. Primary test target: **2026.10.4** (Python 3.14).
- `hacs.json` at repo root: `{"name": "Cololight (local)", "homeassistant": "2025.2.0", "render_readme": true}`.

## 2. Files to create

```
custom_components/cololight_local/
  __init__.py        setup/unload entry, runtime_data, background discovery, options listener
  const.py           DOMAIN, CONF_*, defaults, limits
  coordinator.py     CololightCoordinator + CololightData
  entity.py          CololightEntity base (CoordinatorEntity, device_info, has_entity_name)
  light.py           the light entity + entity services
  number.py          effect speed
  button.py          save state as power-on default
  config_flow.py     user / manual / integration_discovery / dhcp / reconfigure + options flow
  diagnostics.py
  services.yaml
  strings.json       English source of truth
  translations/en.json, translations/fr.json   (en.json == strings.json content)
  icons.json
  manifest.json
tests/
  conftest.py, test_protocol.py, test_effects.py, test_client.py,
  test_config_flow.py, test_init.py, test_coordinator.py, test_light.py,
  test_number.py, test_button.py, test_services.py, test_diagnostics.py
pyproject.toml (pytest config), hacs.json, README.md, docs/mode-emploi.md
```

## 3. Config entry

`entry.data` (set by the config flow):

| Key | Type | Notes |
|---|---|---|
| `host` (`CONF_HOST`) | str | IP address |
| `mac` (`CONF_MAC`) | str | `format_mac()` form `4c:11:ae:b1:b6:14`; also the entry `unique_id` |
| `model` (`CONF_MODEL`) | `"strip"` / `"hexagon"` | effect list depends on it |
| `port` (`CONF_PORT`) | int, optional | **not asked in the UI**; default 8900; exists so tests can target `FakeLamp` |

Title: `"Cololight XXXX"` where XXXX = last 4 hex digits of the MAC, upper case (users rename in UI).

`entry.options` (options flow), with defaults in `const.py`:

| Key | Default | Range / type | Meaning |
|---|---|---|---|
| `scan_interval` | 10 | 5–300 s | polling period |
| `save_as_default` | False | bool | after the state has been stable `save_delay` s, store it in EEPROM (op 07) |
| `save_delay` | 30 | 10–600 s | debounce for the above |
| `hidden_effects` | `[]` | list of built-in effect names | removed from `effect_list` |
| `custom_effects` | `{}` | `{name: {"scheme", "color", "speed", "mode", "code"}}` | user effects; `code` = 8 hex chars, precomputed with `custom_effect_code()` |

Any options change reloads the entry (update listener).

Runtime data: `@dataclass class CololightRuntimeData: client: CololightClient; coordinator: CololightCoordinator`
and `type CololightConfigEntry = ConfigEntry[CololightRuntimeData]` (use `entry.runtime_data`, never `hass.data`).

Setup: create client (`host`, `port`), `await coordinator.async_config_entry_first_refresh()`
(raises `ConfigEntryNotReady` when the lamp does not answer), forward platforms `light`, `number`, `button`.
Unload: unload platforms, `await client.async_stop()`, cancel pending save timer.

## 4. Coordinator (`CololightCoordinator(DataUpdateCoordinator[CololightData])`)

- `CololightData`: frozen dataclass `power: PowerState`, `mode: ModeState`.
- Constructor passes `config_entry=entry`, `update_interval=timedelta(seconds=options.scan_interval)`,
  `name=f"{DOMAIN} {host}"`, logger = module logger.
- `_async_update_data`: `await client.async_get_state()`.
  - On `CololightError`: increment `self.consecutive_failures`. While it is `< 3` **and** previous data exists,
    log at debug and return the previous data (entities stay available: one lost poll must not flap).
    **Rediscovery** at the 2nd and 3rd consecutive failures, then every 4th one (no broadcast at every poll):
    `async_discover(broadcast addresses from homeassistant.components.network.async_get_ipv4_broadcast_addresses)`;
    if a device with the entry MAC answers at another IP, `await client.async_set_host(new)` first, then update
    `entry.data[host]` (the update listener then sees the address already in use and does not reload);
    whether it moved or answered at the same address (it may just have finished booting), read it again and
    keep it available on success.
    At 3 failures raise `UpdateFailed` (translation key `communication_error`) → entities unavailable.
  - On success reset the counter.
  - The client is created with `expected_mac=entry.data[mac]`: a reply carrying another MAC (two lamps swapped
    their addresses) raises `CololightWrongDevice`, i.e. a failed poll, which starts the search by MAC.
- State kept for entities (defaults in brackets):
  `last_brightness` (last brightness while on, capped at 100, [100]), `last_rgb` (last static colour,
  [(255,255,255)]), `last_effect` (name of the last effect **sent by HA**, [None]). Updated from every poll/ACK
  (brightness only when on; rgb only when mode is a colour). `last_effect` is cleared as soon as the lamp reports
  something that cannot be that effect (a colour, another code), so a palette sharing its last frame with it is
  not shown under its name. The light entity is a `RestoreEntity` and seeds these three values after a reload or
  restart (`coordinator.async_restore`), unless the lamp already reported real ones.
- **Command lock**: every command helper and every save holds `self._command_lock`, and reads `self.data` only
  once it holds it (the light, the speed number and the deferred save are concurrent callers; scenes reproduce
  domains in parallel).
- `effects: dict[str, Effect]` = `effects_for_model(model)` minus `hidden_effects`, plus custom effects
  (`Effect(name, (bytes.fromhex(code),))`). Custom names override built-ins of the same name.
- `current_effect_name() -> str | None`: `None` if mode is a colour; else
  `identify_effect(mode.code, all_known_effects, last_effect)` where *all_known* includes hidden ones;
  if unidentified: `f"Effect {mode.code.hex()}"` for single-frame codes, `"Unknown palette effect"` for `0x93` codes.
- Command helpers used by entities/services. Each one calls the client, then
  `self.async_set_updated_data(new CololightData built from the ACKed values)` (no optimistic guess,
  no extra read), then `self._schedule_save()`:
  - `async_turn_on(brightness_pct: int | None = None, rgb: tuple | None = None, effect: str | None = None)`
    1. if `effect` given: `EFFECT_OFF` → send colour `rgb` if given (a scene saved on a static colour sends
       effect "off" **and** its colour), else `last_rgb`; known name → `client.async_set_effect(frames)`,
       set `last_effect`; `"Effect xxxxxxxx"` (8 hex) → send that single frame; `"Unknown palette effect"` (a scene
       or snapshot of an unidentified palette) → leave the mode as it is (warning if another mode runs), still
       apply brightness/power; anything else → raise `ServiceValidationError` (translation key `unknown_effect`).
    2. elif `rgb` given: `client.async_set_color(rgb)`.
    3. power: if `brightness_pct` given → `client.async_turn_on(brightness_pct)`; elif lamp currently off
       → `client.async_turn_on(last_brightness)`; else nothing (a mode change keeps brightness).
    Mode is always sent before power.
  - `async_turn_off()`.
  - `async_set_effect_speed(speed: int)` — only when current mode has a speed (`effect_speed()` not None),
    else `ServiceValidationError` (`no_adjustable_speed`); sends `with_speed(code, speed)`; keeps `last_effect`.
  - `async_set_custom_effect(scheme, color, speed, mode)` → `custom_effect_code(model, ...)` (ValueError →
    `ServiceValidationError` `invalid_custom_effect`), sends it, `last_effect = None`.
  - `async_set_effect_code(frames: list[bytes])` → `client.async_set_effect(frames)`.
  - `async_save_state()` — explicit save (button/service), always writes: a palette effect identified now
    (`current_effect_name()`) is re-sent whole with `client.async_set_effect(frames, save=True)`, then the
    brightness; an unidentified palette raises `HomeAssistantError` (`cannot_save_unknown_palette`), never a lone
    palette frame; otherwise `client.async_save_state(power, mode)`. The power element is only stored when on.
- `_schedule_save()`: only if option `save_as_default`, after commands that turn on or change brightness/mode
  (not after turn off); (re)start an `async_call_later(save_delay)`. When it fires, a background task of the entry
  takes the command lock and stores the state, unless a newer command restarted the delay meanwhile, the lamp is
  off (stored after the next turn on), or the state equals the last one stored (EEPROM wear); an unidentified
  palette stores the brightness only. Failures are logged as warnings. Timer and task are cancelled on unload, and
  a stopped client refuses to reopen its socket.
- Client exceptions inside command helpers are translated: `CololightTimeout`/`CololightConnectionError` →
  `HomeAssistantError(translation_domain=DOMAIN, translation_key="communication_error", translation_placeholders={"host": ...})`,
  `CololightRejected` → key `command_rejected` (placeholder `code`), `ValueError` → `ServiceValidationError`.
  A WARNING is logged with what failed and after how many attempts.

## 5. Entities

Common (`entity.py`): `_attr_has_entity_name = True`; `device_info`: identifiers `{(DOMAIN, mac)}`,
connections `{(CONNECTION_NETWORK_MAC, mac)}`, manufacturer "LifeSmart", model "Cololight Strip"/"Cololight Hexagon",
name = entry title. `unique_id` = `f"{mac}"` for the light, `f"{mac}_effect_speed"`, `f"{mac}_save_state"`.

**Light** (`_attr_name = None` → named after the device):
- `supported_color_modes = {ColorMode.RGB}`; `supported_features = LightEntityFeature.EFFECT`.
- `is_on` = power.on. `brightness` = `round(pct * 255 / 100)` when on, with pct capped to 1-100 (the lamp accepts
  and reports 0 and 101); else `last_brightness` converted.
- Static colour: `color_mode = RGB`, `rgb_color` = mode rgb, `effect = EFFECT_OFF`.
- Effect active: `color_mode = ColorMode.BRIGHTNESS` (allowed by HA while an effect is active), `rgb_color = None`,
  `effect = coordinator.current_effect_name()`.
- `effect_list = [EFFECT_OFF, *coordinator.effects]`.
- `turn_on(**kwargs)`: `ATTR_BRIGHTNESS` → pct `max(1, round(b * 100 / 255))`; `ATTR_RGB_COLOR`; `ATTR_EFFECT`
  → coordinator `async_turn_on`. `turn_off` → `async_turn_off`. No transition/flash support.
- `extra_state_attributes`: `{"effect_code": mode.code.hex()}` when an effect is active, plus
  `"effect_speed"` when it has one.

**Number** `effect_speed` (translation key `effect_speed`): 0–32 step 1, `NumberMode.SLIDER`, icon via icons.json;
`native_value = effect_speed(mode.code)`; `available` only when the coordinator is available **and** the current
mode has an adjustable speed; `async_set_native_value` → coordinator `async_set_effect_speed`.

**Button** `save_state` (translation key `save_state`), `EntityCategory.CONFIG` → coordinator `async_save_state()`.

## 6. Services (domain `cololight_local`, entity services targeting this integration's lights)

| Service | Fields | Action |
|---|---|---|
| `save_state` | – | coordinator `async_save_state()` |
| `set_custom_effect` | `scheme` (required, one of `CUSTOM_SCHEMES`), `color` (required, str, must belong to scheme), `speed` (0–32, default 16), `mode` (1–27, default 1; validated against the model: strip 1–13) | coordinator `async_set_custom_effect` |
| `set_effect_code` | `code` (required str: one or more 8-hex-digit frames separated by spaces or commas; first byte must not be `00`) | coordinator `async_set_effect_code` |

Register them as entity services of the light platform (check the API that is current and not deprecated in the
installed Home Assistant; `entity_platform.async_get_current_platform().async_register_entity_service` is acceptable).
`services.yaml` uses selectors (select for scheme, text for colour/code, number sliders). Validation errors →
`ServiceValidationError` with translation keys.

## 7. Config flow (`ConfigFlow`, `VERSION = 1`)

- `async_step_user`: discover (2 s) via `async_discover(broadcast addresses)`; drop devices whose MAC is already
  configured; if any remain, show a select (`"IP (MAC)"` labels) plus a "manual entry" choice; else go to `manual`.
- `async_step_manual`: field `host`; `async_probe(host)` → MAC; errors `cannot_connect` (any `CololightError`/`OSError`).
  `unique_id = format_mac(mac)`; `_abort_if_unique_id_configured(updates={CONF_HOST: host})`.
- `async_step_device` (after a device is chosen or probed): field `model` (select strip/hexagon, default strip,
  translated) → `async_create_entry(title=..., data=...)`.
- `async_step_integration_discovery` (from background scan, data `{"host", "mac"}`) and `async_step_dhcp`
  (`DhcpServiceInfo` from `homeassistant.helpers.service_info.dhcp`): set unique id, abort if configured
  (updating host), for DHCP also `async_probe` the IP (abort `not_cololight` if it fails); then
  `async_step_discovery_confirm` showing host/MAC with the `model` field; set `self.context["title_placeholders"]`.
- `async_step_reconfigure`: fields `host`, `model`; probe; `_abort_if_unique_id_mismatch`;
  `async_update_reload_and_abort`.
- Options flow (`OptionsFlow`, do **not** store `config_entry` yourself): menu `init` →
  `settings` (scan_interval, save_as_default, save_delay, hidden_effects multi-select of built-in names),
  `add_custom_effect` (name, scheme+colour as one select `"Scheme | Colour"`, speed, mode; compute and store `code`;
  error if name empty or invalid), `remove_custom_effects` (multi-select; abort `no_custom_effects` if none).
  Each step ends with `async_create_entry(data=<full new options dict>)`.

Background discovery (`__init__.async_setup`, which Home Assistant only runs once at least one entry exists: the first lamp comes from DHCP or the scan of the "Add integration" dialog): after Home Assistant has started and then every 15 minutes,
`async_discover(...)` and for each device `discovery_flow.async_create_flow(hass, DOMAIN,
context={"source": SOURCE_INTEGRATION_DISCOVERY}, data={"host": ..., "mac": ...})`
(the flow aborts by itself for configured devices and updates their IP).

## 8. Diagnostics

`async_get_config_entry_diagnostics`: entry data/options (redact `host`, `mac` via `async_redact_data`),
coordinator: last data (power, mode code hex), `consecutive_failures`, `last_effect`, `last_update_success`,
client: `dataclasses.asdict(client.stats)`.

## 9. Translations

`strings.json` (English) and `translations/fr.json` (French, natural wording) must cover: config steps/fields/
errors/aborts (`already_configured`, `cannot_connect`, `not_cololight`, `unique_id_mismatch`, `reconfigure_successful`),
selector options (`model`: strip/hexagon), options menu and steps, entity names (`number.effect_speed`,
`button.save_state`), services (names, descriptions, fields), exceptions
(`communication_error`, `command_rejected`, `unknown_effect`, `no_adjustable_speed`, `invalid_custom_effect`,
`invalid_effect_code`). `translations/en.json` = `strings.json`.

## 10. Quality bar

- Fully async, no blocking I/O in the event loop, typed (`from __future__ import annotations`), ruff-clean style.
- No `hass.data` globals, no deprecated APIs in HA 2026.10 (check warnings in test logs).
- Tests with `pytest-homeassistant-custom-component`; prefer end-to-end through `FakeLamp` (config entry with
  `host="127.0.0.1"`, `port=<fake port>`) over mocks; mock `async_discover`/`async_probe` in config flow tests.
  Target ≥ 90 % coverage of `custom_components/cololight_local`.
- Running the tests:
  - Linux / CI (reference): `pip install -r requirements_test.txt pytest-cov && python -m pytest`
    (`.github/workflows/tests.yml`, Python 3.14; `validate.yml` runs hassfest and the HACS action).
  - This Windows workstation: `sh /d/ColoLight-tmp-ha-src/runtests.sh <outfile> -q` (Python 3.14 venv on D: plus
    two test-only shims for `fcntl`/`resource` and pytest-socket's socketpair; nothing in the project depends on them).
  - Docker (`docker/test.Dockerfile`) also works, but move Docker's disk image to D: first: C: is nearly full.
