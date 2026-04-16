"""Diagnostics support for MikroTik Extended."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import _LOG_BUFFER
from .const import TO_REDACT


async def async_get_config_entry_diagnostics(_hass: HomeAssistant, config_entry: ConfigEntry) -> dict[str, Any]:  # NOSONAR — HA contract requires async
    """Return diagnostics for a config entry."""
    data_coordinator = config_entry.runtime_data.data_coordinator
    tracker_coordinator = config_entry.runtime_data.tracker_coordinator

    return {
        "entry": {
            "data": async_redact_data(config_entry.data, TO_REDACT),
            "options": async_redact_data(config_entry.options, TO_REDACT),
        },
        "data": async_redact_data(data_coordinator.data, TO_REDACT),
        "tracker": async_redact_data(tracker_coordinator.data, TO_REDACT),
        "logs": list(_LOG_BUFFER),
    }
