"""Setup, unload, reload and background discovery (custom_components/cololight_local/__init__.py)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.components.light import ATTR_EFFECT_LIST
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_ON,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.cololight_local.client import CololightClient, DiscoveredDevice
from custom_components.cololight_local.const import DISCOVERY_INTERVAL, DISCOVERY_TIMEOUT, DOMAIN
from tests.fake_lamp import FakeLamp
from tests.helpers import (
    ACK_TIMEOUT,
    BROADCAST_ADDRESSES,
    LAMP_HOST,
    LIGHT_ID,
    MAC,
    OTHER_MAC,
    OTHER_RAW_MAC,
    RAW_MAC,
    RETRY_DELAYS,
    SAVE_BUTTON_ID,
    SECOND_LAMP_HOST,
    SPEED_ID,
    TITLE,
    DiscoveryMocks,
    SetupIntegration,
)


async def test_setup_creates_device_and_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_lamp_port: int,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    entry = init_integration
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, MAC)}
    assert device.connections == {(dr.CONNECTION_NETWORK_MAC, MAC)}
    assert device.manufacturer == "LifeSmart"
    assert device.model == "Cololight Strip"
    assert device.name == TITLE

    expected = {LIGHT_ID: MAC, SPEED_ID: f"{MAC}_effect_speed", SAVE_BUTTON_ID: f"{MAC}_save_state"}
    for entity_id, unique_id in expected.items():
        registered = entity_registry.async_get(entity_id)
        assert registered is not None, entity_id
        assert registered.unique_id == unique_id
        assert registered.device_id == device.id
        assert registered.config_entry_id == entry.entry_id
    assert entity_registry.async_get(SAVE_BUTTON_ID).entity_category is EntityCategory.CONFIG
    assert hass.states.get(LIGHT_ID).state == STATE_ON

    runtime = entry.runtime_data
    assert (runtime.client.host, runtime.client.port) == (LAMP_HOST, fake_lamp_port)
    assert runtime.coordinator.client is runtime.client
    assert runtime.coordinator.update_interval == timedelta(seconds=10)
    # The client got the (shortened) timing of the module attributes.
    assert runtime.client._ack_timeout == ACK_TIMEOUT
    assert runtime.client._retry_delays == RETRY_DELAYS
    # It refuses replies from another lamp (two lamps that swapped their addresses).
    assert runtime.client._expected_mac == RAW_MAC


async def test_hexagon_device_model(
    hass: HomeAssistant, setup_integration: SetupIntegration, device_registry: dr.DeviceRegistry
) -> None:
    entry = await setup_integration(**{CONF_MODEL: "hexagon"})
    (device,) = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert device.model == "Cololight Hexagon"
    assert "Tron" not in hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]


async def test_unload_stops_the_client(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    client = entry.runtime_data.client
    assert client._transport is not None
    with patch.object(client, "async_stop", wraps=client.async_stop) as stop:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    stop.assert_awaited_once()
    assert client._transport is None
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(LIGHT_ID).state == STATE_UNAVAILABLE


async def test_setup_retry_when_lamp_silent(
    hass: HomeAssistant, setup_integration: SetupIntegration, fake_lamp: FakeLamp
) -> None:
    fake_lamp.crashed = True
    stopped: list[CololightClient] = []
    original_stop = CololightClient.async_stop

    async def _spy_stop(self: CololightClient) -> None:
        stopped.append(self)
        await original_stop(self)

    with patch.object(CololightClient, "async_stop", _spy_stop):
        entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert fake_lamp.received  # it did try
    assert len(stopped) == 1  # the socket of the failed attempt is closed
    assert stopped[0]._transport is None
    assert hass.states.get(LIGHT_ID) is None

    # The lamp answers again: the scheduled retry sets the entry up.
    fake_lamp.crashed = False
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(LIGHT_ID).state == STATE_ON


async def test_options_change_reloads(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    old = entry.runtime_data
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 30})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old
    assert entry.runtime_data.coordinator.update_interval == timedelta(seconds=30)
    assert old.client._transport is None  # the old socket was closed


async def test_model_change_reloads(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    old = entry.runtime_data
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_MODEL: "hexagon"})
    await hass.async_block_till_done()
    assert entry.runtime_data is not old
    assert entry.runtime_data.coordinator.model == "hexagon"
    assert "Tron" not in hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]


async def test_host_change_reloads(
    hass: HomeAssistant, init_integration: MockConfigEntry, moved_lamp: FakeLamp
) -> None:
    entry = init_integration
    old = entry.runtime_data
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HOST: SECOND_LAMP_HOST})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST
    assert moved_lamp.received  # the new client read the lamp at its new address


async def test_title_change_does_not_reload(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    old = entry.runtime_data
    hass.config_entries.async_update_entry(entry, title="Living room")
    await hass.async_block_till_done()
    assert entry.runtime_data is old


async def test_background_discovery_creates_flows(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks
) -> None:
    mock_discovery.background.return_value = [DiscoveredDevice(host="192.0.2.10", mac=OTHER_RAW_MAC)]
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_discovery.background.assert_awaited_once_with(BROADCAST_ADDRESSES, timeout=DISCOVERY_TIMEOUT)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    assert flows[0]["context"]["unique_id"] == OTHER_MAC
    assert flows[0]["step_id"] == "discovery_confirm"

    # Scanned again 15 minutes later; the lamp is not offered twice.
    async_fire_time_changed(hass, dt_util.utcnow() + DISCOVERY_INTERVAL)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_discovery.background.await_count == 2
    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == 1


async def test_background_discovery_waits_for_start(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks
) -> None:
    hass.set_state(CoreState.starting)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_discovery.background.assert_not_awaited()

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_discovery.background.assert_awaited_once()


async def test_background_discovery_network_error(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks
) -> None:
    mock_discovery.background.side_effect = OSError("network is unreachable")
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_discovery.background.assert_awaited_once()
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_background_discovery_follows_a_configured_lamp(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
) -> None:
    """The scan finds a configured lamp at a new address: the entry follows it (reload)."""
    entry = init_integration
    old = entry.runtime_data
    mock_discovery.background.return_value = [DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC)]
    async_fire_time_changed(hass, dt_util.utcnow() + DISCOVERY_INTERVAL)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST
    assert hass.states.get(LIGHT_ID).state == STATE_ON
