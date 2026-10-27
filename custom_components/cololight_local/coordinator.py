"""Polling coordinator and command helpers for one Cololight lamp.

Strategy (docs/findings.md, section 6, and docs/integration-design.md, section 4):

* the state is polled (power + mode, two requests); one lost poll must not make the
  entities flap, so the previous data is kept until 3 polls in a row have failed;
* from the 2nd failed poll on, the lamp is looked for on the LAN by its MAC address
  (at the 2nd and 3rd failures, then every 4th one);
* commands update the state from the lamp's acknowledgement (no optimistic guess,
  no extra read), and failures surface as translated Home Assistant errors;
* commands and saves run one at a time (the light, the speed number and the deferred
  save are separate callers), each one building on the state left by the previous one.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import network
from homeassistant.components.light import EFFECT_OFF
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_SCAN_INTERVAL
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CololightClient, CololightRejected, async_discover
from .const import (
    CONF_CUSTOM_EFFECTS,
    CONF_HIDDEN_EFFECTS,
    CONF_SAVE_AS_DEFAULT,
    CONF_SAVE_DELAY,
    CUSTOM_CODE,
    DEFAULT_BRIGHTNESS_PCT,
    DEFAULT_MODEL,
    DEFAULT_RGB,
    DEFAULT_SAVE_AS_DEFAULT,
    DEFAULT_SAVE_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DISCOVERY_TIMEOUT,
    DOMAIN,
    MAX_CONSECUTIVE_FAILURES,
    REDISCOVERY_AFTER_FAILURES,
    REDISCOVERY_EVERY_FAILURES,
    UNKNOWN_EFFECT_PREFIX,
    UNKNOWN_PALETTE_EFFECT,
)
from .effects import (
    CUSTOM_SCHEMES,
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
from .protocol import (
    BRIGHTNESS_MAX,
    MULTI_FRAME_PREFIX,
    CololightError,
    ModeState,
    PowerState,
    format_mac,
)

_LOGGER = logging.getLogger(__name__)

_UNKNOWN_EFFECT_RE = re.compile(rf"^{re.escape(UNKNOWN_EFFECT_PREFIX)}([0-9a-f]{{8}})$")
_COLOR_SEPARATOR = " · "  # colours such as "Red, Green, Blue" contain commas

# What a save stored: the frames of the mode (None: not stored), the brightness (None: not
# stored, the lamp was off).
type SavedState = tuple[tuple[bytes, ...] | None, int | None]


@dataclass(slots=True)
class CololightRuntimeData:
    """What a loaded config entry keeps in ``entry.runtime_data``."""

    client: CololightClient
    coordinator: CololightCoordinator


type CololightConfigEntry = ConfigEntry[CololightRuntimeData]


@dataclass(frozen=True, slots=True)
class CololightData:
    """State of the lamp as last read or acknowledged."""

    power: PowerState
    mode: ModeState


def validation_error(key: str, **placeholders: str) -> ServiceValidationError:
    """A translated error about what the user asked for (nothing was sent)."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def _load_custom_effects(options: dict[str, Any]) -> dict[str, Effect]:
    """Custom effects stored in the options, skipping anything malformed."""
    effects: dict[str, Effect] = {}
    for name, spec in (options.get(CONF_CUSTOM_EFFECTS) or {}).items():
        try:
            frame = bytes.fromhex(str(spec[CUSTOM_CODE]))
        except (KeyError, TypeError, ValueError):
            frame = b""
        if len(frame) != 4 or frame[0] == 0x00:
            _LOGGER.warning("Ignoring custom effect %r: invalid code in the options", name)
            continue
        effects[str(name)] = Effect(str(name), (frame,))
    return effects


class CololightCoordinator(DataUpdateCoordinator[CololightData]):
    """Poll one lamp and send it commands."""

    config_entry: CololightConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CololightConfigEntry, client: CololightClient) -> None:
        options = dict(entry.options)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self.mac: str = entry.data[CONF_MAC]
        self.model = Model(entry.data.get(CONF_MODEL, DEFAULT_MODEL))
        # Snapshot compared by the update listener: an options change reloads the entry.
        self.options = copy.deepcopy(options)
        self.save_as_default: bool = options.get(CONF_SAVE_AS_DEFAULT, DEFAULT_SAVE_AS_DEFAULT)
        self.save_delay: float = options.get(CONF_SAVE_DELAY, DEFAULT_SAVE_DELAY)

        builtin = effects_for_model(self.model)
        custom = _load_custom_effects(options)
        hidden = set(options.get(CONF_HIDDEN_EFFECTS) or ())
        # Shown in the effect list: built-ins minus hidden ones, plus custom ones
        # (a custom effect overrides a built-in of the same name).
        self.effects: dict[str, Effect] = {
            **{name: fx for name, fx in builtin.items() if name not in hidden},
            **custom,
        }
        # Used to name what the lamp reports, hidden effects included.
        self.all_effects: dict[str, Effect] = {**builtin, **custom}

        self.consecutive_failures = 0
        self.last_brightness: int = DEFAULT_BRIGHTNESS_PCT
        self.last_rgb: tuple[int, int, int] = DEFAULT_RGB
        self.last_effect: str | None = None
        # True once the value above comes from the lamp, not from the defaults: the values
        # restored from the previous run (light entity) only fill the others.
        self._brightness_known = False
        self._rgb_known = False

        # One command (or save) at a time: each one reads the state left by the previous one.
        self._command_lock = asyncio.Lock()
        self._save_unsub: CALLBACK_TYPE | None = None
        self._save_task: asyncio.Task[None] | None = None
        self._last_saved: SavedState | None = None  # skip an automatic save of the same state

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> CololightData:
        try:
            state = await self.client.async_get_state()
        except CololightError as err:
            return await self._async_poll_failed(err)
        self.consecutive_failures = 0
        return self._remember(CololightData(power=state.power, mode=state.mode))

    async def _async_poll_failed(self, err: CololightError) -> CololightData:
        self.consecutive_failures += 1
        if self._rediscovery_due():
            data = await self._async_rediscover()
            if data is not None:
                self.consecutive_failures = 0
                return data
        if self.consecutive_failures < MAX_CONSECUTIVE_FAILURES and self.data is not None:
            _LOGGER.debug(
                "%s: poll failed (%d in a row), keeping the previous state: %s",
                self.client.host,
                self.consecutive_failures,
                err,
            )
            return self.data
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="communication_error",
            translation_placeholders={"host": self.client.host},
        ) from err

    def _rediscovery_due(self) -> bool:
        """At the 2nd and 3rd failed polls, then every 4th one (no broadcast at every poll)."""
        failures = self.consecutive_failures
        return failures >= REDISCOVERY_AFTER_FAILURES and (
            failures <= MAX_CONSECUTIVE_FAILURES or failures % REDISCOVERY_EVERY_FAILURES == 0
        )

    async def _async_rediscover(self) -> CololightData | None:
        """Look for the lamp by MAC; follow it if it moved, read it again if it answered."""
        try:
            addresses = await network.async_get_ipv4_broadcast_addresses(self.hass)
            devices = await async_discover(addresses, timeout=DISCOVERY_TIMEOUT, port=self.client.port)
        except OSError as err:
            _LOGGER.debug("%s: rediscovery failed: %s", self.client.host, err)
            return None
        new_host = next((d.host for d in devices if format_mac(d.mac) == self.mac), None)
        if new_host is None:
            _LOGGER.debug("%s: rediscovery did not find the lamp", self.client.host)
            return None
        if new_host != self.client.host:
            _LOGGER.info("Cololight %s moved from %s to %s", self.mac, self.client.host, new_host)
            # Client first: the update listener then sees the address already in use and
            # does not reload the entry.
            await self.client.async_set_host(new_host)
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_HOST: new_host}
            )
        # At the same address, the lamp may just have finished booting: read it again
        # rather than declaring it unavailable.
        try:
            state = await self.client.async_get_state()
        except CololightError as err:
            _LOGGER.debug("%s: no answer after rediscovery: %s", new_host, err)
            return None
        return self._remember(CololightData(power=state.power, mode=state.mode))

    @callback
    def _remember(self, data: CololightData) -> CololightData:
        """Keep what is needed to restore the light later (brightness, colour, effect)."""
        if data.power.on and data.power.brightness:
            # The lamp accepts and reports 101 %; the integration never sends more than 100.
            self.last_brightness = min(data.power.brightness, BRIGHTNESS_MAX)
            self._brightness_known = True
        if (rgb := data.mode.rgb) is not None:
            self.last_rgb = rgb
            self._rgb_known = True
        if self.last_effect is not None and not self._is_running(self.last_effect, data.mode):
            # Something else runs now: the name must not stick to a later frame that only
            # resembles it (palette effects sharing their last frame).
            self.last_effect = None
        return data

    def _is_running(self, name: str, mode: ModeState) -> bool:
        """Whether ``mode`` can be the effect ``name`` (its last frame, any speed)."""
        effect = self.all_effects.get(name)
        return effect is not None and not mode.is_color and identify_effect(mode.code, {name: effect}) == name

    @callback
    def _apply(self, data: CololightData) -> None:
        """Publish a state acknowledged by the lamp."""
        self.consecutive_failures = 0
        self.async_set_updated_data(self._remember(data))

    @callback
    def async_restore(
        self, brightness: int | None, rgb: tuple[int, int, int] | None, effect: str | None
    ) -> None:
        """Seed what the previous run remembered, unless the lamp already told.

        The lamp does not report its brightness while off, nor the colour while an effect
        runs, and reports a palette effect by its last frame only.
        """
        if brightness is not None and 1 <= brightness <= BRIGHTNESS_MAX and not self._brightness_known:
            self.last_brightness = brightness
        if rgb is not None and len(rgb) == 3 and all(0 <= c <= 0xFF for c in rgb) and not self._rgb_known:
            self.last_rgb = (rgb[0], rgb[1], rgb[2])
        if (
            effect is not None
            and self.last_effect is None
            and self.data is not None
            and self._is_running(effect, self.data.mode)
        ):
            self.last_effect = effect

    # ------------------------------------------------------------------ effects

    def current_effect_name(self) -> str | None:
        """Name of the active effect, None while a static colour is shown."""
        mode = self.data.mode
        if mode.is_color:
            return None
        name = identify_effect(mode.code, self.all_effects, self.last_effect)
        if name is not None:
            return name
        if mode.code[0] == MULTI_FRAME_PREFIX:
            return UNKNOWN_PALETTE_EFFECT
        return f"{UNKNOWN_EFFECT_PREFIX}{mode.code.hex()}"

    # ------------------------------------------------------------------ commands

    async def _async_command[T](
        self, action: str, request: Awaitable[T], invalid_key: str = "invalid_effect_code"
    ) -> T:
        """Await a client call, translating its errors for Home Assistant."""
        try:
            return await request
        except CololightRejected as err:
            _LOGGER.warning(
                "Cololight %s: the lamp rejected the request to %s (error code 0x%02x)",
                self.client.host,
                action,
                err.code,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_rejected",
                translation_placeholders={"code": f"0x{err.code:02x}"},
            ) from err
        except CololightError as err:
            _LOGGER.warning("Cololight %s: could not %s: %s", self.client.host, action, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"host": self.client.host},
            ) from err
        except ValueError as err:
            raise validation_error(invalid_key, error=str(err)) from err

    async def _async_send_effect(self, action: str, frames: Sequence[bytes]) -> ModeState:
        return await self._async_command(action, self.client.async_set_effect(frames))

    async def _async_start_effect(self, effect: str) -> ModeState:
        """Start an effect given by its name, or by the name shown for an unknown frame."""
        if (known := self.all_effects.get(effect)) is not None:
            mode = await self._async_send_effect(f"start the effect {effect!r}", known.frames)
            self.last_effect = effect
            return mode
        if (match := _UNKNOWN_EFFECT_RE.match(effect)) is not None:
            frame = bytes.fromhex(match.group(1))
            if frame[0] == 0x00:
                raise validation_error("effect_frame_is_colour", frame=match.group(1))
            mode = await self._async_send_effect(f"start the effect {effect!r}", [frame])
            self.last_effect = None
            return mode
        raise validation_error("unknown_effect", effect=effect)

    def _keep_unknown_palette(self) -> None:
        """Effect "Unknown palette effect": a scene or snapshot of an unidentified palette.

        Its frames are unknown, so it cannot be sent: the mode is left as it is (brightness
        and power are still applied, so that restoring the scene does not fail).
        """
        if self.current_effect_name() != UNKNOWN_PALETTE_EFFECT:
            _LOGGER.warning(
                "Cololight %s: an unidentified palette effect cannot be started again "
                "(the lamp only reports its last frame); the current colour or effect is kept",
                self.client.host,
            )

    async def async_turn_on(
        self,
        brightness_pct: int | None = None,
        rgb: tuple[int, int, int] | None = None,
        effect: str | None = None,
    ) -> None:
        """Turn on, optionally changing brightness, colour or effect (mode first, then power)."""
        async with self._command_lock:
            new_mode: ModeState | None = None
            new_power: PowerState | None = None
            try:
                if effect == EFFECT_OFF:
                    # A scene saved on a static colour gives effect "off" and its colour.
                    new_mode = await self._async_command(
                        "set the colour", self.client.async_set_color(rgb if rgb is not None else self.last_rgb)
                    )
                    self.last_effect = None
                elif effect == UNKNOWN_PALETTE_EFFECT:
                    self._keep_unknown_palette()
                elif effect is not None:
                    new_mode = await self._async_start_effect(effect)
                elif rgb is not None:
                    new_mode = await self._async_command("set the colour", self.client.async_set_color(rgb))
                    self.last_effect = None
                # Read after the mode write: a poll may have updated the state meanwhile.
                power = self.data.power
                if brightness_pct is not None:
                    new_power = await self._async_command("turn on", self.client.async_turn_on(brightness_pct))
                elif not power.on or not power.brightness:
                    new_power = await self._async_command(
                        "turn on", self.client.async_turn_on(self.last_brightness)
                    )
            finally:
                # Publish whatever the lamp acknowledged, even if a later step failed; the
                # rest comes from the latest state, not from a copy taken before the writes.
                if new_mode is not None or new_power is not None:
                    self._apply(
                        CololightData(
                            power=new_power if new_power is not None else self.data.power,
                            mode=new_mode if new_mode is not None else self.data.mode,
                        )
                    )
                    self._schedule_save()

    async def async_turn_off(self) -> None:
        """Turn off. Nothing to store: the power state is never saved."""
        async with self._command_lock:
            power = await self._async_command("turn off", self.client.async_turn_off())
            self._apply(CololightData(power=power, mode=self.data.mode))

    async def async_set_effect_speed(self, speed: int) -> None:
        """Change the speed of the running effect (0 slowest .. 32 fastest)."""
        async with self._command_lock:
            code = self.data.mode.code
            if effect_speed(code) is None:
                raise validation_error("no_adjustable_speed")
            try:
                frame = with_speed(code, speed)
            except ValueError as err:
                raise validation_error("no_adjustable_speed") from err
            mode = await self._async_send_effect("change the effect speed", [frame])
            self._apply(CololightData(power=self.data.power, mode=mode))
            self._schedule_save()

    def _custom_effect_frame(self, scheme: str, color: str, speed: int, mode: int) -> bytes:
        """Frame of a custom effect; ServiceValidationError telling what is wrong."""
        if scheme in CUSTOM_SCHEMES and color not in (colors := scheme_colors(scheme)):
            raise validation_error(
                "unknown_custom_color", color=color, scheme=scheme, colors=_COLOR_SEPARATOR.join(colors)
            )
        if not 1 <= mode <= (count := len(modes_for_model(self.model))):
            raise validation_error("custom_mode_out_of_range", max=str(count))
        try:
            return custom_effect_code(self.model, scheme, color, speed, mode)
        except ValueError as err:
            raise validation_error("invalid_custom_effect", error=str(err)) from err

    async def async_set_custom_effect(self, scheme: str, color: str, speed: int, mode: int) -> None:
        """Start a custom effect (scheme, colour, speed and mode, as in the official app)."""
        frame = self._custom_effect_frame(scheme, color, speed, mode)
        async with self._command_lock:
            new_mode = await self._async_command(
                "start the custom effect", self.client.async_set_effect([frame]), "invalid_custom_effect"
            )
            self.last_effect = None
            self._apply(CololightData(power=self.data.power, mode=new_mode))
            self._schedule_save()

    async def async_set_effect_code(self, frames: Sequence[bytes]) -> None:
        """Send raw effect frames (4 bytes each), in order."""
        async with self._command_lock:
            mode = await self._async_send_effect("send the effect code", frames)
            self.last_effect = None
            self._apply(CololightData(power=self.data.power, mode=mode))
            self._schedule_save()

    # ------------------------------------------------------------------ power-on state (op 07)

    async def async_save_state(self) -> None:
        """Store the current state in the lamp's EEPROM (op 07): it boots with it.

        Explicit save (button, action): it always writes, even a state saved before (the
        official app may have stored another one through the cloud since).
        """
        async with self._command_lock:
            await self._async_save(automatic=False)

    async def _async_save(self, *, automatic: bool) -> None:
        """Store the current state; the caller holds the command lock."""
        power, mode = self.data.power, self.data.mode
        brightness = power.brightness if power.on else None  # a lamp saved "off" would stay dark
        frames: tuple[bytes, ...] | None = (mode.code,)
        if mode.is_multi_frame:
            # The lamp only reports the last frame of a palette effect: send them all, from
            # the effect identified now (never a lone palette frame).
            name = self.current_effect_name()
            known = self.all_effects.get(name) if name is not None else None
            if known is not None and known.is_multi_frame and known.frames[-1] == mode.code:
                frames = known.frames
            elif not automatic:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="cannot_save_unknown_palette")
            else:
                _LOGGER.warning(
                    "Cololight %s: the running palette effect is not identified, so only the "
                    "brightness is stored as power-on state",
                    self.client.host,
                )
                frames = None
        saved: SavedState = (frames, brightness)
        if automatic and saved == self._last_saved:
            _LOGGER.debug("%s: power-on state unchanged, nothing to store", self.client.host)
            return
        if frames is not None and len(frames) > 1:
            await self._async_command(
                "store the effect as power-on state", self.client.async_set_effect(frames, save=True)
            )
        elif frames is not None:
            await self._async_command(
                "store the state as power-on state", self.client.async_save_state(power, mode)
            )
            brightness = None  # stored with the mode
        if brightness is not None:
            await self._async_command(
                "store the brightness as power-on state", self.client.async_turn_on(brightness, save=True)
            )
        self._last_saved = saved
        _LOGGER.debug("%s: state stored as power-on state", self.client.host)

    @callback
    def _schedule_save(self) -> None:
        """(Re)start the debounce timer of the "save as power-on state" option."""
        if not self.save_as_default:
            return
        self._cancel_save_timer()
        self._save_unsub = async_call_later(self.hass, self.save_delay, self._save_timer_fired)

    @callback
    def _save_timer_fired(self, _now: datetime) -> None:
        self._save_unsub = None
        # A task of the entry: cancelled on unload, even while it waits for the lamp.
        self._save_task = self.config_entry.async_create_background_task(
            self.hass, self._async_deferred_save(), f"{DOMAIN} {self.client.host} power-on state save"
        )

    async def _async_deferred_save(self) -> None:
        async with self._command_lock:
            if self._save_unsub is not None:
                # A command ran while this save waited for it, and restarted the delay:
                # what this save would store is already outdated.
                return
            if not self.data.power.on:
                # Turning off changes nothing that is stored; the colour set before is
                # stored after the next turn on.
                _LOGGER.debug("%s: lamp off, power-on state not stored", self.client.host)
                return
            try:
                await self._async_save(automatic=True)
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "Cololight %s: could not store the state as power-on state: %s", self.client.host, err
                )

    @callback
    def _cancel_save_timer(self) -> None:
        if self._save_unsub is not None:
            self._save_unsub()
            self._save_unsub = None

    @callback
    def async_cancel_save(self) -> None:
        """Cancel a pending deferred save, also one already waiting for the lamp."""
        self._cancel_save_timer()
        if self._save_task is not None and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = None

    async def async_shutdown(self) -> None:
        self.async_cancel_save()
        await super().async_shutdown()
