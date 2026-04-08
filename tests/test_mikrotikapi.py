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
        mock_connect.return_value = MagicMock()
        self.api.connection_error_reported = True
        result = self.api.connect()
        assert result is True
        assert self.api.connection_error_reported is False


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
