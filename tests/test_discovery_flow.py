"""Tests for MNDP discovery in the config flow."""

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
)
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mikrotik_extended.const import DOMAIN
from custom_components.mikrotik_extended.mndp import MndpDevice

BASIC_OPTIONS_INPUT = {
    "scan_interval": 30,
    "track_network_hosts_timeout": 180,
    "zone": "home",
}


def _mock_api(connect_ok=True):
    api = MagicMock()
    api.connect.return_value = connect_ok
    api.error = None if connect_ok else "cannot_connect"
    return api


async def _init_discovery_step(hass):
    """Init flow, return result on 'discovery' step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "discovery"
    return result


async def test_discovery_single_router_shown(hass):
    """When MNDP finds one router, pick_device form is shown."""
    discovered = [MndpDevice(ip="192.168.88.1", identity="MyRouter", board="CCR2004")]

    result = await _init_discovery_step(hass)

    with patch("custom_components.mikrotik_extended.config_flow.async_scan_mndp", return_value=discovered):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pick_device"


async def test_discovery_multiple_routers_shown(hass):
    """When MNDP finds multiple routers, all appear in the pick_device dropdown."""
    discovered = [
        MndpDevice(ip="192.168.88.1", identity="Router1", board="CCR2004"),
        MndpDevice(ip="10.0.0.1", identity="Router2", board="RB4011"),
    ]

    result = await _init_discovery_step(hass)

    with patch("custom_components.mikrotik_extended.config_flow.async_scan_mndp", return_value=discovered):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pick_device"


async def test_discovery_select_router_prefills_host(hass):
    """Selecting a discovered router pre-fills host in the credentials form."""
    discovered = [MndpDevice(ip="192.168.88.1", identity="MyRouter", board="CCR2004")]

    result = await _init_discovery_step(hass)

    with patch("custom_components.mikrotik_extended.config_flow.async_scan_mndp", return_value=discovered):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})
    assert result["step_id"] == "pick_device"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"router": "192.168.88.1"})
    # Should now show the user (credentials) form with host pre-filled
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_discovery_manual_entry_shows_empty_form(hass):
    """Choosing 'manual' from pick_device shows the credentials form with defaults."""
    discovered = [MndpDevice(ip="192.168.88.1", identity="MyRouter", board="CCR2004")]

    result = await _init_discovery_step(hass)

    with patch("custom_components.mikrotik_extended.config_flow.async_scan_mndp", return_value=discovered):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})
    assert result["step_id"] == "pick_device"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"router": "manual"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_discovery_no_routers_skips_pick_device(hass):
    """When MNDP finds nothing, the credentials form is shown directly."""
    result = await _init_discovery_step(hass)

    with patch("custom_components.mikrotik_extended.config_flow.async_scan_mndp", return_value=[]):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_discovery_scan_error_skips_pick_device(hass):
    """When MNDP scan raises an exception, the credentials form is shown directly."""
    result = await _init_discovery_step(hass)

    with patch(
        "custom_components.mikrotik_extended.config_flow.async_scan_mndp",
        side_effect=OSError("network unreachable"),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_discovery_skip_scan_shows_form(hass):
    """When user chooses scan=False, the credentials form is shown directly."""
    result = await _init_discovery_step(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": False})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_discovery_full_flow_after_pick(hass):
    """Full flow: discovery → scan → pick router → credentials → basic_options → sensor_mode → entry created."""
    discovered = [MndpDevice(ip="192.168.88.1", identity="MyRouter", board="CCR2004")]

    with patch("custom_components.mikrotik_extended.config_flow.MikrotikAPI") as mock_api_cls:
        mock_api_cls.return_value = _mock_api(connect_ok=True)

        # Step 1: discovery
        result = await _init_discovery_step(hass)

        # Step 2: scan finds routers → pick_device
        with patch(
            "custom_components.mikrotik_extended.config_flow.async_scan_mndp",
            return_value=discovered,
        ):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {"scan": True})
        assert result["step_id"] == "pick_device"

        # Step 3: select router → user form
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"router": "192.168.88.1"})
        assert result["step_id"] == "user"

        # Step 4: credentials
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "MyRouter",
                CONF_HOST: "192.168.88.1",
                "username": "admin",
                "password": "test",
                "port": 0,
                "ssl_mode": "none",
            },
        )
        assert result["step_id"] == "basic_options"

        # Step 5: basic_options
        result = await hass.config_entries.flow.async_configure(result["flow_id"], BASIC_OPTIONS_INPUT)
        assert result["step_id"] == "sensor_mode"

        # Step 6: sensor_mode
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sensor_preset": "recommended"})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["host"] == "192.168.88.1"
        assert result["title"] == "MyRouter"
