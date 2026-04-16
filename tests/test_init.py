"""Tests for Mikrotik Router integration setup, teardown, services and migration."""

from __future__ import annotations

from types import SimpleNamespace
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
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended import (
    async_migrate_entry,
    async_reload_entry,
    async_remove_config_entry_device,
    async_remove_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
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


def _make_entry(hass, data=None, options=None, version=2):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data or ENTRY_DATA,
        options=options or ENTRY_OPTIONS,
        unique_id="192.168.88.1",
        version=version,
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# async_setup_entry — happy path + error branches
# ---------------------------------------------------------------------------


async def test_setup_entry_sets_runtime_data(hass):
    """async_setup_entry stores coordinator instances in runtime_data."""
    entry = _make_entry(hass)

    mock_coord = MagicMock()
    mock_coord.async_config_entry_first_refresh = AsyncMock()
    mock_coord.data = {}

    mock_tracker = MagicMock()
    mock_tracker.async_config_entry_first_refresh = AsyncMock()

    mock_api = MagicMock()
    mock_api.connect.return_value = True
    mock_api.error = ""

    with (
        patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api),
        patch("custom_components.mikrotik_extended.MikrotikCoordinator", return_value=mock_coord),
        patch("custom_components.mikrotik_extended.MikrotikTrackerCoordinator", return_value=mock_tracker),
        patch.object(hass.config_entries, "async_forward_entry_setups", return_value=True),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert hasattr(entry, "runtime_data")
    assert entry.runtime_data.data_coordinator is mock_coord
    assert entry.runtime_data.tracker_coordinator is mock_tracker


async def test_setup_entry_raises_auth_failed_on_wrong_login(hass):
    """Invalid credentials -> ConfigEntryAuthFailed raised."""
    entry = _make_entry(hass)

    mock_api = MagicMock()
    mock_api.connect.return_value = False
    mock_api.error = "wrong_login"

    with (
        patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_entry_raises_not_ready_when_cannot_connect(hass):
    """Non-auth connect failure -> ConfigEntryNotReady raised."""
    entry = _make_entry(hass)

    mock_api = MagicMock()
    mock_api.connect.return_value = False
    mock_api.error = "cannot_connect"

    with (
        patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


# ---------------------------------------------------------------------------
# async_unload_entry
# ---------------------------------------------------------------------------


async def test_unload_entry(hass):
    """async_unload_entry returns True and cleans up platforms."""
    entry = _make_entry(hass)

    mock_coord = MagicMock()
    mock_coord.async_config_entry_first_refresh = AsyncMock()
    mock_coord.data = {}
    mock_coord.api = MagicMock()

    mock_tracker = MagicMock()
    mock_tracker.async_config_entry_first_refresh = AsyncMock()

    mock_api = MagicMock()
    mock_api.connect.return_value = True
    mock_api.error = ""

    with (
        patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api),
        patch("custom_components.mikrotik_extended.MikrotikCoordinator", return_value=mock_coord),
        patch("custom_components.mikrotik_extended.MikrotikTrackerCoordinator", return_value=mock_tracker),
        patch.object(hass.config_entries, "async_forward_entry_setups", return_value=True),
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        unload_result = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert unload_result is True


async def test_unload_entry_no_runtime_data(hass):
    """async_unload_entry works even when runtime_data missing."""
    entry = _make_entry(hass)

    # Don't assign runtime_data; simulate partial setup teardown
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        result = await async_unload_entry(hass, entry)
    assert result is True


# ---------------------------------------------------------------------------
# async_reload_entry
# ---------------------------------------------------------------------------


async def test_reload_entry_invokes_async_reload(hass):
    """async_reload_entry delegates to hass.config_entries.async_reload."""
    entry = _make_entry(hass)

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as mock_reload:
        await async_reload_entry(hass, entry)
    mock_reload.assert_awaited_once_with(entry.entry_id)


# ---------------------------------------------------------------------------
# async_migrate_entry
# ---------------------------------------------------------------------------


async def test_migrate_entry_v1_adds_verify_ssl(hass):
    """Migrating from v1 adds CONF_VERIFY_SSL to entry.data and bumps version."""
    # Build an entry that looks like v1 (no CONF_VERIFY_SSL)
    data_no_vs = {k: v for k, v in ENTRY_DATA.items() if k != CONF_VERIFY_SSL}
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data_no_vs,
        options=ENTRY_OPTIONS,
        unique_id="192.168.88.1",
        version=1,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)
    assert result is True
    assert CONF_VERIFY_SSL in entry.data
    assert entry.version == 2


async def test_migrate_entry_already_current_version(hass):
    """Migration on a v2 entry is a no-op but still returns True."""
    entry = _make_entry(hass, version=2)
    result = await async_migrate_entry(hass, entry)
    assert result is True
    assert entry.version == 2


# ---------------------------------------------------------------------------
# async_remove_config_entry_device
# ---------------------------------------------------------------------------


async def test_remove_config_entry_device_returns_true(hass):
    """Stub that always allows device removal."""
    entry = _make_entry(hass)
    device = MagicMock()
    result = await async_remove_config_entry_device(hass, entry, device)
    assert result is True


# ---------------------------------------------------------------------------
# async_setup — registers services
# ---------------------------------------------------------------------------


async def test_async_setup_registers_services(hass):
    """async_setup returns True and registers the four services."""
    # Call directly — autouse fixtures have already set things up
    result = await async_setup(hass, {})
    assert result is True
    services = hass.services.async_services().get(DOMAIN, {})
    assert "send_magic_packet" in services
    assert "api_test" in services
    assert "refresh_data" in services
    assert "set_environment" in services


# ---------------------------------------------------------------------------
# send_magic_packet service
# ---------------------------------------------------------------------------


async def test_send_magic_packet_invalid_mac_raises(hass):
    """Invalid MAC raises ServiceValidationError."""
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "send_magic_packet",
            {"mac": "not-a-mac"},
            blocking=True,
        )


async def test_send_magic_packet_success(hass):
    """Valid MAC dispatches wol() on each configured router's API."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.wol = MagicMock(return_value=True)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    await hass.services.async_call(
        DOMAIN,
        "send_magic_packet",
        {"mac": "AA:BB:CC:DD:EE:FF"},
        blocking=True,
    )
    mock_api.wol.assert_called_once_with("AA:BB:CC:DD:EE:FF", None)


async def test_send_magic_packet_logs_failure(hass, caplog):
    """When wol() returns False, a warning is logged (branch coverage)."""
    import logging

    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.wol = MagicMock(return_value=False)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    with caplog.at_level(logging.WARNING, logger="custom_components.mikrotik_extended"):
        await hass.services.async_call(
            DOMAIN,
            "send_magic_packet",
            {"mac": "AA:BB:CC:DD:EE:FF", "interface": "ether1"},
            blocking=True,
        )
    mock_api.wol.assert_called_once_with("AA:BB:CC:DD:EE:FF", "ether1")


async def test_send_magic_packet_skips_entries_without_runtime_data(hass):
    """Entries without runtime_data are ignored silently."""
    await async_setup(hass, {})

    _make_entry(hass)  # Registered but no runtime_data attached

    await hass.services.async_call(
        DOMAIN,
        "send_magic_packet",
        {"mac": "AA:BB:CC:DD:EE:FF"},
        blocking=True,
    )


# ---------------------------------------------------------------------------
# api_test service
# ---------------------------------------------------------------------------


async def test_api_test_returns_response_from_api_query(hass):
    """api_test calls coordinator.api.query and returns truncated results."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.query = MagicMock(return_value=[{"id": "1", "name": "n"}, {"id": "2", "name": "m"}])

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.data = None

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "/interface"},
        blocking=True,
        return_response=True,
    )
    assert "result" in response
    assert "192.168.88.1" in response["result"]
    assert response["result"]["192.168.88.1"]["total_returned"] == 2


async def test_api_test_reports_no_response_when_query_returns_none(hass):
    """If coordinator.api.query returns None, an error is reported."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.query = MagicMock(return_value=None)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.data = None

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "/interface"},
        blocking=True,
        return_response=True,
    )
    assert "error" in response["result"]["192.168.88.1"]


async def test_api_test_coordinator_data_dict_mode(hass):
    """coordinator_data=True returns items from coordinator.data[path]."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    coord = MagicMock()
    coord.api = MagicMock()
    coord.config_entry = entry
    coord.data = {"interface": {"e1": {"name": "e1", "type": "ether"}, "e2": {"name": "e2", "type": "ether"}}}

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "interface", "coordinator_data": True},
        blocking=True,
        return_response=True,
    )
    result = response["result"]["192.168.88.1"]
    assert result["total_keys"] == 2


async def test_api_test_coordinator_data_path_missing(hass):
    """coordinator_data=True with missing path yields an error message."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    coord = MagicMock()
    coord.api = MagicMock()
    coord.config_entry = entry
    coord.data = {"other": {}}

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "missing", "coordinator_data": True},
        blocking=True,
        return_response=True,
    )
    assert "error" in response["result"]["192.168.88.1"]


async def test_api_test_coordinator_data_scalar_value(hass):
    """coordinator_data=True with a non-dict value is stringified."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    coord = MagicMock()
    coord.api = MagicMock()
    coord.config_entry = entry
    coord.data = {"string_path": "a string"}

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "string_path", "coordinator_data": True},
        blocking=True,
        return_response=True,
    )
    assert response["result"]["192.168.88.1"]["value"] == "a string"


async def test_api_test_host_filter_skips_mismatched(hass):
    """host filter restricts which entries are queried."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    coord = MagicMock()
    coord.api = MagicMock()
    coord.config_entry = entry
    coord.data = {}

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "x", "host": "192.168.99.99"},
        blocking=True,
        return_response=True,
    )
    assert response["result"] == {}


async def test_api_test_handles_exception(hass):
    """Exceptions inside the try/except are captured as 'error'."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.query = MagicMock(side_effect=RuntimeError("boom"))

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.data = None

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "/interface"},
        blocking=True,
        return_response=True,
    )
    assert "error" in response["result"]["192.168.88.1"]


async def test_api_test_query_returns_scalar_items(hass):
    """raw items that aren't dicts are stringified."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.query = MagicMock(return_value=["scalar-a", "scalar-b"])

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.data = None

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "/anything"},
        blocking=True,
        return_response=True,
    )
    items = response["result"]["192.168.88.1"]["items"]
    assert items == ["scalar-a", "scalar-b"]


async def test_api_test_skips_entries_without_runtime_data(hass):
    """api_test ignores entries lacking runtime_data."""
    await async_setup(hass, {})

    _make_entry(hass)  # registration side-effect only
    # No runtime_data assigned

    response = await hass.services.async_call(
        DOMAIN,
        "api_test",
        {"path": "/anything"},
        blocking=True,
        return_response=True,
    )
    assert response["result"] == {}


# ---------------------------------------------------------------------------
# refresh_data service
# ---------------------------------------------------------------------------


async def test_refresh_data_requests_refresh_on_both_coordinators(hass):
    """refresh_data triggers async_request_refresh on both coordinators."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    data_coord = MagicMock()
    data_coord.api = MagicMock()
    data_coord.config_entry = entry
    data_coord.async_request_refresh = AsyncMock()

    tracker_coord = MagicMock()
    tracker_coord.async_request_refresh = AsyncMock()

    entry.runtime_data = SimpleNamespace(data_coordinator=data_coord, tracker_coordinator=tracker_coord)

    await hass.services.async_call(DOMAIN, "refresh_data", {}, blocking=True)

    data_coord.async_request_refresh.assert_awaited_once()
    tracker_coord.async_request_refresh.assert_awaited_once()


async def test_refresh_data_host_filter_skips_mismatched(hass):
    """Host filter prevents refresh on non-matching entries."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    data_coord = MagicMock()
    data_coord.api = MagicMock()
    data_coord.config_entry = entry
    data_coord.async_request_refresh = AsyncMock()

    tracker_coord = MagicMock()
    tracker_coord.async_request_refresh = AsyncMock()

    entry.runtime_data = SimpleNamespace(data_coordinator=data_coord, tracker_coordinator=tracker_coord)

    await hass.services.async_call(DOMAIN, "refresh_data", {"host": "10.0.0.0"}, blocking=True)

    data_coord.async_request_refresh.assert_not_awaited()


async def test_refresh_data_skips_entries_without_runtime_data(hass):
    """refresh_data silently ignores entries without runtime_data."""
    await async_setup(hass, {})

    _make_entry(hass)

    # No exception should be raised
    await hass.services.async_call(DOMAIN, "refresh_data", {}, blocking=True)


# ---------------------------------------------------------------------------
# set_environment service
# ---------------------------------------------------------------------------


async def test_set_environment_requires_value_on_set(hass):
    """ServiceValidationError raised when action=set but no value provided."""
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_environment",
            {"name": "var", "action": "set"},
            blocking=True,
        )


async def test_set_environment_set_success(hass):
    """set_environment(action=set) calls set_env_variable and refreshes the coordinator."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.set_env_variable = MagicMock(return_value=True)
    mock_api.remove_env_variable = MagicMock(return_value=True)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.async_request_refresh = AsyncMock()

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    await hass.services.async_call(
        DOMAIN,
        "set_environment",
        {"name": "VAR", "value": "val", "action": "set"},
        blocking=True,
    )
    mock_api.set_env_variable.assert_called_once_with("VAR", "val")
    coord.async_request_refresh.assert_awaited()


async def test_set_environment_remove_success(hass):
    """set_environment(action=remove) calls remove_env_variable."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.remove_env_variable = MagicMock(return_value=True)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.async_request_refresh = AsyncMock()

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    await hass.services.async_call(
        DOMAIN,
        "set_environment",
        {"name": "VAR", "action": "remove"},
        blocking=True,
    )
    mock_api.remove_env_variable.assert_called_once_with("VAR")


async def test_set_environment_logs_on_failure(hass):
    """When set_env_variable returns False, a warning is emitted and no refresh happens."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.set_env_variable = MagicMock(return_value=False)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.async_request_refresh = AsyncMock()

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    await hass.services.async_call(
        DOMAIN,
        "set_environment",
        {"name": "VAR", "value": "val", "action": "set"},
        blocking=True,
    )
    coord.async_request_refresh.assert_not_awaited()


async def test_set_environment_host_filter(hass):
    """host filter prevents action against non-matching entries."""
    await async_setup(hass, {})

    entry = _make_entry(hass)
    mock_api = MagicMock()
    mock_api.set_env_variable = MagicMock(return_value=True)

    coord = MagicMock()
    coord.api = mock_api
    coord.config_entry = entry
    coord.async_request_refresh = AsyncMock()

    entry.runtime_data = SimpleNamespace(data_coordinator=coord, tracker_coordinator=MagicMock())

    await hass.services.async_call(
        DOMAIN,
        "set_environment",
        {"name": "VAR", "value": "v", "host": "9.9.9.9", "action": "set"},
        blocking=True,
    )
    mock_api.set_env_variable.assert_not_called()


async def test_set_environment_skips_entries_without_runtime_data(hass):
    """set_environment silently skips entries without runtime_data."""
    await async_setup(hass, {})

    _make_entry(hass)
    # No runtime_data

    await hass.services.async_call(
        DOMAIN,
        "set_environment",
        {"name": "VAR", "value": "v", "action": "set"},
        blocking=True,
    )


# ---------------------------------------------------------------------------
# async_remove_entry — router-side cleanup
# ---------------------------------------------------------------------------


async def test_remove_entry_connects_and_removes_kidcontrol(hass):
    """async_remove_entry removes the ha-monitoring kid-control profile when present."""
    entry = _make_entry(hass)

    mock_api = MagicMock()
    mock_api.connect = MagicMock(return_value=True)
    mock_api.query = MagicMock(return_value=[{"name": "ha-monitoring"}])
    mock_api.execute = MagicMock()
    mock_api.disconnect = MagicMock()

    with patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api):
        await async_remove_entry(hass, entry)

    mock_api.execute.assert_called_once_with("/ip/kid-control", "remove", "name", "ha-monitoring")
    mock_api.disconnect.assert_called_once()


async def test_remove_entry_no_profile_skips_execute(hass):
    """When the ha-monitoring profile isn't present, execute is not called."""
    entry = _make_entry(hass)

    mock_api = MagicMock()
    mock_api.connect = MagicMock(return_value=True)
    mock_api.query = MagicMock(return_value=[{"name": "other-profile"}])
    mock_api.execute = MagicMock()
    mock_api.disconnect = MagicMock()

    with patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api):
        await async_remove_entry(hass, entry)

    mock_api.execute.assert_not_called()
    mock_api.disconnect.assert_called_once()


async def test_remove_entry_cannot_connect_skips_cleanup(hass):
    """When the router is unreachable, cleanup is skipped silently."""
    entry = _make_entry(hass)

    mock_api = MagicMock()
    mock_api.connect = MagicMock(return_value=False)
    mock_api.query = MagicMock()
    mock_api.execute = MagicMock()
    mock_api.disconnect = MagicMock()

    with patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api):
        await async_remove_entry(hass, entry)

    mock_api.query.assert_not_called()
    mock_api.execute.assert_not_called()


async def test_remove_entry_query_returns_none_handled(hass):
    """When query() returns None, cleanup does not crash (defaults to empty list)."""
    entry = _make_entry(hass)

    mock_api = MagicMock()
    mock_api.connect = MagicMock(return_value=True)
    mock_api.query = MagicMock(return_value=None)
    mock_api.execute = MagicMock()
    mock_api.disconnect = MagicMock()

    with patch("custom_components.mikrotik_extended.MikrotikAPI", return_value=mock_api):
        await async_remove_entry(hass, entry)

    mock_api.execute.assert_not_called()
    mock_api.disconnect.assert_called_once()
