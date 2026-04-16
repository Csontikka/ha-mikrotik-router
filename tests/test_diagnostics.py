"""Tests for diagnostics export."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.mikrotik_extended.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_and_returns_shape(hass):
    """async_get_config_entry_diagnostics returns redacted data + logs key."""
    entry = MagicMock()
    entry.data = {"host": "192.168.88.1", "password": "secret", "username": "admin"}
    entry.options = {"scan_interval": 10, "password": "shouldberedacted"}

    data_coord = SimpleNamespace(data={"router": {"serial_number": "ABC123", "arp": [{"mac-address": "AA:BB:CC:DD:EE:FF"}]}})
    tracker_coord = SimpleNamespace(data={"host": {"01": {"mac-address": "AA:BB:CC:DD:EE:FF", "host-name": "laptop"}}})
    entry.runtime_data = SimpleNamespace(
        data_coordinator=data_coord,
        tracker_coordinator=tracker_coord,
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert set(result.keys()) == {"entry", "data", "tracker", "logs"}
    assert "data" in result["entry"]
    assert "options" in result["entry"]
    # password in entry.data should be redacted
    assert result["entry"]["data"]["password"] != "secret"
    assert isinstance(result["logs"], list)
