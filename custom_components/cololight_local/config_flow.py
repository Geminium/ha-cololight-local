"""Config flow of the Cololight (local) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import network
from homeassistant.components.light import EFFECT_OFF
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.typing import DiscoveryInfoType

from .client import async_discover, async_probe
from .const import (
    CONF_CUSTOM_EFFECTS,
    CONF_HIDDEN_EFFECTS,
    CONF_SAVE_AS_DEFAULT,
    CONF_SAVE_DELAY,
    CUSTOM_CODE,
    CUSTOM_COLOR,
    CUSTOM_MODE,
    CUSTOM_SCHEME,
    CUSTOM_SPEED,
    DEFAULT_CUSTOM_SPEED,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    DEFAULT_SAVE_AS_DEFAULT,
    DEFAULT_SAVE_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DISCOVERY_TIMEOUT,
    DOMAIN,
    MAX_SAVE_DELAY,
    MAX_SCAN_INTERVAL,
    MIN_CUSTOM_MODE,
    MIN_SAVE_DELAY,
    MIN_SCAN_INTERVAL,
    UNKNOWN_EFFECT_PREFIX,
    UNKNOWN_PALETTE_EFFECT,
)
from .effects import (
    CUSTOM_SCHEMES,
    SPEED_MAX,
    SPEED_MIN,
    Model,
    custom_effect_code,
    effects_for_model,
    modes_for_model,
    scheme_colors,
)
from .protocol import CololightError, format_mac

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE = "device"
CONF_SCHEME_COLOR = "scheme_color"
CONF_EFFECTS = "effects"
MANUAL_ENTRY = "manual"
SCHEME_COLOR_SEPARATOR = " | "

MODEL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[model.value for model in Model],
        translation_key=CONF_MODEL,
        mode=SelectSelectorMode.LIST,
    )
)
MODEL_SCHEMA = vol.Schema({vol.Required(CONF_MODEL, default=DEFAULT_MODEL.value): MODEL_SELECTOR})
MANUAL_SCHEMA = vol.Schema({vol.Required(CONF_HOST): TextSelector()})
RECONFIGURE_SCHEMA = vol.Schema(
    {vol.Required(CONF_HOST): TextSelector(), vol.Required(CONF_MODEL): MODEL_SELECTOR}
)


def entry_title(mac: str) -> str:
    """'4c:11:ae:b1:b6:14' -> 'Cololight B614'."""
    return f"Cololight {mac.replace(':', '')[-4:].upper()}"


class CololightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a lamp: picked from a LAN scan, typed by IP, or discovered (scan / DHCP)."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}  # formatted MAC -> IP address
        self._host: str | None = None
        self._mac: str | None = None  # formatted MAC, also the unique id

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CololightOptionsFlow:
        return CololightOptionsFlow()

    # ------------------------------------------------------------------ user

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Scan the LAN and offer the lamps not configured yet, or the manual entry."""
        if user_input is not None:
            choice = user_input[CONF_DEVICE]
            if choice == MANUAL_ENTRY or choice not in self._discovered:
                return await self.async_step_manual()
            await self.async_set_unique_id(choice, raise_on_progress=False)
            self._abort_if_configured(self._discovered[choice])
            self._host, self._mac = self._discovered[choice], choice
            return await self.async_step_device()

        configured = self._async_current_ids(include_ignore=False)
        try:
            addresses = await network.async_get_ipv4_broadcast_addresses(self.hass)
            devices = await async_discover(addresses, timeout=DISCOVERY_TIMEOUT)
        except OSError as err:
            _LOGGER.debug("Discovery failed: %s", err)
            devices = []
        self._discovered = {
            mac: device.host for device in devices if (mac := format_mac(device.mac)) not in configured
        }
        if not self._discovered:
            return await self.async_step_manual()

        options = [
            SelectOptionDict(value=mac, label=f"{host} ({mac.upper()})")
            for mac, host in sorted(self._discovered.items(), key=lambda item: item[1])
        ]
        options.append(SelectOptionDict(value=MANUAL_ENTRY, label=MANUAL_ENTRY))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): SelectSelector(
                        SelectSelectorConfig(
                            options=options, translation_key=CONF_DEVICE, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the IP address and check that a Cololight answers there."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                device = await async_probe(host, port=DEFAULT_PORT)
            except (CololightError, OSError) as err:
                _LOGGER.debug("No Cololight answered at %s: %s", host, err)
                errors["base"] = "cannot_connect"
            else:
                mac = format_mac(device.mac)
                await self.async_set_unique_id(mac, raise_on_progress=False)
                self._abort_if_configured(host)
                self._host, self._mac = host, mac
                return await self.async_step_device()
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(MANUAL_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the model (it sets the effect list), then create the entry."""
        if user_input is not None:
            return self._async_create_entry(user_input[CONF_MODEL])
        return self.async_show_form(
            step_id="device", data_schema=MODEL_SCHEMA, description_placeholders=self._placeholders()
        )

    # ------------------------------------------------------------------ discovery

    async def async_step_integration_discovery(self, discovery_info: DiscoveryInfoType) -> ConfigFlowResult:
        """A lamp answered the background LAN scan."""
        host: str = discovery_info[CONF_HOST]
        mac = format_mac(discovery_info[CONF_MAC])
        await self.async_set_unique_id(mac)
        self._abort_if_configured(host)
        self._host, self._mac = host, mac
        return await self.async_step_discovery_confirm()

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """A device with a Cololight-like MAC got an address: check it is one."""
        host = discovery_info.ip
        mac = format_mac(discovery_info.macaddress)
        await self.async_set_unique_id(mac)
        self._abort_if_configured(host)
        try:
            device = await async_probe(host, port=DEFAULT_PORT)
        except (CololightError, OSError) as err:
            _LOGGER.debug("%s (%s) is not a Cololight: %s", host, mac, err)
            return self.async_abort(reason="not_cololight")
        if format_mac(device.mac) != mac:
            return self.async_abort(reason="not_cololight")
        self._host, self._mac = host, mac
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the discovered lamp and ask for its model."""
        if user_input is not None:
            return self._async_create_entry(user_input[CONF_MODEL])
        assert self._mac is not None
        self.context["title_placeholders"] = {CONF_NAME: entry_title(self._mac), CONF_HOST: self._host or ""}
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=MODEL_SCHEMA,
            description_placeholders=self._placeholders(),
        )

    # ------------------------------------------------------------------ reconfigure

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the address or the model of a configured lamp."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                device = await async_probe(host, port=entry.data.get(CONF_PORT, DEFAULT_PORT))
            except (CololightError, OSError) as err:
                _LOGGER.debug("No Cololight answered at %s: %s", host, err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(format_mac(device.mac))
                self._abort_if_unique_id_mismatch(reason="unique_id_mismatch")
                changed = self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_HOST: host, CONF_MODEL: user_input[CONF_MODEL]}
                )
                # A loaded entry is reloaded by its update listener when it changes
                # (in Home Assistant 2026.10 async_update_reload_and_abort reports a
                # deprecation for entries with an update listener); otherwise reload here.
                if not changed or not entry.update_listeners:
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
        suggested = user_input or {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_MODEL: entry.data.get(CONF_MODEL, DEFAULT_MODEL.value),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(RECONFIGURE_SCHEMA, suggested),
            errors=errors,
        )

    # ------------------------------------------------------------------ helpers

    @callback
    def _abort_if_configured(self, host: str) -> None:
        """Abort if the lamp is configured, storing its (possibly new) address.

        A loaded entry is reloaded by its update listener when the address changed (Home
        Assistant 2026.10 reports a deprecation when a flow reloads an entry that has
        one). An entry without a listener (waiting for a setup retry) is reloaded by Home
        Assistant, from any step: a manual entry of the new address too.
        """
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, self.unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host}, reload_on_update=entry is None or not entry.update_listeners
        )

    def _placeholders(self) -> dict[str, str]:
        return {CONF_HOST: self._host or "", CONF_MAC: (self._mac or "").upper()}

    @callback
    def _async_create_entry(self, model: str) -> ConfigFlowResult:
        assert self._host is not None
        assert self._mac is not None
        return self.async_create_entry(
            title=entry_title(self._mac),
            data={CONF_HOST: self._host, CONF_MAC: self._mac, CONF_MODEL: Model(model).value},
        )


class CololightOptionsFlow(OptionsFlow):
    """Polling, power-on state saving, effect list and custom effects."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "add_custom_effect", "remove_custom_effects"]
        )

    @property
    def _model(self) -> Model:
        return Model(self.config_entry.data.get(CONF_MODEL, DEFAULT_MODEL))

    def _options(self) -> dict[str, Any]:
        """A copy of the current options that can be modified safely."""
        options = dict(self.config_entry.options)
        options[CONF_HIDDEN_EFFECTS] = list(options.get(CONF_HIDDEN_EFFECTS) or [])
        options[CONF_CUSTOM_EFFECTS] = {
            name: dict(spec) for name, spec in (options.get(CONF_CUSTOM_EFFECTS) or {}).items()
        }
        return options

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Polling interval, save as power-on state, hidden effects."""
        options = self._options()
        builtin = list(effects_for_model(self._model))
        if user_input is not None:
            options[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            options[CONF_SAVE_AS_DEFAULT] = bool(user_input[CONF_SAVE_AS_DEFAULT])
            options[CONF_SAVE_DELAY] = int(user_input[CONF_SAVE_DELAY])
            options[CONF_HIDDEN_EFFECTS] = [
                name for name in user_input.get(CONF_HIDDEN_EFFECTS, []) if name in builtin
            ]
            return self.async_create_entry(data=options)

        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_SAVE_AS_DEFAULT, default=DEFAULT_SAVE_AS_DEFAULT): BooleanSelector(),
                vol.Required(CONF_SAVE_DELAY, default=DEFAULT_SAVE_DELAY): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SAVE_DELAY,
                        max=MAX_SAVE_DELAY,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_HIDDEN_EFFECTS, default=[]): SelectSelector(
                    SelectSelectorConfig(options=builtin, multiple=True, mode=SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        suggested = {
            CONF_SCAN_INTERVAL: options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            CONF_SAVE_AS_DEFAULT: options.get(CONF_SAVE_AS_DEFAULT, DEFAULT_SAVE_AS_DEFAULT),
            CONF_SAVE_DELAY: options.get(CONF_SAVE_DELAY, DEFAULT_SAVE_DELAY),
            CONF_HIDDEN_EFFECTS: [name for name in options[CONF_HIDDEN_EFFECTS] if name in builtin],
        }
        return self.async_show_form(
            step_id="settings", data_schema=self.add_suggested_values_to_schema(schema, suggested)
        )

    async def async_step_add_custom_effect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name a custom effect (scheme, colour, speed, mode) so it joins the effect list."""
        model = self._model
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(CONF_NAME, "")).strip()
            scheme, _, color = str(user_input[CONF_SCHEME_COLOR]).partition(SCHEME_COLOR_SEPARATOR)
            speed = int(user_input[CUSTOM_SPEED])
            mode = int(user_input[CUSTOM_MODE])
            if (
                not name
                or name in (EFFECT_OFF, UNKNOWN_PALETTE_EFFECT)
                or name.startswith(UNKNOWN_EFFECT_PREFIX)
            ):
                errors[CONF_NAME] = "invalid_name"
            else:
                try:
                    code = custom_effect_code(model, scheme, color, speed, mode)
                except ValueError as err:
                    _LOGGER.debug("Invalid custom effect %r: %s", name, err)
                    errors["base"] = "invalid_custom_effect"
                else:
                    options = self._options()
                    options[CONF_CUSTOM_EFFECTS][name] = {
                        CUSTOM_SCHEME: scheme,
                        CUSTOM_COLOR: color,
                        CUSTOM_SPEED: speed,
                        CUSTOM_MODE: mode,
                        CUSTOM_CODE: code.hex(),
                    }
                    return self.async_create_entry(data=options)

        scheme_color_options = [
            f"{scheme}{SCHEME_COLOR_SEPARATOR}{color}"
            for scheme in CUSTOM_SCHEMES
            for color in scheme_colors(scheme)
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_SCHEME_COLOR): SelectSelector(
                    SelectSelectorConfig(options=scheme_color_options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CUSTOM_SPEED, default=DEFAULT_CUSTOM_SPEED): NumberSelector(
                    NumberSelectorConfig(min=SPEED_MIN, max=SPEED_MAX, step=1, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Required(CUSTOM_MODE, default=MIN_CUSTOM_MODE): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_CUSTOM_MODE,
                        max=len(modes_for_model(model)),
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="add_custom_effect",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders={"modes": str(len(modes_for_model(model)))},
        )

    async def async_step_remove_custom_effects(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete custom effects."""
        options = self._options()
        custom: dict[str, Any] = options[CONF_CUSTOM_EFFECTS]
        if not custom:
            return self.async_abort(reason="no_custom_effects")
        if user_input is not None:
            for name in user_input.get(CONF_EFFECTS, []):
                custom.pop(name, None)
            return self.async_create_entry(data=options)
        return self.async_show_form(
            step_id="remove_custom_effects",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EFFECTS): SelectSelector(
                        SelectSelectorConfig(
                            options=sorted(custom), multiple=True, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )
