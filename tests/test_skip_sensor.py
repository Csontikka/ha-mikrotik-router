"""Tests for the _skip_sensor filter function in entity.py."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.mikrotik_router.entity import _skip_sensor
from custom_components.mikrotik_router.const import (
    CONF_SENSOR_PORT_TRAFFIC,
    CONF_SENSOR_PORT_TRACKER,
    CONF_SENSOR_NETWATCH_TRACKER,
    CONF_TRACK_HOSTS,
)


def _make_config_entry(**options):
    entry = MagicMock()
    entry.options = options
    return entry


def _make_desc(func="SomeFunc", data_path="interface", data_attribute="enabled"):
    desc = MagicMock()
    desc.func = func
    desc.data_path = data_path
    desc.data_attribute = data_attribute
    return desc


# ---------------------------------------------------------------------------
# MikrotikInterfaceTrafficSensor skips
# ---------------------------------------------------------------------------

class TestSkipTrafficSensor:
    def test_skip_when_traffic_disabled(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRAFFIC: False})
        desc = _make_desc(func="MikrotikInterfaceTrafficSensor")
        data = {"eth0": {"type": "ether"}}
        assert _skip_sensor(entry, desc, data, "eth0") is True

    def test_no_skip_when_traffic_enabled(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRAFFIC: True})
        desc = _make_desc(func="MikrotikInterfaceTrafficSensor")
        data = {"eth0": {"type": "ether"}}
        assert _skip_sensor(entry, desc, data, "eth0") is False

    def test_skip_bridge_type(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRAFFIC: True})
        desc = _make_desc(func="MikrotikInterfaceTrafficSensor")
        data = {"br0": {"type": "bridge"}}
        assert _skip_sensor(entry, desc, data, "br0") is True

    def test_no_skip_ether_type(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRAFFIC: True})
        desc = _make_desc(func="MikrotikInterfaceTrafficSensor")
        data = {"eth0": {"type": "ether"}}
        assert _skip_sensor(entry, desc, data, "eth0") is False


# ---------------------------------------------------------------------------
# client_traffic skips
# ---------------------------------------------------------------------------

class TestSkipClientTraffic:
    def test_skip_when_unavailable(self):
        entry = _make_config_entry()
        desc = _make_desc(data_path="client_traffic", data_attribute="tx-byte")
        data = {"client1": {"available": False, "tx-byte": 100}}
        assert _skip_sensor(entry, desc, data, "client1") is True

    def test_skip_when_attribute_missing(self):
        entry = _make_config_entry()
        desc = _make_desc(data_path="client_traffic", data_attribute="tx-byte")
        data = {"client1": {"available": True}}
        assert _skip_sensor(entry, desc, data, "client1") is True

    def test_no_skip_when_available_and_attribute_present(self):
        entry = _make_config_entry()
        desc = _make_desc(data_path="client_traffic", data_attribute="tx-byte")
        data = {"client1": {"available": True, "tx-byte": 100}}
        assert _skip_sensor(entry, desc, data, "client1") is False

    def test_skip_when_available_key_missing(self):
        entry = _make_config_entry()
        desc = _make_desc(data_path="client_traffic", data_attribute="tx-byte")
        data = {"client1": {"tx-byte": 100}}
        assert _skip_sensor(entry, desc, data, "client1") is True


# ---------------------------------------------------------------------------
# MikrotikPortBinarySensor skips
# ---------------------------------------------------------------------------

class TestSkipPortBinarySensor:
    def test_skip_wlan_type(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRACKER: True})
        desc = _make_desc(func="MikrotikPortBinarySensor")
        data = {"wlan0": {"type": "wlan"}}
        assert _skip_sensor(entry, desc, data, "wlan0") is True

    def test_skip_when_tracker_disabled(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRACKER: False})
        desc = _make_desc(func="MikrotikPortBinarySensor")
        data = {"eth0": {"type": "ether"}}
        assert _skip_sensor(entry, desc, data, "eth0") is True

    def test_no_skip_ether_with_tracker_enabled(self):
        entry = _make_config_entry(**{CONF_SENSOR_PORT_TRACKER: True})
        desc = _make_desc(func="MikrotikPortBinarySensor")
        data = {"eth0": {"type": "ether"}}
        assert _skip_sensor(entry, desc, data, "eth0") is False


# ---------------------------------------------------------------------------
# Netwatch skips
# ---------------------------------------------------------------------------

class TestSkipNetwatch:
    def test_skip_when_netwatch_disabled(self):
        entry = _make_config_entry(**{CONF_SENSOR_NETWATCH_TRACKER: False})
        desc = _make_desc(data_path="netwatch")
        data = {"nw1": {}}
        assert _skip_sensor(entry, desc, data, "nw1") is True

    def test_no_skip_when_netwatch_enabled(self):
        entry = _make_config_entry(**{CONF_SENSOR_NETWATCH_TRACKER: True})
        desc = _make_desc(data_path="netwatch")
        data = {"nw1": {}}
        assert _skip_sensor(entry, desc, data, "nw1") is False


# ---------------------------------------------------------------------------
# MikrotikHostDeviceTracker skips
# ---------------------------------------------------------------------------

class TestSkipHostTracker:
    def test_skip_when_host_tracking_disabled(self):
        entry = _make_config_entry(**{CONF_TRACK_HOSTS: False})
        desc = _make_desc(func="MikrotikHostDeviceTracker")
        data = {"host1": {}}
        assert _skip_sensor(entry, desc, data, "host1") is True

    def test_no_skip_when_host_tracking_enabled(self):
        entry = _make_config_entry(**{CONF_TRACK_HOSTS: True})
        desc = _make_desc(func="MikrotikHostDeviceTracker")
        data = {"host1": {}}
        assert _skip_sensor(entry, desc, data, "host1") is False


# ---------------------------------------------------------------------------
# Default — no skip
# ---------------------------------------------------------------------------

class TestNoSkip:
    def test_unknown_func_not_skipped(self):
        entry = _make_config_entry()
        desc = _make_desc(func="SomeOtherSensor", data_path="something")
        data = {"uid1": {"type": "ether"}}
        assert _skip_sensor(entry, desc, data, "uid1") is False
