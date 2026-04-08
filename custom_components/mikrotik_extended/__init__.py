"""MikroTik Extended integration."""

from __future__ import annotations

import logging
import re
from collections import deque

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_SSL, CONF_USERNAME

from .const import DEFAULT_VERIFY_SSL, DOMAIN, PLATFORMS
from .coordinator import MikrotikCoordinator, MikrotikData, MikrotikTrackerCoordinator
from .mikrotikapi import MikrotikAPI

SCRIPT_SCHEMA = vol.Schema({vol.Required("router"): cv.string, vol.Required("script"): cv.string})

WOL_SCHEMA = vol.Schema(
    {
        vol.Required("mac"): cv.string,
        vol.Optional("interface"): cv.string,
    }
)

API_TEST_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Optional("limit", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional("host"): cv.string,
        vol.Optional("coordinator_data", default=False): cv.boolean,
    }
)

_LOGGER = logging.getLogger(__name__)

# Ring buffer for diagnostics log capture
_LOG_BUFFER = deque(maxlen=1000)


class _RingBufferHandler(logging.Handler):
    """Logging handler that stores records in a ring buffer for diagnostics."""

    def __init__(self, buffer):
        super().__init__()
        self._buffer = buffer

    def emit(self, record):
        self._buffer.append(self.format(record))


_log_handler = _RingBufferHandler(_LOG_BUFFER)
_log_handler.setLevel(logging.DEBUG)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
_integration_logger = logging.getLogger("custom_components.mikrotik_extended")
_integration_logger.addHandler(_log_handler)
_integration_logger.setLevel(logging.DEBUG)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


# ---------------------------
#   async_setup
# ---------------------------
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register global actions (services) once at integration load time."""

    async def async_send_magic_packet(call) -> None:
        """Send a WoL magic packet via all connected MikroTik routers."""
        mac = call.data["mac"]
        if not _MAC_RE.match(mac):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_mac",
                translation_placeholders={"mac": mac},
            )
        interface = call.data.get("interface")
        for entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data"):
                continue
            entry_data = entry.runtime_data
            success = await hass.async_add_executor_job(entry_data.data_coordinator.api.wol, mac, interface)
            if not success:
                _LOGGER.warning(
                    "WoL: failed to send magic packet to %s via router %s",
                    mac,
                    entry_data.data_coordinator.config_entry.data.get("host", "unknown"),
                )

    hass.services.async_register(
        DOMAIN,
        "send_magic_packet",
        async_send_magic_packet,
        schema=WOL_SCHEMA,
    )

    async def async_api_test(call):
        """Test a raw Mikrotik API call and return the response."""
        path = call.data["path"]
        limit = call.data.get("limit", 10)
        host_filter = call.data.get("host")
        use_coordinator_data = call.data.get("coordinator_data", False)

        results = {}
        for entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data"):
                continue
            entry_data = entry.runtime_data
            coordinator = entry_data.data_coordinator
            router_host = coordinator.config_entry.data.get("host", "unknown")
            if host_filter and router_host != host_filter:
                continue
            try:
                if use_coordinator_data:
                    data = coordinator.data.get(path) if coordinator.data else None
                    if data is None:
                        results[router_host] = {"error": f"No coordinator data for path '{path}'"}
                    elif isinstance(data, dict):
                        items = list(data.items())[:limit]
                        safe_items = {str(k): {str(ik): str(iv) for ik, iv in v.items()} if isinstance(v, dict) else str(v) for k, v in items}
                        results[router_host] = {"total_keys": len(data), "items": safe_items}
                    else:
                        results[router_host] = {"value": str(data)}
                else:
                    raw = await hass.async_add_executor_job(coordinator.api.query, path)
                    if raw is None:
                        results[router_host] = {"error": "No response or not connected"}
                    else:
                        items = raw[:limit]
                        safe_items = []
                        for item in items:
                            if isinstance(item, dict):
                                safe_items.append({str(k): str(v) for k, v in item.items()})
                            else:
                                safe_items.append(str(item))
                        results[router_host] = {"total_returned": len(raw), "items": safe_items}
            except Exception as exc:
                results[router_host] = {"error": str(exc)}

        return {"result": results}

    hass.services.async_register(
        DOMAIN,
        "api_test",
        async_api_test,
        schema=API_TEST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def async_refresh_data(call) -> None:
        """Force an immediate data refresh on all (or a specific) router."""
        host_filter = call.data.get("host")
        for entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data"):
                continue
            entry_data = entry.runtime_data
            router_host = entry_data.data_coordinator.config_entry.data.get("host", "unknown")
            if host_filter and router_host != host_filter:
                continue
            await entry_data.data_coordinator.async_request_refresh()
            await entry_data.tracker_coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "refresh_data",
        async_refresh_data,
        schema=vol.Schema({vol.Optional("host"): cv.string}),
    )

    async def async_set_environment(call) -> None:
        """Set, create or remove a RouterOS script environment variable."""
        name = call.data["name"]
        value = call.data.get("value")
        action = call.data.get("action", "set")
        host_filter = call.data.get("host")

        if action in ("add", "set") and value is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="missing_value",
            )

        for entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data"):
                continue
            entry_data = entry.runtime_data
            coordinator = entry_data.data_coordinator
            router_host = coordinator.config_entry.data.get("host", "unknown")
            if host_filter and router_host != host_filter:
                continue

            if action == "remove":
                success = await hass.async_add_executor_job(
                    coordinator.api.remove_env_variable,
                    name,
                )
            else:  # add or set
                success = await hass.async_add_executor_job(
                    coordinator.api.set_env_variable,
                    name,
                    value,
                )

            if not success:
                _LOGGER.warning(
                    "set_environment: %s '%s' failed on %s",
                    action,
                    name,
                    router_host,
                )
            else:
                await entry_data.data_coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "set_environment",
        async_set_environment,
        schema=vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("value"): cv.string,
                vol.Optional("action", default="set"): vol.In(["set", "add", "remove"]),
                vol.Optional("host"): cv.string,
            }
        ),
    )

    return True


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    host = config_entry.data.get(CONF_HOST, "unknown")
    _LOGGER.info("Setting up MikroTik Extended integration for %s", host)

    # Early credential check — raises ConfigEntryAuthFailed immediately
    # so HA triggers reauth flow instead of setup_retry loop.
    api = MikrotikAPI(
        config_entry.data[CONF_HOST],
        config_entry.data[CONF_USERNAME],
        config_entry.data[CONF_PASSWORD],
        config_entry.data[CONF_PORT],
        config_entry.data[CONF_SSL],
        config_entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    connected = await hass.async_add_executor_job(api.connect)
    if not connected:
        if api.error == "wrong_login":
            raise ConfigEntryAuthFailed(f"Invalid credentials for {host}")
        raise ConfigEntryNotReady(f"Cannot connect to {host}")
    api.close()

    coordinator = MikrotikCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
    coordinatorTracker = MikrotikTrackerCoordinator(hass, config_entry, coordinator)
    await coordinatorTracker.async_config_entry_first_refresh()
    config_entry.runtime_data = MikrotikData(
        data_coordinator=coordinator,
        tracker_coordinator=coordinatorTracker,
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    config_entry.async_on_unload(config_entry.add_update_listener(async_reload_entry))

    return True


# ---------------------------
#   async_reload_entry
# ---------------------------
async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload the config entry when it changed."""
    await hass.config_entries.async_reload(config_entry.entry_id)


# ---------------------------
#   async_unload_entry
# ---------------------------
async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    # Suppress disconnect error logs before platform unload cancels the coordinator
    if hasattr(config_entry, "runtime_data") and config_entry.runtime_data:
        coordinator = config_entry.runtime_data.data_coordinator
        if coordinator and coordinator.api:
            coordinator.api.connection_error_reported = True

    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    if hasattr(config_entry, "runtime_data") and config_entry.runtime_data:
        coordinator = config_entry.runtime_data.data_coordinator
        if coordinator and coordinator.api:
            await hass.async_add_executor_job(coordinator.api.close)

    return unload_ok


# ---------------------------
#   async_remove_entry
# ---------------------------
async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Clean up router-side resources when the integration is removed."""
    api = MikrotikAPI(
        config_entry.data[CONF_HOST],
        config_entry.data[CONF_USERNAME],
        config_entry.data[CONF_PASSWORD],
        config_entry.data[CONF_PORT],
        config_entry.data[CONF_SSL],
        config_entry.data[CONF_VERIFY_SSL],
    )

    connected = await hass.async_add_executor_job(api.connect)
    if not connected:
        _LOGGER.warning(
            "Mikrotik %s: Could not connect during removal — skipping cleanup",
            config_entry.data.get(CONF_HOST),
        )
        return

    def _cleanup():
        try:
            existing = api.query("/ip/kid-control") or []
            if any(p.get("name") == "ha-monitoring" for p in existing):
                api.execute("/ip/kid-control", "remove", "name", "ha-monitoring")
                _LOGGER.info(
                    "Mikrotik %s: Removed ha-monitoring kid-control profile",
                    config_entry.data.get(CONF_HOST),
                )
        finally:
            api.disconnect()

    await hass.async_add_executor_job(_cleanup)


# ---------------------------
#   async_remove_config_entry_device
# ---------------------------
async def async_remove_config_entry_device(hass, config_entry: ConfigEntry, device_entry: device_registry.DeviceEntry) -> bool:
    """Remove a config entry from a device."""
    return True


# ---------------------------
#   async_migrate_entry
# ---------------------------
async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version < 2:
        new_data = {**config_entry.data}
        new_data[CONF_VERIFY_SSL] = DEFAULT_VERIFY_SSL
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )
    return True
