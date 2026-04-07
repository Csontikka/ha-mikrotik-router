"""Support for the Mikrotik Router device tracker."""

from __future__ import annotations

PARALLEL_UPDATES = 0

from collections.abc import Callable, Mapping
from datetime import timedelta
from logging import getLogger
from typing import Any

from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_NOT_HOME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    entity_platform as ep,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify
from homeassistant.util.dt import utcnow

from .const import (
    CONF_TRACK_HOSTS,
    CONF_TRACK_HOSTS_TIMEOUT,
    DEFAULT_TRACK_HOST_TIMEOUT,
    DEFAULT_TRACK_HOSTS,
    DOMAIN,
)
from .coordinator import MikrotikCoordinator
from .device_tracker_types import (
    SENSOR_SERVICES,  # noqa: F401 — accessed via platform.platform.SENSOR_SERVICES
    SENSOR_TYPES,  # noqa: F401 — accessed via platform.platform.SENSOR_TYPES
)
from .entity import MikrotikEntity, _skip_sensor
from .helper import format_attribute

_LOGGER = getLogger(__name__)


async def async_add_entities(hass: HomeAssistant, config_entry: ConfigEntry, dispatcher: dict[str, Callable]):
    """Add entities."""
    platform = ep.async_get_current_platform()
    services = platform.platform.SENSOR_SERVICES
    descriptions = platform.platform.SENSOR_TYPES

    for service in services:
        platform.async_register_entity_service(service[0], service[1], service[2])

    @callback
    async def async_update_controller(coordinator):
        """Update the values of the controller."""
        if coordinator.data is None:
            return

        async def async_check_exist(obj, coordinator, uid: None) -> None:
            """Check entity exists."""
            entity_registry = er.async_get(hass)
            entry_id = config_entry.entry_id
            if uid:
                unique_id = f"{entry_id}-{obj.entity_description.key}-{slugify(str(obj._data[obj.entity_description.data_reference]).lower())}"
            else:
                unique_id = f"{entry_id}-{obj.entity_description.key}"

            entity_id = entity_registry.async_get_entity_id(platform.domain, DOMAIN, unique_id)
            entity = entity_registry.async_get(entity_id)
            if entity is None or ((entity_id not in platform.entities) and (entity.disabled is False)):
                _LOGGER.debug("Add entity %s", entity_id)
                await platform.async_add_entities([obj])

        for entity_description in descriptions:
            data = coordinator.data.get(entity_description.data_path)
            if data is None:
                continue
            if not entity_description.data_reference:
                if data.get(entity_description.data_attribute) is None:
                    continue
                func = dispatcher.get(entity_description.func)
                if func is None:
                    continue
                obj = func(coordinator, entity_description)
                await async_check_exist(obj, coordinator, None)
            else:
                if isinstance(data, (dict, list)):
                    for uid in data:
                        if _skip_sensor(config_entry, entity_description, data, uid):
                            continue
                        func = dispatcher.get(entity_description.func)
                        if func is None:
                            continue
                        obj = func(coordinator, entity_description, uid)
                        await async_check_exist(obj, coordinator, uid)

    await async_update_controller(config_entry.runtime_data.tracker_coordinator)

    # Remove orphaned entities that are no longer provided by this platform.
    # Only run if tracker data is available; skip on first startup before any data arrives.
    if config_entry.runtime_data.tracker_coordinator.data is not None:
        entity_registry = er.async_get(hass)
        for entry in er.async_entries_for_config_entry(entity_registry, config_entry.entry_id):
            if entry.domain == platform.domain and entry.entity_id not in platform.entities:
                if entry.disabled:
                    continue
                _LOGGER.debug("Removing orphaned entity %s", entry.entity_id)
                entity_registry.async_remove(entry.entity_id)

    @callback
    async def async_update_controller_wrapper(coordinator):
        """Dispatcher fires with MikrotikCoordinator, but device trackers need tracker_coordinator."""
        await async_update_controller(config_entry.runtime_data.tracker_coordinator)

    unsub = async_dispatcher_connect(hass, f"update_sensors_{config_entry.entry_id}", async_update_controller_wrapper)
    config_entry.async_on_unload(unsub)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry for component"""
    dispatcher = {
        "MikrotikDeviceTracker": MikrotikDeviceTracker,
        "MikrotikHostDeviceTracker": MikrotikHostDeviceTracker,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   MikrotikDeviceTracker
# ---------------------------
class MikrotikDeviceTracker(MikrotikEntity, ScannerEntity):
    """Representation of a device tracker."""

    def __init__(
        self,
        coordinator: MikrotikCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Initialize entity"""
        super().__init__(coordinator, entity_description, uid)
        self._attr_name = None

    @property
    def ip_address(self) -> str:
        """Return the primary ip address of the device."""
        return self._data.get("address", None)

    @property
    def mac_address(self) -> str:
        """Return the mac address of the device."""
        if self.entity_description.data_reference in self._data:
            return self._data[self.entity_description.data_reference]

        return ""

    @property
    def hostname(self) -> str:
        """Return hostname of the device."""
        if self.entity_description.data_name in self._data:
            return self._data[self.entity_description.data_name]

        return ""

    @property
    def is_connected(self) -> bool:
        """Return true if device is connected."""
        return self._data[self.entity_description.data_attribute]

    @property
    def source_type(self) -> str:
        """Return the source type of the port."""
        return SourceType.ROUTER


# ---------------------------
#   MikrotikHostDeviceTracker
# ---------------------------
class MikrotikHostDeviceTracker(MikrotikDeviceTracker):
    """Representation of a network device."""

    @property
    def option_track_network_hosts(self):
        """Config entry option to not track ARP."""
        return self._config_entry.options.get(CONF_TRACK_HOSTS, DEFAULT_TRACK_HOSTS)

    @property
    def option_track_network_hosts_timeout(self):
        """Config entry option scan interval."""
        track_network_hosts_timeout = self._config_entry.options.get(CONF_TRACK_HOSTS_TIMEOUT, DEFAULT_TRACK_HOST_TIMEOUT)
        return timedelta(seconds=track_network_hosts_timeout)

    @property
    def is_connected(self) -> bool:
        """Return true if the host is connected to the network."""
        if not self.option_track_network_hosts:
            return False

        if self._data["source"] in ["capsman", "wireless"]:
            return self._data[self.entity_description.data_attribute]

        return bool(self._data["last-seen"] and utcnow() - self._data["last-seen"] < self.option_track_network_hosts_timeout)

    @property
    def icon(self) -> str:
        """Return the icon."""
        if self._data["source"] in ["capsman", "wireless"]:
            if self._data[self.entity_description.data_attribute]:
                return self.entity_description.icon_enabled
            else:
                return self.entity_description.icon_disabled

        if self._data["last-seen"] and (utcnow() - self._data["last-seen"]) < self.option_track_network_hosts_timeout:
            return self.entity_description.icon_enabled
        return self.entity_description.icon_disabled

    @property
    def state(self) -> str:
        """Return the state of the device."""
        return self.coordinator.option_zone if self.is_connected else STATE_NOT_HOME

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes
        if self.is_connected:
            attributes[format_attribute("last-seen")] = "Now"

        if not attributes[format_attribute("last-seen")]:
            attributes[format_attribute("last-seen")] = "Unknown"

        return attributes
