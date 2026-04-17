"""Tests for MikrotikEntity base class and async_add_entities."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.const import DOMAIN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 8728,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "TestRouter",
}

ENTRY_OPTIONS = {
    "scan_interval": 30,
    "track_network_hosts_timeout": 180,
    "zone": "home",
}


def _make_entity_description(
    data_path="resource",
    data_attribute="cpu-load",
    data_reference=None,
    data_name=None,
    data_name_comment=False,
    name="CPU Load",
    key="cpu_load",
    ha_group="System",
    ha_connection=None,
    ha_connection_value=None,
    func="MikrotikSensor",
    data_attributes_list=None,
    entity_registry_enabled_default=True,
    enable_on_option=None,
):
    desc = MagicMock()
    desc.data_path = data_path
    desc.data_attribute = data_attribute
    desc.data_reference = data_reference
    desc.data_name = data_name
    desc.data_name_comment = data_name_comment
    desc.name = name
    desc.key = key
    desc.ha_group = ha_group
    desc.ha_connection = ha_connection
    desc.ha_connection_value = ha_connection_value
    desc.func = func
    desc.data_attributes_list = data_attributes_list or []
    desc.entity_registry_enabled_default = entity_registry_enabled_default
    desc.enable_on_option = enable_on_option
    return desc


def _make_coordinator(hass, data=None):
    """Return a MagicMock coordinator with the given data dict."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.config_entry = entry
    coordinator.data = data or {}
    coordinator.hass = hass
    return coordinator


def _make_entity(coordinator, entity_description, uid=None):
    """Instantiate a MikrotikEntity subclass for testing."""
    from custom_components.mikrotik_extended.entity import MikrotikEntity

    class _TestEntity(MikrotikEntity):
        """Minimal concrete subclass."""

        @property
        def state(self):
            return self._data.get(self.entity_description.data_attribute)

    return _TestEntity(coordinator, entity_description, uid=uid)


# ---------------------------------------------------------------------------
# _skip_sensor — exercise all skip branches in this file so coverage of
# entity.py reaches ≥95% even without loading test_skip_sensor.py
# ---------------------------------------------------------------------------


class TestSkipSensor:
    def _desc(self, func="X", data_path="path", data_attribute="attr"):
        d = MagicMock()
        d.func = func
        d.data_path = data_path
        d.data_attribute = data_attribute
        return d

    def _entry(self, **options):
        e = MagicMock()
        e.options = options
        return e

    def test_traffic_sensor_skipped_when_option_disabled(self):
        from custom_components.mikrotik_extended.const import CONF_SENSOR_PORT_TRAFFIC
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert (
            _skip_sensor(
                self._entry(**{CONF_SENSOR_PORT_TRAFFIC: False}),
                self._desc(func="MikrotikInterfaceTrafficSensor"),
                {"e0": {"type": "ether"}},
                "e0",
            )
            is True
        )

    def test_traffic_sensor_skipped_for_bridge(self):
        from custom_components.mikrotik_extended.const import CONF_SENSOR_PORT_TRAFFIC
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert (
            _skip_sensor(
                self._entry(**{CONF_SENSOR_PORT_TRAFFIC: True}),
                self._desc(func="MikrotikInterfaceTrafficSensor"),
                {"b0": {"type": "bridge"}},
                "b0",
            )
            is True
        )

    def test_client_traffic_skipped_when_unavailable(self):
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert _skip_sensor(self._entry(), self._desc(data_path="client_traffic", data_attribute="tx"), {"c": {"available": False}}, "c") is True

    def test_client_traffic_skipped_when_attribute_missing(self):
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert _skip_sensor(self._entry(), self._desc(data_path="client_traffic", data_attribute="tx"), {"c": {"available": True}}, "c") is True

    def test_port_binary_wlan_skipped(self):
        from custom_components.mikrotik_extended.const import CONF_SENSOR_PORT_TRACKER
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert (
            _skip_sensor(
                self._entry(**{CONF_SENSOR_PORT_TRACKER: True}),
                self._desc(func="MikrotikPortBinarySensor"),
                {"w": {"type": "wlan"}},
                "w",
            )
            is True
        )

    def test_port_binary_skipped_when_tracker_disabled(self):
        from custom_components.mikrotik_extended.const import CONF_SENSOR_PORT_TRACKER
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert (
            _skip_sensor(
                self._entry(**{CONF_SENSOR_PORT_TRACKER: False}),
                self._desc(func="MikrotikPortBinarySensor"),
                {"e": {"type": "ether"}},
                "e",
            )
            is True
        )

    def test_netwatch_skipped_when_disabled(self):
        from custom_components.mikrotik_extended.const import CONF_SENSOR_NETWATCH_TRACKER
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert _skip_sensor(self._entry(**{CONF_SENSOR_NETWATCH_TRACKER: False}), self._desc(data_path="netwatch"), {"n": {}}, "n") is True

    def test_host_tracker_skipped_when_disabled(self):
        from custom_components.mikrotik_extended.const import CONF_TRACK_HOSTS
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert _skip_sensor(self._entry(**{CONF_TRACK_HOSTS: False}), self._desc(func="MikrotikHostDeviceTracker"), {"h": {}}, "h") is True

    def test_default_no_skip(self):
        from custom_components.mikrotik_extended.entity import _skip_sensor

        assert _skip_sensor(self._entry(), self._desc(func="OtherFunc"), {"u": {}}, "u") is False


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestMikrotikEntityConstruction:
    def test_flat_entity_sets_data_from_path(self, hass):
        """Entity without uid stores path-level dict in _data."""
        desc = _make_entity_description(data_path="resource")
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 42}})
        entity = _make_entity(coord, desc, uid=None)
        assert entity._data == {"cpu-load": 42}

    def test_uid_entity_sets_data_from_nested_path(self, hass):
        """Entity with uid stores uid-level dict in _data."""
        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        coord = _make_coordinator(
            hass,
            data={"interface": {"ether1": {"name": "ether1", "type": "ether"}}},
        )
        entity = _make_entity(coord, desc, uid="ether1")
        assert entity._data == {"name": "ether1", "type": "ether"}

    def test_inst_taken_from_config_entry_name(self, hass):
        desc = _make_entity_description()
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc)
        assert entity._inst == "TestRouter"


# ---------------------------------------------------------------------------
# _handle_coordinator_update
# ---------------------------------------------------------------------------


class TestHandleCoordinatorUpdate:
    def test_updates_data_when_path_and_uid_present(self, hass):
        """_handle_coordinator_update refreshes _data when uid is in path_data."""
        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        coord = _make_coordinator(hass, data={"interface": {"ether1": {"name": "ether1", "running": True}}})
        entity = _make_entity(coord, desc, uid="ether1")
        assert entity._data["running"] is True

        # Update coordinator data
        coord.data = {"interface": {"ether1": {"name": "ether1", "running": False}}}

        # Just call it directly, catching the super() call
        with contextlib.suppress(Exception):
            entity._handle_coordinator_update()

        assert entity._data["running"] is False

    def test_returns_early_when_data_path_missing(self, hass):
        """_handle_coordinator_update returns early when path_data is None."""
        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        coord = _make_coordinator(hass, data={"interface": {"ether1": {"name": "ether1"}}})
        entity = _make_entity(coord, desc, uid="ether1")

        original_data = dict(entity._data)
        coord.data = {}  # Remove the path

        with contextlib.suppress(Exception):
            entity._handle_coordinator_update()

        # _data should not have changed
        assert entity._data == original_data

    def test_returns_early_when_uid_not_in_path_data(self, hass):
        """_handle_coordinator_update returns early when uid is missing from path_data."""
        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        coord = _make_coordinator(hass, data={"interface": {"ether1": {"name": "ether1"}}})
        entity = _make_entity(coord, desc, uid="ether1")

        original_data = dict(entity._data)
        coord.data = {"interface": {}}  # uid gone

        with contextlib.suppress(Exception):
            entity._handle_coordinator_update()

        assert entity._data == original_data

    def test_updates_flat_data_without_uid(self, hass):
        """_handle_coordinator_update updates _data correctly when uid is None."""
        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 10}})
        entity = _make_entity(coord, desc, uid=None)

        coord.data = {"resource": {"cpu-load": 99}}

        with contextlib.suppress(Exception):
            entity._handle_coordinator_update()

        assert entity._data["cpu-load"] == 99

    def test_calls_super_when_update_succeeds(self, hass):
        """super()._handle_coordinator_update() called when data is valid."""
        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 5}})
        entity = _make_entity(coord, desc, uid=None)

        coord.data = {"resource": {"cpu-load": 20}}

        with patch.object(type(entity), "async_write_ha_state", return_value=None):
            entity._handle_coordinator_update()

        assert entity._data["cpu-load"] == 20


# ---------------------------------------------------------------------------
# custom_name property
# ---------------------------------------------------------------------------


class TestCustomName:
    def test_returns_entity_description_name_for_flat_entity(self, hass):
        desc = _make_entity_description(name="Uptime", data_path="resource")
        coord = _make_coordinator(hass, data={"resource": {"uptime": "1d"}})
        entity = _make_entity(coord, desc, uid=None)
        assert entity.custom_name == "Uptime"

    def test_comment_overrides_name_when_data_name_comment_true(self, hass):
        """When data_name_comment=True and data has comment, name is 'comment name'."""
        desc = _make_entity_description(
            name="Rule",
            data_path="nat",
            data_name_comment=True,
        )
        coord = _make_coordinator(hass, data={"nat": {"comment": "MyRule"}})
        entity = _make_entity(coord, desc, uid=None)
        assert entity.custom_name == "MyRule Rule"

    def test_comment_only_when_no_entity_description_name(self, hass):
        desc = _make_entity_description(
            name=None,
            data_path="nat",
            data_name_comment=True,
        )
        coord = _make_coordinator(hass, data={"nat": {"comment": "JustComment"}})
        entity = _make_entity(coord, desc, uid=None)
        assert entity.custom_name == "JustComment"

    def test_name_without_comment(self, hass):
        desc = _make_entity_description(
            name="Rule",
            data_path="nat",
            data_name_comment=True,
        )
        coord = _make_coordinator(hass, data={"nat": {"action": "accept"}})
        entity = _make_entity(coord, desc, uid=None)
        assert entity.custom_name == "Rule"

    def test_uid_entity_with_matching_reference_and_name(self, hass):
        """When data_reference == data_name, just return entity_description.name."""
        desc = _make_entity_description(
            name="Status",
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        coord = _make_coordinator(hass, data={"interface": {"ether1": {"name": "ether1"}}})
        entity = _make_entity(coord, desc, uid="ether1")
        assert entity.custom_name == "Status"

    def test_uid_entity_with_different_reference_and_name(self, hass):
        """When data_reference != data_name, prefix with data_name value."""
        desc = _make_entity_description(
            name="TX",
            data_path="interface",
            data_reference="default-name",
            data_name="name",
        )
        coord = _make_coordinator(
            hass,
            data={"interface": {"ether1": {"name": "LAN", "default-name": "ether1"}}},
        )
        entity = _make_entity(coord, desc, uid="ether1")
        assert entity.custom_name == "LAN TX"

    def test_uid_entity_with_comment_and_description_name(self, hass):
        """UID entity with data_name_comment=True and comment present + description name."""
        desc = _make_entity_description(
            name="Rule",
            data_path="nat",
            data_reference="chain",
            data_name="chain",
            data_name_comment=True,
        )
        coord = _make_coordinator(
            hass,
            data={"nat": {"u1": {"chain": "srcnat", "comment": "LANMasq"}}},
        )
        entity = _make_entity(coord, desc, uid="u1")
        assert entity.custom_name == "LANMasq Rule"

    def test_uid_entity_with_comment_no_description_name(self, hass):
        """UID entity with data_name_comment=True, comment present, name=None."""
        desc = _make_entity_description(
            name=None,
            data_path="nat",
            data_reference="chain",
            data_name="chain",
            data_name_comment=True,
        )
        coord = _make_coordinator(
            hass,
            data={"nat": {"u1": {"chain": "srcnat", "comment": "OnlyComment"}}},
        )
        entity = _make_entity(coord, desc, uid="u1")
        assert entity.custom_name == "OnlyComment"

    def test_uid_entity_without_description_name_returns_data_name(self, hass):
        """UID entity with no description name, no comment → data_name value."""
        desc = _make_entity_description(
            name=None,
            data_path="interface",
            data_reference="name",
            data_name="name",
            data_name_comment=False,
        )
        coord = _make_coordinator(
            hass,
            data={"interface": {"ether1": {"name": "ether1"}}},
        )
        entity = _make_entity(coord, desc, uid="ether1")
        assert entity.custom_name == "ether1"


# ---------------------------------------------------------------------------
# unique_id property
# ---------------------------------------------------------------------------


class TestUniqueId:
    def test_unique_id_without_uid(self, hass):
        desc = _make_entity_description(key="cpu_load", data_path="resource")
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc, uid=None)
        entry_id = coord.config_entry.entry_id
        assert entity.unique_id == f"{entry_id}-cpu_load"

    def test_unique_id_with_uid_uses_data_reference(self, hass):
        desc = _make_entity_description(
            key="iface_status",
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        coord = _make_coordinator(
            hass,
            data={"interface": {"ether1": {"name": "ether1", "type": "ether"}}},
        )
        entity = _make_entity(coord, desc, uid="ether1")
        entry_id = coord.config_entry.entry_id
        assert entity.unique_id == f"{entry_id}-iface_status-ether1"

    def test_unique_id_does_not_contain_inst_name(self, hass):
        """unique_id should use entry_id, not the config entry name."""
        desc = _make_entity_description(key="cpu_load", data_path="resource")
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc, uid=None)
        assert "testrouter" not in entity.unique_id
        assert coord.config_entry.entry_id in entity.unique_id


# ---------------------------------------------------------------------------
# entity_registry_enabled_default
# ---------------------------------------------------------------------------


class TestEntityRegistryEnabledDefault:
    def test_returns_true_when_desc_flag_true(self, hass):
        desc = _make_entity_description(entity_registry_enabled_default=True)
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc)
        assert entity.entity_registry_enabled_default is True

    def test_returns_true_when_option_enabled(self, hass):
        """When desc flag=False but option is True, enabled by default."""
        desc = _make_entity_description(
            entity_registry_enabled_default=False,
            enable_on_option="my_option",
        )
        # Build an entry that already has the option enabled
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options={**ENTRY_OPTIONS, "my_option": True},
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)
        coord = MagicMock()
        coord.config_entry = entry
        coord.data = {"resource": {"cpu-load": 0}}
        coord.hass = hass
        entity = _make_entity(coord, desc)
        assert entity.entity_registry_enabled_default is True

    def test_returns_false_when_option_missing(self, hass):
        """When desc flag=False and option is absent/False, disabled by default."""
        desc = _make_entity_description(
            entity_registry_enabled_default=False,
            enable_on_option="my_option",
        )
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc)
        assert entity.entity_registry_enabled_default is False

    def test_returns_false_when_no_enable_on_option(self, hass):
        """When desc flag=False and no enable_on_option, disabled by default."""
        desc = _make_entity_description(
            entity_registry_enabled_default=False,
            enable_on_option=None,
        )
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc)
        assert entity.entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# device_info
# ---------------------------------------------------------------------------


class TestDeviceInfo:
    def test_system_group_returns_router_core(self, hass):
        """ha_group == 'System' returns the System DeviceInfo."""
        desc = _make_entity_description(
            ha_group="System",
            data_reference="serial-number",
            data_path="resource",
        )
        coord = _make_coordinator(
            hass,
            data={
                "resource": {
                    "cpu-load": 0,
                    "board-name": "RB5009",
                    "platform": "MikroTik",
                    "version": "7.1",
                },
                "routerboard": {"serial-number": "ABC123"},
            },
        )
        entity = _make_entity(coord, desc)
        info = entity.device_info
        assert "router Core" in info["name"]
        assert info["model"] == "RB5009"
        assert info["manufacturer"] == "MikroTik"
        assert info["sw_version"] == "7.1"
        assert info["configuration_url"].startswith("http://")

    def test_mac_address_reference_uses_host_lookup(self, hass):
        """When data_reference contains 'mac-address' and the literal key is in host data."""
        desc = _make_entity_description(
            ha_group="Port",
            data_reference="mac-address",
            data_name="name",
            data_path="interface",
        )
        coord = _make_coordinator(
            hass,
            data={
                "interface": {
                    "ether1": {
                        "name": "ether1",
                        "mac-address": "AA:BB:CC:DD:EE:FF",
                        "type": "ether",
                    }
                },
                # The code looks up self.entity_description.data_reference (literal "mac-address")
                # as a key in coordinator.data["host"], so the host dict key must match.
                "host": {
                    "mac-address": {
                        "host-name": "my-laptop",
                        "manufacturer": "Apple",
                    }
                },
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="ether1")
        info = entity.device_info
        assert info["default_name"] == "my-laptop"
        assert info["default_manufacturer"] == "Apple"

    def test_mac_address_reference_no_host_lookup(self, hass):
        """When data_reference contains 'mac-address' but host lookup missing."""
        desc = _make_entity_description(
            ha_group="Port",
            data_reference="mac-address",
            data_name="name",
            data_path="interface",
        )
        coord = _make_coordinator(
            hass,
            data={
                "interface": {
                    "ether1": {
                        "name": "ether1-name",
                        "mac-address": "AA:BB:CC:DD:EE:FF",
                        "type": "ether",
                    }
                },
                "host": {},  # no match
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="ether1")
        info = entity.device_info
        # Falls back to the interface's data_name
        assert info["default_name"] == "ether1-name"
        assert info["default_manufacturer"] == ""

    def test_interface_data_group_with_ether_type(self, hass):
        """ha_group starts with 'data__' and type='ether' → category 'port'."""
        desc = _make_entity_description(
            ha_group="data__default-name",
            data_reference="default-name",
            data_name="name",
            data_path="interface",
        )
        coord = _make_coordinator(
            hass,
            data={
                "interface": {
                    "ether1": {
                        "name": "LAN",
                        "default-name": "ether1",
                        "type": "ether",
                    }
                },
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="ether1")
        info = entity.device_info
        # dev_display_name includes "port" + dev_group (the resolved data__ value)
        assert "port" in info["default_name"]

    def test_interface_data_group_with_vlan_type(self, hass):
        """ha_group starts with 'data__' and type='vlan' → category 'vlan'."""
        desc = _make_entity_description(
            ha_group="data__name",
            data_reference="name",
            data_name="name",
            data_path="interface",
        )
        coord = _make_coordinator(
            hass,
            data={
                "interface": {
                    "v10": {
                        "name": "v10",
                        "type": "vlan",
                    }
                },
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="v10")
        info = entity.device_info
        assert "vlan" in info["default_name"]

    def test_firewall_group(self, hass):
        """ha_group in _FIREWALL_GROUPS produces 'firewall <group>' display name."""
        desc = _make_entity_description(
            ha_group="NAT",
            data_reference="chain",
            data_name="chain",
            data_path="nat",
        )
        coord = _make_coordinator(
            hass,
            data={
                "nat": {"u1": {"chain": "srcnat"}},
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="u1")
        info = entity.device_info
        assert "firewall" in info["default_name"]
        assert "NAT" in info["default_name"]

    def test_generic_group(self, hass):
        """Non-System, non-data__, non-firewall group → plain 'router <group>'."""
        desc = _make_entity_description(
            ha_group="Scripts",
            data_reference="name",
            data_name="name",
            data_path="script",
        )
        coord = _make_coordinator(
            hass,
            data={
                "script": {"s1": {"name": "s1"}},
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="s1")
        info = entity.device_info
        assert "Scripts" in info["default_name"]

    def test_ha_connection_override(self, hass):
        """ha_connection override replaces the connection namespace."""
        desc = _make_entity_description(
            ha_group="Scripts",
            data_reference="name",
            data_name="name",
            data_path="script",
            ha_connection="custom_conn",
            ha_connection_value="fixed-value",
        )
        coord = _make_coordinator(
            hass,
            data={
                "script": {"s1": {"name": "s1"}},
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="s1")
        info = entity.device_info
        conns = info["connections"]
        # At least one connection should use the custom namespace
        assert any(c[0] == "custom_conn" for c in conns)

    def test_ha_connection_value_data_lookup(self, hass):
        """ha_connection_value starts with 'data__' → pulled from self._data."""
        desc = _make_entity_description(
            ha_group="Scripts",
            data_reference="name",
            data_name="name",
            data_path="script",
            ha_connection_value="data__owner",
        )
        coord = _make_coordinator(
            hass,
            data={
                "script": {"s1": {"name": "s1", "owner": "admin-user"}},
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="s1")
        info = entity.device_info
        # connections should include our resolved owner value
        conns = info["connections"]
        assert any("admin-user" in c[1] for c in conns)

    def test_data_group_resolves_to_data_attribute(self, hass):
        """ha_group='data__xxx' and xxx present in data → dev_group = data[xxx]."""
        desc = _make_entity_description(
            ha_group="data__name",
            data_reference="name",
            data_name="name",
            data_path="interface",
        )
        coord = _make_coordinator(
            hass,
            data={
                "interface": {
                    "wg0": {
                        "name": "wg0-resolved",
                        "type": "wireguard",
                    }
                },
                "routerboard": {"serial-number": "XYZ"},
                "resource": {"board-name": "RB", "platform": "P", "version": "v"},
            },
        )
        entity = _make_entity(coord, desc, uid="wg0")
        info = entity.device_info
        # After dev_group resolves to data[name]='wg0-resolved', dev_connection_value = same
        # and since wireguard is in _IFACE_TYPE_CATEGORY as 'vpn', category=vpn
        assert "vpn" in info["default_name"]
        assert "wg0-resolved" in info["default_name"]


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


class TestExtraStateAttributes:
    def test_includes_listed_attributes(self, hass):
        """Attributes in data_attributes_list are extracted to extra state."""
        desc = _make_entity_description(
            data_attributes_list=["uptime", "version"],
            data_path="resource",
        )
        coord = _make_coordinator(
            hass,
            data={
                "resource": {
                    "cpu-load": 10,
                    "uptime": "5d",
                    "version": "7.1",
                    "unlisted": "skipme",
                }
            },
        )
        entity = _make_entity(coord, desc)
        attrs = entity.extra_state_attributes
        # format_attribute replaces dashes with underscores
        assert attrs.get("uptime") == "5d"
        assert attrs.get("version") == "7.1"
        assert "unlisted" not in attrs

    def test_skips_missing_attributes(self, hass):
        """Attributes missing from _data are silently skipped."""
        desc = _make_entity_description(
            data_attributes_list=["missing-field"],
            data_path="resource",
        )
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 10}})
        entity = _make_entity(coord, desc)
        attrs = entity.extra_state_attributes
        assert "missing_field" not in attrs
        assert "missing-field" not in attrs


# ---------------------------------------------------------------------------
# start / stop / restart / reload — NotImplementedError
# ---------------------------------------------------------------------------


class TestNotImplementedMethods:
    @pytest.mark.parametrize("method_name", ["start", "stop", "restart", "reload"])
    async def test_method_raises(self, hass, method_name):
        desc = _make_entity_description()
        coord = _make_coordinator(hass, data={"resource": {"cpu-load": 0}})
        entity = _make_entity(coord, desc)
        with pytest.raises(NotImplementedError):
            await getattr(entity, method_name)()


# ---------------------------------------------------------------------------
# async_add_entities orchestrator (lines 92-170)
# ---------------------------------------------------------------------------


def _build_platform_mock(descriptions, services=None, domain="sensor", entities=None):
    platform_mock = MagicMock()
    platform_mock.platform.SENSOR_SERVICES = services or []
    platform_mock.platform.SENSOR_TYPES = descriptions
    platform_mock.domain = domain
    platform_mock.entities = entities or {}
    platform_mock.async_register_entity_service = MagicMock()
    platform_mock.async_add_entities = AsyncMock()
    return platform_mock


def _build_registry_mock(get_entity_id="sensor.existing", get_entry=None):
    registry_mock = MagicMock()
    registry_mock.async_get_entity_id = MagicMock(return_value=get_entity_id)
    registry_mock.async_get = MagicMock(return_value=get_entry)
    registry_mock.async_remove = MagicMock()
    registry_mock.async_update_entity = MagicMock()
    return registry_mock


class TestAsyncAddEntities:
    async def test_adds_new_entity_when_registry_missing(self, hass):
        """When entity is not in registry, it is added to the platform."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        class _Fake:
            def __init__(self, coordinator, entity_description):
                self.entity_description = entity_description
                self._data = coordinator.data[entity_description.data_path]

        dispatcher = {"MikrotikSensor": _Fake}

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, dispatcher)

        platform_mock.async_add_entities.assert_awaited()

    async def test_registers_services(self, hass):
        """SENSOR_SERVICES are registered on the platform at startup."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = None  # early return in async_update_controller
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        services = [("my_service", None, AsyncMock())]
        platform_mock = _build_platform_mock((desc,), services=services)
        registry_mock = _build_registry_mock()

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {})

        platform_mock.async_register_entity_service.assert_called_once()

    async def test_uid_path_with_skip_sensor(self, hass):
        """When _skip_sensor returns True, the uid loop skips that entity."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"interface": {"uid1": {"type": "ether", "name": "uid1"}}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        class _Fake:
            def __init__(self, coordinator, entity_description, uid=None):
                self.entity_description = entity_description
                self._data = coordinator.data[entity_description.data_path][uid]

        dispatcher = {"MikrotikSensor": _Fake}

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity._skip_sensor", return_value=True),
        ):
            await async_add_entities(hass, entry, dispatcher)

        platform_mock.async_add_entities.assert_not_awaited()

    async def test_data_path_missing_is_skipped(self, hass):
        """Descriptions whose data_path is absent from coordinator.data are skipped."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"present": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(
            data_path="missing_path",
            data_attribute="cpu-load",
        )
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {})

        platform_mock.async_add_entities.assert_not_awaited()

    async def test_no_reference_attribute_missing_is_skipped(self, hass):
        """No-reference description with absent attribute is skipped."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"other": 1}}  # cpu-load absent
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {"MikrotikSensor": MagicMock})

        platform_mock.async_add_entities.assert_not_awaited()

    async def test_no_reference_dispatcher_missing_is_skipped(self, hass):
        """No-reference description with no dispatcher match is silently skipped."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(
            data_path="resource",
            data_attribute="cpu-load",
            func="MissingFunc",
        )
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {})

        platform_mock.async_add_entities.assert_not_awaited()

    async def test_uid_dispatcher_missing_is_skipped(self, hass):
        """UID-based description with no dispatcher match is silently skipped."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"interface": {"uid1": {"type": "ether", "name": "uid1"}}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
            func="MissingFunc",
        )
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity._skip_sensor", return_value=False),
        ):
            await async_add_entities(hass, entry, {})

        platform_mock.async_add_entities.assert_not_awaited()

    async def test_removes_orphan_registry_entries(self, hass):
        """Orphan registry entries (not in platform.entities) are removed."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        orphan = MagicMock()
        orphan.domain = "sensor"
        orphan.entity_id = "sensor.orphan"
        orphan.disabled = False

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[orphan]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {})

        registry_mock.async_remove.assert_called_once_with("sensor.orphan")

    async def test_skips_disabled_orphan_entries(self, hass):
        """Disabled registry entries are left alone."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        disabled_orphan = MagicMock()
        disabled_orphan.domain = "sensor"
        disabled_orphan.entity_id = "sensor.disabled_orphan"
        disabled_orphan.disabled = True

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[disabled_orphan]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {})

        registry_mock.async_remove.assert_not_called()

    async def test_data_none_short_circuits(self, hass):
        """When coordinator.data is None, update_controller returns early."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = None
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock()

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {})

        platform_mock.async_add_entities.assert_not_awaited()

    async def test_re_enables_entity_disabled_by_integration(self, hass):
        """Existing disabled-by-integration entries are re-enabled when option turns on."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options={**ENTRY_OPTIONS, "toggle_opt": True},
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(
            data_path="resource",
            data_attribute="cpu-load",
            enable_on_option="toggle_opt",
        )
        platform_mock = _build_platform_mock((desc,))

        # Existing registry entry, disabled by integration
        reg_entry = MagicMock()
        reg_entry.disabled = True
        reg_entry.disabled_by = er.RegistryEntryDisabler.INTEGRATION
        reg_entry.domain = "sensor"
        reg_entry.entity_id = "sensor.existing"
        registry_mock = _build_registry_mock(get_entity_id="sensor.existing", get_entry=reg_entry)

        class _Fake:
            def __init__(self, coordinator, entity_description):
                self.entity_description = entity_description
                self._data = coordinator.data[entity_description.data_path]

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
        ):
            await async_add_entities(hass, entry, {"MikrotikSensor": _Fake})

        registry_mock.async_update_entity.assert_called_once()
        platform_mock.async_add_entities.assert_awaited()

    async def test_adds_new_uid_entity(self, hass):
        """UID-based description builds entity with unique_id including slugified reference."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"interface": {"uid1": {"name": "ether1", "type": "ether"}}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(
            data_path="interface",
            data_reference="name",
            data_name="name",
        )
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        class _Fake:
            def __init__(self, coordinator, entity_description, uid=None):
                self.entity_description = entity_description
                self._data = coordinator.data[entity_description.data_path][uid]

        dispatcher = {"MikrotikSensor": _Fake}

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get"),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity._skip_sensor", return_value=False),
        ):
            await async_add_entities(hass, entry, dispatcher)

        platform_mock.async_add_entities.assert_awaited()

    async def test_removes_empty_devices(self, hass):
        """Devices with no entities are removed by dr.async_remove_device."""
        from custom_components.mikrotik_extended.entity import async_add_entities

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            options=ENTRY_OPTIONS,
            unique_id="192.168.88.1",
        )
        entry.add_to_hass(hass)

        coord = MagicMock()
        coord.data = {"resource": {"cpu-load": 1}}
        coord.config_entry = entry
        entry.runtime_data = MagicMock(data_coordinator=coord)

        desc = _make_entity_description(data_path="resource", data_attribute="cpu-load")
        platform_mock = _build_platform_mock((desc,))
        registry_mock = _build_registry_mock(get_entity_id=None, get_entry=None)

        empty_device = MagicMock()
        empty_device.id = "dev-empty"
        empty_device.name = "EmptyDev"

        device_registry_mock = MagicMock()
        device_registry_mock.async_remove_device = MagicMock()

        with (
            patch("custom_components.mikrotik_extended.entity.ep.async_get_current_platform", return_value=platform_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_get", return_value=registry_mock),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_config_entry", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.er.async_entries_for_device", return_value=[]),
            patch("custom_components.mikrotik_extended.entity.dr.async_get", return_value=device_registry_mock),
            patch("custom_components.mikrotik_extended.entity.dr.async_entries_for_config_entry", return_value=[empty_device]),
        ):
            await async_add_entities(hass, entry, {})

        device_registry_mock.async_remove_device.assert_called_once_with("dev-empty")
