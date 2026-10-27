"""Cololight (local): LifeSmart Cololight lamps over the local UDP protocol."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components import network
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .client import DEFAULT_ACK_TIMEOUT, DEFAULT_RETRY_DELAYS, CololightClient, async_discover
from .const import DEFAULT_MODEL, DEFAULT_PORT, DISCOVERY_INTERVAL, DISCOVERY_TIMEOUT, DOMAIN
from .coordinator import CololightConfigEntry, CololightCoordinator, CololightRuntimeData
from .protocol import format_mac

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.NUMBER, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Timing of the UDP client (docs/findings.md, section 6.2), read when an entry is set
# up. Module attributes so that the tests can shorten them.
ACK_TIMEOUT: float = DEFAULT_ACK_TIMEOUT
RETRY_DELAYS: tuple[float, ...] = DEFAULT_RETRY_DELAYS


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Look for lamps on the LAN once Home Assistant has started, then every 15 minutes.

    Home Assistant only sets up an integration that has a config entry: the first lamp
    is found by DHCP or by the scan of the "Add integration" dialog. Like the core
    integrations doing the same (tplink, wiz...), the scan then runs until shutdown.
    """

    async def _async_scan(_now: datetime | None = None) -> None:
        try:
            addresses = await network.async_get_ipv4_broadcast_addresses(hass)
            devices = await async_discover(addresses, timeout=DISCOVERY_TIMEOUT)
        except OSError as err:
            _LOGGER.debug("Background discovery failed: %s", err)
            return
        for device in devices:
            # The flow aborts by itself for a configured lamp (and updates its address).
            discovery_flow.async_create_flow(
                hass,
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_HOST: device.host, CONF_MAC: format_mac(device.mac)},
            )

    @callback
    def _async_start_scan(_hass: HomeAssistant) -> None:
        hass.async_create_background_task(_async_scan(), f"{DOMAIN} discovery")

    async_at_started(hass, _async_start_scan)
    async_track_time_interval(
        hass, _async_scan, DISCOVERY_INTERVAL, name=f"{DOMAIN} discovery", cancel_on_shutdown=True
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CololightConfigEntry) -> bool:
    """Connect to the lamp; ConfigEntryNotReady (retried later) if it does not answer."""
    client = CololightClient(
        entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        ack_timeout=ACK_TIMEOUT,
        retry_delays=RETRY_DELAYS,
        # Another lamp answering at this address (two lamps swapped their addresses) is
        # a failure, which starts the search of this one by its MAC address.
        expected_mac=entry.data[CONF_MAC],
    )
    coordinator = CololightCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_stop()
        raise
    entry.runtime_data = CololightRuntimeData(client=client, coordinator=coordinator)
    entry.async_on_unload(coordinator.async_cancel_save)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CololightConfigEntry) -> bool:
    """Unload the platforms and close the socket."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data.coordinator.async_cancel_save()
        await entry.runtime_data.client.async_stop()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: CololightConfigEntry) -> None:
    """Reload when the options, the address or the model change.

    This listener is the only place that reloads a loaded entry: in Home Assistant
    2026.10 the config flow helpers report a deprecation when they reload an entry
    that has an update listener. A new address set by the coordinator itself (after
    a rediscovery) is already in use, so it does not trigger a reload.
    """
    runtime = entry.runtime_data
    if (
        dict(entry.options) != runtime.coordinator.options
        or entry.data[CONF_HOST] != runtime.client.host
        or entry.data.get(CONF_MODEL, DEFAULT_MODEL) != runtime.coordinator.model
    ):
        await hass.config_entries.async_reload(entry.entry_id)
