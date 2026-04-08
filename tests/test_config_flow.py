"""Tests for Mikrotik Router config flow."""

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.const import DOMAIN

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "oldpass",
    CONF_PORT: 0,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "Mikrotik",
}

# User step schema requires: name, host, username, password, port, ssl_mode
USER_INPUT = {
    CONF_NAME: "Mikrotik",
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 0,
    "ssl_mode": "none",
}

BASIC_OPTIONS_INPUT = {
    "scan_interval": 30,
    "track_network_hosts_timeout": 180,
    "zone": "home",
}


async def _init_and_skip_discovery(hass):
    """Init flow, pass through discovery step (scan=False), return flow result on 'user' step."""
    with patch(
        "custom_components.mikrotik_extended.config_flow.async_scan_mndp",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "discovery"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": False})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_successful_setup_recommended(hass):
    """Test full config flow with recommended preset — entry is created."""
    with patch("custom_components.mikrotik_extended.config_flow.MikrotikAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.connect.return_value = True
        mock_api.error = None
        mock_api_cls.return_value = mock_api

        result = await _init_and_skip_discovery(hass)

        # Step: user — credentials
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "basic_options"

        # Step: basic_options
        result = await hass.config_entries.flow.async_configure(result["flow_id"], BASIC_OPTIONS_INPUT)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "sensor_mode"

        # Step: sensor_mode — choose recommended preset
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sensor_preset": "recommended"})

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Mikrotik"
        assert result["data"][CONF_HOST] == "192.168.88.1"


async def test_duplicate_entry_aborted(hass):
    """Test config flow aborts when the same host is added a second time."""
    with patch("custom_components.mikrotik_extended.config_flow.MikrotikAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.connect.return_value = True
        mock_api.error = None
        mock_api_cls.return_value = mock_api

        # First entry — full flow
        result = await _init_and_skip_discovery(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], BASIC_OPTIONS_INPUT)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sensor_preset": "recommended"})
        assert result["type"] == FlowResultType.CREATE_ENTRY

        # Second attempt with the same host — should abort
        result2 = await _init_and_skip_discovery(hass)
        result2 = await hass.config_entries.flow.async_configure(result2["flow_id"], USER_INPUT)
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "already_configured"


async def test_connection_failure(hass):
    """Test config flow shows error when router is unreachable."""
    with patch("custom_components.mikrotik_extended.config_flow.MikrotikAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.connect.return_value = False
        mock_api.error = "cannot_connect"
        mock_api_cls.return_value = mock_api

        result = await _init_and_skip_discovery(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

        # Should stay on user step with error
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"][CONF_HOST] == "cannot_connect"


async def test_reauth_flow_success(hass):
    """Reauth flow updates credentials and aborts with reauth_successful."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    with patch("custom_components.mikrotik_extended.config_flow.MikrotikAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.connect.return_value = True
        mock_api.error = None
        mock_api_cls.return_value = mock_api

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "newadmin", CONF_PASSWORD: "newpass"},
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_USERNAME] == "newadmin"
        assert entry.data[CONF_PASSWORD] == "newpass"


async def test_reauth_flow_wrong_credentials(hass):
    """Reauth flow stays on form when credentials are rejected by the router."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    with patch("custom_components.mikrotik_extended.config_flow.MikrotikAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.connect.return_value = False
        mock_api.error = "wrong_login"
        mock_api_cls.return_value = mock_api

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "admin", CONF_PASSWORD: "wrongpass"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"][CONF_PASSWORD] == "wrong_login"
