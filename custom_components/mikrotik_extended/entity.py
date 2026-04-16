"""Mikrotik HA shared entity model"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from logging import getLogger
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION, CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_platform as ep,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    ATTRIBUTION,
    CONF_SENSOR_NETWATCH_TRACKER,
    CONF_SENSOR_PORT_TRACKER,
    CONF_SENSOR_PORT_TRAFFIC,
    CONF_TRACK_HOSTS,
    DEFAULT_SENSOR_NETWATCH_TRACKER,
    DEFAULT_SENSOR_PORT_TRACKER,
    DEFAULT_SENSOR_PORT_TRAFFIC,
    DEFAULT_TRACK_HOSTS,
    DOMAIN,
)
from .coordinator import MikrotikCoordinator, MikrotikTrackerCoordinator
from .helper import format_attribute

_LOGGER = getLogger(__name__)

_FIREWALL_GROUPS = {"NAT", "Mangle", "Filter", "Routing Rules"}
_IFACE_TYPE_CATEGORY = {
    "ether": "port",
    "vlan": "vlan",
    "wlan": "wifi",
    "bridge": "bridge",
    "pppoe-out": "ppp",
    "ppp": "ppp",
    "l2tp-out": "vpn",
    "sstp-out": "vpn",
    "ovpn-out": "vpn",
    "wireguard": "vpn",
}


def _skip_interface_traffic_sensor(config_entry, entity_description, item) -> bool:
    if entity_description.func != "MikrotikInterfaceTrafficSensor":
        return False
    if not config_entry.options.get(CONF_SENSOR_PORT_TRAFFIC, DEFAULT_SENSOR_PORT_TRAFFIC):
        return True
    return item["type"] == "bridge"


def _skip_client_traffic(entity_description, item) -> bool:
    if entity_description.data_path != "client_traffic":
        return False
    if not item.get("available", False):
        return True
    return entity_description.data_attribute not in item


def _skip_port_binary_sensor(config_entry, entity_description, item) -> bool:
    if entity_description.func != "MikrotikPortBinarySensor":
        return False
    if item["type"] == "wlan":
        return True
    return not config_entry.options.get(CONF_SENSOR_PORT_TRACKER, DEFAULT_SENSOR_PORT_TRACKER)


def _skip_netwatch(config_entry, entity_description) -> bool:
    return entity_description.data_path == "netwatch" and not config_entry.options.get(CONF_SENSOR_NETWATCH_TRACKER, DEFAULT_SENSOR_NETWATCH_TRACKER)


def _skip_host_tracker(config_entry, entity_description) -> bool:
    return entity_description.func == "MikrotikHostDeviceTracker" and not config_entry.options.get(CONF_TRACK_HOSTS, DEFAULT_TRACK_HOSTS)


def _skip_sensor(config_entry, entity_description, data, uid) -> bool:
    item = data[uid]
    if _skip_interface_traffic_sensor(config_entry, entity_description, item):
        return True
    if _skip_client_traffic(entity_description, item):
        return True
    if _skip_port_binary_sensor(config_entry, entity_description, item):
        return True
    if _skip_netwatch(config_entry, entity_description):
        return True
    return _skip_host_tracker(config_entry, entity_description)


# ---------------------------
#   async_add_entities
# ---------------------------
def _build_unique_id(entry_id, obj, uid) -> str:
    if uid:
        return f"{entry_id}-{obj.entity_description.key}-{slugify(str(obj._data[obj.entity_description.data_reference]).lower())}"
    return f"{entry_id}-{obj.entity_description.key}"


async def _try_re_enable_entity(platform, entity_registry, entity, entity_id, obj, config_entry) -> None:
    """Re-enable a previously disabled integration entity when its option flips on."""
    if entity.disabled_by != er.RegistryEntryDisabler.INTEGRATION:
        return
    enable_on = getattr(obj.entity_description, "enable_on_option", None)
    if enable_on and config_entry.options.get(enable_on, False):
        _LOGGER.debug("Re-enabling entity %s", entity_id)
        entity_registry.async_update_entity(entity_id, disabled_by=None)
        await platform.async_add_entities([obj])


def _cleanup_orphans(hass, platform, config_entry) -> None:
    """Remove orphaned entities and empty devices for this config entry."""
    entity_registry = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(entity_registry, config_entry.entry_id):
        if entry.domain == platform.domain and entry.entity_id not in platform.entities:
            if entry.disabled:
                continue
            _LOGGER.debug("Removing orphaned entity %s", entry.entity_id)
            entity_registry.async_remove(entry.entity_id)

    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_registry, config_entry.entry_id):
        device_entities = er.async_entries_for_device(entity_registry, device_entry.id, include_disabled_entities=True)
        if not device_entities:
            _LOGGER.debug("Removing empty device %s", device_entry.name)
            device_registry.async_remove_device(device_entry.id)


async def async_add_entities(hass: HomeAssistant, config_entry: ConfigEntry, dispatcher: dict[str, Callable]):
    """Add entities."""
    platform = ep.async_get_current_platform()
    services = platform.platform.SENSOR_SERVICES
    descriptions = platform.platform.SENSOR_TYPES

    for service in services:
        platform.async_register_entity_service(service[0], service[1], service[2])

    async def async_check_exist(obj, uid: str | None = None) -> None:
        """Check entity exists and add or re-enable as appropriate."""
        entity_registry = er.async_get(hass)
        unique_id = _build_unique_id(config_entry.entry_id, obj, uid)
        entity_id = entity_registry.async_get_entity_id(platform.domain, DOMAIN, unique_id)
        entity = entity_registry.async_get(entity_id)
        if entity is None or ((entity_id not in platform.entities) and (entity.disabled is False)):
            _LOGGER.debug("Add entity %s", entity_id)
            await platform.async_add_entities([obj])
        elif entity is not None:
            await _try_re_enable_entity(platform, entity_registry, entity, entity_id, obj, config_entry)

    async def _process_singleton(coordinator, entity_description, data) -> None:
        if data.get(entity_description.data_attribute) is None:
            return
        func = dispatcher.get(entity_description.func)
        if func is None:
            return
        obj = func(coordinator, entity_description)
        await async_check_exist(obj)

    async def _process_keyed(coordinator, entity_description, data) -> None:
        if not isinstance(data, (dict, list)):
            return
        for uid in data:
            if _skip_sensor(config_entry, entity_description, data, uid):
                continue
            func = dispatcher.get(entity_description.func)
            if func is None:
                continue
            obj = func(coordinator, entity_description, uid)
            await async_check_exist(obj, uid)

    @callback
    async def async_update_controller(coordinator):
        """Update the values of the controller."""
        if coordinator.data is None:
            return

        for entity_description in descriptions:
            data = coordinator.data.get(entity_description.data_path)
            if data is None:
                continue
            if not entity_description.data_reference:
                await _process_singleton(coordinator, entity_description, data)
            else:
                await _process_keyed(coordinator, entity_description, data)

        _cleanup_orphans(hass, platform, config_entry)

    await async_update_controller(config_entry.runtime_data.data_coordinator)

    unsub = async_dispatcher_connect(hass, f"update_sensors_{config_entry.entry_id}", async_update_controller)
    config_entry.async_on_unload(unsub)


_MikrotikCoordinatorT = TypeVar(
    "_MikrotikCoordinatorT",
    bound=MikrotikCoordinator | MikrotikTrackerCoordinator,
)


# ---------------------------
#   MikrotikEntity
# ---------------------------
class MikrotikEntity(CoordinatorEntity[_MikrotikCoordinatorT], Entity):
    """Define entity"""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"leases", "wired_clients_list", "wireless_clients_list"})

    def __init__(
        self,
        coordinator: MikrotikCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Initialize entity"""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._inst = coordinator.config_entry.data[CONF_NAME]
        self._config_entry = self.coordinator.config_entry
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._uid = uid
        self._data = coordinator.data[self.entity_description.data_path]
        if self._uid:
            self._data = coordinator.data[self.entity_description.data_path][self._uid]

        self._attr_name = self.custom_name

    @callback
    def _handle_coordinator_update(self) -> None:
        path_data = self.coordinator.data.get(self.entity_description.data_path)
        if path_data is None:
            return
        if self._uid:
            if self._uid not in path_data:
                return
            self._data = path_data[self._uid]
        else:
            self._data = path_data
        self._attr_name = self.custom_name
        super()._handle_coordinator_update()

    @property
    def custom_name(self) -> str:
        """Return the name for this entity"""
        if not self._uid:
            if self.entity_description.data_name_comment and self._data.get("comment"):
                comment = self._data["comment"]
                if self.entity_description.name:
                    return f"{comment} {self.entity_description.name}"
                return comment

            return f"{self.entity_description.name}"

        if self.entity_description.data_name_comment and self._data.get("comment"):
            comment = self._data["comment"]
            if self.entity_description.name:
                return f"{comment} {self.entity_description.name}"
            return comment

        if self.entity_description.name:
            if self._data[self.entity_description.data_reference] == self._data[self.entity_description.data_name]:
                return f"{self.entity_description.name}"

            return f"{self._data[self.entity_description.data_name]} {self.entity_description.name}"

        return f"{self._data[self.entity_description.data_name]}"

    @property
    def unique_id(self) -> str:
        """Return a unique id for this entity"""
        entry_id = self._config_entry.entry_id
        if self._uid:
            return f"{entry_id}-{self.entity_description.key}-{slugify(str(self._data[self.entity_description.data_reference]).lower())}"
        else:
            return f"{entry_id}-{self.entity_description.key}"

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if entity should be enabled by default."""
        if self.entity_description.entity_registry_enabled_default:
            return True
        enable_on = getattr(self.entity_description, "enable_on_option", None)
        if enable_on:
            return bool(self._config_entry.options.get(enable_on, False))
        return False

    def _resolve_device_identity(self) -> tuple[str, Any, str]:
        """Resolve (dev_connection, dev_connection_value, dev_group) from entity description."""
        dev_connection = DOMAIN
        dev_connection_value = self.entity_description.data_reference
        dev_group = self.entity_description.ha_group
        if self.entity_description.ha_group == "System":
            dev_group = self.coordinator.data["resource"]["board-name"]
            dev_connection_value = self.coordinator.data["routerboard"]["serial-number"]

        if self.entity_description.ha_group.startswith("data__"):
            dev_group = self.entity_description.ha_group[6:]
            if dev_group in self._data:
                dev_group = self._data[dev_group]
                dev_connection_value = dev_group

        if self.entity_description.ha_connection:
            dev_connection = self.entity_description.ha_connection

        if self.entity_description.ha_connection_value:
            dev_connection_value = self.entity_description.ha_connection_value
            if dev_connection_value.startswith("data__"):
                dev_connection_value = dev_connection_value[6:]
                dev_connection_value = self._data[dev_connection_value]

        return dev_connection, dev_connection_value, dev_group

    def _build_system_device_info(self, entry_id, dev_connection, dev_connection_value) -> DeviceInfo:
        return DeviceInfo(
            connections={(dev_connection, f"{entry_id}-{dev_connection_value}")},
            identifiers={(dev_connection, f"{entry_id}-{dev_connection_value}")},
            name=f"{self._inst} router Core",
            model=f"{self.coordinator.data['resource']['board-name']}",
            manufacturer=f"{self.coordinator.data['resource']['platform']}",
            sw_version=f"{self.coordinator.data['resource']['version']}",
            configuration_url=f"http://{self.coordinator.config_entry.data[CONF_HOST]}",  # NOSONAR
        )

    def _build_mac_device_info(self, entry_id, dev_connection, dev_connection_value) -> DeviceInfo:
        dev_group = self._data[self.entity_description.data_name]
        dev_manufacturer = ""
        if dev_connection_value in self.coordinator.data["host"]:
            dev_group = self.coordinator.data["host"][dev_connection_value]["host-name"]
            dev_manufacturer = self.coordinator.data["host"][dev_connection_value]["manufacturer"]

        return DeviceInfo(
            connections={(dev_connection, f"{dev_connection_value}")},
            default_name=f"{dev_group}",
            default_manufacturer=f"{dev_manufacturer}",
            via_device=(
                DOMAIN,
                f"{entry_id}-{self.coordinator.data['routerboard']['serial-number']}",
            ),
        )

    def _build_generic_device_info(self, entry_id, dev_connection, dev_connection_value, dev_group) -> DeviceInfo:
        orig_ha_group = self.entity_description.ha_group
        if orig_ha_group.startswith("data__"):
            iface_type = self._data.get("type", "")
            category = _IFACE_TYPE_CATEGORY.get(iface_type, "port")
            dev_display_name = f"{self._inst} router {category} {dev_group}"
        elif orig_ha_group in _FIREWALL_GROUPS:
            dev_display_name = f"{self._inst} router firewall {dev_group}"
        else:
            dev_display_name = f"{self._inst} router {dev_group}"
        return DeviceInfo(
            connections={(dev_connection, f"{entry_id}-{dev_connection_value}")},
            default_name=dev_display_name,
            default_model=f"{self.coordinator.data['resource']['board-name']}",
            default_manufacturer=f"{self.coordinator.data['resource']['platform']}",
            via_device=(
                DOMAIN,
                f"{entry_id}-{self.coordinator.data['routerboard']['serial-number']}",
            ),
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return a description for device registry."""
        dev_connection, dev_connection_value, dev_group = self._resolve_device_identity()
        entry_id = self._config_entry.entry_id
        if self.entity_description.ha_group == "System":
            return self._build_system_device_info(entry_id, dev_connection, dev_connection_value)
        elif "mac-address" in self.entity_description.data_reference:
            return self._build_mac_device_info(entry_id, dev_connection, dev_connection_value)
        else:
            return self._build_generic_device_info(entry_id, dev_connection, dev_connection_value, dev_group)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes
        for variable in self.entity_description.data_attributes_list:
            if variable in self._data:
                attributes[format_attribute(variable)] = self._data[variable]

        return attributes

    async def start(self):
        """Dummy run function"""
        raise NotImplementedError()

    async def stop(self):
        """Dummy stop function"""
        raise NotImplementedError()

    async def restart(self):
        """Dummy restart function"""
        raise NotImplementedError()

    async def reload(self):
        """Dummy reload function"""
        raise NotImplementedError()
