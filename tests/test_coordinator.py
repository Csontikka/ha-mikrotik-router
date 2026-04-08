"""Tests for MikrotikCoordinator and MikrotikTrackerCoordinator."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
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
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.const import DOMAIN


# Provide IssueSeverity fallback for test environment
class _FakeIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 8728,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "Mikrotik",
}

ENTRY_OPTIONS = {
    "scan_interval": 30,
    "track_network_hosts_timeout": 180,
    "zone": "home",
}


def _make_config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
        unique_id="192.168.88.1",
    )


def _make_coordinator(hass):
    """Build a MikrotikCoordinator with a mocked MikrotikAPI."""
    from custom_components.mikrotik_extended.coordinator import MikrotikCoordinator

    entry = _make_config_entry()
    entry.add_to_hass(hass)

    with patch("custom_components.mikrotik_extended.coordinator.MikrotikAPI") as MockAPI:
        mock_api = MagicMock()
        MockAPI.return_value = mock_api
        with patch(
            "custom_components.mikrotik_extended.coordinator.IssueSeverity",
            _FakeIssueSeverity,
        ):
            coordinator = MikrotikCoordinator(hass, entry)

    coordinator.api = mock_api
    # Ensure config_entry is accessible (some HA versions use weakref)
    coordinator.config_entry = entry
    return coordinator


# ---------------------------------------------------------------------------
# _get_stale_counters
# ---------------------------------------------------------------------------


class TestGetStaleCounters:
    def test_creates_empty_dict_for_new_key(self, hass):
        coord = _make_coordinator(hass)
        result = coord._get_stale_counters("interface")
        assert result == {}

    def test_returns_same_dict_on_second_call(self, hass):
        coord = _make_coordinator(hass)
        first = coord._get_stale_counters("interface")
        first["eth0"] = 3
        second = coord._get_stale_counters("interface")
        assert second is first
        assert second["eth0"] == 3

    def test_different_keys_are_isolated(self, hass):
        coord = _make_coordinator(hass)
        a = coord._get_stale_counters("interface")
        b = coord._get_stale_counters("host")
        a["x"] = 99
        assert "x" not in b

    def test_multiple_keys_stored_independently(self, hass):
        coord = _make_coordinator(hass)
        coord._get_stale_counters("nat")["rule1"] = 1
        coord._get_stale_counters("filter")["rule2"] = 2
        assert coord._get_stale_counters("nat") == {"rule1": 1}
        assert coord._get_stale_counters("filter") == {"rule2": 2}


# ---------------------------------------------------------------------------
# _async_update_data — connection / reconnect flow
# ---------------------------------------------------------------------------


class TestAsyncUpdateDataConnection:
    async def _run_update(self, coordinator):
        """Invoke _async_update_data directly."""
        return await coordinator._async_update_data()

    def _stub_all_get_methods(self, coordinator):
        """Stub every get_* / async_get_* / process_* method to be a no-op."""
        noop_sync = MagicMock(return_value=None)
        noop_async = AsyncMock(return_value=None)
        for attr in dir(coordinator):
            if attr.startswith("get_") or attr.startswith("process_") or attr.startswith("sync_"):
                if attr.startswith("async_") or "async" in attr:
                    setattr(coordinator, attr, noop_async)
                else:
                    setattr(coordinator, attr, noop_sync)
        # Explicitly cover the ones called via async_add_executor_job
        for name in [
            "get_access",
            "get_firmware_update",
            "get_system_resource",
            "get_capabilities",
            "get_system_routerboard",
            "get_script",
            "get_dhcp_network",
            "get_dns",
            "get_system_health",
            "get_dhcp_client",
            "get_interface",
            "get_ip_address",
            "get_cloud",
            "get_capsman_hosts",
            "get_wireless",
            "get_wireless_hosts",
            "get_bridge",
            "get_arp",
            "get_dhcp",
            "process_interface_client",
            "get_nat",
            "get_kidcontrol",
            "get_mangle",
            "get_routing_rules",
            "get_wireguard_peers",
            "get_containers",
            "get_device_mode",
            "get_packages",
            "get_filter",
            "get_netwatch",
            "get_ppp",
            "sync_kid_control_monitoring_profile",
            "process_kid_control_devices",
            "get_captive",
            "get_queue",
            "get_environment",
            "get_ups",
            "get_gps",
        ]:
            setattr(coordinator, name, MagicMock(return_value=None))

        coordinator.async_get_host_hass = AsyncMock(return_value=None)
        coordinator.async_process_host = AsyncMock(return_value=None)

    async def test_raises_update_failed_when_api_not_connected_after_reconnect(self, hass):
        """UpdateFailed is raised when api stays disconnected after reconnect attempt."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        # has_reconnected triggers the reconnect block
        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "connection_refused"

        with pytest.raises(UpdateFailed, match="Mikrotik Disconnected"):
            await self._run_update(coordinator)

    async def test_raises_update_failed_at_end_when_disconnected(self, hass):
        """UpdateFailed raised at end of update when still disconnected."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        # Skip reconnect block (has_reconnected=False, delta > 4h not triggered)
        coordinator.api.has_reconnected.return_value = False
        coordinator.last_hwinfo_update = datetime.now()
        # Stays disconnected throughout
        coordinator.api.connected.return_value = False
        coordinator.api.error = ""

        with pytest.raises(UpdateFailed, match="Mikrotik Disconnected"):
            await self._run_update(coordinator)

    async def test_returns_ds_on_successful_update(self, hass):
        """Returns coordinator.ds dict when connected throughout."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = False
        coordinator.last_hwinfo_update = datetime.now()
        coordinator.api.connected.return_value = True
        coordinator.api.error = ""

        with (
            patch("custom_components.mikrotik_extended.coordinator.IssueSeverity", _FakeIssueSeverity),
            patch("custom_components.mikrotik_extended.coordinator.async_create_issue", MagicMock()),
            patch("custom_components.mikrotik_extended.coordinator.async_delete_issue", MagicMock()),
            patch("custom_components.mikrotik_extended.coordinator.async_dispatcher_send"),
        ):
            result = await self._run_update(coordinator)

        assert result is coordinator.ds


# ---------------------------------------------------------------------------
# _async_update_data — repair issues
# ---------------------------------------------------------------------------


class TestRepairIssues:
    def _stub_all_get_methods(self, coordinator):
        for name in [
            "get_access",
            "get_firmware_update",
            "get_system_resource",
            "get_capabilities",
            "get_system_routerboard",
            "get_script",
            "get_dhcp_network",
            "get_dns",
        ]:
            setattr(coordinator, name, MagicMock(return_value=None))
        coordinator.async_get_host_hass = AsyncMock(return_value=None)
        coordinator.async_process_host = AsyncMock(return_value=None)

    def _patch_severity_and_issues(self, mock_create=None, mock_delete=None):
        """Context manager that patches IssueSeverity + create/delete issue."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            with (
                patch("custom_components.mikrotik_extended.coordinator.IssueSeverity", _FakeIssueSeverity),
                patch("custom_components.mikrotik_extended.coordinator.async_create_issue", mock_create),
                patch("custom_components.mikrotik_extended.coordinator.async_delete_issue", mock_delete),
            ):
                yield

        return _ctx()

    async def test_wrong_login_creates_repair_issue(self, hass):
        """async_create_issue called with wrong_credentials when error is wrong_login."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "wrong_login"

        mock_create = MagicMock()

        with self._patch_severity_and_issues(mock_create, MagicMock()), pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        mock_create.assert_called_once()
        assert mock_create.call_args[0][2] == "wrong_credentials"

    async def test_ssl_error_creates_repair_issue(self, hass):
        """async_create_issue called with ssl_error for ssl_handshake_failure."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "ssl_handshake_failure"

        mock_create = MagicMock()

        with self._patch_severity_and_issues(mock_create, MagicMock()), pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        mock_create.assert_called_once()
        assert mock_create.call_args[0][2] == "ssl_error"

    async def test_ssl_verify_failure_creates_repair_issue(self, hass):
        """async_create_issue called with ssl_error for ssl_verify_failure."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "ssl_verify_failure"

        mock_create = MagicMock()

        with self._patch_severity_and_issues(mock_create, MagicMock()), pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert mock_create.call_args[0][2] == "ssl_error"

    async def test_repair_issue_not_called_when_async_create_issue_is_none(self, hass):
        """No error raised when async_create_issue is None (import failed)."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "wrong_login"

        with (
            patch("custom_components.mikrotik_extended.coordinator.IssueSeverity", None),
            patch("custom_components.mikrotik_extended.coordinator.async_create_issue", None),
            patch("custom_components.mikrotik_extended.coordinator.async_delete_issue", None),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await coordinator._async_update_data()

    async def test_repair_issues_deleted_on_successful_reconnect(self, hass):
        """async_delete_issue called for both issue keys after successful reconnect."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.last_hwinfo_update = datetime(1970, 1, 1)
        coordinator.api.has_reconnected.return_value = False
        coordinator.api.connected.return_value = True
        coordinator.api.error = ""

        mock_delete = MagicMock()

        with self._patch_severity_and_issues(MagicMock(), mock_delete), patch("custom_components.mikrotik_extended.coordinator.async_dispatcher_send"):
            await coordinator._async_update_data()

        deleted_issue_ids = [c[0][2] for c in mock_delete.call_args_list]
        assert "wrong_credentials" in deleted_issue_ids
        assert "ssl_error" in deleted_issue_ids

    async def test_wrong_login_triggers_reauth(self, hass):
        """ConfigEntryAuthFailed raised on wrong_login, which triggers reauth automatically."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "wrong_login"

        with self._patch_severity_and_issues(MagicMock(), MagicMock()), pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    async def test_non_wrong_login_error_does_not_trigger_reauth(self, hass):
        """async_start_reauth NOT called for non-auth errors."""
        coordinator = _make_coordinator(hass)
        self._stub_all_get_methods(coordinator)

        coordinator.api.has_reconnected.return_value = True
        coordinator.api.connected.return_value = False
        coordinator.api.error = "ssl_handshake_failure"

        mock_reauth = MagicMock()
        coordinator.config_entry.async_start_reauth = mock_reauth

        with self._patch_severity_and_issues(MagicMock(), MagicMock()), pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        mock_reauth.assert_not_called()
