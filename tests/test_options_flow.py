"""Tests for Mikrotik Router options flow."""

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    CONF_ZONE,
    STATE_HOME,
)
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.const import (
    CONF_SCAN_INTERVAL,
    CONF_SENSOR_CLIENT_CAPTIVE,
    CONF_SENSOR_CLIENT_TRAFFIC,
    CONF_SENSOR_CONTAINERS,
    CONF_SENSOR_ENVIRONMENT,
    CONF_SENSOR_FILTER,
    CONF_SENSOR_KIDCONTROL,
    CONF_SENSOR_MANGLE,
    CONF_SENSOR_NAT,
    CONF_SENSOR_NETWATCH_TRACKER,
    CONF_SENSOR_PORT_TRACKER,
    CONF_SENSOR_PORT_TRAFFIC,
    CONF_SENSOR_PPP,
    CONF_SENSOR_ROUTING_RULES,
    CONF_SENSOR_SCRIPTS,
    CONF_SENSOR_SIMPLE_QUEUES,
    CONF_SENSOR_WIREGUARD,
    CONF_TRACK_HOSTS,
    CONF_TRACK_HOSTS_TIMEOUT,
    DOMAIN,
)

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 0,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "Mikrotik",
}

INITIAL_OPTIONS = {
    CONF_SCAN_INTERVAL: 30,
    CONF_TRACK_HOSTS_TIMEOUT: 180,
    CONF_ZONE: STATE_HOME,
    CONF_SENSOR_PORT_TRACKER: True,
    CONF_SENSOR_NAT: True,
    CONF_SENSOR_MANGLE: False,
    CONF_SENSOR_FILTER: True,
    CONF_SENSOR_WIREGUARD: False,
    CONF_SENSOR_CONTAINERS: False,
    CONF_SENSOR_PPP: False,
    CONF_SENSOR_KIDCONTROL: False,
    CONF_SENSOR_SCRIPTS: True,
    CONF_SENSOR_ENVIRONMENT: False,
    CONF_SENSOR_NETWATCH_TRACKER: True,
    CONF_SENSOR_PORT_TRAFFIC: False,
    CONF_SENSOR_CLIENT_TRAFFIC: False,
    CONF_SENSOR_CLIENT_CAPTIVE: False,
    CONF_SENSOR_SIMPLE_QUEUES: False,
    CONF_SENSOR_ROUTING_RULES: False,
    CONF_TRACK_HOSTS: False,
}

SENSOR_SELECT_INPUT = {
    CONF_SENSOR_PORT_TRACKER: True,
    CONF_SENSOR_NAT: True,
    CONF_SENSOR_MANGLE: True,
    CONF_SENSOR_FILTER: True,
    CONF_SENSOR_WIREGUARD: False,
    CONF_SENSOR_CONTAINERS: False,
    CONF_SENSOR_PPP: False,
    CONF_SENSOR_KIDCONTROL: False,
    CONF_SENSOR_SCRIPTS: True,
    CONF_SENSOR_ENVIRONMENT: False,
    CONF_SENSOR_NETWATCH_TRACKER: True,
    CONF_SENSOR_PORT_TRAFFIC: False,
    CONF_SENSOR_CLIENT_TRAFFIC: False,
    CONF_SENSOR_CLIENT_CAPTIVE: False,
    CONF_SENSOR_SIMPLE_QUEUES: False,
    CONF_SENSOR_ROUTING_RULES: False,
    CONF_TRACK_HOSTS: False,
}


async def test_options_flow_updates_scan_interval(hass):
    """Options flow saves updated scan_interval and zone."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=INITIAL_OPTIONS,
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    # Step 1: basic_options
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "basic_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 60,
            CONF_TRACK_HOSTS_TIMEOUT: 300,
            CONF_ZONE: "away",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sensor_mode"

    # Step 2: sensor_mode — choose custom
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"sensor_preset": "custom"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sensor_select"

    # Step 3: sensor_select — save
    result = await hass.config_entries.options.async_configure(result["flow_id"], SENSOR_SELECT_INPUT)
    assert result["type"] == FlowResultType.CREATE_ENTRY

    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert entry.options[CONF_TRACK_HOSTS_TIMEOUT] == 300
    assert entry.options[CONF_ZONE] == "away"
    assert entry.options[CONF_SENSOR_MANGLE] is True


async def test_options_flow_sensor_toggle(hass):
    """Options flow can disable sensors that were previously enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=INITIAL_OPTIONS,
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 30,
            CONF_TRACK_HOSTS_TIMEOUT: 180,
            CONF_ZONE: STATE_HOME,
        },
    )

    # sensor_mode — choose custom
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"sensor_preset": "custom"})

    disabled_sensors = {k: False for k in SENSOR_SELECT_INPUT}
    disabled_sensors[CONF_SENSOR_PORT_TRACKER] = True  # keep at least one

    result = await hass.config_entries.options.async_configure(result["flow_id"], disabled_sensors)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SENSOR_NAT] is False
    assert entry.options[CONF_SENSOR_FILTER] is False
