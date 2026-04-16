"""Mikrotik sensor platform."""

from __future__ import annotations

PARALLEL_UPDATES = 0

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from logging import getLogger
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import MikrotikCoordinator
from .entity import MikrotikEntity, async_add_entities
from .helper import format_attribute
from .sensor_types import (
    DEVICE_ATTRIBUTES_IFACE_ETHER,
    DEVICE_ATTRIBUTES_IFACE_SFP,
    DEVICE_ATTRIBUTES_IFACE_WIRELESS,
    SENSOR_SERVICES,  # noqa: F401 — accessed via platform.platform.SENSOR_SERVICES
    SENSOR_TYPES,  # noqa: F401 — accessed via platform.platform.SENSOR_TYPES
)

_LOGGER = getLogger(__name__)


def _collect_iface_attributes(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return formatted iface attributes based on the iface type."""
    collected: dict[str, Any] = {}
    iface_type = data["type"]
    if iface_type == "ether":
        _add_present_attributes(collected, data, DEVICE_ATTRIBUTES_IFACE_ETHER)
        if "sfp-shutdown-temperature" in data:
            _add_present_attributes(collected, data, DEVICE_ATTRIBUTES_IFACE_SFP)
    elif iface_type == "wlan":
        _add_present_attributes(collected, data, DEVICE_ATTRIBUTES_IFACE_WIRELESS)
    return collected


def _add_present_attributes(target: dict[str, Any], data: Mapping[str, Any], variables) -> None:
    """Copy formatted attributes from data into target for each present variable."""
    for variable in variables:
        if variable in data:
            target[format_attribute(variable)] = data[variable]


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
        "MikrotikSensor": MikrotikSensor,
        "MikrotikInterfaceTrafficSensor": MikrotikInterfaceTrafficSensor,
        "MikrotikClientTrafficSensor": MikrotikClientTrafficSensor,
        "MikrotikIPAddressSensor": MikrotikIPAddressSensor,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   MikrotikSensor
# ---------------------------
class MikrotikSensor(MikrotikEntity, SensorEntity):
    """Define an Mikrotik sensor."""

    def __init__(
        self,
        coordinator: MikrotikCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, entity_description, uid)
        self._attr_suggested_unit_of_measurement = self.entity_description.suggested_unit_of_measurement

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        return self._data[self.entity_description.data_attribute]

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is expressed in."""
        if self.entity_description.native_unit_of_measurement:
            if self.entity_description.native_unit_of_measurement.startswith("data__"):
                uom = self.entity_description.native_unit_of_measurement[6:]
                if uom in self._data:
                    return self._data[uom]

            return self.entity_description.native_unit_of_measurement

        return None


# ---------------------------
#   MikrotikInterfaceTrafficSensor
# ---------------------------
class MikrotikInterfaceTrafficSensor(MikrotikSensor):
    """Define an Mikrotik MikrotikInterfaceTrafficSensor sensor."""

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes
        attributes.update(_collect_iface_attributes(self._data))
        return attributes


# ---------------------------
#   MikrotikIPAddressSensor
# ---------------------------
class MikrotikIPAddressSensor(MikrotikSensor):
    """IP Address sensor with static name."""

    @property
    def custom_name(self) -> str:
        return "IP Address"


# ---------------------------
#   MikrotikClientTrafficSensor
# ---------------------------
class MikrotikClientTrafficSensor(MikrotikSensor):
    """Define an Mikrotik MikrotikClientTrafficSensor sensor."""

    @property
    def custom_name(self) -> str:
        """Return the name for this entity"""
        return f"{self.entity_description.name} ({self._inst})"

    @property
    def available(self) -> bool:
        """Return if kid-control data is available for this client."""
        return super().available and self._data.get("available", False)
