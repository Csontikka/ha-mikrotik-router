"""Tests for MikrotikAPI class."""

from time import time
from unittest.mock import MagicMock, patch

from custom_components.mikrotik_extended.mikrotikapi import MikrotikAPI


class TestMikrotikAPIInit:
    def test_default_ssl_port(self):
        api = MikrotikAPI("192.168.88.1", "admin", "pass", port=0, use_ssl=True)
        assert api._port == 8729

    def test_default_plaintext_port(self):
        api = MikrotikAPI("192.168.88.1", "admin", "pass", port=0, use_ssl=False)
        assert api._port == 8728

    def test_custom_port(self):
        api = MikrotikAPI("192.168.88.1", "admin", "pass", port=9999)
        assert api._port == 9999

    def test_initial_state(self):
        api = MikrotikAPI("192.168.88.1", "admin", "pass")
        assert api.connected() is False
        assert api.error is None
        assert api.connection_error_reported is True  # suppressed until first successful connect


class TestErrorToStrings:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")

    def test_wrong_login(self):
        self.api.error_to_strings("invalid user name or password (6)")
        assert self.api.error == "wrong_login"

    def test_ssl_handshake(self):
        self.api.error_to_strings("some ALERT_HANDSHAKE_FAILURE error")
        assert self.api.error == "ssl_handshake_failure"

    def test_ssl_verify(self):
        self.api.error_to_strings("CERTIFICATE_VERIFY_FAILED blah")
        assert self.api.error == "ssl_verify_failure"

    def test_generic_error(self):
        self.api.error_to_strings("connection refused")
        assert self.api.error == "cannot_connect"


class TestConnect:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass", use_ssl=False)

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_successful_connect(self, mock_connect):
        mock_connect.return_value = MagicMock()
        result = self.api.connect()
        assert result is True
        assert self.api.connected() is True
        assert self.api._reconnected is True

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_failed_connect(self, mock_connect):
        mock_connect.side_effect = Exception("connection refused")
        result = self.api.connect()
        assert result is False
        assert self.api.connected() is False
        assert self.api.error == "cannot_connect"

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_wrong_login_connect(self, mock_connect):
        mock_connect.side_effect = Exception("invalid user name or password (6)")
        result = self.api.connect()
        assert result is False
        assert self.api.error == "wrong_login"

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_reconnect_logs_warning(self, mock_connect):
        """Covers lines 161-162: reconnect warning path (first_connect=False)."""
        mock_connect.return_value = MagicMock()
        self.api.connection_error_reported = True
        self.api._first_connect = False
        result = self.api.connect()
        assert result is True
        assert self.api.connection_error_reported is False

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_failed_connect_reports_error_once(self, mock_connect):
        """Covers lines 154-155: connection_error_reported=False logs error then sets True."""
        mock_connect.side_effect = Exception("connection refused")
        self.api.connection_error_reported = False
        result = self.api.connect()
        assert result is False
        assert self.api.connection_error_reported is True


class TestConnectSsl:
    """Covers lines 141-150: SSL-specific connect branches."""

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_ssl_verify_true(self, mock_connect):
        mock_connect.return_value = MagicMock()
        api = MikrotikAPI("192.168.88.1", "admin", "pass", use_ssl=True, ssl_verify=True)
        result = api.connect()
        assert result is True
        assert api._ssl_wrapper is not None

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_ssl_verify_false(self, mock_connect):
        mock_connect.return_value = MagicMock()
        api = MikrotikAPI("192.168.88.1", "admin", "pass", use_ssl=True, ssl_verify=False)
        result = api.connect()
        assert result is True
        assert api._ssl_wrapper is not None

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_ssl_wrapper_cached(self, mock_connect):
        """Second connect reuses ssl_wrapper without re-creating."""
        mock_connect.return_value = MagicMock()
        api = MikrotikAPI("192.168.88.1", "admin", "pass", use_ssl=True)
        api.connect()
        first_wrapper = api._ssl_wrapper
        api.connect()
        assert api._ssl_wrapper is first_wrapper


class TestClose:
    """Covers lines 93-100: close() method."""

    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")

    def test_close_with_connection(self):
        mock_conn = MagicMock()
        self.api._connection = mock_conn
        self.api._connected = True
        self.api.close()
        mock_conn.close.assert_called_once()
        assert self.api._connected is False
        assert self.api._connection is None
        assert self.api._connection_epoch == 0
        assert self.api.connection_error_reported is True

    def test_close_without_connection(self):
        self.api._connection = None
        self.api.close()
        assert self.api._connected is False

    def test_close_swallows_exception(self):
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("close failed")
        self.api._connection = mock_conn
        # Should not raise
        self.api.close()
        assert self.api._connection is None


class TestDisconnect:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_disconnect_clears_state(self):
        self.api.disconnect("test", "some error")
        assert self.api._connected is False
        assert self.api._connection is None
        assert self.api._connection_epoch == 0

    def test_disconnect_sets_error_reported(self):
        self.api.disconnect("test", "some error")
        assert self.api.connection_error_reported is True

    def test_disconnect_only_reports_once(self):
        self.api.disconnect("test", "error1")
        assert self.api.connection_error_reported is True
        # Second disconnect should not re-log
        self.api.connection_error_reported = True
        self.api.disconnect("test2", "error2")
        assert self.api.connection_error_reported is True

    def test_disconnect_no_error_defaults_unknown(self):
        """Covers line 108: error is None -> set to 'unknown'."""
        self.api.connection_error_reported = False
        self.api.disconnect("somewhere", None)
        assert self.api.connection_error_reported is True

    def test_disconnect_unknown_location_debug_path(self):
        """Covers lines 111-112: location == 'unknown' goes down debug branch."""
        self.api.connection_error_reported = False
        self.api.disconnect("unknown", "some error")
        assert self.api.connection_error_reported is True

    def test_disconnect_named_location_warning_path(self):
        """Covers lines 113-116: named location logs warning."""
        self.api.connection_error_reported = False
        self.api.disconnect("query", "timeout")
        assert self.api.connection_error_reported is True


class TestHasReconnected:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")

    def test_returns_true_once(self):
        self.api._reconnected = True
        assert self.api.has_reconnected() is True
        assert self.api.has_reconnected() is False

    def test_returns_false_when_not_reconnected(self):
        self.api._reconnected = False
        assert self.api.has_reconnected() is False


class TestConnectionCheck:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass", use_ssl=False)

    def test_connected_returns_true(self):
        self.api._connected = True
        self.api._connection = MagicMock()
        assert self.api.connection_check() is True

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_disconnected_tries_reconnect(self, mock_connect):
        mock_connect.return_value = MagicMock()
        self.api._connected = False
        self.api._connection = None
        self.api._connection_epoch = 0
        result = self.api.connection_check()
        assert result is True
        mock_connect.assert_called_once()

    def test_recent_failure_skips_reconnect(self):
        self.api._connected = False
        self.api._connection = None
        self.api._connection_epoch = time()  # just failed
        result = self.api.connection_check()
        assert result is False

    @patch("custom_components.mikrotik_extended.mikrotikapi.librouteros.connect")
    def test_reconnect_fails_returns_false(self, mock_connect):
        """Covers line 84: connect() returns False -> connection_check returns False."""
        mock_connect.side_effect = Exception("down")
        self.api._connected = False
        self.api._connection = None
        self.api._connection_epoch = 0
        result = self.api.connection_check()
        assert result is False


class TestConnected:
    def test_connected_returns_internal_state(self):
        api = MikrotikAPI("192.168.88.1", "admin", "pass")
        api._connected = True
        assert api.connected() is True
        api._connected = False
        assert api.connected() is False


class TestQuery:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_query_returns_list(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{"name": "eth0"}]))
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/interface")
        assert result == [{"name": "eth0"}]

    def test_query_returns_none_when_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        result = self.api.query("/interface")
        assert result is None

    def test_query_health_disabled(self):
        self.api.disable_health = True
        result = self.api.query("/system/health")
        assert result is None

    def test_query_path_exception_disconnects(self):
        self.api._connection.path.side_effect = Exception("timeout")
        result = self.api.query("/interface")
        assert result is None
        assert self.api.connected() is False

    def test_query_list_exception_disconnects(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(side_effect=Exception("broken"))
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/interface")
        assert result is None
        assert self.api.connected() is False

    def test_query_no_such_command_returns_none(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(side_effect=Exception("no such command prefix"))
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/interface")
        assert result is None
        # Should NOT disconnect for "no such command"
        assert self.api.connected() is True

    def test_query_health_no_such_command_disables(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(side_effect=Exception("no such command prefix"))
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/system/health")
        assert result is None
        assert self.api.disable_health is True

    def test_query_with_command(self):
        mock_path = MagicMock()
        mock_path.return_value = [{"result": "ok"}]
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/system/reboot", command="reboot")
        assert result == [{"result": "ok"}]

    def test_query_with_command_exception(self):
        """Covers lines 237-239: exception raised when running command."""
        mock_path = MagicMock()
        mock_path.side_effect = Exception("boom")
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/system/reboot", command="reboot")
        assert result is None
        assert self.api.connected() is False

    def test_query_empty_response_returns_none(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([]))
        self.api._connection.path.return_value = mock_path
        result = self.api.query("/interface")
        assert result is None


class TestSetValue:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_set_value_success(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "eth0"}]))
        mock_path.update = MagicMock()
        self.api._connection.path.return_value = mock_path
        result = self.api.set_value("/interface", "name", "eth0", "disabled", True)
        assert result is True
        mock_path.update.assert_called_once_with(**{".id": "*1", "disabled": True})

    def test_set_value_not_found(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "eth0"}]))
        self.api._connection.path.return_value = mock_path
        result = self.api.set_value("/interface", "name", "eth99", "disabled", True)
        assert result is False

    def test_set_value_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        result = self.api.set_value("/interface", "name", "eth0", "disabled", True)
        assert result is False

    def test_set_value_query_returns_none(self):
        """Covers line 264: response is None -> return False."""
        self.api._connection.path.side_effect = Exception("timeout")
        result = self.api.set_value("/interface", "name", "eth0", "disabled", True)
        assert result is False

    def test_set_value_param_not_in_entry(self):
        """Covers line 268: param not in entry -> continue."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(
            return_value=iter(
                [
                    {".id": "*1", "something_else": "x"},  # missing 'name'
                    {".id": "*2", "name": "eth0"},
                ]
            )
        )
        mock_path.update = MagicMock()
        self.api._connection.path.return_value = mock_path
        result = self.api.set_value("/interface", "name", "eth0", "disabled", True)
        assert result is True
        mock_path.update.assert_called_once_with(**{".id": "*2", "disabled": True})

    def test_set_value_update_exception(self):
        """Covers lines 288-290: update raises exception."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "eth0"}]))
        mock_path.update = MagicMock(side_effect=Exception("update failed"))
        self.api._connection.path.return_value = mock_path
        result = self.api.set_value("/interface", "name", "eth0", "disabled", True)
        assert result is False
        assert self.api.connected() is False


class TestExecute:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_execute_success(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "script1"}]))
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.execute("/system/script", "run", "name", "script1")
        assert result is True

    def test_execute_not_found(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "script1"}]))
        self.api._connection.path.return_value = mock_path
        result = self.api.execute("/system/script", "run", "name", "nonexistent")
        assert result is False

    def test_execute_no_param(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([]))
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.execute("/system/reboot", "reboot", None, None)
        assert result is True

    def test_execute_disconnected(self):
        """Covers line 303: connection_check fails -> return False."""
        self.api._connected = False
        self.api._connection_epoch = time()
        result = self.api.execute("/x", "y", None, None)
        assert result is False

    def test_execute_query_returns_none(self):
        """Covers line 307: response None -> return False."""
        self.api._connection.path.side_effect = Exception("timeout")
        result = self.api.execute("/x", "y", None, None)
        assert result is False

    def test_execute_param_not_in_entry(self):
        """Covers line 312: param not in tmp -> continue."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(
            return_value=iter(
                [
                    {".id": "*1", "other": "x"},
                    {".id": "*2", "name": "script1"},
                ]
            )
        )
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.execute("/system/script", "run", "name", "script1")
        assert result is True

    def test_execute_with_attributes(self):
        """Covers line 332: attributes passed and merged."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([]))
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.execute("/system/reboot", "reboot", None, None, attributes={"force": True})
        assert result is True

    def test_execute_command_exception(self):
        """Covers lines 337-339: exception during tuple(response(...))."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([]))
        mock_path.side_effect = Exception("exec failed")
        self.api._connection.path.return_value = mock_path
        result = self.api.execute("/x", "y", None, None)
        assert result is False
        assert self.api.connected() is False


class TestWol:
    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_wol_with_interface(self):
        mock_path = MagicMock()
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.wol("AA:BB:CC:DD:EE:FF", "ether1")
        assert result is True

    def test_wol_without_interface(self):
        mock_path = MagicMock()
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.wol("AA:BB:CC:DD:EE:FF")
        assert result is True

    def test_wol_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        result = self.api.wol("AA:BB:CC:DD:EE:FF")
        assert result is False

    def test_wol_unknown_interface_ignored(self):
        mock_path = MagicMock()
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        result = self.api.wol("AA:BB:CC:DD:EE:FF", "unknown")
        assert result is True

    def test_wol_exception(self):
        """Covers lines 364-366: exception -> disconnect."""
        self.api._connection.path.side_effect = Exception("wol failed")
        result = self.api.wol("AA:BB:CC:DD:EE:FF")
        assert result is False
        assert self.api.connected() is False


class TestRunScript:
    """Covers lines 375-404: run_script."""

    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_run_script_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        assert self.api.run_script("myscript") is False

    def test_run_script_query_returns_none(self):
        self.api._connection.path.side_effect = Exception("timeout")
        assert self.api.run_script("myscript") is False

    def test_run_script_not_found(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "other_script"}]))
        self.api._connection.path.return_value = mock_path
        assert self.api.run_script("myscript") is False

    def test_run_script_skips_entry_without_name(self):
        """Covers 'name' not in tmp -> continue."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(
            return_value=iter(
                [
                    {".id": "*1"},  # no name
                    {".id": "*2", "name": "myscript"},
                ]
            )
        )
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        assert self.api.run_script("myscript") is True

    def test_run_script_success(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "myscript"}]))
        mock_path.return_value = iter([])
        self.api._connection.path.return_value = mock_path
        assert self.api.run_script("myscript") is True

    def test_run_script_run_exception(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{".id": "*1", "name": "myscript"}]))
        mock_path.side_effect = Exception("run failed")
        self.api._connection.path.return_value = mock_path
        assert self.api.run_script("myscript") is False
        assert self.api.connected() is False


class TestSetEnvVariable:
    """Covers lines 411-472: set_env_variable."""

    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_set_env_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        assert self.api.set_env_variable("myvar", "x") is False

    def test_set_env_update_existing(self):
        """Existing variable -> update directly."""
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([{".id": "*e1", "name": "myvar", "value": "old"}]))
        env_path.update = MagicMock()
        self.api._connection.path.return_value = env_path
        assert self.api.set_env_variable("myvar", "new_val") is True
        env_path.update.assert_called_once()

    def test_set_env_update_existing_exception(self):
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([{".id": "*e1", "name": "myvar", "value": "old"}]))
        env_path.update = MagicMock(side_effect=Exception("update error"))
        self.api._connection.path.return_value = env_path
        assert self.api.set_env_variable("myvar", "new_val") is False
        assert self.api.connected() is False

    def test_set_env_list_exception(self):
        """Exception while listing env variables."""
        self.api._connection.path.side_effect = Exception("list failed")
        assert self.api.set_env_variable("myvar", "x") is False
        assert self.api.connected() is False

    @patch("custom_components.mikrotik_extended.mikrotikapi.sleep")
    def test_set_env_create_via_scheduler_success(self, mock_sleep):
        """Create variable via scheduler and verify after sleep."""
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([]))  # no existing
        sched_path = MagicMock()
        sched_path.return_value = iter([])
        env_path_after = MagicMock()
        env_path_after.__iter__ = MagicMock(return_value=iter([{".id": "*e1", "name": "myvar", "value": "x"}]))
        # path called 3 times: env list, sched add, env verify
        self.api._connection.path.side_effect = [env_path, sched_path, env_path_after]
        assert self.api.set_env_variable("myvar", 'val"with"quotes') is True
        mock_sleep.assert_called_once_with(2)

    @patch("custom_components.mikrotik_extended.mikrotikapi.sleep")
    def test_set_env_scheduler_add_exception(self, mock_sleep):
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([]))
        sched_path = MagicMock()
        sched_path.side_effect = Exception("sched add failed")
        self.api._connection.path.side_effect = [env_path, sched_path]
        assert self.api.set_env_variable("myvar", "x") is False
        assert self.api.connected() is False

    @patch("custom_components.mikrotik_extended.mikrotikapi.sleep")
    def test_set_env_verify_exception(self, mock_sleep):
        """Scheduler succeeded but verify-read raises."""
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([]))
        sched_path = MagicMock()
        sched_path.return_value = iter([])
        verify_path = MagicMock()
        verify_path.__iter__ = MagicMock(side_effect=Exception("verify failed"))
        self.api._connection.path.side_effect = [env_path, sched_path, verify_path]
        assert self.api.set_env_variable("myvar", "x") is False
        assert self.api.connected() is False

    @patch("custom_components.mikrotik_extended.mikrotikapi.sleep")
    def test_set_env_verify_not_found_cleans_up_scheduler(self, mock_sleep):
        """Verify doesn't find var, cleanup scheduler step triggered."""
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([]))
        sched_path = MagicMock()
        sched_path.return_value = iter([])
        verify_path = MagicMock()
        verify_path.__iter__ = MagicMock(return_value=iter([]))  # not created
        cleanup_sched = MagicMock()
        cleanup_sched.__iter__ = MagicMock(return_value=iter([{".id": "*s1", "name": "_ha_env_set"}]))
        cleanup_sched.remove = MagicMock()
        self.api._connection.path.side_effect = [
            env_path,
            sched_path,
            verify_path,
            cleanup_sched,
        ]
        assert self.api.set_env_variable("myvar", "x") is False
        cleanup_sched.remove.assert_called_once_with("*s1")

    @patch("custom_components.mikrotik_extended.mikrotikapi.sleep")
    def test_set_env_verify_not_found_cleanup_swallows_exception(self, mock_sleep):
        """Cleanup branch where iteration raises — exception swallowed."""
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([]))
        sched_path = MagicMock()
        sched_path.return_value = iter([])
        verify_path = MagicMock()
        verify_path.__iter__ = MagicMock(return_value=iter([]))
        cleanup_sched = MagicMock()
        cleanup_sched.__iter__ = MagicMock(side_effect=Exception("cleanup error"))
        self.api._connection.path.side_effect = [
            env_path,
            sched_path,
            verify_path,
            cleanup_sched,
        ]
        # Should return False but not raise
        assert self.api.set_env_variable("myvar", "x") is False


class TestRemoveEnvVariable:
    """Covers lines 479-495: remove_env_variable."""

    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_remove_env_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        assert self.api.remove_env_variable("myvar") is False

    def test_remove_env_success(self):
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([{".id": "*e1", "name": "myvar"}]))
        env_path.remove = MagicMock()
        self.api._connection.path.return_value = env_path
        assert self.api.remove_env_variable("myvar") is True
        env_path.remove.assert_called_once_with("*e1")

    def test_remove_env_not_found(self):
        env_path = MagicMock()
        env_path.__iter__ = MagicMock(return_value=iter([{".id": "*e1", "name": "other"}]))
        self.api._connection.path.return_value = env_path
        assert self.api.remove_env_variable("myvar") is False

    def test_remove_env_exception(self):
        self.api._connection.path.side_effect = Exception("remove failed")
        assert self.api.remove_env_variable("myvar") is False
        assert self.api.connected() is False


class TestArpPing:
    """Covers lines 502-536: arp_ping."""

    def setup_method(self):
        self.api = MikrotikAPI("192.168.88.1", "admin", "pass")
        self.api._connected = True
        self.api._connection = MagicMock()

    def test_arp_ping_disconnected(self):
        self.api._connected = False
        self.api._connection_epoch = time()
        assert self.api.arp_ping("1.2.3.4", "ether1") is False

    def test_arp_ping_query_returns_none(self):
        self.api._connection.path.side_effect = Exception("timeout")
        assert self.api.arp_ping("1.2.3.4", "ether1") is False

    def test_arp_ping_success(self):
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{"seq": 1}]))

        ping_gen = MagicMock()
        ping_gen.__iter__ = MagicMock(return_value=iter([{"received": 1}]))
        mock_path.return_value = ping_gen

        self.api._connection.path.return_value = mock_path
        assert self.api.arp_ping("1.2.3.4", "ether1") is True

    def test_arp_ping_no_response(self):
        """received == 0 -> return False."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{"seq": 1}]))
        ping_gen = MagicMock()
        ping_gen.__iter__ = MagicMock(return_value=iter([{"received": 0}]))
        mock_path.return_value = ping_gen
        self.api._connection.path.return_value = mock_path
        assert self.api.arp_ping("1.2.3.4", "ether1") is False

    def test_arp_ping_no_received_key(self):
        """ping results without 'received' key -> return False."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{"seq": 1}]))
        ping_gen = MagicMock()
        ping_gen.__iter__ = MagicMock(return_value=iter([{"sent": 3}]))
        mock_path.return_value = ping_gen
        self.api._connection.path.return_value = mock_path
        assert self.api.arp_ping("1.2.3.4", "ether1") is False

    def test_arp_ping_call_exception(self):
        """response(/ping, **args) raises -> disconnect."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{"seq": 1}]))
        mock_path.side_effect = Exception("ping call failed")
        self.api._connection.path.return_value = mock_path
        assert self.api.arp_ping("1.2.3.4", "ether1") is False
        assert self.api.connected() is False

    def test_arp_ping_list_exception(self):
        """list(ping) raises -> disconnect."""
        mock_path = MagicMock()
        mock_path.__iter__ = MagicMock(return_value=iter([{"seq": 1}]))
        ping_gen = MagicMock()
        ping_gen.__iter__ = MagicMock(side_effect=Exception("list failed"))
        mock_path.return_value = ping_gen
        self.api._connection.path.return_value = mock_path
        assert self.api.arp_ping("1.2.3.4", "ether1") is False
        assert self.api.connected() is False
