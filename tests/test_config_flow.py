"""Config flow and options flow (config_flow.py).

The LAN scan and the probe are mocked (``mock_discovery`` in conftest.py). Entries created
by a flow are not set up (``mock_setup_entry``): the addresses used here (TEST-NET-1,
192.0.2.x) are never contacted. Reconfiguration and discovery of a configured lamp run
against the emulator, to check that the entry follows the lamp.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.light import ATTR_EFFECT_LIST
from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_IGNORE,
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cololight_local.client import CololightTimeout, DiscoveredDevice
from custom_components.cololight_local.config_flow import entry_title
from custom_components.cololight_local.const import (
    CONF_CUSTOM_EFFECTS,
    CONF_HIDDEN_EFFECTS,
    CONF_SAVE_AS_DEFAULT,
    CONF_SAVE_DELAY,
    DEFAULT_PORT,
    DISCOVERY_TIMEOUT,
    DOMAIN,
)
from custom_components.cololight_local.effects import custom_effect_code
from custom_components.cololight_local.protocol import ProtocolError
from tests.fake_lamp import FakeLamp
from tests.helpers import (
    BROADCAST_ADDRESSES,
    LIGHT_ID,
    MAC,
    OTHER_MAC,
    OTHER_RAW_MAC,
    RAW_MAC,
    SECOND_LAMP_HOST,
    TITLE,
    DiscoveryMocks,
    SetupIntegration,
    coordinator_of,
)

HOST = "192.0.2.10"
OTHER_HOST = "192.0.2.11"
NEW_HOST = "192.0.2.99"
# What Home Assistant 2026.10 logs when a flow reloads an entry that has an update listener.
# (Not just "update listener": asyncio's slow-callback warnings name the listener task.)
DEPRECATION = "should use it for scheduling a reload"


@pytest.fixture
async def mock_setup_entry(hass: HomeAssistant) -> AsyncGenerator[AsyncMock]:
    """Do not set up the entries created by the flows."""
    with (
        patch("custom_components.cololight_local.async_setup_entry", return_value=True) as setup_entry,
        patch("custom_components.cololight_local.async_unload_entry", return_value=True),
    ):
        yield setup_entry
        # Unload while the patches are active (the hass fixture unloads entries afterwards).
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await hass.config_entries.async_unload(entry.entry_id)


def _configured_entry(
    hass: HomeAssistant, mac: str = MAC, host: str = HOST, **kwargs: Any
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=mac,
        title=entry_title(mac),
        data={CONF_HOST: host, CONF_MAC: mac, CONF_MODEL: "strip"},
        **kwargs,
    )
    entry.add_to_hass(hass)
    return entry


def test_entry_title() -> None:
    assert entry_title("4c:11:ae:b1:b6:14") == "Cololight B614"


# ---------------------------------------------------------------------- user / manual


async def test_user_without_discovered_lamp_goes_to_manual(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {}
    mock_discovery.config_flow.assert_awaited_once_with(BROADCAST_ADDRESSES, timeout=DISCOVERY_TIMEOUT)

    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: f" {HOST} "})
    mock_discovery.probe.assert_awaited_once_with(HOST, port=DEFAULT_PORT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device"
    assert result["description_placeholders"] == {CONF_HOST: HOST, CONF_MAC: MAC.upper()}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MODEL: "hexagon"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {CONF_HOST: HOST, CONF_MAC: MAC, CONF_MODEL: "hexagon"}
    assert result["result"].unique_id == MAC
    assert CONF_PORT not in result["data"]
    mock_setup_entry.assert_awaited_once()


async def test_user_picks_a_discovered_lamp(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    configured_mac = "4c:11:ae:00:00:02"
    _configured_entry(hass, mac=configured_mac, host="192.0.2.12")
    mock_discovery.config_flow.return_value = [
        DiscoveredDevice(host=OTHER_HOST, mac=OTHER_RAW_MAC),
        DiscoveredDevice(host=HOST, mac=RAW_MAC),
        DiscoveredDevice(host="192.0.2.12", mac="4C11AE000002"),  # already configured
    ]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    selector = result["data_schema"].schema["device"]
    assert selector.config["translation_key"] == "device"
    assert selector.config["options"] == [
        {"value": MAC, "label": f"{HOST} ({MAC.upper()})"},
        {"value": OTHER_MAC, "label": f"{OTHER_HOST} ({OTHER_MAC.upper()})"},
        {"value": "manual", "label": "manual"},
    ]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": OTHER_MAC})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MODEL: "strip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cololight 0001"
    assert result["data"] == {CONF_HOST: OTHER_HOST, CONF_MAC: OTHER_MAC, CONF_MODEL: "strip"}
    mock_discovery.probe.assert_not_awaited()  # it already answered the scan


async def test_user_chooses_manual_entry(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    mock_discovery.config_flow.return_value = [DiscoveredDevice(host=HOST, mac=RAW_MAC)]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "manual"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


async def test_user_discovery_network_error(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    mock_discovery.config_flow.side_effect = OSError("network is unreachable")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


async def test_user_offers_an_ignored_lamp(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    ignored = _configured_entry(hass, source=SOURCE_IGNORE)
    mock_discovery.config_flow.return_value = [DiscoveredDevice(host=HOST, mac=RAW_MAC)]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": MAC})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MODEL: "strip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entries = hass.config_entries.async_entries(DOMAIN)
    assert [entry.source for entry in entries] == [SOURCE_USER]
    assert ignored.entry_id not in [entry.entry_id for entry in entries]


@pytest.mark.parametrize(
    "error", [CololightTimeout("silent"), ProtocolError("no MAC"), OSError("unreachable")]
)
async def test_manual_cannot_connect(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock, error: Exception
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    mock_discovery.probe.side_effect = error
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "cannot_connect"}

    # Fixed (lamp plugged in): the same flow goes on.
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["step_id"] == "device"


async def test_manual_already_configured_updates_the_address(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=NEW_HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: NEW_HOST})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == NEW_HOST
    mock_setup_entry.assert_not_awaited()


async def test_manual_entry_of_the_new_address_of_an_entry_waiting_for_its_lamp(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The lamp moved while Home Assistant was off; the user adds it again by its new
    address: the entry is set up at once, not at its next retry (up to 10 minutes)."""
    fake_lamp.crashed = True
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: SECOND_LAMP_HOST})
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST
    assert moved_lamp.received
    assert DEPRECATION not in caplog.text


# ---------------------------------------------------------------------- integration discovery


async def test_integration_discovery_creates_entry(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_HOST: HOST, CONF_MAC: MAC},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {CONF_HOST: HOST, CONF_MAC: MAC.upper()}
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["title_placeholders"] == {CONF_NAME: TITLE, CONF_HOST: HOST}
    assert flow["context"]["unique_id"] == MAC

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MODEL: "strip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST, CONF_MAC: MAC, CONF_MODEL: "strip"}
    mock_discovery.probe.assert_not_awaited()


async def test_integration_discovery_accepts_a_raw_mac(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_HOST: HOST, CONF_MAC: RAW_MAC},
    )
    assert result["step_id"] == "discovery_confirm"
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["unique_id"] == MAC


async def test_integration_discovery_already_in_progress(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    data = {CONF_HOST: HOST, CONF_MAC: MAC}
    context = {"source": SOURCE_INTEGRATION_DISCOVERY}
    await hass.config_entries.flow.async_init(DOMAIN, context=context, data=data)
    result = await hass.config_entries.flow.async_init(DOMAIN, context=context, data=data)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"


async def test_integration_discovery_already_configured_updates_the_address(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_HOST: NEW_HOST, CONF_MAC: MAC},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == NEW_HOST


async def test_discovery_sets_up_an_entry_waiting_for_its_lamp(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
    moved_lamp: FakeLamp,
) -> None:
    """The lamp changed address while Home Assistant was off: discovery fixes the entry."""
    fake_lamp.crashed = True
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_HOST: SECOND_LAMP_HOST, CONF_MAC: MAC},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST


async def test_discovery_of_a_loaded_entry_at_a_new_address(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    moved_lamp: FakeLamp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = init_integration
    old = entry.runtime_data
    with patch.object(
        hass.config_entries, "async_schedule_reload", wraps=hass.config_entries.async_schedule_reload
    ) as schedule_reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_HOST: SECOND_LAMP_HOST, CONF_MAC: MAC},
        )
        assert result["reason"] == "already_configured"
        await hass.async_block_till_done()
    schedule_reload.assert_not_called()  # the flow left the reload to the update listener
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old  # reloaded by the update listener
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST
    assert DEPRECATION not in caplog.text


async def test_discovery_of_a_loaded_entry_at_the_same_address(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    entry = init_integration
    old = entry.runtime_data
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_HOST: entry.data[CONF_HOST], CONF_MAC: MAC},
    )
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done()
    assert entry.runtime_data is old  # nothing changed: no reload


# ---------------------------------------------------------------------- DHCP


def _dhcp(ip: str = HOST, mac: str = "4c11aeb1b614") -> DhcpServiceInfo:
    return DhcpServiceInfo(ip=ip, hostname="esp_b1b614", macaddress=mac)


async def test_dhcp_creates_entry(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=_dhcp())
    mock_discovery.probe.assert_awaited_once_with(HOST, port=DEFAULT_PORT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MODEL: "strip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST, CONF_MAC: MAC, CONF_MODEL: "strip"}


@pytest.mark.parametrize(
    "probe",
    [
        {"side_effect": CololightTimeout("silent")},
        {"side_effect": OSError("unreachable")},
        {"side_effect": None, "return_value": DiscoveredDevice(host=HOST, mac=OTHER_RAW_MAC)},
    ],
)
async def test_dhcp_not_a_cololight(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock, probe: dict[str, Any]
) -> None:
    mock_discovery.probe.configure_mock(**probe)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=_dhcp())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_cololight"


async def test_dhcp_already_configured_updates_the_address(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=_dhcp(ip=NEW_HOST)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == NEW_HOST
    mock_discovery.probe.assert_not_awaited()


# ---------------------------------------------------------------------- reconfigure


async def test_reconfigure_loaded_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
    fake_lamp_port: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = init_integration
    old = entry.runtime_data
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    schema = result["data_schema"].schema
    suggested = {str(key): key.description["suggested_value"] for key in schema}
    assert suggested == {CONF_HOST: "127.0.0.1", CONF_MODEL: "strip"}

    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: SECOND_LAMP_HOST, CONF_MODEL: "hexagon"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    mock_discovery.probe.assert_awaited_once_with(SECOND_LAMP_HOST, port=fake_lamp_port)
    await hass.async_block_till_done()

    assert entry.data[CONF_HOST] == SECOND_LAMP_HOST
    assert entry.data[CONF_MODEL] == "hexagon"
    assert entry.data[CONF_PORT] == fake_lamp_port
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST
    assert coordinator_of(entry).model == "hexagon"
    assert "Tron" not in hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]
    assert DEPRECATION not in caplog.text


async def test_reconfigure_without_change_reloads(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_discovery: DiscoveryMocks
) -> None:
    entry = init_integration
    old = entry.runtime_data
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host="127.0.0.1", mac=RAW_MAC)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_MODEL: "strip"}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old


async def test_reconfigure_entry_waiting_for_its_lamp(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    fake_lamp: FakeLamp,
    moved_lamp: FakeLamp,
    mock_discovery: DiscoveryMocks,
) -> None:
    fake_lamp.crashed = True
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=SECOND_LAMP_HOST, mac=RAW_MAC)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: SECOND_LAMP_HOST, CONF_MODEL: "strip"}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client.host == SECOND_LAMP_HOST


async def test_reconfigure_cannot_connect(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {NEW_HOST} ", CONF_MODEL: "hexagon"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    # The form keeps what was typed.
    suggested = {str(key): key.description["suggested_value"] for key in result["data_schema"].schema}
    assert suggested == {CONF_HOST: f" {NEW_HOST} ", CONF_MODEL: "hexagon"}

    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=NEW_HOST, mac=RAW_MAC)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {NEW_HOST} ", CONF_MODEL: "hexagon"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_HOST: NEW_HOST, CONF_MAC: MAC, CONF_MODEL: "hexagon"}
    mock_discovery.probe.assert_awaited_with(NEW_HOST, port=DEFAULT_PORT)


async def test_reconfigure_unique_id_mismatch(
    hass: HomeAssistant, mock_discovery: DiscoveryMocks, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    mock_discovery.probe.side_effect = None
    mock_discovery.probe.return_value = DiscoveredDevice(host=NEW_HOST, mac=OTHER_RAW_MAC)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_MODEL: "strip"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_HOST] == HOST


# ---------------------------------------------------------------------- options flow


async def _open_options(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["settings", "add_custom_effect", "remove_custom_effects"]
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})


async def test_options_settings(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    old = entry.runtime_data
    result = await _open_options(hass, entry, "settings")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    suggested = {str(key): key.description["suggested_value"] for key in result["data_schema"].schema}
    assert suggested == {
        CONF_SCAN_INTERVAL: 10,
        CONF_SAVE_AS_DEFAULT: False,
        CONF_SAVE_DELAY: 30,
        CONF_HIDDEN_EFFECTS: [],
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 30.0,  # number selectors return floats
            CONF_SAVE_AS_DEFAULT: True,
            CONF_SAVE_DELAY: 60.0,
            CONF_HIDDEN_EFFECTS: ["Sunrise", "Tron"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    expected = {
        CONF_SCAN_INTERVAL: 30,
        CONF_SAVE_AS_DEFAULT: True,
        CONF_SAVE_DELAY: 60,
        CONF_HIDDEN_EFFECTS: ["Sunrise", "Tron"],
        CONF_CUSTOM_EFFECTS: {},
    }
    assert result["data"] == expected
    assert dict(entry.options) == expected
    await hass.async_block_till_done()

    # The entry was reloaded with the new options.
    assert entry.runtime_data is not old
    coordinator = coordinator_of(entry)
    assert coordinator.update_interval is not None
    assert coordinator.update_interval.total_seconds() == 30
    assert (coordinator.save_as_default, coordinator.save_delay) == (True, 60)
    effect_list = hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]
    assert "Sunrise" not in effect_list
    assert "Tron" not in effect_list

    # The form shows the current values next time.
    result = await _open_options(hass, entry, "settings")
    suggested = {str(key): key.description["suggested_value"] for key in result["data_schema"].schema}
    assert suggested[CONF_HIDDEN_EFFECTS] == ["Sunrise", "Tron"]
    assert suggested[CONF_SCAN_INTERVAL] == 30


async def test_options_settings_hexagon_effects(hass: HomeAssistant, mock_setup_entry: AsyncMock) -> None:
    entry = _configured_entry(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_MODEL: "hexagon"})
    result = await _open_options(hass, entry, "settings")
    options = result["data_schema"].schema[CONF_HIDDEN_EFFECTS].config["options"]
    assert "Sunrise" in options
    assert "Tron" not in options  # strip only


async def test_options_add_custom_effect(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    result = await _open_options(hass, entry, "add_custom_effect")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "add_custom_effect"
    assert result["description_placeholders"] == {"modes": "13"}
    options = result["data_schema"].schema["scheme_color"].config["options"]
    assert "Mood | Red" in options
    assert "Selected | Sunrise" in options
    assert "Selected | " not in options  # gaps of the table are not offered

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: " Red mood ", "scheme_color": "Mood | Red", "speed": 20.0, "mode": 3.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    code = custom_effect_code("strip", "Mood", "Red", 20, 3).hex()
    assert result["data"][CONF_CUSTOM_EFFECTS] == {
        "Red mood": {"scheme": "Mood", "color": "Red", "speed": 20, "mode": 3, "code": code}
    }
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST][-1] == "Red mood"


async def test_options_add_custom_effect_keeps_other_options(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(
        hass,
        options={
            CONF_SCAN_INTERVAL: 20,
            CONF_HIDDEN_EFFECTS: ["Sunrise"],
            CONF_CUSTOM_EFFECTS: {"Old": {"code": "05b40c10"}},
        },
    )
    result = await _open_options(hass, entry, "add_custom_effect")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "New", "scheme_color": "Breath | Rainbow", "speed": 0, "mode": 1}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_INTERVAL] == 20
    assert result["data"][CONF_HIDDEN_EFFECTS] == ["Sunrise"]
    assert list(result["data"][CONF_CUSTOM_EFFECTS]) == ["Old", "New"]


@pytest.mark.parametrize("name", ["", "   ", "off", "Effect 05b40c10", "Unknown palette effect"])
async def test_options_add_custom_effect_invalid_name(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, name: str
) -> None:
    entry = _configured_entry(hass)
    result = await _open_options(hass, entry, "add_custom_effect")
    user_input = {CONF_NAME: name, "scheme_color": "Mood | Red", "speed": 16, "mode": 1}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "invalid_name"}
    assert entry.options == {}


async def test_options_add_custom_effect_invalid_combination(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    result = await _open_options(hass, entry, "add_custom_effect")
    with patch(
        "custom_components.cololight_local.config_flow.custom_effect_code",
        side_effect=ValueError("mode must be 1-13"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_NAME: "Mine", "scheme_color": "Mood | Red", "speed": 16, "mode": 1}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_custom_effect"}


async def test_options_remove_custom_effects(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    custom = {"A": {"code": "05b40c10"}, "B": {"code": "05b50c10"}, "C": {"code": "05b60c10"}}
    hass.config_entries.async_update_entry(entry, options={CONF_CUSTOM_EFFECTS: custom})
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST][-3:] == ["A", "B", "C"]

    result = await _open_options(hass, entry, "remove_custom_effects")
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"].schema["effects"].config["options"] == ["A", "B", "C"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"effects": ["A", "C"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CUSTOM_EFFECTS] == {"B": {"code": "05b50c10"}}
    await hass.async_block_till_done()
    effect_list = hass.states.get(LIGHT_ID).attributes[ATTR_EFFECT_LIST]
    assert effect_list[-1] == "B"
    assert "A" not in effect_list


async def test_options_remove_without_custom_effects(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    entry = _configured_entry(hass)
    result = await _open_options(hass, entry, "remove_custom_effects")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_custom_effects"
