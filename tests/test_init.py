"""Tests for Mikrotik Router integration setup and teardown."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.const import DOMAIN

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 0,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "Mikrotik",
}

ENTRY_OPTIONS = {
    "scan_interval": 30,
    "track_network_hosts_timeout": 180,
    "zone": "home",
}


async def test_setup_entry_sets_runtime_data(hass):
    """async_setup_entry stores coordinator instances in runtime_data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    mock_coord = MagicMock()
    mock_coord.async_config_entry_first_refresh = AsyncMock()
    mock_coord.data = {}

    mock_tracker = MagicMock()
    mock_tracker.async_config_entry_first_refresh = AsyncMock()

    mock_api = MagicMock()
    mock_api.connect.return_value = True
    mock_api.error = ""

    with (
        patch(
            "custom_components.mikrotik_extended.MikrotikAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.mikrotik_extended.MikrotikCoordinator",
            return_value=mock_coord,
        ),
        patch(
            "custom_components.mikrotik_extended.MikrotikTrackerCoordinator",
            return_value=mock_tracker,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", return_value=True),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert hasattr(entry, "runtime_data")
    assert entry.runtime_data.data_coordinator is mock_coord
    assert entry.runtime_data.tracker_coordinator is mock_tracker


async def test_unload_entry(hass):
    """async_unload_entry returns True and cleans up platforms."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    mock_coord = MagicMock()
    mock_coord.async_config_entry_first_refresh = AsyncMock()
    mock_coord.data = {}

    mock_tracker = MagicMock()
    mock_tracker.async_config_entry_first_refresh = AsyncMock()

    mock_api = MagicMock()
    mock_api.connect.return_value = True
    mock_api.error = ""

    with (
        patch(
            "custom_components.mikrotik_extended.MikrotikAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.mikrotik_extended.MikrotikCoordinator",
            return_value=mock_coord,
        ),
        patch(
            "custom_components.mikrotik_extended.MikrotikTrackerCoordinator",
            return_value=mock_tracker,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", return_value=True),
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        unload_result = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert unload_result is True
