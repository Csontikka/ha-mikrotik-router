"""Tests for MikrotikEntity base class."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

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

        # Call _handle_coordinator_update — patch super to avoid HA internals
        from custom_components.mikrotik_extended.entity import MikrotikEntity

        with patch.object(MikrotikEntity, "_handle_coordinator_update", entity._handle_coordinator_update.__func__):
            # Call the actual implementation directly
            pass

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
        # unique_id must NOT contain the instance name
        assert "testrouter" not in entity.unique_id
        # unique_id must contain the entry_id
        assert coord.config_entry.entry_id in entity.unique_id
