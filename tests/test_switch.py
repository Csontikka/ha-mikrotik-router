"""Tests for the switch platform."""

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
from custom_components.mikrotik_extended.switch import (
    MikrotikContainerSwitch,
    MikrotikFilterSwitch,
    MikrotikKidcontrolPauseSwitch,
    MikrotikMangleSwitch,
    MikrotikNATSwitch,
    MikrotikPortSwitch,
    MikrotikQueueSwitch,
    MikrotikRoutingRulesSwitch,
    MikrotikSwitch,
    MikrotikWireguardPeerSwitch,
    async_setup_entry,
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
    func="MikrotikSwitch",
    key="k",
    name="N",
    data_path="resource",
    data_attribute="enabled",
    data_reference=None,
    data_name=None,
    data_switch_path="/interface",
    data_switch_parameter="disabled",
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
    desc.data_switch_path = data_switch_path
    desc.data_switch_parameter = data_switch_parameter
    desc.icon_enabled = icon_enabled
    desc.icon_disabled = icon_disabled
    for k, v in extra.items():
        setattr(desc, k, v)
    return desc


def _make_coordinator(hass, data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    coord = MagicMock()
    coord.config_entry = entry
    coord.data = data
    coord.hass = hass
    coord.host = "192.168.88.1"
    coord.set_value = MagicMock()
    coord.execute = MagicMock()
    coord.async_refresh = AsyncMock()
    return coord


async def test_async_setup_entry_dispatcher(hass):
    """async_setup_entry forwards dispatcher containing all 10 switch classes."""
    entry = MagicMock()
    with patch("custom_components.mikrotik_extended.switch.async_add_entities", new=AsyncMock()) as mock_add:
        await async_setup_entry(hass, entry, MagicMock())
    mock_add.assert_awaited_once()
    _, _, dispatcher = mock_add.await_args.args
    assert set(dispatcher.keys()) == {
        "MikrotikSwitch",
        "MikrotikPortSwitch",
        "MikrotikNATSwitch",
        "MikrotikMangleSwitch",
        "MikrotikRoutingRulesSwitch",
        "MikrotikFilterSwitch",
        "MikrotikQueueSwitch",
        "MikrotikKidcontrolPauseSwitch",
        "MikrotikWireguardPeerSwitch",
        "MikrotikContainerSwitch",
    }


async def test_mikrotik_switch_is_on_icon_and_stubs(hass):
    """MikrotikSwitch: is_on/icon reflect data; turn_on/turn_off sync stubs are no-ops."""
    desc = _make_description(data_attribute="enabled", data_reference="name")
    coord = _make_coordinator(hass, {"resource": {"enabled": True, "name": "ether1"}, "access": {"write"}})
    sw = MikrotikSwitch(coord, desc)

    assert sw.is_on is True
    assert sw.icon == "mdi:on"
    sw._data = {"enabled": False, "name": "ether1"}
    assert sw.icon == "mdi:off"

    # Abstract turn_on/turn_off are pass-throughs
    sw.turn_on()
    sw.turn_off()


async def test_mikrotik_switch_async_turn_on_off_access_gated(hass):
    """MikrotikSwitch.async_turn_on/off early-return when 'write' access is missing; otherwise call set_value."""
    desc = _make_description(data_attribute="enabled", data_reference="name")

    coord = _make_coordinator(hass, {"resource": {"enabled": True, "name": "ether1"}, "access": set()})
    sw = MikrotikSwitch(coord, desc)
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord2 = _make_coordinator(hass, {"resource": {"enabled": True, "name": "ether1"}, "access": {"write"}})
    sw2 = MikrotikSwitch(coord2, desc)
    await sw2.async_turn_on()
    await sw2.async_turn_off()
    assert coord2.set_value.call_count == 2
    coord2.async_refresh.assert_awaited()


async def test_port_switch_extra_state_attributes_ether_and_wlan(hass):
    """MikrotikPortSwitch.extra_state_attributes includes DEVICE_ATTRIBUTES_IFACE_ETHER/_SFP or _WIRELESS."""
    desc = _make_description(func="MikrotikPortSwitch", data_path="interface", data_reference="name", data_name="name", data_attribute="enabled")
    iface = {
        "ether1": {
            "name": "ether1",
            "type": "ether",
            "enabled": True,
            "running": True,
            "rate": "1Gbps",
            "status": "link-ok",
            "sfp-shutdown-temperature": "80C",
            "sfp-temperature": "40C",
            "port-mac-address": "AA:BB:CC:DD:EE:FF",
            "about": "",
        }
    }
    coord = _make_coordinator(hass, {"interface": iface, "access": {"write"}})
    sw = MikrotikPortSwitch(coord, desc, uid="ether1")
    attrs = sw.extra_state_attributes
    assert "rate" in attrs
    assert any("sfp" in k for k in attrs)

    # wlan branch
    iface_w = {"wlan1": {"name": "wlan1", "type": "wlan", "enabled": True, "running": True, "ssid": "home-wifi", "port-mac-address": "-", "about": ""}}
    coord2 = _make_coordinator(hass, {"interface": iface_w, "access": {"write"}})
    sw2 = MikrotikPortSwitch(coord2, desc, uid="wlan1")
    attrs2 = sw2.extra_state_attributes
    assert "ssid" in attrs2


async def test_port_switch_icon_branches(hass):
    """MikrotikPortSwitch.icon: running+enabled→enabled; not running→disabled; disabled→lan-disconnect."""
    desc = _make_description(func="MikrotikPortSwitch", data_path="interface", data_reference="name", data_name="name", data_attribute="enabled")
    iface = {"ether1": {"name": "ether1", "type": "ether", "enabled": True, "running": True, "port-mac-address": "AA:BB:CC:DD:EE:FF", "about": ""}}
    coord = _make_coordinator(hass, {"interface": iface, "access": {"write"}})
    sw = MikrotikPortSwitch(coord, desc, uid="ether1")
    assert sw.icon == "mdi:on"

    sw._data["running"] = False
    assert sw.icon == "mdi:off"

    sw._data["enabled"] = False
    assert sw.icon == "mdi:lan-disconnect"


async def test_port_switch_async_turn_on_and_off(hass):
    """MikrotikPortSwitch.async_turn_on/off: write-gated, CAPsMAN abort, normal + poe-out toggling."""
    desc = _make_description(func="MikrotikPortSwitch", data_path="interface", data_reference="name", data_name="name", data_attribute="enabled")
    iface = {
        "ether1": {
            "name": "ether1",
            "type": "ether",
            "enabled": True,
            "running": True,
            "port-mac-address": "AA:BB:CC:DD:EE:FF",
            "about": "",
            "poe-out": "off",
        }
    }
    tracker = MagicMock()
    tracker.async_request_refresh = AsyncMock()
    coord = _make_coordinator(hass, {"interface": iface, "access": {"write"}})
    coord.config_entry.runtime_data = MagicMock(tracker_coordinator=tracker)
    sw = MikrotikPortSwitch(coord, desc, uid="ether1")

    # access missing → noop
    coord.data["access"] = set()
    await sw.async_turn_on()
    coord.set_value.assert_not_called()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    # restore access
    coord.data["access"] = {"write"}

    # CAPsMAN aborts both paths
    sw._data["about"] = "managed by CAPsMAN"
    assert await sw.async_turn_on() == "managed by CAPsMAN"
    assert await sw.async_turn_off() == "managed by CAPsMAN"
    coord.set_value.assert_not_called()

    # Normal turn_on with poe-out off → second call toggles PoE to auto-on
    sw._data["about"] = ""
    sw._data["port-mac-address"] = "AA-BB"  # triggers the '-' branch changing param to 'name'
    await sw.async_turn_on()
    assert coord.set_value.call_count >= 2  # main disable + poe-out auto-on
    tracker.async_request_refresh.assert_awaited()

    # Normal turn_off with poe-out auto-on → extra poe-out off call
    coord.set_value.reset_mock()
    sw._data["poe-out"] = "auto-on"
    await sw.async_turn_off()
    assert coord.set_value.call_count >= 2


async def test_nat_switch_async_turn_on_off(hass):
    """MikrotikNATSwitch turn_on/off matches by uniq-id and calls set_value; early returns w/o access."""
    desc = _make_description(func="MikrotikNATSwitch", data_path="nat", data_reference="uniq-id", data_name="uniq-id")
    uniq = "srcnat,masq,tcp,ether1:80-::"
    nat_data = {
        "r1": {
            ".id": "*1",
            "uniq-id": uniq,
            "chain": "srcnat",
            "action": "masq",
            "protocol": "tcp",
            "in-interface": "ether1",
            "dst-port": "80",
            "out-interface": "",
            "to-addresses": "",
            "to-ports": "",
            "enabled": True,
        }
    }
    coord = _make_coordinator(hass, {"nat": nat_data, "access": set()})
    sw = MikrotikNATSwitch(coord, desc, uid="r1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert coord.set_value.call_count == 2


async def test_mangle_switch_async_turn_on_off(hass):
    """MikrotikMangleSwitch turn_on/off matches by uniq-id; write-gated."""
    desc = _make_description(func="MikrotikMangleSwitch", data_path="mangle", data_reference="uniq-id", data_name="uniq-id")
    uniq = "forward,mark,tcp,1.2.3.4:80-5.6.7.8:443,list1-list2"
    mangle_data = {
        "m1": {
            ".id": "*1",
            "uniq-id": uniq,
            "chain": "forward",
            "action": "mark",
            "protocol": "tcp",
            "src-address": "1.2.3.4",
            "src-port": "80",
            "dst-address": "5.6.7.8",
            "dst-port": "443",
            "src-address-list": "list1",
            "dst-address-list": "list2",
            "enabled": True,
        }
    }
    coord = _make_coordinator(hass, {"mangle": mangle_data, "access": set()})
    sw = MikrotikMangleSwitch(coord, desc, uid="m1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert coord.set_value.call_count == 2


async def test_routing_rules_switch_async_turn_on_off(hass):
    """MikrotikRoutingRulesSwitch turn_on/off matches by uniq-id; write-gated."""
    desc = _make_description(func="MikrotikRoutingRulesSwitch", data_path="routing_rules", data_reference="uniq-id", data_name="uniq-id")
    uniq = "comment,lookup,1.2.3.4,5.6.7.8,main,ether1"
    rr_data = {
        "rr1": {
            ".id": "*1",
            "uniq-id": uniq,
            "comment": "comment",
            "action": "lookup",
            "src-address": "1.2.3.4",
            "dst-address": "5.6.7.8",
            "routing-mark": "main",
            "interface": "ether1",
            "enabled": True,
        }
    }
    coord = _make_coordinator(hass, {"routing_rules": rr_data, "access": set()})
    sw = MikrotikRoutingRulesSwitch(coord, desc, uid="rr1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert coord.set_value.call_count == 2


async def test_filter_switch_async_turn_on_off(hass):
    """MikrotikFilterSwitch turn_on/off matches by uniq-id; write-gated."""
    desc = _make_description(func="MikrotikFilterSwitch", data_path="filter", data_reference="uniq-id", data_name="uniq-id")
    uniq = "forward,drop,tcp,http,ether1,list1:1.2.3.4,srclist:80-ether2,list2:5.6.7.8,dstlist:443"
    fd = {
        "f1": {
            ".id": "*1",
            "uniq-id": uniq,
            "chain": "forward",
            "action": "drop",
            "protocol": "tcp",
            "layer7-protocol": "http",
            "in-interface": "ether1",
            "in-interface-list": "list1",
            "src-address": "1.2.3.4",
            "src-address-list": "srclist",
            "src-port": "80",
            "out-interface": "ether2",
            "out-interface-list": "list2",
            "dst-address": "5.6.7.8",
            "dst-address-list": "dstlist",
            "dst-port": "443",
            "enabled": True,
        }
    }
    coord = _make_coordinator(hass, {"filter": fd, "access": set()})
    sw = MikrotikFilterSwitch(coord, desc, uid="f1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert coord.set_value.call_count == 2


async def test_queue_switch_async_turn_on_off(hass):
    """MikrotikQueueSwitch turn_on/off matches by name; write-gated."""
    desc = _make_description(func="MikrotikQueueSwitch", data_path="queue", data_reference="name", data_name="name")
    queue_data = {"q1": {".id": "*q", "name": "myqueue", "enabled": True}}
    coord = _make_coordinator(hass, {"queue": queue_data, "access": set()})
    sw = MikrotikQueueSwitch(coord, desc, uid="q1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert coord.set_value.call_count == 2


async def test_kidcontrol_pause_switch_async_turn_on_off(hass):
    """MikrotikKidcontrolPauseSwitch.async_turn_on/off calls coordinator.execute with pause/resume."""
    desc = _make_description(func="MikrotikKidcontrolPauseSwitch", data_path="kidcontrol", data_reference="name", data_name="name", data_switch_path="/ip/kid-control")
    kc = {"kid1": {"name": "kid1", "enabled": True}}
    coord = _make_coordinator(hass, {"kidcontrol": kc, "access": set()})
    sw = MikrotikKidcontrolPauseSwitch(coord, desc, uid="kid1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.execute.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    coord.execute.assert_called_with("/ip/kid-control", "resume", "name", "kid1")
    await sw.async_turn_off()
    coord.execute.assert_called_with("/ip/kid-control", "pause", "name", "kid1")


async def test_wireguard_peer_switch_async_turn_on_off(hass):
    """MikrotikWireguardPeerSwitch.async_turn_on/off calls set_value with .id; write-gated."""
    desc = _make_description(func="MikrotikWireguardPeerSwitch", data_path="wireguard_peer", data_reference=".id", data_name=".id", data_switch_path="/interface/wireguard/peers")
    wg = {"p1": {".id": "*p1", "enabled": True}}
    coord = _make_coordinator(hass, {"wireguard_peer": wg, "access": set()})
    sw = MikrotikWireguardPeerSwitch(coord, desc, uid="p1")
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.set_value.assert_not_called()

    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert coord.set_value.call_count == 2


async def test_container_switch_is_on_icon_and_turn_on_off(hass):
    """MikrotikContainerSwitch: is_on reflects status; icon branches; turn_on/off → execute; write-gated."""
    desc = _make_description(func="MikrotikContainerSwitch", data_path="container", data_reference=".id", data_name=".id", data_switch_path="/container")
    cont = {"c1": {".id": "*c1", "status": "running"}}
    coord = _make_coordinator(hass, {"container": cont, "access": set()})
    sw = MikrotikContainerSwitch(coord, desc, uid="c1")

    assert sw.is_on is True
    assert sw.icon == "mdi:on"
    sw._data["status"] = "stopped"
    assert sw.is_on is False
    assert sw.icon == "mdi:off"

    # access missing
    await sw.async_turn_on()
    await sw.async_turn_off()
    coord.execute.assert_not_called()

    # granted
    coord.data["access"] = {"write"}
    await sw.async_turn_on()
    coord.execute.assert_called_with("/container", "start", ".id", "*c1")
    await sw.async_turn_off()
    coord.execute.assert_called_with("/container", "stop", ".id", "*c1")
