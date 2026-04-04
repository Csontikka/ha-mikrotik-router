"""Mikrotik Router integration."""

from __future__ import annotations

import voluptuous as vol
import logging
from collections import deque

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry
from homeassistant.config_entries import ConfigEntry

from homeassistant.const import CONF_VERIFY_SSL

from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_PORT, CONF_SSL

from .const import PLATFORMS, DOMAIN, DEFAULT_VERIFY_SSL
from .coordinator import MikrotikData, MikrotikCoordinator, MikrotikTrackerCoordinator
from .mikrotikapi import MikrotikAPI

SCRIPT_SCHEMA = vol.Schema(
    {vol.Required("router"): cv.string, vol.Required("script"): cv.string}
)

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
_log_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
_integration_logger = logging.getLogger("custom_components.mikrotik_router")
_integration_logger.addHandler(_log_handler)
_integration_logger.setLevel(logging.DEBUG)


# ---------------------------
#   async_setup
# ---------------------------
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register global actions (services) once at integration load time."""

    async def async_send_magic_packet(call) -> None:
        """Send a WoL magic packet via all connected MikroTik routers."""
        mac = call.data["mac"]
        interface = call.data.get("interface")
        for entry_data in hass.data.get(DOMAIN, {}).values():
            success = await hass.async_add_executor_job(
                entry_data.data_coordinator.api.wol, mac, interface
            )
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
        for entry_data in hass.data.get(DOMAIN, {}).values():
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

    return True


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    _LOGGER.info(
        "Setting up Mikrotik Router integration for %s",
        config_entry.data.get("host", "unknown"),
    )
    coordinator = MikrotikCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
    coordinatorTracker = MikrotikTrackerCoordinator(hass, config_entry, coordinator)
    await coordinatorTracker.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = MikrotikData(
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

    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        hass.data[DOMAIN].pop(config_entry.entry_id)

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
async def async_remove_config_entry_device(
    hass, config_entry: ConfigEntry, device_entry: device_registry.DeviceEntry
) -> bool:
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
