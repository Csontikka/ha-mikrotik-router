"""Definitions for Mikrotik Router binary sensor entities."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import EntityCategory

from .const import CONF_SENSOR_PPP, DOMAIN

DEVICE_ATTRIBUTES_PPP_SECRET = [
    "connected",
    "service",
    "profile",
    "comment",
    "caller-id",
    "encoding",
]

DEVICE_ATTRIBUTES_IFACE = [
    "running",
    "enabled",
    "comment",
    "client-ip-address",
    "client-mac-address",
    "port-mac-address",
    "last-link-down-time",
    "last-link-up-time",
    "link-downs",
    "actual-mtu",
    "type",
    "name",
]

DEVICE_ATTRIBUTES_IFACE_ETHER = [
    "status",
    "auto-negotiation",
    "rate",
    "full-duplex",
    "default-name",
    "poe-out",
]

DEVICE_ATTRIBUTES_IFACE_SFP = [
    "status",
    "auto-negotiation",
    "advertising",
    "link-partner-advertising",
    "sfp-temperature",
    "sfp-supply-voltage",
    "sfp-module-present",
    "sfp-tx-bias-current",
    "sfp-tx-power",
    "sfp-rx-power",
    "sfp-rx-loss",
    "sfp-tx-fault",
    "sfp-type",
    "sfp-connector-type",
    "sfp-vendor-name",
    "sfp-vendor-part-number",
    "sfp-vendor-revision",
    "sfp-vendor-serial",
    "sfp-manufacturing-date",
    "eeprom-checksum",
]

DEVICE_ATTRIBUTES_IFACE_WIRELESS = [
    "ssid",
    "mode",
    "radio-name",
    "interface-type",
    "country",
    "installation",
    "antenna-gain",
    "frequency",
    "band",
    "channel-width",
    "secondary-frequency",
    "wireless-protocol",
    "rate-set",
    "distance",
    "tx-power-mode",
    "vlan-id",
    "wds-mode",
    "wds-default-bridge",
    "bridge-mode",
    "hide-ssid",
]

DEVICE_ATTRIBUTES_UPS = [
    "name",
    "offline-time",
    "min-runtime",
    "alarm-setting",
    "model",
    "serial",
    "manufacture-date",
    "nominal-battery-voltage",
    "runtime-left",
    "battery-charge",
    "battery-voltage",
    "line-voltage",
    "load",
    "hid-self-test",
]

DEVICE_ATTRIBUTES_NETWATCH = [
    "host",
    "type",
    "interval",
    "port",
    "http-codes",
    "status",
    "comment",
]


@dataclass
class MikrotikBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Class describing mikrotik entities."""

    icon_enabled: str | None = None
    icon_disabled: str | None = None
    ha_group: str | None = None
    ha_connection: str | None = None
    ha_connection_value: str | None = None
    data_path: str | None = None
    data_attribute: str = "available"
    data_name: str | None = None
    data_name_comment: bool = False
    data_uid: str | None = None
    data_reference: str | None = None
    data_attributes_list: list = field(default_factory=lambda: [])
    func: str = "MikrotikBinarySensor"
    enable_on_option: str | None = None


DEVICE_ATTRIBUTES_WIREGUARD_PEER = [
    "interface",
    "allowed-address",
    "last-handshake",
    "last-handshake-seconds",
    "rx",
    "tx",
]


SENSOR_TYPES: tuple[BinarySensorEntityDescription, ...] = (
    MikrotikBinarySensorEntityDescription(
        key="system_ups",
        name="UPS",
        translation_key="system_ups",
        icon_enabled="",
        icon_disabled="",
        device_class=BinarySensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        ha_group="System",
        data_path="ups",
        data_attribute="on-line",
        data_uid="",
        data_reference="",
        data_attributes_list=DEVICE_ATTRIBUTES_UPS,
    ),
    MikrotikBinarySensorEntityDescription(
        key="ppp_tracker",
        name="PPP",
        translation_key="ppp_tracker",
        icon_enabled="mdi:account-network-outline",
        icon_disabled="mdi:account-off-outline",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_registry_enabled_default=False,
        ha_group="PPP",
        ha_connection=DOMAIN,
        ha_connection_value="PPP",
        data_path="ppp_secret",
        data_attribute="connected",
        data_name="name",
        data_uid="name",
        data_reference="name",
        data_attributes_list=DEVICE_ATTRIBUTES_PPP_SECRET,
        func="MikrotikPPPSecretBinarySensor",
        enable_on_option=CONF_SENSOR_PPP,
    ),
    MikrotikBinarySensorEntityDescription(
        key="interface-connection",
        name="Connection",
        translation_key="interface_connection",
        icon_enabled="mdi:lan-connect",
        icon_disabled="mdi:lan-pending",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ha_group="data__default-name",
        ha_connection=CONNECTION_NETWORK_MAC,
        ha_connection_value="data__port-mac-address",
        data_path="interface",
        data_attribute="running",
        data_name="default-name",
        data_uid="default-name",
        data_reference="default-name",
        data_attributes_list=DEVICE_ATTRIBUTES_IFACE,
        func="MikrotikPortBinarySensor",
    ),
    MikrotikBinarySensorEntityDescription(
        key="netwatch",
        name="Netwatch",
        translation_key="netwatch",
        icon_enabled="mdi:lan-connect",
        icon_disabled="mdi:lan-pending",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ha_group="Netwatch",
        ha_connection=DOMAIN,
        ha_connection_value="Netwatch",
        data_path="netwatch",
        data_attribute="status",
        data_name="host",
        data_name_comment=True,
        data_uid="host",
        data_reference="host",
        data_attributes_list=DEVICE_ATTRIBUTES_NETWATCH,
        func="MikrotikBinarySensor",
    ),
    MikrotikBinarySensorEntityDescription(
        key="wireguard_peer",
        name="Connected",
        translation_key="wireguard_peer",
        icon_enabled="mdi:vpn",
        icon_disabled="mdi:vpn",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ha_group="WireGuard",
        ha_connection=DOMAIN,
        ha_connection_value="WireGuard",
        data_path="wireguard_peers",
        data_attribute="connected",
        data_name="name",
        data_name_comment=True,
        data_uid="uniq-id",
        data_reference="uniq-id",
        data_attributes_list=DEVICE_ATTRIBUTES_WIREGUARD_PEER,
        func="MikrotikWireguardPeerBinarySensor",
    ),
)

SENSOR_SERVICES = {}
