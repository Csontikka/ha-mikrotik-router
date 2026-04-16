"""Mikrotik API for MikroTik Extended."""

import contextlib
import logging
import ssl
from threading import Lock
from time import sleep, time

import librouteros
from voluptuous import Optional

from .const import (
    DEFAULT_ENCODING,
    DEFAULT_LOGIN_METHOD,
)

_LOGGER = logging.getLogger(__name__)

SCRIPT_ENVIRONMENT_PATH = "/system/script/environment"


# ---------------------------
#   MikrotikAPI
# ---------------------------
class MikrotikAPI:
    """Handle all communication with the Mikrotik API."""

    def __init__(
        self,
        host,
        username,
        password,
        port=0,
        use_ssl=True,
        ssl_verify=True,
        login_method=DEFAULT_LOGIN_METHOD,
        encoding=DEFAULT_ENCODING,
    ):
        """Initialize the Mikrotik Client."""
        self._host = host
        self._use_ssl = use_ssl
        self._ssl_verify = ssl_verify
        self._port = port
        self._username = username
        self._password = password
        self._login_method = login_method
        self._encoding = encoding
        self._ssl_wrapper = None
        self.lock = Lock()

        self._connection = None
        self._connected = False
        self._reconnected = True
        self._connection_epoch = 0
        self._connection_retry_sec = 58
        self.error = None
        self.connection_error_reported = True  # suppress first disconnect after startup
        self._first_connect = True
        self.disable_health = False

        # Default ports
        if not self._port:
            self._port = 8729 if self._use_ssl else 8728

    # ---------------------------
    #   has_reconnected
    # ---------------------------
    def has_reconnected(self) -> bool:
        """Check if mikrotik has reconnected"""
        if self._reconnected:
            self._reconnected = False
            return True

        return False

    # ---------------------------
    #   connection_check
    # ---------------------------
    def connection_check(self) -> bool:
        """Check if mikrotik is connected"""
        if not self._connected or not self._connection:
            if self._connection_epoch > time() - self._connection_retry_sec:
                return False

            if not self.connect():
                return False

        return True

    # ---------------------------
    #   close
    # ---------------------------
    def close(self):
        """Gracefully close the API connection without logging errors."""
        self.connection_error_reported = True
        if self._connection:
            with contextlib.suppress(Exception):
                self._connection.close()
        self._reconnected = False
        self._connected = False
        self._connection = None
        self._connection_epoch = 0

    # ---------------------------
    #   disconnect
    # ---------------------------
    def disconnect(self, location="unknown", error=None):
        """Disconnect from Mikrotik device."""
        if not error:
            error = "unknown"

        if not self.connection_error_reported:
            if location == "unknown":
                _LOGGER.debug("Mikrotik %s connection closed", self._host)
            else:
                _LOGGER.warning("Mikrotik %s error while %s : %s", self._host, location, error)

            self.connection_error_reported = True

        self._reconnected = False
        self._connected = False
        self._connection = None
        self._connection_epoch = 0

    # ---------------------------
    #   connect
    # ---------------------------
    def connect(self) -> bool:
        """Connect to Mikrotik device."""
        self.error = ""
        self._connected = False
        self._connection_epoch = time()

        kwargs = {
            "encoding": self._encoding,
            "login_methods": self._login_method,
            "port": self._port,
        }

        with self.lock:
            try:
                if self._use_ssl:
                    if self._ssl_wrapper is None:
                        ssl_context = ssl.create_default_context()  # NOSONAR
                        if self._ssl_verify:
                            ssl_context.verify_mode = ssl.CERT_REQUIRED
                            ssl_context.verify_flags &= ~ssl.VERIFY_X509_STRICT
                        else:
                            ssl_context.check_hostname = False  # NOSONAR
                            ssl_context.verify_mode = ssl.CERT_NONE  # NOSONAR
                        self._ssl_wrapper = ssl_context.wrap_socket
                    kwargs["ssl_wrapper"] = self._ssl_wrapper
                self._connection = librouteros.connect(self._host, self._username, self._password, **kwargs)
            except Exception as e:
                if not self.connection_error_reported:
                    _LOGGER.error("Mikrotik %s error while connecting: %s", self._host, e)
                    self.connection_error_reported = True

                self.error_to_strings(f"{e}")
                self._connection = None
                return False
            else:
                if self.connection_error_reported and not self._first_connect:
                    _LOGGER.warning("Mikrotik Reconnected to %s", self._host)
                self.connection_error_reported = False
                self._first_connect = False

                self._connected = True
                self._reconnected = True

        return self._connected

    # ---------------------------
    #   error_to_strings
    # ---------------------------
    def error_to_strings(self, error):
        """Translate error output to error string."""
        self.error = "cannot_connect"
        if error == "invalid user name or password (6)":
            self.error = "wrong_login"

        if "ALERT_HANDSHAKE_FAILURE" in error:
            self.error = "ssl_handshake_failure"

        if "CERTIFICATE_VERIFY_FAILED" in error:
            self.error = "ssl_verify_failure"

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self) -> bool:
        """Return connected boolean."""
        return self._connected

    # ---------------------------
    #   query
    # ---------------------------
    def query(self, path, command=None, args=None, return_list=True) -> Optional(list):
        """Retrieve data from Mikrotik API."""
        """Returns generator object, unless return_list passed as True"""
        if path == "/system/health" and self.disable_health:
            return None

        if args is None:
            args = {}

        if not self.connection_check():
            return None

        with self.lock:
            try:
                _LOGGER.debug("API query: %s", path)
                response = self._connection.path(path)
            except Exception as e:
                self.disconnect("path", e)
                return None

            if response and return_list and not command:
                try:
                    response = list(response)
                    _LOGGER.debug("API query %s returned %d entries", path, len(response) if response else 0)
                    _LOGGER.debug("API query %s raw response: %s", path, response)
                except Exception as e:
                    if path == "/system/health" and "no such command prefix" in str(e):
                        self.disable_health = True
                        return None

                    if "no such command prefix" in str(e):
                        _LOGGER.debug("Mikrotik %s path %s not available: %s", self._host, path, e)
                        return None

                    self.disconnect(f"building list for path {path}", e)
                    return None

            elif response and command:
                _LOGGER.debug("API query: %s, %s, %s", path, command, args)
                try:
                    response = list(response(command, **args))
                except Exception as e:
                    self.disconnect("path", e)
                    return None

        return response or None

    # ---------------------------
    #   set_value
    # ---------------------------
    def set_value(self, path, param, value, mod_param, mod_value) -> bool:
        """Modify a parameter"""
        _LOGGER.debug(
            "Mikrotik %s set_value: path=%s param=%s value=%s mod_param=%s mod_value=%s",
            self._host,
            path,
            param,
            value,
            mod_param,
            mod_value,
        )
        entry_found = None

        if not self.connection_check():
            return False

        response = self.query(path, return_list=False)
        if response is None:
            return False

        for tmp in response:
            if param not in tmp:
                continue

            if tmp[param] != value:
                continue

            entry_found = tmp[".id"]

        if not entry_found:
            _LOGGER.warning(
                "Mikrotik %s set_value parameter %s with value %s not found",
                self._host,
                param,
                value,
            )
            return False

        params = {".id": entry_found, mod_param: mod_value}
        with self.lock:
            try:
                response.update(**params)
            except Exception as e:
                self.disconnect("set_value", e)
                return False

        return True

    # ---------------------------
    #   execute
    # ---------------------------
    def execute(self, path, command, param, value, attributes=None) -> bool:
        """Execute a command"""
        entry_found = None
        params = {}

        if not self.connection_check():
            return False

        response = self.query(path, return_list=False)
        if response is None:
            return False

        if param:
            for tmp in response:
                if param not in tmp:
                    continue

                if tmp[param] != value:
                    continue

                entry_found = tmp[".id"]

            if not entry_found:
                _LOGGER.warning(
                    "Mikrotik %s Execute %s parameter %s with value %s not found",
                    self._host,
                    command,
                    param,
                    value,
                )
                return False

            params = {".id": entry_found}

        if attributes:
            params.update(attributes)

        with self.lock:
            try:
                tuple(response(command, **params))
            except Exception as e:
                self.disconnect("execute", e)
                return False

        return True

    # ---------------------------
    #   wol
    # ---------------------------
    def wol(self, mac: str, interface: str | None = None) -> bool:
        """Send Wake-on-LAN magic packet via MikroTik /tool wol"""
        if not self.connection_check():
            return False

        args = {"mac": mac}
        if interface and interface != "unknown":
            args["interface"] = interface

        with self.lock:
            try:
                _LOGGER.debug(
                    "WoL: sending magic packet to %s via %s",
                    mac,
                    interface or "broadcast",
                )
                response = self._connection.path("/tool")
                tuple(response("wol", **args))
            except Exception as e:
                self.disconnect("wol", e)
                return False

        return True

    # ---------------------------
    #   run_script
    # ---------------------------
    def run_script(self, name) -> bool:
        """Run script"""
        entry_found = None
        if not self.connection_check():
            return False

        response = self.query("/system/script", return_list=False)
        if response is None:
            return False

        with self.lock:
            for tmp in response:
                if "name" not in tmp:
                    continue

                if tmp["name"] != name:
                    continue

                entry_found = tmp[".id"]

            if not entry_found:
                _LOGGER.error("Mikrotik %s Script %s not found", self._host, name)
                return False

            try:
                run = response("run", **{".id": entry_found})
                tuple(run)
            except Exception as e:
                self.disconnect("run_script", e)
                return False

        return True

    # ---------------------------
    #   set_env_variable
    # ---------------------------
    def set_env_variable(self, name, value) -> bool:
        """Create or update a RouterOS script environment variable."""
        if not self.connection_check():
            return False

        with self.lock:
            # Check if variable already exists
            try:
                env = self._connection.path(SCRIPT_ENVIRONMENT_PATH)
                entries = list(env)
                entry_id = None
                for e in entries:
                    if e.get("name") == name:
                        entry_id = e[".id"]
                        break
            except Exception as e:
                self.disconnect("set_env_variable", e)
                return False

            if entry_id:
                # Update existing variable directly via API
                try:
                    env.update(**{".id": entry_id, "value": str(value)})
                except Exception as e:
                    self.disconnect("set_env_variable", e)
                    return False
                return True

            # Variable doesn't exist — create via one-shot scheduler
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            sched_name = "_ha_env_set"
            on_event = f':global {name} "{escaped}"; /system/scheduler/remove [find name={sched_name}]'
            try:
                sched = self._connection.path("/system/scheduler")
                tuple(sched("add", name=sched_name, **{"on-event": on_event, "interval": "1s"}))
            except Exception as e:
                self.disconnect("set_env_variable", e)
                return False

        # Wait for scheduler to execute (runs within 1s)
        sleep(2)

        # Verify the variable was created
        with self.lock:
            try:
                env2 = self._connection.path(SCRIPT_ENVIRONMENT_PATH)
                for e in env2:
                    if e.get("name") == name:
                        return True
            except Exception as e:
                self.disconnect("set_env_variable", e)
                return False

            # Clean up scheduler if it didn't self-delete
            try:
                sched2 = self._connection.path("/system/scheduler")
                for s in sched2:
                    if s.get("name") == sched_name:
                        sched2.remove(s[".id"])
            except Exception:
                pass

        _LOGGER.error("Mikrotik %s env variable %s not created by scheduler", self._host, name)
        return False

    # ---------------------------
    #   remove_env_variable
    # ---------------------------
    def remove_env_variable(self, name) -> bool:
        """Remove a RouterOS script environment variable."""
        if not self.connection_check():
            return False

        with self.lock:
            try:
                env = self._connection.path(SCRIPT_ENVIRONMENT_PATH)
                entries = list(env)
                for e in entries:
                    if e.get("name") == name:
                        env.remove(e[".id"])
                        return True
            except Exception as e:
                self.disconnect("remove_env_variable", e)
                return False

        _LOGGER.warning("Mikrotik %s env variable %s not found", self._host, name)
        return False

    # ---------------------------
    #   arp_ping
    # ---------------------------
    def arp_ping(self, address, interface) -> bool:
        """Check arp ping response traffic stats"""
        if not self.connection_check():
            return False

        response = self.query("/ping", return_list=False)
        if response is None:
            return False

        args = {
            "arp-ping": "no",
            "interval": "100ms",
            "count": 3,
            "interface": interface,
            "address": address,
        }
        with self.lock:
            try:
                # _LOGGER.debug("Ping host query: %s", args["address"])
                ping = response("/ping", **args)
            except Exception as e:
                self.disconnect("arp_ping", e)
                return False

            try:
                ping = list(ping)
            except Exception as e:
                self.disconnect("arp_ping", e)
                return False

        for tmp in ping:
            if "received" in tmp and tmp["received"] > 0:
                _LOGGER.debug("Ping host success: %s", args["address"])
                return True

        _LOGGER.debug("Ping host failure: %s", args["address"])
        return False
