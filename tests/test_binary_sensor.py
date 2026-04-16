"""Tests for the binary_sensor platform."""

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

from custom_components.mikrotik_extended.binary_sensor import (
    MikrotikBinarySensor,
    MikrotikPortBinarySensor,
    MikrotikPPPSecretBinarySensor,
    MikrotikWireguardPeerBinarySensor,
    async_setup_entry,
)
from custom_components.mikrotik_extended.const import (
    CONF_SENSOR_PORT_TRACKER,
    CONF_SENSOR_PPP,
    DOMAIN,
)

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 0,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "TestRouter",
}


def _make_description(
    func="MikrotikBinarySensor",
    key="k",
    name="N",
    data_path="resource",
    data_attribute="enabled",
    data_reference=None,
    data_name=None,
    icon_enabled="mdi:on",
    icon_disabled="mdi:off",
    **extra,
):
    desc = MagicMock()
    desc.func = func
    desc.key = key
    desc.name = name
    desc.data_path = data_path
    desc.data_attribute = data_attribute
    desc.data_reference = data_reference
    desc.data_name = data_name
    desc.data_name_comment = False
    desc.data_attributes_list = []
    desc.ha_group = None
    desc.ha_connection = None
    desc.ha_connection_value = None
    desc.entity_registry_enabled_default = True
    desc.icon_enabled = icon_enabled
    desc.icon_disabled = icon_disabled
    for k, v in extra.items():
        setattr(desc, k, v)
    return desc


def _make_coordinator(hass, data, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=options or {},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)
    coord = MagicMock()
    coord.config_entry = entry
    coord.data = data
    return coord


async def test_async_setup_entry_dispatcher(hass):
    """async_setup_entry forwards dispatcher with all 4 binary sensor classes."""
    entry = MagicMock()
    with patch("custom_components.mikrotik_extended.binary_sensor.async_add_entities", new=AsyncMock()) as mock_add:
        await async_setup_entry(hass, entry, MagicMock())
    _, _, dispatcher = mock_add.await_args.args
    assert set(dispatcher.keys()) == {
        "MikrotikBinarySensor",
        "MikrotikPPPSecretBinarySensor",
        "MikrotikPortBinarySensor",
        "MikrotikWireguardPeerBinarySensor",
    }


async def test_binary_sensor_is_on_and_icon(hass):
    """MikrotikBinarySensor: is_on reflects attribute; icon branches on enabled/disabled."""
    desc = _make_description(data_attribute="enabled")
    coord = _make_coordinator(hass, {"resource": {"enabled": True}})
    bs = MikrotikBinarySensor(coord, desc)
    assert bs.is_on is True
    assert bs.icon == "mdi:on"
    bs._data = {"enabled": False}
    assert bs.icon == "mdi:off"

    # When no icon_enabled configured, icon returns None
    desc2 = _make_description(data_attribute="enabled", icon_enabled=None)
    coord2 = _make_coordinator(hass, {"resource": {"enabled": True}})
    bs2 = MikrotikBinarySensor(coord2, desc2)
    assert bs2.icon is None


async def test_ppp_secret_is_on_respects_option(hass):
    """MikrotikPPPSecretBinarySensor.is_on returns False when sensor_ppp option is disabled."""
    desc = _make_description(func="MikrotikPPPSecretBinarySensor", data_attribute="connected")
    # sensor_ppp disabled → is_on is False
    coord = _make_coordinator(hass, {"resource": {"connected": True}}, options={CONF_SENSOR_PPP: False})
    bs = MikrotikPPPSecretBinarySensor(coord, desc)
    assert bs.is_on is False

    # sensor_ppp enabled → value from data
    coord2 = _make_coordinator(hass, {"resource": {"connected": True}}, options={CONF_SENSOR_PPP: True})
    bs2 = MikrotikPPPSecretBinarySensor(coord2, desc)
    assert bs2.is_on is True


async def test_port_binary_sensor_option_and_icon_and_attrs(hass):
    """MikrotikPortBinarySensor: option property, icon branches, extra_state_attributes ether/wlan."""
    desc = _make_description(
        func="MikrotikPortBinarySensor",
        data_path="interface",
        data_reference="name",
        data_name="name",
        data_attribute="running",
    )
    iface = {
        "ether1": {
            "name": "ether1",
            "type": "ether",
            "running": True,
            "enabled": True,
            "rate": "1Gbps",
            "status": "link-ok",
            "sfp-shutdown-temperature": "80C",
            "sfp-temperature": "40C",
        }
    }
    coord = _make_coordinator(
        hass,
        {"interface": iface},
        options={CONF_SENSOR_PORT_TRACKER: True},
    )
    bs = MikrotikPortBinarySensor(coord, desc, uid="ether1")

    # option flag
    assert bs.option_sensor_port_tracker is True

    # icon running+enabled → enabled; running=False → disabled; enabled=False → mdi:lan-disconnect
    assert bs.icon == "mdi:on"
    bs._data["running"] = False
    assert bs.icon == "mdi:off"
    bs._data["enabled"] = False
    assert bs.icon == "mdi:lan-disconnect"

    # extra_state_attributes: ether branch + SFP
    bs._data["running"] = True
    bs._data["enabled"] = True
    attrs = bs.extra_state_attributes
    assert "rate" in attrs
    assert any("sfp" in k for k in attrs)

    # wlan branch
    iface_w = {"wlan1": {"name": "wlan1", "type": "wlan", "running": True, "enabled": True, "ssid": "home-wifi"}}
    coord2 = _make_coordinator(hass, {"interface": iface_w}, options={CONF_SENSOR_PORT_TRACKER: True})
    bs2 = MikrotikPortBinarySensor(coord2, desc, uid="wlan1")
    attrs2 = bs2.extra_state_attributes
    assert "ssid" in attrs2


async def test_wireguard_peer_binary_sensor_is_on(hass):
    """MikrotikWireguardPeerBinarySensor.is_on uses 'connected' from _data (default False)."""
    desc = _make_description(
        func="MikrotikWireguardPeerBinarySensor",
        data_path="wireguard_peer",
        data_reference=".id",
        data_name=".id",
        data_attribute="connected",
    )
    wg = {"p1": {".id": "*p1", "connected": True}}
    coord = _make_coordinator(hass, {"wireguard_peer": wg})
    bs = MikrotikWireguardPeerBinarySensor(coord, desc, uid="p1")
    assert bs.is_on is True

    bs._data = {".id": "*p1"}  # no connected key → default False
    assert bs.is_on is False
