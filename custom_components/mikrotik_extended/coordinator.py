"""Mikrotik coordinator."""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from mac_vendor_lookup import AsyncMacLookup

try:
    from homeassistant.components.repairs import (
        IssueSeverity,
        async_create_issue,
        async_delete_issue,
    )
except ImportError:
    try:
        from homeassistant.components.repairs import (
            async_create_issue,
            async_delete_issue,
        )
        from homeassistant.helpers.issue_registry import IssueSeverity
    except ImportError:
        async_create_issue = None
        async_delete_issue = None
        IssueSeverity = None
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    CONF_ZONE,
    STATE_HOME,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .apiparser import parse_api
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SENSOR_CLIENT_CAPTIVE,
    CONF_SENSOR_CLIENT_TRAFFIC,
    CONF_SENSOR_CONTAINERS,
    CONF_SENSOR_ENVIRONMENT,
    CONF_SENSOR_FILTER,
    CONF_SENSOR_KIDCONTROL,
    CONF_SENSOR_MANGLE,
    CONF_SENSOR_NAT,
    CONF_SENSOR_NETWATCH_TRACKER,
    CONF_SENSOR_PORT_TRAFFIC,
    CONF_SENSOR_PPP,
    CONF_SENSOR_ROUTING_RULES,
    CONF_SENSOR_SCRIPTS,
    CONF_SENSOR_SIMPLE_QUEUES,
    CONF_SENSOR_WIREGUARD,
    CONF_TRACK_HOSTS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SENSOR_CLIENT_CAPTIVE,
    DEFAULT_SENSOR_CLIENT_TRAFFIC,
    DEFAULT_SENSOR_CONTAINERS,
    DEFAULT_SENSOR_ENVIRONMENT,
    DEFAULT_SENSOR_FILTER,
    DEFAULT_SENSOR_KIDCONTROL,
    DEFAULT_SENSOR_MANGLE,
    DEFAULT_SENSOR_NAT,
    DEFAULT_SENSOR_NETWATCH_TRACKER,
    DEFAULT_SENSOR_PORT_TRAFFIC,
    DEFAULT_SENSOR_PPP,
    DEFAULT_SENSOR_ROUTING_RULES,
    DEFAULT_SENSOR_SCRIPTS,
    DEFAULT_SENSOR_SIMPLE_QUEUES,
    DEFAULT_SENSOR_WIREGUARD,
    DEFAULT_TRACK_HOSTS,
    DOMAIN,
)
from .mikrotikapi import MikrotikAPI

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIME_ZONE = None

PATH_INTERFACE_ETHERNET = "/interface/ethernet"
PATH_IP_KID_CONTROL = "/ip/kid-control"
PPP_NOT_CONNECTED = "not connected"


def _parse_uptime_str(uptime_str: str) -> int:
    """Parse a RouterOS uptime string like ``1w2d3h4m5s`` into seconds."""
    multipliers = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    total = 0
    current = ""
    for char in uptime_str:
        if char.isdigit():
            current += char
        elif char in multipliers and current:
            total += int(current) * multipliers[char]
            current = ""
    return total


def _should_update_uptime(current, uptime_tm) -> bool:
    """Decide whether to refresh the stored uptime timestamp."""
    if not current:
        return True
    uptime_old = datetime.timestamp(current)
    return uptime_tm > uptime_old + 10


def _percent_usage(total, free):
    """Return percent-used for a total/free pair, or 'unknown' when total<=0."""
    if total > 0:
        return round(((total - free) / total) * 100)
    return "unknown"


def _package_enabled(packages: dict, name: str) -> bool:
    """Return True when ``name`` is present and enabled in the packages dict."""
    return name in packages and packages[name]["enabled"]


def _split_queue_fields(entry: dict, vals: dict) -> None:
    """Populate upload/download split fields on a queue entry in place."""
    entry["comment"] = str(entry["comment"])
    if "uniq-id" not in entry:
        entry["uniq-id"] = entry["name"]

    _bps_split_pair = [
        ("max-limit", "upload-max-limit", "download-max-limit"),
        ("rate", "upload-rate", "download-rate"),
        ("limit-at", "upload-limit-at", "download-limit-at"),
        ("burst-limit", "upload-burst-limit", "download-burst-limit"),
        ("burst-threshold", "upload-burst-threshold", "download-burst-threshold"),
    ]
    for source_key, up_key, down_key in _bps_split_pair:
        up_bps, down_bps = [int(x) for x in vals[source_key].split("/")]
        entry[up_key] = f"{up_bps} bps"
        entry[down_key] = f"{down_bps} bps"

    upload_burst_time, download_burst_time = vals["burst-time"].split("/")
    entry["upload-burst-time"] = upload_burst_time
    entry["download-burst-time"] = download_burst_time


def _parse_duration_seconds(s: str) -> int:
    """Parse a MikroTik duration string like '3m45s' into total seconds."""
    if not s or s.lower() in ("never", ""):
        return 0
    total = 0
    for pattern, multiplier in [
        (r"(\d+)w", 604800),
        (r"(\d+)d", 86400),
        (r"(\d+)h", 3600),
        (r"(\d+)m", 60),
        (r"(\d+)s", 1),
    ]:
        m = re.search(pattern, s)
        if m:
            total += int(m.group(1)) * multiplier
    return total


def is_valid_ip(address):
    try:
        ipaddress.ip_address(address)
        return True
    except ValueError:
        return False


def utc_from_timestamp(timestamp: float) -> datetime:
    """Return a UTC time from a timestamp."""
    return datetime.fromtimestamp(timestamp, tz=UTC)


def as_local(dattim: datetime) -> datetime:
    """Convert a UTC datetime object to local time zone."""
    if dattim.tzinfo == DEFAULT_TIME_ZONE:
        return dattim
    if dattim.tzinfo is None:
        dattim = dattim.replace(tzinfo=UTC)

    return dattim.astimezone(DEFAULT_TIME_ZONE)


@dataclass
class MikrotikData:
    """Data for the mikrotik integration."""

    data_coordinator: MikrotikCoordinator
    tracker_coordinator: MikrotikTrackerCoordinator


class MikrotikTrackerCoordinator(DataUpdateCoordinator[None]):
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        coordinator: MikrotikCoordinator,
    ):
        """Initialize MikrotikTrackerCoordinator."""
        self.hass = hass
        self.config_entry: ConfigEntry = config_entry
        self.coordinator = coordinator

        super().__init__(
            self.hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=10),
        )
        self.name = config_entry.data[CONF_NAME]
        self.host = config_entry.data[CONF_HOST]

        self.api = MikrotikAPI(
            config_entry.data[CONF_HOST],
            config_entry.data[CONF_USERNAME],
            config_entry.data[CONF_PASSWORD],
            config_entry.data[CONF_PORT],
            config_entry.data[CONF_SSL],
            config_entry.data[CONF_VERIFY_SSL],
        )

    # ---------------------------
    #   option_zone
    # ---------------------------
    @property
    def option_zone(self):
        """Config entry option zones."""
        return self.config_entry.options.get(CONF_ZONE, STATE_HOME)

    # ---------------------------
    #   _async_update_data
    # ---------------------------
    @staticmethod
    def _fill_host_defaults(host: dict) -> None:
        """Populate missing default fields on a host entry."""
        defaults = {
            "address": "unknown",
            "mac-address": "unknown",
            "interface": "unknown",
            "host-name": "unknown",
            "last-seen": False,
            "available": False,
        }
        for key, default in defaults.items():
            if key not in host:
                host[key] = default

    def _should_ping_host(self, host) -> bool:
        """Return True if the host should be arp-pinged this refresh."""
        return self.coordinator.host_tracking_initialized and host["source"] not in ["capsman", "wireless"] and host["address"] not in ["unknown", ""] and host["interface"] not in ["unknown", ""]

    async def _ping_host(self, uid: str) -> None:
        """Run an arp_ping for host ``uid`` and update its ``available`` flag."""
        host = self.coordinator.ds["host"][uid]
        tmp_interface = host["interface"]
        arp = self.coordinator.ds["arp"]
        if uid in arp and arp[uid]["bridge"] != "":
            tmp_interface = arp[uid]["bridge"]

        _LOGGER.debug("Ping host: %s", host["address"])

        host["available"] = await self.hass.async_add_executor_job(
            self.api.arp_ping,
            host["address"],
            tmp_interface,
        )

    async def _async_update_data(self):
        """Trigger update by timer"""
        if not self.coordinator.option_track_network_hosts:
            return

        if "test" not in self.coordinator.ds["access"]:
            return

        for uid in list(self.coordinator.ds["host"]):
            if not self.coordinator.host_tracking_initialized:
                self._fill_host_defaults(self.coordinator.ds["host"][uid])

            # Check host availability — skip on first refresh to avoid blocking
            # initial setup when there are many tracked hosts (each arp_ping takes
            # ~300 ms; sequentially over 100 hosts exceeds HA's 30-second limit).
            if self._should_ping_host(self.coordinator.ds["host"][uid]):
                await self._ping_host(uid)

            # Update last seen
            if self.coordinator.ds["host"][uid]["available"]:
                self.coordinator.ds["host"][uid]["last-seen"] = utcnow()

        self.coordinator.host_tracking_initialized = True

        await self.coordinator.async_process_host()
        return {
            "host": self.coordinator.ds["host"],
            "routerboard": self.coordinator.ds["routerboard"],
        }


# ---------------------------
#   MikrotikControllerData
# ---------------------------
class MikrotikCoordinator(DataUpdateCoordinator[None]):
    """MikrotikCoordinator Class"""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize MikrotikCoordinator."""
        self.hass = hass
        self.config_entry: ConfigEntry = config_entry
        super().__init__(
            self.hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self.option_scan_interval,
        )
        self.name = config_entry.data[CONF_NAME]
        self.host = config_entry.data[CONF_HOST]

        self.ds = {
            "access": {},
            "routerboard": {},
            "resource": {},
            "health": {},
            "health7": {},
            "interface": {},
            "bonding": {},
            "bonding_slaves": {},
            "bridge": {},
            "bridge_host": {},
            "arp": {},
            "nat": {},
            "kid-control": {},
            "mangle": {},
            "routing_rules": {},
            "filter": {},
            "ppp_secret": {},
            "ppp_active": {},
            "fw-update": {},
            "script": {},
            "queue": {},
            "dns": {},
            "dhcp-server": {},
            "dhcp-client": {},
            "dhcp-network": {},
            "dhcp": {},
            "capsman_hosts": {},
            "wireless": {},
            "wireless_hosts": {},
            "host": {},
            "host_hass": {},
            "hostspot_host": {},
            "client_traffic": {},
            "environment": {},
            "ups": {},
            "gps": {},
            "netwatch": {},
            "ip_address": {},
            "cloud": {},
            "wireguard_peers": {},
            "containers": {},
            "system_device_mode": {},
            "system_packages": {},
            "dhcp_leases": {},
        }

        self.notified_flags = []

        self.api = MikrotikAPI(
            config_entry.data[CONF_HOST],
            config_entry.data[CONF_USERNAME],
            config_entry.data[CONF_PASSWORD],
            config_entry.data[CONF_PORT],
            config_entry.data[CONF_SSL],
            config_entry.data[CONF_VERIFY_SSL],
        )

        self.debug = False
        if _LOGGER.getEffectiveLevel() == 10:
            self.debug = True

        self._stale_counters: dict[str, dict] = {}

        self.nat_removed = {}
        self.mangle_removed = {}
        self.routing_rules_removed = {}
        self.filter_removed = {}
        self.queue_removed = {}
        self.host_hass_recovered = False
        self.host_tracking_initialized = False

        self.support_capsman = False
        self.support_wireless = False
        self.support_ppp = False
        self.support_ups = False
        self.support_gps = False
        self.support_wireguard = False
        self.support_containers = False
        self.support_cloud = False
        self._wifimodule = "wireless"

        self.major_fw_version = 0
        self.minor_fw_version = 0

        self.async_mac_lookup = AsyncMacLookup()
        self.accessrights_reported = False

        self.last_hwinfo_update = datetime(1970, 1, 1)
        self.rebootcheck = 0

    def _get_stale_counters(self, key: str) -> dict:
        """Get or create stale counter dict for a data path."""
        if key not in self._stale_counters:
            self._stale_counters[key] = {}
        return self._stale_counters[key]

    # ---------------------------
    #   option_track_iface_clients
    # ---------------------------
    @property
    def option_track_iface_clients(self):
        """Always show client MAC and IP on interface sensors."""
        return True

    # ---------------------------
    #   option_track_network_hosts
    # ---------------------------
    @property
    def option_track_network_hosts(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_TRACK_HOSTS, DEFAULT_TRACK_HOSTS)

    # ---------------------------
    #   option_sensor_port_traffic
    # ---------------------------
    @property
    def option_sensor_port_traffic(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_PORT_TRAFFIC, DEFAULT_SENSOR_PORT_TRAFFIC)

    # ---------------------------
    #   option_sensor_client_traffic
    # ---------------------------
    @property
    def option_sensor_client_traffic(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_CLIENT_TRAFFIC, DEFAULT_SENSOR_CLIENT_TRAFFIC)

    # ---------------------------
    #   option_sensor_client_captive
    # ---------------------------
    @property
    def option_sensor_client_captive(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_CLIENT_CAPTIVE, DEFAULT_SENSOR_CLIENT_CAPTIVE)

    # ---------------------------
    #   option_sensor_simple_queues
    # ---------------------------
    @property
    def option_sensor_simple_queues(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_SIMPLE_QUEUES, DEFAULT_SENSOR_SIMPLE_QUEUES)

    # ---------------------------
    #   option_sensor_nat
    # ---------------------------
    @property
    def option_sensor_nat(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_NAT, DEFAULT_SENSOR_NAT)

    # ---------------------------
    #   option_sensor_mangle
    # ---------------------------
    @property
    def option_sensor_mangle(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_MANGLE, DEFAULT_SENSOR_MANGLE)

    # ---------------------------
    #   option_sensor_routing_rules
    # ---------------------------
    @property
    def option_sensor_routing_rules(self):
        """Config entry option for routing rules."""
        return self.config_entry.options.get(CONF_SENSOR_ROUTING_RULES, DEFAULT_SENSOR_ROUTING_RULES)

    # ---------------------------
    #   option_sensor_wireguard
    # ---------------------------
    @property
    def option_sensor_wireguard(self):
        """Config entry option for wireguard peers."""
        return self.config_entry.options.get(CONF_SENSOR_WIREGUARD, DEFAULT_SENSOR_WIREGUARD)

    # ---------------------------
    #   option_sensor_containers
    # ---------------------------
    @property
    def option_sensor_containers(self):
        """Config entry option for container sensors."""
        return self.config_entry.options.get(CONF_SENSOR_CONTAINERS, DEFAULT_SENSOR_CONTAINERS)

    # ---------------------------
    #   option_sensor_filter
    # ---------------------------
    @property
    def option_sensor_filter(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_FILTER, DEFAULT_SENSOR_FILTER)

    # ---------------------------
    #   option_sensor_kidcontrol
    # ---------------------------
    @property
    def option_sensor_kidcontrol(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_KIDCONTROL, DEFAULT_SENSOR_KIDCONTROL)

    # ---------------------------
    #   option_sensor_netwatch
    # ---------------------------
    @property
    def option_sensor_netwatch(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_NETWATCH_TRACKER, DEFAULT_SENSOR_NETWATCH_TRACKER)

    # ---------------------------
    #   option_sensor_ppp
    # ---------------------------
    @property
    def option_sensor_ppp(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_PPP, DEFAULT_SENSOR_PPP)

    # ---------------------------
    #   option_sensor_scripts
    # ---------------------------
    @property
    def option_sensor_scripts(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_SCRIPTS, DEFAULT_SENSOR_SCRIPTS)

    # ---------------------------
    #   option_sensor_environment
    # ---------------------------
    @property
    def option_sensor_environment(self):
        """Config entry option to not track ARP."""
        return self.config_entry.options.get(CONF_SENSOR_ENVIRONMENT, DEFAULT_SENSOR_ENVIRONMENT)

    # ---------------------------
    #   option_scan_interval
    # ---------------------------
    @property
    def option_scan_interval(self):
        """Config entry option scan interval."""
        scan_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return timedelta(seconds=scan_interval)

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self):
        """Return connected state"""
        return self.api.connected()

    # ---------------------------
    #   set_value
    # ---------------------------
    def set_value(self, path, param, value, mod_param, mod_value):
        """Change value using Mikrotik API"""
        return self.api.set_value(path, param, value, mod_param, mod_value)

    # ---------------------------
    #   execute
    # ---------------------------
    def execute(self, path, command, param, value, attributes=None):
        """Change value using Mikrotik API"""
        return self.api.execute(path, command, param, value, attributes)

    # ---------------------------
    #   get_capabilities
    # ---------------------------
    def get_capabilities(self):
        """Update Mikrotik data"""
        packages = parse_api(
            data={},
            source=self.api.query("/system/package"),
            key="name",
            vals=[
                {"name": "name"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
        )

        if 0 < self.major_fw_version >= 7:
            self._detect_v7_wifi(packages)

        if _package_enabled(packages, "ups"):
            self.support_ups = True

        if _package_enabled(packages, "gps"):
            self.support_gps = True

        # WireGuard is built-in from RouterOS v7
        if self.major_fw_version >= 7 or _package_enabled(packages, "wireguard"):
            self.support_wireguard = True

        # Container support available from RouterOS v7
        if self.major_fw_version >= 7:
            self.support_containers = True

    def _detect_v7_wifi(self, packages) -> None:
        """Resolve wifi module and CAPsMAN/wireless flags on RouterOS v7."""
        self.support_ppp = True
        self.support_wireless = True
        if _package_enabled(packages, "wifiwave2"):
            self.support_capsman = False
            self._wifimodule = "wifiwave2"
        elif self._has_v7_wifi_module(packages):
            self.support_capsman = False
            self._wifimodule = "wifi"
        else:
            self.support_capsman = True
            self.support_wireless = bool(self.minor_fw_version < 13)

        _LOGGER.debug(
            "Mikrotik %s wifi module=%s",
            self.host,
            self._wifimodule,
        )

    def _has_v7_wifi_module(self, packages) -> bool:
        """Return True when any v7 ``wifi``/``wifi-qcom*`` package is usable."""
        return (
            _package_enabled(packages, "wifi")
            or _package_enabled(packages, "wifi-qcom")
            or _package_enabled(packages, "wifi-qcom-ac")
            or (self.major_fw_version == 7 and self.minor_fw_version >= 13)
            or self.major_fw_version > 7
        )

    # ---------------------------
    #   async_get_host_hass
    # ---------------------------
    def _mac_from_host_entity(self, entity) -> str | None:
        """Extract the MAC from a device_tracker entity's unique_id."""
        parts = entity.unique_id.split("-")
        if len(parts) < 3 or parts[1] != "host":
            return None

        if parts[0] == self.config_entry.entry_id:
            mac = parts[2].replace("_", ":").upper()
        elif parts[0] == self.name.lower() and ":" in parts[2]:
            mac = parts[2].upper()
        else:
            return None

        return mac if len(mac) == 17 else None

    async def async_get_host_hass(self):
        """Get host data from HA entity registry"""
        registry = entity_registry.async_get(self.hass)
        for entity in registry.entities.values():
            if entity.config_entry_id != self.config_entry.entry_id:
                continue
            if not entity.entity_id.startswith("device_tracker."):
                continue
            mac = self._mac_from_host_entity(entity)
            if mac is None:
                continue
            self.ds["host_hass"][mac] = entity.original_name

    # ---------------------------
    #   _async_update_data
    # ---------------------------
    async def _async_update_data(self):
        """Update Mikrotik data"""
        _cycle_start = datetime.now()
        _LOGGER.debug("Mikrotik %s starting data update cycle", self.host)
        delta = datetime.now().replace(microsecond=0) - self.last_hwinfo_update
        if self.api.has_reconnected() or delta.total_seconds() > 60 * 60 * 4:
            await self.hass.async_add_executor_job(self.get_access)

            if self.api.connected():
                await self.hass.async_add_executor_job(self.get_firmware_update)

            if self.api.connected():
                await self.hass.async_add_executor_job(self.get_system_resource)

            if self.api.connected():
                await self.hass.async_add_executor_job(self.get_capabilities)

            if self.api.connected():
                await self.hass.async_add_executor_job(self.get_system_routerboard)

            if self.api.connected() and self.option_sensor_scripts:
                await self.hass.async_add_executor_job(self.get_script)

            if self.api.connected():
                await self.hass.async_add_executor_job(self.get_dhcp_network)

            if self.api.connected():
                await self.hass.async_add_executor_job(self.get_dns)

            if not self.api.connected():
                if async_create_issue is not None:
                    if self.api.error == "wrong_login":
                        async_create_issue(
                            self.hass,
                            DOMAIN,
                            "wrong_credentials",
                            is_fixable=False,
                            severity=IssueSeverity.ERROR,
                            translation_key="wrong_credentials",
                            translation_placeholders={"host": self.host},
                        )
                    elif self.api.error in ("ssl_handshake_failure", "ssl_verify_failure"):
                        async_create_issue(
                            self.hass,
                            DOMAIN,
                            "ssl_error",
                            is_fixable=False,
                            severity=IssueSeverity.ERROR,
                            translation_key="ssl_error",
                            translation_placeholders={"host": self.host},
                        )
                if self.api.error == "wrong_login":
                    raise ConfigEntryAuthFailed(f"Invalid credentials for {self.host}")
                raise UpdateFailed("Mikrotik Disconnected")

            if self.api.connected():
                self.last_hwinfo_update = datetime.now().replace(microsecond=0)
                if async_delete_issue is not None:
                    async_delete_issue(self.hass, DOMAIN, "wrong_credentials")
                    async_delete_issue(self.hass, DOMAIN, "ssl_error")
                if async_create_issue is not None:
                    missing = self.ds.get("access_missing", [])
                    if missing:
                        async_create_issue(
                            self.hass,
                            DOMAIN,
                            "insufficient_permissions",
                            is_fixable=False,
                            severity=IssueSeverity.WARNING,
                            translation_key="insufficient_permissions",
                            translation_placeholders={
                                "host": self.host,
                                "username": self.config_entry.data[CONF_USERNAME],
                                "missing": ", ".join(missing),
                            },
                        )
                    else:
                        async_delete_issue(self.hass, DOMAIN, "insufficient_permissions")

        await self.hass.async_add_executor_job(self.get_system_resource)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_system_health)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_dhcp_client)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_interface)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_ip_address)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_cloud)

        if self.api.connected() and not self.ds["host_hass"]:
            await self.async_get_host_hass()

        if self.api.connected() and self.support_capsman:
            await self.hass.async_add_executor_job(self.get_capsman_hosts)

        if self.api.connected() and self.support_wireless:
            await self.hass.async_add_executor_job(self.get_wireless)

        if self.api.connected() and self.support_wireless:
            await self.hass.async_add_executor_job(self.get_wireless_hosts)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_bridge)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_arp)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_dhcp)

        if self.api.connected():
            await self.async_process_host()

        if self.api.connected():
            await self.hass.async_add_executor_job(self.process_interface_client)

        if self.api.connected() and self.option_sensor_nat:
            await self.hass.async_add_executor_job(self.get_nat)

        if self.api.connected() and self.option_sensor_kidcontrol:
            await self.hass.async_add_executor_job(self.get_kidcontrol)

        if self.api.connected() and self.option_sensor_mangle:
            await self.hass.async_add_executor_job(self.get_mangle)

        if self.api.connected() and self.option_sensor_routing_rules:
            await self.hass.async_add_executor_job(self.get_routing_rules)

        if self.api.connected() and self.support_wireguard and self.option_sensor_wireguard:
            await self.hass.async_add_executor_job(self.get_wireguard_peers)

        if self.api.connected() and self.support_containers and self.option_sensor_containers:
            await self.hass.async_add_executor_job(self.get_containers)

        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_device_mode)
        if self.api.connected():
            await self.hass.async_add_executor_job(self.get_packages)

        if self.api.connected() and self.option_sensor_filter:
            await self.hass.async_add_executor_job(self.get_filter)

        if self.api.connected() and self.option_sensor_netwatch:
            await self.hass.async_add_executor_job(self.get_netwatch)

        if self.api.connected() and self.support_ppp and self.option_sensor_ppp:
            await self.hass.async_add_executor_job(self.get_ppp)

        if self.api.connected() and 0 < self.major_fw_version >= 7:
            await self.hass.async_add_executor_job(self.sync_kid_control_monitoring_profile)

        if self.api.connected() and self.option_sensor_client_traffic and 0 < self.major_fw_version >= 7:
            await self.hass.async_add_executor_job(self.process_kid_control_devices)

        if self.api.connected() and self.option_sensor_client_captive:
            await self.hass.async_add_executor_job(self.get_captive)

        if self.api.connected() and self.option_sensor_simple_queues:
            await self.hass.async_add_executor_job(self.get_queue)

        if self.api.connected() and self.option_sensor_environment:
            await self.hass.async_add_executor_job(self.get_environment)

        if self.api.connected() and self.support_ups:
            await self.hass.async_add_executor_job(self.get_ups)

        if self.api.connected() and self.support_gps:
            await self.hass.async_add_executor_job(self.get_gps)

        if not self.api.connected():
            if self.api.error == "wrong_login":
                raise ConfigEntryAuthFailed(f"Invalid credentials for {self.host}")
            raise UpdateFailed("Mikrotik Disconnected")

        _cycle_s = (datetime.now() - _cycle_start).total_seconds()
        if _cycle_s > 5:
            _LOGGER.warning(
                "Mikrotik %s update cycle took %.1fs (interfaces=%d, hosts=%d) — consider increasing scan interval",
                self.host,
                _cycle_s,
                len(self.ds.get("interface", {})),
                len(self.ds.get("host", {})),
            )
        _LOGGER.debug(
            "Mikrotik %s data update cycle complete (interfaces=%d, hosts=%d, routing_rules=%d)",
            self.host,
            len(self.ds.get("interface", {})),
            len(self.ds.get("host", {})),
            len(self.ds.get("routing_rules", {})),
        )
        async_dispatcher_send(self.hass, f"update_sensors_{self.config_entry.entry_id}", self)
        return self.ds

    # ---------------------------
    #   get_access
    # ---------------------------
    def get_access(self) -> None:
        """Get access rights from Mikrotik"""
        tmp_user = parse_api(
            data={},
            source=self.api.query("/user"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "group"},
            ],
        )

        tmp_group = parse_api(
            data={},
            source=self.api.query("/user/group"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "policy"},
            ],
        )

        if tmp_user[self.config_entry.data[CONF_USERNAME]]["group"] in tmp_group:
            self.ds["access"] = tmp_group[tmp_user[self.config_entry.data[CONF_USERNAME]]["group"]]["policy"].split(",")

        required = ("write", "policy", "reboot", "test")
        missing = [p for p in required if p not in self.ds["access"]]
        self.ds["access_missing"] = missing

        if not self.accessrights_reported:
            self.accessrights_reported = True
            if missing:
                _LOGGER.warning(
                    "Mikrotik %s user %s is missing access rights: %s. Integration functionality will be limited.",
                    self.host,
                    self.config_entry.data[CONF_USERNAME],
                    ", ".join(missing),
                )

    # ---------------------------
    #   get_interface
    # ---------------------------
    def get_interface(self) -> None:
        """Get all interfaces data from Mikrotik"""
        self.ds["interface"] = parse_api(
            data=self.ds["interface"],
            source=self.api.query("/interface"),
            key="default-name",
            key_secondary="name",
            vals=[
                {"name": "default-name"},
                {"name": ".id"},
                {"name": "name", "default_val": "default-name"},
                {"name": "type", "default": "unknown"},
                {"name": "running", "type": "bool"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
                {"name": "port-mac-address", "source": "mac-address"},
                {"name": "comment"},
                {"name": "last-link-down-time"},
                {"name": "last-link-up-time"},
                {"name": "link-downs"},
                {"name": "tx-queue-drop"},
                {"name": "actual-mtu"},
                {"name": "about", "source": ".about", "default": ""},
                {"name": "rx-current", "source": "rx-byte", "default": 0.0},
                {"name": "tx-current", "source": "tx-byte", "default": 0.0},
            ],
            ensure_vals=[
                {"name": "client-ip-address"},
                {"name": "client-mac-address"},
                {"name": "rx-previous", "default": 0.0},
                {"name": "tx-previous", "default": 0.0},
                {"name": "rx", "default": 0.0},
                {"name": "tx", "default": 0.0},
                {"name": "rx-total", "default": 0.0},
                {"name": "tx-total", "default": 0.0},
            ],
            skip=[
                {"name": "type", "value": "bridge"},
                {"name": "type", "value": "loopback"},
                {"name": "type", "value": "ppp-in"},
                {"name": "type", "value": "pptp-in"},
                {"name": "type", "value": "sstp-in"},
                {"name": "type", "value": "l2tp-in"},
                {"name": "type", "value": "pppoe-in"},
                {"name": "type", "value": "ovpn-in"},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("interface"),
        )

        if self.option_sensor_port_traffic:
            self._compute_interface_traffic_deltas()

        self.ds["interface"] = parse_api(
            data=self.ds["interface"],
            source=self.api.query(PATH_INTERFACE_ETHERNET),
            key="default-name",
            key_secondary="name",
            vals=[
                {"name": "default-name"},
                {"name": "name", "default_val": "default-name"},
                {"name": "poe-out", "default": "N/A"},
                {"name": "sfp-shutdown-temperature", "default": 0},
            ],
            skip=[
                {"name": "type", "value": "bridge"},
                {"name": "type", "value": "ppp-in"},
                {"name": "type", "value": "pptp-in"},
                {"name": "type", "value": "sstp-in"},
                {"name": "type", "value": "l2tp-in"},
                {"name": "type", "value": "pppoe-in"},
                {"name": "type", "value": "ovpn-in"},
            ],
        )

        bonding = self._post_process_interfaces()
        if bonding:
            self._load_bonding_slaves()

    def _compute_interface_traffic_deltas(self) -> None:
        """Convert rx/tx byte counters into per-interval rates."""
        interval_seconds = self.option_scan_interval.seconds
        for uid, vals in self.ds["interface"].items():
            entry = self.ds["interface"][uid]

            current_tx = vals["tx-current"]
            previous_tx = vals["tx-previous"] or current_tx
            entry["tx"] = round(max(0, current_tx - previous_tx) / interval_seconds)
            entry["tx-previous"] = current_tx

            current_rx = vals["rx-current"]
            previous_rx = vals["rx-previous"] or current_rx
            entry["rx"] = round(max(0, current_rx - previous_rx) / interval_seconds)
            entry["rx-previous"] = current_rx

            entry["tx-total"] = current_tx
            entry["rx-total"] = current_rx

    def _post_process_interfaces(self) -> bool:
        """Stringify comments, fix virtual iface names, and fetch ether monitor data."""
        bonding = False
        for uid, vals in self.ds["interface"].items():
            entry = self.ds["interface"][uid]
            if entry["type"] == "bond":
                bonding = True

            entry["comment"] = str(entry["comment"])

            if vals["default-name"] == "":
                entry["default-name"] = vals["name"]
                entry["port-mac-address"] = f"{vals['port-mac-address']}-{vals['name']}"

            if entry["type"] == "ether":
                self._fetch_ether_monitor(vals)
        return bonding

    def _fetch_ether_monitor(self, vals) -> None:
        """Run /interface/ethernet monitor once for the given ether iface."""
        if "sfp-shutdown-temperature" in vals and vals["sfp-shutdown-temperature"] != "":
            monitor_vals = [
                {"name": "status", "default": "unknown"},
                {"name": "auto-negotiation", "default": "unknown"},
                {"name": "advertising", "default": "unknown"},
                {"name": "link-partner-advertising", "default": "unknown"},
                {"name": "sfp-temperature", "default": 0},
                {"name": "sfp-supply-voltage", "default": "unknown"},
                {"name": "sfp-module-present", "default": "unknown"},
                {"name": "sfp-tx-bias-current", "default": "unknown"},
                {"name": "sfp-tx-power", "default": "unknown"},
                {"name": "sfp-rx-power", "default": "unknown"},
                {"name": "sfp-rx-loss", "default": "unknown"},
                {"name": "sfp-tx-fault", "default": "unknown"},
                {"name": "sfp-type", "default": "unknown"},
                {"name": "sfp-connector-type", "default": "unknown"},
                {"name": "sfp-vendor-name", "default": "unknown"},
                {"name": "sfp-vendor-part-number", "default": "unknown"},
                {"name": "sfp-vendor-revision", "default": "unknown"},
                {"name": "sfp-vendor-serial", "default": "unknown"},
                {"name": "sfp-manufacturing-date", "default": "unknown"},
                {"name": "eeprom-checksum", "default": "unknown"},
            ]
        else:
            monitor_vals = [
                {"name": "status", "default": "unknown"},
                {"name": "rate", "default": "unknown"},
                {"name": "full-duplex", "default": "unknown"},
                {"name": "auto-negotiation", "default": "unknown"},
            ]
        self.ds["interface"] = parse_api(
            data=self.ds["interface"],
            source=self.api.query(
                PATH_INTERFACE_ETHERNET,
                command="monitor",
                args={".id": vals[".id"], "once": True},
            ),
            key_search="name",
            vals=monitor_vals,
        )

    def _load_bonding_slaves(self) -> None:
        """Populate ds['bonding'] / ds['bonding_slaves'] when a bond iface exists."""
        self.ds["bonding"] = parse_api(
            data={},
            source=self.api.query("/interface/bonding"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "mac-address"},
                {"name": "slaves"},
                {"name": "mode"},
            ],
        )

        self.ds["bonding_slaves"] = {}
        for uid, vals in self.ds["bonding"].items():
            for tmp in vals["slaves"].split(","):
                self.ds["bonding_slaves"][tmp] = vals
                self.ds["bonding_slaves"][tmp]["master"] = uid

    # ---------------------------
    #   get_bridge
    # ---------------------------
    def get_bridge(self) -> None:
        """Get system resources data from Mikrotik"""
        self.ds["bridge_host"] = parse_api(
            data=self.ds["bridge_host"],
            source=self.api.query("/interface/bridge/host"),
            key="mac-address",
            vals=[
                {"name": "mac-address"},
                {"name": "interface", "default": "unknown"},
                {"name": "bridge", "default": "unknown"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            only=[{"key": "local", "value": False}],
        )

        for _uid, vals in self.ds["bridge_host"].items():
            self.ds["bridge"][vals["bridge"]] = True

    # ---------------------------
    #   process_interface_client
    # ---------------------------
    def process_interface_client(self) -> None:
        # Remove data if disabled
        if not self.option_track_iface_clients:
            for uid in self.ds["interface"]:
                self.ds["interface"][uid]["client-ip-address"] = "disabled"
                self.ds["interface"][uid]["client-mac-address"] = "disabled"
            return

        for uid, vals in self.ds["interface"].items():
            self._resolve_interface_client(uid, vals)

    def _arp_belongs_to_iface(self, iface_name: str, arp_vals) -> bool:
        """Return True if the arp entry matches iface or its bonding master."""
        if arp_vals["interface"] == iface_name:
            return True
        bonding_slaves = self.ds["bonding_slaves"]
        return iface_name in bonding_slaves and bonding_slaves[iface_name]["master"] == arp_vals["interface"]

    def _resolve_interface_client(self, uid, vals) -> None:
        """Populate client-ip/client-mac for interface ``uid`` based on arp + dhcp-client."""
        entry = self.ds["interface"][uid]
        entry["client-ip-address"] = ""
        entry["client-mac-address"] = ""
        for _arp_uid, arp_vals in self.ds["arp"].items():
            if not self._arp_belongs_to_iface(vals["name"], arp_vals):
                continue

            entry["client-ip-address"] = "multiple" if entry["client-ip-address"] else arp_vals["address"]
            entry["client-mac-address"] = "multiple" if entry["client-mac-address"] else arp_vals["mac-address"]

        if entry["client-ip-address"] == "":
            dhcp_client = self.ds["dhcp-client"]
            if entry["name"] in dhcp_client:
                entry["client-ip-address"] = dhcp_client[entry["name"]]["address"]
            else:
                entry["client-ip-address"] = "none"

        if entry["client-mac-address"] == "":
            entry["client-mac-address"] = "none"

    # ---------------------------
    #   get_nat
    # ---------------------------
    def get_nat(self) -> None:
        """Get NAT data from Mikrotik"""
        self.ds["nat"] = parse_api(
            data=self.ds["nat"],
            source=self.api.query("/ip/firewall/nat"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "chain", "default": "unknown"},
                {"name": "action", "default": "unknown"},
                {"name": "protocol", "default": "any"},
                {"name": "dst-port", "default": "any"},
                {"name": "in-interface", "default": "any"},
                {"name": "out-interface", "default": "any"},
                {"name": "to-addresses"},
                {"name": "to-ports", "default": "any"},
                {"name": "comment"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            val_proc=[
                [
                    {"name": "uniq-id"},
                    {"action": "combine"},
                    {"key": "chain"},
                    {"text": ","},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "protocol"},
                    {"text": ","},
                    {"key": "in-interface"},
                    {"text": ":"},
                    {"key": "dst-port"},
                    {"text": "-"},
                    {"key": "out-interface"},
                    {"text": ":"},
                    {"key": "to-addresses"},
                    {"text": ":"},
                    {"key": "to-ports"},
                ],
                [
                    {"name": "name"},
                    {"action": "combine"},
                    {"key": "protocol"},
                    {"text": ":"},
                    {"key": "dst-port"},
                ],
            ],
            only=[{"key": "action", "value": "dst-nat"}],
            prune_stale=True,
            stale_counters=self._get_stale_counters("nat"),
        )

        # Handle duplicate NAT entries - suffix uniq-id with RouterOS ID to keep all rules
        nat_seen = {}
        for uid in self.ds["nat"]:
            self.ds["nat"][uid]["comment"] = str(self.ds["nat"][uid]["comment"])
            tmp_name = self.ds["nat"][uid]["uniq-id"]
            if tmp_name not in nat_seen:
                nat_seen[tmp_name] = [uid]
            else:
                nat_seen[tmp_name].append(uid)

        for tmp_name, uids in nat_seen.items():
            if len(uids) > 1:
                for uid in uids:
                    router_id = self.ds["nat"][uid].get(".id", uid)
                    self.ds["nat"][uid]["uniq-id"] = f"{tmp_name} ({router_id})"
                if tmp_name not in self.nat_removed:
                    self.nat_removed[tmp_name] = 1
                    _LOGGER.info(
                        "Mikrotik %s duplicate NAT rule '%s' — RouterOS ID suffix added. Add unique comments to the rules to remove this warning.",
                        self.host,
                        self.ds["nat"][uids[0]]["name"],
                    )

    # ---------------------------
    #   get_mangle
    # ---------------------------
    def get_mangle(self) -> None:
        """Get Mangle data from Mikrotik"""
        self.ds["mangle"] = parse_api(
            data=self.ds["mangle"],
            source=self.api.query("/ip/firewall/mangle"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "chain"},
                {"name": "action"},
                {"name": "comment"},
                {"name": "address-list"},
                {"name": "passthrough", "type": "bool", "default": False},
                {"name": "protocol", "default": "any"},
                {"name": "src-address", "default": "any"},
                {"name": "src-port", "default": "any"},
                {"name": "dst-address", "default": "any"},
                {"name": "dst-port", "default": "any"},
                {"name": "src-address-list", "default": "any"},
                {"name": "dst-address-list", "default": "any"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            val_proc=[
                [
                    {"name": "uniq-id"},
                    {"action": "combine"},
                    {"key": "chain"},
                    {"text": ","},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "protocol"},
                    {"text": ","},
                    {"key": "src-address"},
                    {"text": ":"},
                    {"key": "src-port"},
                    {"text": "-"},
                    {"key": "dst-address"},
                    {"text": ":"},
                    {"key": "dst-port"},
                    {"text": ","},
                    {"key": "src-address-list"},
                    {"text": "-"},
                    {"key": "dst-address-list"},
                ],
                [
                    {"name": "name"},
                    {"action": "combine"},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "protocol"},
                    {"text": ":"},
                    {"key": "dst-port"},
                ],
            ],
            skip=[
                {"name": "dynamic", "value": True},
                {"name": "action", "value": "jump"},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("mangle"),
        )

        # Handle duplicate Mangle entries - suffix uniq-id with RouterOS ID to keep all rules
        mangle_seen = {}
        for uid in self.ds["mangle"]:
            self.ds["mangle"][uid]["comment"] = str(self.ds["mangle"][uid]["comment"])
            tmp_name = self.ds["mangle"][uid]["uniq-id"]
            if tmp_name not in mangle_seen:
                mangle_seen[tmp_name] = [uid]
            else:
                mangle_seen[tmp_name].append(uid)

        for tmp_name, uids in mangle_seen.items():
            if len(uids) > 1:
                for uid in uids:
                    router_id = self.ds["mangle"][uid].get(".id", uid)
                    self.ds["mangle"][uid]["uniq-id"] = f"{tmp_name} ({router_id})"
                if tmp_name not in self.mangle_removed:
                    self.mangle_removed[tmp_name] = 1
                    _LOGGER.info(
                        "Mikrotik %s duplicate Mangle rule '%s' — RouterOS ID suffix added. Add unique comments to the rules to remove this warning.",
                        self.host,
                        self.ds["mangle"][uids[0]]["name"],
                    )

    # ---------------------------
    #   get_routing_rules
    # ---------------------------
    def get_routing_rules(self) -> None:
        """Get Routing Rules data from Mikrotik"""
        _LOGGER.debug("Mikrotik %s fetching routing rules", self.host)
        self.ds["routing_rules"] = parse_api(
            data=self.ds["routing_rules"],
            source=self.api.query("/routing/rule"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "comment", "default_val": "src-address"},
                {"name": "action"},
                {"name": "src-address", "default": "any"},
                {"name": "dst-address", "default": "any"},
                {"name": "routing-mark", "default": "any"},
                {"name": "interface", "default": "any"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            val_proc=[
                [
                    {"name": "uniq-id"},
                    {"action": "combine"},
                    {"key": "comment"},
                    {"text": ","},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "src-address"},
                    {"text": ","},
                    {"key": "dst-address"},
                    {"text": ","},
                    {"key": "routing-mark"},
                    {"text": ","},
                    {"key": "interface"},
                ],
                [
                    {"name": "name"},
                    {"action": "combine"},
                    {"key": "comment"},
                    {"text": ","},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "src-address"},
                    {"text": ","},
                    {"key": "dst-address"},
                ],
            ],
            skip=[
                {"name": "dynamic", "value": True},
                {"name": "action", "value": "jump"},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("routing_rules"),
        )

        # Handle duplicate Routing Rules entries - suffix uniq-id with RouterOS ID to keep all rules
        routing_rules_seen = {}
        for uid in self.ds["routing_rules"]:
            self.ds["routing_rules"][uid]["comment"] = str(self.ds["routing_rules"][uid]["comment"])
            tmp_name = self.ds["routing_rules"][uid]["uniq-id"]
            if tmp_name not in routing_rules_seen:
                routing_rules_seen[tmp_name] = [uid]
            else:
                routing_rules_seen[tmp_name].append(uid)

        for tmp_name, uids in routing_rules_seen.items():
            if len(uids) > 1:
                for uid in uids:
                    router_id = self.ds["routing_rules"][uid].get(".id", uid)
                    self.ds["routing_rules"][uid]["uniq-id"] = f"{tmp_name} ({router_id})"
                if tmp_name not in self.routing_rules_removed:
                    self.routing_rules_removed[tmp_name] = 1
                    _LOGGER.info(
                        "Mikrotik %s duplicate Routing Rule '%s' — RouterOS ID suffix added. Add unique comments to the rules to remove this warning.",
                        self.host,
                        self.ds["routing_rules"][uids[0]]["name"],
                    )

    # ---------------------------
    #   get_wireguard_peers
    # ---------------------------
    def get_wireguard_peers(self) -> None:
        """Get WireGuard peers data from Mikrotik"""
        _LOGGER.debug("Mikrotik %s fetching wireguard peers", self.host)
        self.ds["wireguard_peers"] = parse_api(
            data=self.ds["wireguard_peers"],
            source=self.api.query("/interface/wireguard/peers"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "public-key"},
                {"name": "interface"},
                {"name": "peer-name", "source": "name", "default": ""},
                {"name": "comment", "default": ""},
                {"name": "allowed-address", "default": ""},
                {"name": "rx", "default": "0"},
                {"name": "tx", "default": "0"},
                {"name": "last-handshake", "default": ""},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("wireguard_peers"),
        )

        for uid in self.ds["wireguard_peers"]:
            peer = self.ds["wireguard_peers"][uid]

            # Parse last-handshake string to seconds
            peer["last-handshake-seconds"] = _parse_duration_seconds(str(peer.get("last-handshake", "")))

            # Connected if handshake within last 3 minutes
            peer["connected"] = 0 < peer["last-handshake-seconds"] < 180

            peer["uniq-id"] = peer.get("public-key", uid)

            # name = peer-name > comment > first 8 chars of public-key
            peer_name = str(peer.get("peer-name", "")).strip()
            comment = str(peer.get("comment", "")).strip()
            peer["name"] = peer_name or comment or peer.get("public-key", "")[:8]

    # ---------------------------
    #   get_device_mode
    # ---------------------------
    def get_device_mode(self) -> None:
        """Get Device Mode data from Mikrotik"""
        _LOGGER.debug("Mikrotik %s fetching device mode", self.host)
        self.ds["system_device_mode"] = parse_api(
            data=self.ds["system_device_mode"],
            source=self.api.query("/system/device-mode"),
            vals=[
                {"name": "mode", "default": ""},
                {"name": "container", "type": "bool", "default": False},
                {"name": "zerotier", "type": "bool", "default": False},
                {"name": "ipsec", "type": "bool", "default": False},
                {"name": "hotspot", "type": "bool", "default": False},
                {"name": "bandwidth-test", "type": "bool", "default": False},
                {"name": "traffic-gen", "type": "bool", "default": False},
                {"name": "sniffer", "type": "bool", "default": False},
                {"name": "proxy", "type": "bool", "default": False},
                {"name": "scheduler", "type": "bool", "default": False},
                {"name": "socks", "type": "bool", "default": False},
                {"name": "fetch", "type": "bool", "default": False},
                {"name": "pptp", "type": "bool", "default": False},
                {"name": "l2tp", "type": "bool", "default": False},
                {"name": "romon", "type": "bool", "default": False},
                {"name": "smb", "type": "bool", "default": False},
                {"name": "email", "type": "bool", "default": False},
            ],
        )

    # ---------------------------
    #   get_packages
    # ---------------------------
    def get_packages(self) -> None:
        """Get installed packages data from Mikrotik"""
        _LOGGER.debug("Mikrotik %s fetching packages", self.host)
        raw = self.api.query("/system/package") or []

        active = {p["name"]: p.get("version", "") for p in raw if not p.get("disabled", True) and p.get("name") != "routeros"}

        known = [
            "container",
            "gps",
            "ups",
            "zerotier",
            "dude",
            "iot",
            "wireless",
            "wifi-qcom",
            "wifi-qcom-be",
            "calea",
            "rose-storage",
            "user-manager",
            "tr069-client",
        ]

        result = {"count": len(active)}
        for pkg in known:
            result[pkg] = active.get(pkg, False)

        self.ds["system_packages"] = result

    # ---------------------------
    #   get_containers
    # ---------------------------
    def get_containers(self) -> None:
        """Get Container data from Mikrotik"""
        _LOGGER.debug("Mikrotik %s fetching containers", self.host)
        self.ds["containers"] = parse_api(
            data=self.ds["containers"],
            source=self.api.query("/container"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "name", "default": ""},
                {"name": "tag", "default": ""},
                {"name": "os", "default": ""},
                {"name": "arch", "default": ""},
                {"name": "interface", "default": ""},
                {"name": "root-dir", "default": ""},
                {"name": "mounts", "default": ""},
                {"name": "comment", "default": ""},
                {"name": "start-on-boot", "default": "false"},
                {"name": "running", "type": "bool", "default": False},
                {"name": "memory-current", "default": ""},
                {"name": "cpu-usage", "default": ""},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("containers"),
        )

        for uid in self.ds["containers"]:
            container = self.ds["containers"][uid]
            container["uniq-id"] = uid
            cname = str(container.get("name", "")).strip()
            comment = str(container.get("comment", "")).strip()
            tag = str(container.get("tag", "")).strip()
            container["display-name"] = cname or comment or tag or uid
            container["status"] = "running" if container.get("running", False) else "stopped"

    # ---------------------------
    #   get_filter
    # ---------------------------
    def get_filter(self) -> None:
        """Get Filter data from Mikrotik"""
        self.ds["filter"] = parse_api(
            data=self.ds["filter"],
            source=self.api.query("/ip/firewall/filter"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "chain"},
                {"name": "action"},
                {"name": "comment"},
                {"name": "address-list"},
                {"name": "protocol", "default": "any"},
                {"name": "in-interface", "default": "any"},
                {"name": "in-interface-list", "default": "any"},
                {"name": "out-interface", "default": "any"},
                {"name": "out-interface-list", "default": "any"},
                {"name": "src-address", "default": "any"},
                {"name": "src-address-list", "default": "any"},
                {"name": "src-port", "default": "any"},
                {"name": "dst-address", "default": "any"},
                {"name": "dst-address-list", "default": "any"},
                {"name": "dst-port", "default": "any"},
                {"name": "layer7-protocol", "default": "any"},
                {"name": "connection-state", "default": "any"},
                {"name": "tcp-flags", "default": "any"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                    "default": True,
                },
            ],
            val_proc=[
                [
                    {"name": "uniq-id"},
                    {"action": "combine"},
                    {"key": "chain"},
                    {"text": ","},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "protocol"},
                    {"text": ","},
                    {"key": "layer7-protocol"},
                    {"text": ","},
                    {"key": "in-interface"},
                    {"text": ","},
                    {"key": "in-interface-list"},
                    {"text": ":"},
                    {"key": "src-address"},
                    {"text": ","},
                    {"key": "src-address-list"},
                    {"text": ":"},
                    {"key": "src-port"},
                    {"text": "-"},
                    {"key": "out-interface"},
                    {"text": ","},
                    {"key": "out-interface-list"},
                    {"text": ":"},
                    {"key": "dst-address"},
                    {"text": ","},
                    {"key": "dst-address-list"},
                    {"text": ":"},
                    {"key": "dst-port"},
                ],
                [
                    {"name": "name"},
                    {"action": "combine"},
                    {"key": "action"},
                    {"text": ","},
                    {"key": "protocol"},
                    {"text": ":"},
                    {"key": "dst-port"},
                ],
            ],
            skip=[
                {"name": "dynamic", "value": True},
                {"name": "action", "value": "jump"},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("filter"),
        )

        # Handle duplicate filter entries - suffix uniq-id with RouterOS ID to keep all rules
        filter_seen = {}
        for uid in self.ds["filter"]:
            self.ds["filter"][uid]["comment"] = str(self.ds["filter"][uid]["comment"])
            tmp_name = self.ds["filter"][uid]["uniq-id"]
            if tmp_name not in filter_seen:
                filter_seen[tmp_name] = [uid]
            else:
                filter_seen[tmp_name].append(uid)

        for tmp_name, uids in filter_seen.items():
            if len(uids) > 1:
                for uid in uids:
                    router_id = self.ds["filter"][uid].get(".id", uid)
                    self.ds["filter"][uid]["uniq-id"] = f"{tmp_name} ({router_id})"
                if tmp_name not in self.filter_removed:
                    self.filter_removed[tmp_name] = 1
                    _LOGGER.info(
                        "Mikrotik %s duplicate Filter rule '%s' — RouterOS ID suffix added. Add unique comments to the rules to remove this warning.",
                        self.host,
                        self.ds["filter"][uids[0]]["name"],
                    )

    # ---------------------------
    #   get_kidcontrol
    # ---------------------------
    def get_kidcontrol(self) -> None:
        """Get Kid-control data from Mikrotik"""
        self.ds["kid-control"] = parse_api(
            data=self.ds["kid-control"],
            source=self.api.query(PATH_IP_KID_CONTROL),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "rate-limit"},
                {"name": "mon", "default": "None"},
                {"name": "tue", "default": "None"},
                {"name": "wed", "default": "None"},
                {"name": "thu", "default": "None"},
                {"name": "fri", "default": "None"},
                {"name": "sat", "default": "None"},
                {"name": "sun", "default": "None"},
                {"name": "comment"},
                {"name": "blocked", "type": "bool", "default": False},
                {"name": "paused", "type": "bool", "reverse": True},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("kid-control"),
        )

        for uid in self.ds["kid-control"]:
            self.ds["kid-control"][uid]["comment"] = str(self.ds["kid-control"][uid]["comment"])

    # ---------------------------
    #   get_ppp
    # ---------------------------
    def get_ppp(self) -> None:
        """Get PPP data from Mikrotik"""
        self.ds["ppp_secret"] = parse_api(
            data=self.ds["ppp_secret"],
            source=self.api.query("/ppp/secret"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "service"},
                {"name": "profile"},
                {"name": "comment"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            ensure_vals=[
                {"name": "caller-id", "default": ""},
                {"name": "address", "default": ""},
                {"name": "encoding", "default": ""},
                {"name": "connected", "default": False},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("ppp_secret"),
        )

        self.ds["ppp_active"] = parse_api(
            data={},
            source=self.api.query("/ppp/active"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "service"},
                {"name": "caller-id"},
                {"name": "address"},
                {"name": "encoding"},
            ],
        )

        for uid in self.ds["ppp_secret"]:
            self.ds["ppp_secret"][uid]["comment"] = str(self.ds["ppp_secret"][uid]["comment"])

            if self.ds["ppp_secret"][uid]["name"] in self.ds["ppp_active"]:
                self.ds["ppp_secret"][uid]["connected"] = True
                self.ds["ppp_secret"][uid]["caller-id"] = self.ds["ppp_active"][uid]["caller-id"]
                self.ds["ppp_secret"][uid]["address"] = self.ds["ppp_active"][uid]["address"]
                self.ds["ppp_secret"][uid]["encoding"] = self.ds["ppp_active"][uid]["encoding"]
            else:
                self.ds["ppp_secret"][uid]["connected"] = False
                self.ds["ppp_secret"][uid]["caller-id"] = PPP_NOT_CONNECTED
                self.ds["ppp_secret"][uid]["address"] = PPP_NOT_CONNECTED
                self.ds["ppp_secret"][uid]["encoding"] = PPP_NOT_CONNECTED

    # ---------------------------
    #   get_netwatch
    # ---------------------------
    def get_netwatch(self) -> None:
        """Get netwatch data from Mikrotik"""
        self.ds["netwatch"] = parse_api(
            data=self.ds["netwatch"],
            source=self.api.query("/tool/netwatch"),
            key="host",
            vals=[
                {"name": "host"},
                {"name": "type"},
                {"name": "interval"},
                {"name": "port"},
                {"name": "http-codes"},
                {"name": "status", "type": "bool", "default": "unknown"},
                {"name": "comment"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("netwatch"),
        )

    # ---------------------------
    #   get_system_routerboard
    # ---------------------------
    def get_system_routerboard(self) -> None:
        """Get routerboard data from Mikrotik"""
        if self.ds["resource"]["board-name"].startswith("x86") or self.ds["resource"]["board-name"].startswith("CHR"):
            self.ds["routerboard"]["routerboard"] = False
            self.ds["routerboard"]["model"] = self.ds["resource"]["board-name"]
            self.ds["routerboard"]["serial-number"] = "N/A"
        else:
            self.ds["routerboard"] = parse_api(
                data=self.ds["routerboard"],
                source=self.api.query("/system/routerboard"),
                vals=[
                    {"name": "routerboard", "type": "bool"},
                    {"name": "model", "default": "unknown"},
                    {"name": "serial-number", "default": "unknown"},
                    {"name": "current-firmware", "default": "unknown"},
                    {"name": "upgrade-firmware", "default": "unknown"},
                ],
            )

            if "write" not in self.ds["access"] or "policy" not in self.ds["access"] or "reboot" not in self.ds["access"]:
                self.ds["routerboard"].pop("current-firmware")
                self.ds["routerboard"].pop("upgrade-firmware")

    # ---------------------------
    #   get_system_health
    # ---------------------------
    def get_system_health(self) -> None:
        """Get routerboard data from Mikrotik"""
        if "write" not in self.ds["access"] or "policy" not in self.ds["access"] or "reboot" not in self.ds["access"]:
            return

        if 0 < self.major_fw_version >= 7:
            self.ds["health7"] = parse_api(
                data=self.ds["health7"],
                source=self.api.query("/system/health"),
                key="name",
                vals=[
                    {"name": "value", "default": "unknown"},
                ],
            )
            if self.ds["health7"]:
                for uid, vals in self.ds["health7"].items():
                    self.ds["health"][uid] = vals["value"]

    # ---------------------------
    #   get_system_resource
    # ---------------------------
    def get_system_resource(self) -> None:
        """Get system resources data from Mikrotik"""
        self.ds["resource"] = parse_api(
            data=self.ds["resource"],
            source=self.api.query("/system/resource"),
            vals=[
                {"name": "platform", "default": "unknown"},
                {"name": "board-name", "default": "unknown"},
                {"name": "version", "default": "unknown"},
                {"name": "uptime_str", "source": "uptime", "default": "unknown"},
                {"name": "cpu-load", "default": "unknown"},
                {"name": "free-memory", "default": 0},
                {"name": "total-memory", "default": 0},
                {"name": "free-hdd-space", "default": 0},
                {"name": "total-hdd-space", "default": 0},
            ],
            ensure_vals=[
                {"name": "uptime", "default": 0},
                {"name": "uptime_epoch", "default": 0},
                {"name": "clients_wired", "default": 0},
                {"name": "clients_wireless", "default": 0},
                {"name": "captive_authorized", "default": 0},
            ],
        )

        tmp_uptime = _parse_uptime_str(self.ds["resource"]["uptime_str"])
        self.ds["resource"]["uptime_epoch"] = tmp_uptime
        now = datetime.now().replace(microsecond=0)
        uptime_tm = datetime.timestamp(now - timedelta(seconds=tmp_uptime))
        if _should_update_uptime(self.ds["resource"]["uptime"], uptime_tm):
            self.ds["resource"]["uptime"] = utc_from_timestamp(uptime_tm)

        self.ds["resource"]["memory-usage"] = _percent_usage(self.ds["resource"]["total-memory"], self.ds["resource"]["free-memory"])
        self.ds["resource"]["hdd-usage"] = _percent_usage(self.ds["resource"]["total-hdd-space"], self.ds["resource"]["free-hdd-space"])

        if "uptime_epoch" in self.ds["resource"] and self.rebootcheck > self.ds["resource"]["uptime_epoch"]:
            self.get_firmware_update()

        if "uptime_epoch" in self.ds["resource"]:
            self.rebootcheck = self.ds["resource"]["uptime_epoch"]

    # ---------------------------
    #   get_firmware_update
    # ---------------------------
    def get_firmware_update(self) -> None:
        """Check for firmware update on Mikrotik"""
        if "write" not in self.ds["access"] or "policy" not in self.ds["access"] or "reboot" not in self.ds["access"]:
            return

        self.execute("/system/package/update", "check-for-updates", None, None, {"duration": 10})
        self.ds["fw-update"] = parse_api(
            data=self.ds["fw-update"],
            source=self.api.query("/system/package/update"),
            vals=[
                {"name": "status"},
                {"name": "channel", "default": "unknown"},
                {"name": "installed-version", "default": "unknown"},
                {"name": "latest-version", "default": "unknown"},
            ],
        )

        if "status" in self.ds["fw-update"]:
            self.ds["fw-update"]["available"] = self.ds["fw-update"]["status"] == "New version is available" and self.ds["fw-update"].get("latest-version", "unknown") != "unknown"

        else:
            self.ds["fw-update"]["available"] = False

        if self.ds["fw-update"]["installed-version"] != "unknown":
            try:
                full_version = self.ds["fw-update"].get("installed-version")
                split_end = min(len(full_version), 4)
                version = re.sub("[^0-9\\.]", "", full_version[0:split_end])
                self.major_fw_version = int(version.split(".")[0])
                self.minor_fw_version = int(version.split(".")[1])
                _LOGGER.debug(
                    "Mikrotik %s FW version major=%s minor=%s (%s)",
                    self.host,
                    self.major_fw_version,
                    self.minor_fw_version,
                    full_version,
                )
            except Exception:
                _LOGGER.error(
                    "Mikrotik %s unable to determine major FW version (%s).",
                    self.host,
                    full_version,
                )

    # ---------------------------
    #   get_ups
    # ---------------------------
    def get_ups(self) -> None:
        """Get UPS info from Mikrotik"""
        self.ds["ups"] = parse_api(
            data=self.ds["ups"],
            source=self.api.query("/system/ups"),
            vals=[
                {"name": "name", "default": "unknown"},
                {"name": "offline-time", "default": "unknown"},
                {"name": "min-runtime", "default": "unknown"},
                {"name": "alarm-setting", "default": "unknown"},
                {"name": "model", "default": "unknown"},
                {"name": "serial", "default": "unknown"},
                {"name": "manufacture-date", "default": "unknown"},
                {"name": "nominal-battery-voltage", "default": "unknown"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            ensure_vals=[
                {"name": "on-line", "type": "bool"},
                {"name": "runtime-left", "default": "unknown"},
                {"name": "battery-charge", "default": 0},
                {"name": "battery-voltage", "default": 0.0},
                {"name": "line-voltage", "default": 0},
                {"name": "load", "default": 0},
                {"name": "hid-self-test", "default": "unknown"},
            ],
        )
        if self.ds["ups"]["enabled"]:
            self.ds["ups"] = parse_api(
                data=self.ds["ups"],
                source=self.api.query(
                    "/system/ups",
                    command="monitor",
                    args={".id": 0, "once": True},
                ),
                vals=[
                    {"name": "on-line", "type": "bool"},
                    {"name": "runtime-left", "default": 0},
                    {"name": "battery-charge", "default": 0},
                    {"name": "battery-voltage", "default": 0.0},
                    {"name": "line-voltage", "default": 0},
                    {"name": "load", "default": 0},
                    {"name": "hid-self-test", "default": "unknown"},
                ],
            )

    # ---------------------------
    #   get_gps
    # ---------------------------
    def get_gps(self) -> None:
        """Get GPS data from Mikrotik"""
        self.ds["gps"] = parse_api(
            data=self.ds["gps"],
            source=self.api.query(
                "/system/gps",
                command="monitor",
                args={"once": True},
            ),
            vals=[
                {"name": "valid", "type": "bool"},
                {"name": "latitude", "default": "unknown"},
                {"name": "longitude", "default": "unknown"},
                {"name": "altitude", "default": "unknown"},
                {"name": "speed", "default": "unknown"},
                {"name": "destination-bearing", "default": "unknown"},
                {"name": "true-bearing", "default": "unknown"},
                {"name": "magnetic-bearing", "default": "unknown"},
                {"name": "satellites", "default": 0},
                {"name": "fix-quality", "default": 0},
                {"name": "horizontal-dilution", "default": "unknown"},
            ],
        )

    # ---------------------------
    #   get_script
    # ---------------------------
    def get_script(self) -> None:
        """Get list of all scripts from Mikrotik"""
        self.ds["script"] = parse_api(
            data=self.ds["script"],
            source=self.api.query("/system/script"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "last-started", "default": "unknown"},
                {"name": "run-count", "default": "unknown"},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("script"),
        )

    # ---------------------------
    #   get_environment
    # ---------------------------
    def get_environment(self) -> None:
        """Get list of all environment variables from Mikrotik"""
        self.ds["environment"] = parse_api(
            data=self.ds["environment"],
            source=self.api.query("/system/script/environment"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "value"},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("environment"),
        )

    # ---------------------------
    #   get_captive
    # ---------------------------
    def get_captive(self) -> None:
        """Get list of all environment variables from Mikrotik"""
        self.ds["hostspot_host"] = parse_api(
            data={},
            source=self.api.query("/ip/hotspot/host"),
            key="mac-address",
            vals=[
                {"name": "mac-address"},
                {"name": "authorized", "type": "bool"},
                {"name": "bypassed", "type": "bool"},
            ],
        )

        auth_hosts = sum(1 for uid in self.ds["hostspot_host"] if self.ds["hostspot_host"][uid]["authorized"])
        self.ds["resource"]["captive_authorized"] = auth_hosts

    # ---------------------------
    #   get_queue
    # ---------------------------
    def get_queue(self) -> None:
        """Get Queue data from Mikrotik"""
        self.ds["queue"] = parse_api(
            data=self.ds["queue"],
            source=self.api.query("/queue/simple"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "name", "default": "unknown"},
                {"name": "target", "default": "unknown"},
                {"name": "rate", "default": "0/0"},
                {"name": "max-limit", "default": "0/0"},
                {"name": "limit-at", "default": "0/0"},
                {"name": "burst-limit", "default": "0/0"},
                {"name": "burst-threshold", "default": "0/0"},
                {"name": "burst-time", "default": "0s/0s"},
                {"name": "packet-marks", "default": "none"},
                {"name": "parent", "default": "none"},
                {"name": "comment"},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("queue"),
        )

        for uid, vals in self.ds["queue"].items():
            _split_queue_fields(self.ds["queue"][uid], vals)

        self._dedupe_queue_uniq_ids()

    def _dedupe_queue_uniq_ids(self) -> None:
        """Suffix uniq-id with RouterOS id when multiple queues share a name."""
        queue_seen: dict[str, list[str]] = {}
        for uid in self.ds["queue"]:
            tmp_name = self.ds["queue"][uid]["uniq-id"]
            queue_seen.setdefault(tmp_name, []).append(uid)

        for tmp_name, uids in queue_seen.items():
            if len(uids) > 1:
                for uid in uids:
                    router_id = self.ds["queue"][uid].get(".id", uid)
                    self.ds["queue"][uid]["uniq-id"] = f"{tmp_name} ({router_id})"
                if tmp_name not in self.queue_removed:
                    self.queue_removed[tmp_name] = 1
                    _LOGGER.info(
                        "Mikrotik %s duplicate Queue rule '%s' — RouterOS ID suffix added. Add unique names to the rules to remove this warning.",
                        self.host,
                        tmp_name,
                    )

    # ---------------------------
    #   get_arp
    # ---------------------------
    def get_arp(self) -> None:
        """Get ARP data from Mikrotik"""
        self.ds["arp"] = parse_api(
            data=self.ds["arp"],
            source=self.api.query("/ip/arp"),
            key="mac-address",
            vals=[{"name": "mac-address"}, {"name": "address"}, {"name": "interface"}],
            ensure_vals=[{"name": "bridge", "default": ""}],
        )

        for uid, vals in self.ds["arp"].items():
            if vals["interface"] in self.ds["bridge"] and uid in self.ds["bridge_host"]:
                self.ds["arp"][uid]["bridge"] = vals["interface"]
                self.ds["arp"][uid]["interface"] = self.ds["bridge_host"][uid]["interface"]

        if self.ds["dhcp-client"]:
            to_remove = [uid for uid, vals in self.ds["arp"].items() if vals["interface"] in self.ds["dhcp-client"]]

            for uid in to_remove:
                self.ds["arp"].pop(uid)

    # ---------------------------
    #   get_dns
    # ---------------------------
    def get_dns(self) -> None:
        """Get static DNS data from Mikrotik"""
        self.ds["dns"] = parse_api(
            data=self.ds["dns"],
            source=self.api.query("/ip/dns/static"),
            key="name",
            vals=[{"name": "name"}, {"name": "address"}, {"name": "comment"}],
        )

        for uid, _vals in self.ds["dns"].items():
            self.ds["dns"][uid]["comment"] = str(self.ds["dns"][uid]["comment"])

    # ---------------------------
    #   get_dhcp
    # ---------------------------
    def get_dhcp(self) -> None:
        """Get DHCP data from Mikrotik"""
        self.ds["dhcp"] = parse_api(
            data=self.ds["dhcp"],
            source=self.api.query("/ip/dhcp-server/lease"),
            key="mac-address",
            vals=[
                {"name": "mac-address"},
                {"name": "active-mac-address", "default": "unknown"},
                {"name": "address", "default": "unknown"},
                {"name": "active-address", "default": "unknown"},
                {"name": "host-name", "default": "unknown"},
                {"name": "status", "default": "unknown"},
                {"name": "last-seen", "default": "unknown"},
                {"name": "server", "default": "unknown"},
                {"name": "comment", "default": ""},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
            ensure_vals=[{"name": "interface", "default": "unknown"}],
        )

        dhcpserver_query = False
        for uid in self.ds["dhcp"]:
            dhcpserver_query = self._process_dhcp_entry(uid, dhcpserver_query)

        self._build_dhcp_lease_summary()

    def _reconcile_dhcp_addresses(self, entry) -> None:
        """Validate address / active-address / mac-address pairs on a DHCP entry."""
        if entry["address"] == "unknown":
            return
        if not is_valid_ip(entry["address"]):
            entry["address"] = "unknown"

        if entry["active-address"] not in [entry["address"], "unknown"]:
            entry["address"] = entry["active-address"]

        if entry["mac-address"] != entry["active-mac-address"] != "unknown":
            entry["mac-address"] = entry["active-mac-address"]

    def _resolve_dhcp_interface(self, uid, entry) -> None:
        """Resolve DHCP entry interface from dhcp-server or arp data."""
        dhcp_server = self.ds["dhcp-server"]
        if entry["server"] in dhcp_server:
            entry["interface"] = dhcp_server[entry["server"]]["interface"]
            return
        arp = self.ds["arp"]
        if uid in arp:
            entry["interface"] = arp[uid]["bridge"] if arp[uid]["bridge"] != "unknown" else arp[uid]["interface"]

    def _process_dhcp_entry(self, uid, dhcpserver_query) -> bool:
        """Normalize a single DHCP entry. Returns updated ``dhcpserver_query`` flag."""
        entry = self.ds["dhcp"][uid]
        entry["comment"] = str(entry["comment"])

        self._reconcile_dhcp_addresses(entry)

        if not dhcpserver_query and entry["server"] not in self.ds["dhcp-server"]:
            self.get_dhcp_server()
            dhcpserver_query = True

        self._resolve_dhcp_interface(uid, entry)
        return dhcpserver_query

    def _build_dhcp_lease_summary(self) -> None:
        """Summarize current DHCP leases into the ``dhcp_leases`` sensor shape."""
        total = len(self.ds["dhcp"])
        bound = 0
        leases = []
        for uid, entry in self.ds["dhcp"].items():
            if entry.get("status") == "bound":
                bound += 1
            leases.append(
                {
                    "mac": uid,
                    "address": entry.get("address", "unknown"),
                    "host_name": entry.get("host-name", "unknown"),
                    "status": entry.get("status", "unknown"),
                    "server": entry.get("server", "unknown"),
                    "interface": entry.get("interface", "unknown"),
                }
            )
        self.ds["dhcp_leases"] = {
            "total": total,
            "bound": bound,
            "leases": leases,
        }

    # ---------------------------
    #   get_dhcp_server
    # ---------------------------
    def get_dhcp_server(self) -> None:
        """Get DHCP server data from Mikrotik"""
        self.ds["dhcp-server"] = parse_api(
            data=self.ds["dhcp-server"],
            source=self.api.query("/ip/dhcp-server"),
            key="name",
            vals=[
                {"name": "name"},
                {"name": "interface", "default": "unknown"},
            ],
        )

    # ---------------------------
    #   get_ip_address
    # ---------------------------
    def get_ip_address(self) -> None:
        """Get IP address data from Mikrotik"""
        self.ds["ip_address"] = parse_api(
            data=self.ds["ip_address"],
            source=self.api.query("/ip/address"),
            key=".id",
            vals=[
                {"name": ".id"},
                {"name": "address", "default": ""},
                {"name": "network", "default": ""},
                {"name": "interface", "default": ""},
                {"name": "comment", "default": ""},
                {"name": "dynamic", "type": "bool", "default": False},
                {"name": "disabled", "type": "bool", "default": False},
            ],
            ensure_vals=[
                {"name": "port-mac-address", "default": ""},
                {"name": "ip", "default": ""},
            ],
            prune_stale=True,
            stale_counters=self._get_stale_counters("ip_address"),
        )
        for uid in self.ds["ip_address"]:
            iface_name = self.ds["ip_address"][uid]["interface"]
            for iface_uid, iface_data in self.ds["interface"].items():
                if iface_data.get("name") == iface_name or iface_uid == iface_name:
                    self.ds["ip_address"][uid]["port-mac-address"] = iface_data.get("port-mac-address", "")
                    break
            addr = self.ds["ip_address"][uid].get("address", "")
            self.ds["ip_address"][uid]["ip"] = addr.split("/")[0] if addr else ""

        # Remove IP entries for bridge/virtual interfaces with no port-mac-address
        uids_to_remove = [uid for uid in self.ds["ip_address"] if not self.ds["ip_address"][uid].get("port-mac-address")]
        for uid in uids_to_remove:
            del self.ds["ip_address"][uid]

    # ---------------------------
    #   get_cloud
    # ---------------------------
    def get_cloud(self) -> None:
        """Get IP cloud data from Mikrotik"""
        try:
            self.ds["cloud"] = parse_api(
                data=self.ds["cloud"],
                source=self.api.query("/ip/cloud"),
                vals=[
                    {"name": "public-address", "default": ""},
                    {"name": "ddns-enabled", "default": ""},
                    {"name": "dns-name", "default": ""},
                    {"name": "status", "default": ""},
                    {"name": "back-to-home-vpn", "default": ""},
                ],
            )
            self.ds["cloud"]["ddns-hostname"] = self.ds["cloud"].pop("dns-name", "")
            self.ds["cloud"]["ddns-status"] = self.ds["cloud"].pop("status", "")
        except Exception as e:
            _LOGGER.warning("Mikrotik get_cloud failed: %s", e)

    # ---------------------------
    #   get_dhcp_client
    # ---------------------------
    def get_dhcp_client(self) -> None:
        """Get DHCP client data from Mikrotik"""
        self.ds["dhcp-client"] = parse_api(
            data=self.ds["dhcp-client"],
            source=self.api.query("/ip/dhcp-client"),
            key="interface",
            vals=[
                {"name": "interface", "default": "unknown"},
                {"name": "status", "default": "unknown"},
                {"name": "address", "default": "unknown"},
            ],
        )

    # ---------------------------
    #   get_dhcp_network
    # ---------------------------
    def get_dhcp_network(self) -> None:
        """Get DHCP network data from Mikrotik"""
        self.ds["dhcp-network"] = parse_api(
            data=self.ds["dhcp-network"],
            source=self.api.query("/ip/dhcp-server/network"),
            key="address",
            vals=[
                {"name": "address"},
                {"name": "gateway", "default": ""},
                {"name": "netmask", "default": ""},
                {"name": "dns-server", "default": ""},
                {"name": "domain", "default": ""},
            ],
            ensure_vals=[{"name": "address"}, {"name": "IPv4Network", "default": ""}],
        )

        for uid, vals in self.ds["dhcp-network"].items():
            if vals["IPv4Network"] == "":
                self.ds["dhcp-network"][uid]["IPv4Network"] = IPv4Network(vals["address"])

    # ---------------------------
    #   get_capsman_hosts
    # ---------------------------
    def get_capsman_hosts(self) -> None:
        """Get CAPS-MAN hosts data from Mikrotik"""

        if self.major_fw_version > 7 or (self.major_fw_version == 7 and self.minor_fw_version >= 13):
            registration_path = "/interface/wifi/registration-table"

        else:
            registration_path = "/caps-man/registration-table"

        self.ds["capsman_hosts"] = parse_api(
            data={},
            source=self.api.query(registration_path),
            key="mac-address",
            vals=[
                {"name": "mac-address"},
                {"name": "interface", "default": "unknown"},
                {"name": "ssid", "default": "unknown"},
            ],
        )

    # ---------------------------
    #   get_wireless
    # ---------------------------
    def get_wireless(self) -> None:
        """Get wireless data from Mikrotik"""

        self.ds["wireless"] = parse_api(
            data=self.ds["wireless"],
            source=self.api.query(f"/interface/{self._wifimodule}"),
            key="name",
            vals=[
                {"name": "master-interface", "default": ""},
                {"name": "mac-address", "default": "unknown"},
                {"name": "ssid", "default": "unknown"},
                {"name": "mode", "default": "unknown"},
                {"name": "radio-name", "default": "unknown"},
                {"name": "interface-type", "default": "unknown"},
                {"name": "country", "default": "unknown"},
                {"name": "installation", "default": "unknown"},
                {"name": "antenna-gain", "default": "unknown"},
                {"name": "frequency", "default": "unknown"},
                {"name": "band", "default": "unknown"},
                {"name": "channel-width", "default": "unknown"},
                {"name": "secondary-frequency", "default": "unknown"},
                {"name": "wireless-protocol", "default": "unknown"},
                {"name": "rate-set", "default": "unknown"},
                {"name": "distance", "default": "unknown"},
                {"name": "tx-power-mode", "default": "unknown"},
                {"name": "vlan-id", "default": "unknown"},
                {"name": "wds-mode", "default": "unknown"},
                {"name": "wds-default-bridge", "default": "unknown"},
                {"name": "bridge-mode", "default": "unknown"},
                {"name": "hide-ssid", "type": "bool"},
                {"name": "running", "type": "bool"},
                {"name": "disabled", "type": "bool"},
            ],
        )

        for uid in self.ds["wireless"]:
            if self.ds["wireless"][uid]["master-interface"]:
                for tmp in self.ds["wireless"][uid]:
                    if self.ds["wireless"][uid][tmp] == "unknown":
                        self.ds["wireless"][uid][tmp] = self.ds["wireless"][self.ds["wireless"][uid]["master-interface"]][tmp]

            if uid in self.ds["interface"]:
                for tmp in self.ds["wireless"][uid]:
                    self.ds["interface"][uid][tmp] = self.ds["wireless"][uid][tmp]

    # ---------------------------
    #   get_wireless_hosts
    # ---------------------------
    def get_wireless_hosts(self) -> None:
        """Get wireless hosts data from Mikrotik"""
        self.ds["wireless_hosts"] = parse_api(
            data={},
            source=self.api.query(f"/interface/{self._wifimodule}/registration-table"),
            key="mac-address",
            vals=[
                {"name": "mac-address"},
                {"name": "interface", "default": "unknown"},
                {"name": "ap", "type": "bool"},
                {"name": "uptime"},
                {"name": "signal-strength"},
                {"name": "tx-ccq"},
                {"name": "tx-rate"},
                {"name": "rx-rate"},
            ],
        )

    # ---------------------------
    #   async_process_host
    # ---------------------------
    async def async_process_host(self) -> None:
        """Get host tracking data"""
        # Add hosts from CAPS-MAN
        capsman_detected = {}
        if self.support_capsman:
            for uid, vals in self.ds["capsman_hosts"].items():
                if uid not in self.ds["host"]:
                    self.ds["host"][uid] = {"source": "capsman"}
                elif self.ds["host"][uid]["source"] != "capsman":
                    continue

                capsman_detected[uid] = True
                self.ds["host"][uid]["available"] = True
                self.ds["host"][uid]["last-seen"] = utcnow()
                for key in ["mac-address", "interface"]:
                    self.ds["host"][uid][key] = vals[key]

        # Add hosts from wireless
        wireless_detected = {}
        if self.support_wireless:
            for uid, vals in self.ds["wireless_hosts"].items():
                if vals["ap"]:
                    continue

                if uid not in self.ds["host"]:
                    self.ds["host"][uid] = {"source": "wireless"}
                elif self.ds["host"][uid]["source"] == "capsman":
                    continue
                else:
                    self.ds["host"][uid]["source"] = "wireless"

                wireless_detected[uid] = True
                self.ds["host"][uid]["available"] = True
                self.ds["host"][uid]["last-seen"] = utcnow()
                for key in [
                    "mac-address",
                    "interface",
                    "signal-strength",
                    "tx-ccq",
                    "tx-rate",
                    "rx-rate",
                ]:
                    self.ds["host"][uid][key] = vals[key]

        # Add hosts from DHCP
        for uid, vals in self.ds["dhcp"].items():
            if not vals["enabled"]:
                continue

            if uid not in self.ds["host"]:
                self.ds["host"][uid] = {"source": "dhcp"}
            elif self.ds["host"][uid]["source"] != "dhcp":
                continue

            for key in ["address", "mac-address", "interface"]:
                self.ds["host"][uid][key] = vals[key]

        # Add hosts from ARP
        for uid, vals in self.ds["arp"].items():
            if uid not in self.ds["host"]:
                self.ds["host"][uid] = {"source": "arp"}
            elif self.ds["host"][uid]["source"] != "arp":
                continue

            for key in ["address", "mac-address", "interface"]:
                self.ds["host"][uid][key] = vals[key]

        # Add restored hosts from hass registry
        if not self.host_hass_recovered:
            self.host_hass_recovered = True
            for uid in self.ds["host_hass"]:
                uid_lower = uid.lower()
                if uid_lower not in self.ds["host"]:
                    self.ds["host"][uid_lower] = {"source": "restored"}
                    self.ds["host"][uid_lower]["mac-address"] = uid_lower
                    self.ds["host"][uid_lower]["host-name"] = self.ds["host_hass"][uid]

        for uid, _vals in self.ds["host"].items():
            # Add missing default values
            for key, default in zip(
                [
                    "address",
                    "mac-address",
                    "interface",
                    "host-name",
                    "manufacturer",
                    "last-seen",
                    "available",
                ],
                ["unknown", "unknown", "unknown", "unknown", "detect", False, False],
                strict=False,
            ):
                if key not in self.ds["host"][uid]:
                    self.ds["host"][uid][key] = default

        # Mark wired hosts available if present in ARP table
        for uid, vals in self.ds["host"].items():
            if vals.get("source") not in ["capsman", "wireless", "restored"] and (uid in self.ds["arp"] and self.ds["arp"][uid].get("address", "unknown") not in ["unknown", ""]):
                self.ds["host"][uid]["available"] = True
                self.ds["host"][uid]["last-seen"] = utcnow()

        # Process hosts
        self.ds["resource"]["clients_wired"] = 0
        self.ds["resource"]["clients_wireless"] = 0
        _wired_clients = []
        _wireless_clients = []
        for uid, vals in self.ds["host"].items():
            # Captive portal data
            if self.option_sensor_client_captive:
                if uid in self.ds["hostspot_host"]:
                    self.ds["host"][uid]["authorized"] = self.ds["hostspot_host"][uid]["authorized"]
                    self.ds["host"][uid]["bypassed"] = self.ds["hostspot_host"][uid]["bypassed"]
                elif "authorized" in self.ds["host"][uid]:
                    del self.ds["host"][uid]["authorized"]
                    del self.ds["host"][uid]["bypassed"]

            # CAPS-MAN availability
            if vals["source"] == "capsman" and uid not in capsman_detected:
                self.ds["host"][uid]["available"] = False

            # Wireless availability
            if vals["source"] == "wireless" and uid not in wireless_detected:
                self.ds["host"][uid]["available"] = False

            # Update IP and interface (DHCP/returned host)
            if uid in self.ds["dhcp"] and self.ds["dhcp"][uid]["enabled"] and "." in self.ds["dhcp"][uid]["address"]:
                if self.ds["dhcp"][uid]["address"] != self.ds["host"][uid]["address"]:
                    self.ds["host"][uid]["address"] = self.ds["dhcp"][uid]["address"]
                    if vals["source"] not in ["capsman", "wireless"]:
                        self.ds["host"][uid]["source"] = "dhcp"
                        self.ds["host"][uid]["interface"] = self.ds["dhcp"][uid]["interface"]

            elif uid in self.ds["arp"] and "." in self.ds["arp"][uid]["address"] and self.ds["arp"][uid]["address"] != self.ds["host"][uid]["address"]:
                self.ds["host"][uid]["address"] = self.ds["arp"][uid]["address"]
                if vals["source"] not in ["capsman", "wireless"]:
                    self.ds["host"][uid]["source"] = "arp"
                    self.ds["host"][uid]["interface"] = self.ds["arp"][uid]["interface"]

            if vals["host-name"] == "unknown":
                # Resolve hostname from static DNS
                if vals["address"] != "unknown":
                    for _dns_uid, dns_vals in self.ds["dns"].items():
                        if dns_vals["address"] == vals["address"]:
                            if dns_vals["comment"].split("#", 1)[0] != "":
                                self.ds["host"][uid]["host-name"] = dns_vals["comment"].split("#", 1)[0]
                            elif uid in self.ds["dhcp"] and self.ds["dhcp"][uid]["enabled"] and self.ds["dhcp"][uid]["comment"].split("#", 1)[0] != "":
                                # Override name if DHCP comment exists
                                self.ds["host"][uid]["host-name"] = self.ds["dhcp"][uid]["comment"].split("#", 1)[0]
                            else:
                                self.ds["host"][uid]["host-name"] = dns_vals["name"].split(".")[0]
                            break

                if self.ds["host"][uid]["host-name"] == "unknown":
                    # Resolve hostname from DHCP comment
                    if uid in self.ds["dhcp"] and self.ds["dhcp"][uid]["enabled"] and self.ds["dhcp"][uid]["comment"].split("#", 1)[0] != "":
                        self.ds["host"][uid]["host-name"] = self.ds["dhcp"][uid]["comment"].split("#", 1)[0]
                    # Resolve hostname from DHCP hostname
                    elif uid in self.ds["dhcp"] and self.ds["dhcp"][uid]["enabled"] and self.ds["dhcp"][uid]["host-name"] != "unknown":
                        self.ds["host"][uid]["host-name"] = self.ds["dhcp"][uid]["host-name"]
                    # Fallback to mac address for hostname
                    else:
                        self.ds["host"][uid]["host-name"] = uid

            # Resolve manufacturer
            if vals["manufacturer"] == "detect" and vals["mac-address"] != "unknown":
                try:
                    self.ds["host"][uid]["manufacturer"] = await self.async_mac_lookup.lookup(vals["mac-address"])
                except Exception:
                    self.ds["host"][uid]["manufacturer"] = ""

            if vals["manufacturer"] == "detect":
                self.ds["host"][uid]["manufacturer"] = ""

            # Count hosts and build client lists
            if self.ds["host"][uid]["available"]:
                client_info = {
                    "mac": vals.get("mac-address", uid),
                    "address": vals.get("address", "unknown"),
                    "host_name": vals.get("host-name", "unknown"),
                    "interface": vals.get("interface", "unknown"),
                }
                if vals["source"] in ["capsman", "wireless"]:
                    self.ds["resource"]["clients_wireless"] += 1
                    _wireless_clients.append(client_info)
                else:
                    self.ds["resource"]["clients_wired"] += 1
                    _wired_clients.append(client_info)

        self.ds["resource"]["wired_clients_list"] = _wired_clients
        self.ds["resource"]["wireless_clients_list"] = _wireless_clients

    # ---------------------------
    #   _get_iface_from_entry
    # ---------------------------
    def _get_iface_from_entry(self, entry):
        """Get interface default-name using name from interface dict"""
        uid = None
        for ifacename in self.ds["interface"]:
            if self.ds["interface"][ifacename]["name"] == entry["interface"]:
                uid = ifacename
                break

        return uid

    # ---------------------------
    #   sync_kid_control_monitoring_profile
    # ---------------------------
    _HA_MONITORING_PROFILE = "ha-monitoring"

    def sync_kid_control_monitoring_profile(self) -> None:
        """Create or remove the ha-monitoring kid-control profile based on integration option."""
        existing = self.api.query(PATH_IP_KID_CONTROL) or []
        has_profile = any(p.get("name") == self._HA_MONITORING_PROFILE for p in existing)

        if self.option_sensor_client_traffic:
            if not has_profile:
                success = self.api.execute(
                    PATH_IP_KID_CONTROL,
                    "add",
                    None,
                    None,
                    attributes={
                        "name": self._HA_MONITORING_PROFILE,
                        "mon": "0s-1d",
                        "tue": "0s-1d",
                        "wed": "0s-1d",
                        "thu": "0s-1d",
                        "fri": "0s-1d",
                        "sat": "0s-1d",
                        "sun": "0s-1d",
                    },
                )
                if success:
                    _LOGGER.info(
                        "Mikrotik %s: Created kid-control profile '%s' for device traffic monitoring",
                        self.host,
                        self._HA_MONITORING_PROFILE,
                    )
                else:
                    _LOGGER.warning(
                        "Mikrotik %s: Could not create kid-control profile '%s'. Create it manually: /ip/kid-control/add name=%s mon=0s-1d tue=0s-1d wed=0s-1d thu=0s-1d fri=0s-1d sat=0s-1d sun=0s-1d",
                        self.host,
                        self._HA_MONITORING_PROFILE,
                        self._HA_MONITORING_PROFILE,
                    )
        else:
            if has_profile:
                success = self.api.execute(PATH_IP_KID_CONTROL, "remove", "name", self._HA_MONITORING_PROFILE)
                if success:
                    _LOGGER.info(
                        "Mikrotik %s: Removed kid-control profile '%s'",
                        self.host,
                        self._HA_MONITORING_PROFILE,
                    )

    # ---------------------------
    #   process_kid_control
    # ---------------------------
    def process_kid_control_devices(self) -> None:
        """Get Kid Control Device data from Mikrotik"""

        # Build missing hosts from main hosts dict
        for uid, vals in self.ds["host"].items():
            if uid not in self.ds["client_traffic"]:
                self.ds["client_traffic"][uid] = {
                    "address": vals["address"],
                    "mac-address": vals["mac-address"],
                    "host-name": vals["host-name"],
                    "tx": 0.0,
                    "rx": 0.0,
                    "available": False,
                }

        _LOGGER.debug(f"Working with {len(self.ds['client_traffic'])} kid control devices")

        kid_control_devices_data = parse_api(
            data={},
            source=self.api.query("/ip/kid-control/device"),
            key="mac-address",
            vals=[
                {"name": "mac-address"},
                {"name": "rate-down", "default": 0},
                {"name": "rate-up", "default": 0},
                {
                    "name": "enabled",
                    "source": "disabled",
                    "type": "bool",
                    "reverse": True,
                },
            ],
        )

        if not kid_control_devices_data:
            if "kid-control-devices" not in self.notified_flags:
                _LOGGER.warning(
                    "Mikrotik %s: No Kid Control devices found. Either configure Kid Control on your router, or disable 'Kid control' in the integration options.",
                    self.host,
                )
                self.notified_flags.append("kid-control-devices")
            return
        elif "kid-control-devices" in self.notified_flags:
            self.notified_flags.remove("kid-control-devices")

        for uid, vals in kid_control_devices_data.items():
            if uid not in self.ds["client_traffic"]:
                _LOGGER.debug(f"Skipping unknown device {uid}")
                continue

            self.ds["client_traffic"][uid]["available"] = vals["enabled"]
            # Dynamic kid-control entries (created by ha-monitoring profile) report
            # rate-up/rate-down in bits/sec; convert to bytes/sec for the sensor unit
            self.ds["client_traffic"][uid]["tx"] = round(vals["rate-up"] / 8)
            self.ds["client_traffic"][uid]["rx"] = round(vals["rate-down"] / 8)
