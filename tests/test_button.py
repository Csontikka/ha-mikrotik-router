"""Tests for the button platform."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.button import (
    MikrotikButton,
    MikrotikRebootButton,
    MikrotikScriptButton,
    async_setup_entry,
)
from custom_components.mikrotik_extended.const import DOMAIN

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 0,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "TestRouter",
}


def _make_description(func="MikrotikButton", key="k", name="N", data_path="resource", data_attribute="x", **extra):
    desc = MagicMock()
    desc.func = func
    desc.key = key
    desc.name = name
    desc.data_path = data_path
    desc.data_attribute = data_attribute
    desc.data_reference = None
    desc.data_name = None
    desc.data_name_comment = False
    desc.data_attributes_list = []
    desc.ha_group = None
    desc.ha_connection = None
    desc.ha_connection_value = None
    desc.entity_registry_enabled_default = True
    for k, v in extra.items():
        setattr(desc, k, v)
    return desc


def _make_coordinator(hass, data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    coord = MagicMock()
    coord.config_entry = entry
    coord.data = data
    coord.hass = hass
    coord.host = "192.168.88.1"
    return coord


async def test_async_setup_entry_invokes_add_entities(hass):
    """async_setup_entry forwards dispatcher dict into async_add_entities."""
    entry = MagicMock()
    add_entities = MagicMock()
    with patch("custom_components.mikrotik_extended.button.async_add_entities", new=AsyncMock()) as mock_add:
        await async_setup_entry(hass, entry, add_entities)
    mock_add.assert_awaited_once()
    _, _, dispatcher = mock_add.await_args.args
    assert set(dispatcher.keys()) == {"MikrotikButton", "MikrotikScriptButton", "MikrotikRebootButton"}


async def test_mikrotik_button_press_is_noop(hass):
    """Base MikrotikButton's async_press is a noop that doesn't raise."""
    desc = _make_description(func="MikrotikButton")
    coord = _make_coordinator(hass, data={"resource": {"x": "y"}})
    button = MikrotikButton(coord, desc)
    await button.async_update()
    await button.async_press()  # no exception, no side effect


async def test_reboot_button_aborts_without_access(hass):
    """MikrotikRebootButton.async_press aborts early if 'reboot' is missing from access."""
    desc = _make_description(func="MikrotikRebootButton")
    coord = _make_coordinator(hass, data={"resource": {"x": "y"}})
    coord.ds = {"access": set()}  # no reboot access
    coord.execute = MagicMock()
    button = MikrotikRebootButton(coord, desc)
    await button.async_press()
    coord.execute.assert_not_called()


async def test_reboot_button_executes_reboot_when_allowed(hass):
    """MikrotikRebootButton.async_press calls the reboot command when permitted."""
    desc = _make_description(func="MikrotikRebootButton")
    coord = _make_coordinator(hass, data={"resource": {"x": "y"}})
    coord.ds = {"access": {"reboot"}}
    coord.execute = MagicMock(return_value=True)
    button = MikrotikRebootButton(coord, desc)
    button.hass = hass
    await button.async_press()
    coord.execute.assert_called_once_with("/system", "reboot", None, None)


async def test_script_button_runs_and_refreshes_on_success(hass):
    """MikrotikScriptButton.async_press runs the script and triggers refreshes."""
    desc = _make_description(
        func="MikrotikScriptButton",
        data_path="script",
        data_name="name",
        data_uid="name",
        data_reference="name",
    )
    script_data = {"myscript": {"name": "myscript", "last-started": "now", "run-count": 1}}
    coord = _make_coordinator(hass, data={"script": script_data})
    coord.api = MagicMock()
    coord.api.run_script = MagicMock(return_value=True)
    coord.async_refresh = AsyncMock()

    tracker = MagicMock()
    tracker.async_request_refresh = AsyncMock()
    coord.config_entry.runtime_data = MagicMock(tracker_coordinator=tracker)

    button = MikrotikScriptButton(coord, desc, uid="myscript")
    button.hass = hass
    await button.async_press()

    coord.api.run_script.assert_called_once_with("myscript")
    coord.async_refresh.assert_awaited_once()
    tracker.async_request_refresh.assert_awaited_once()


async def test_script_button_aborts_on_failure(hass):
    """MikrotikScriptButton.async_press aborts when run_script returns False."""
    desc = _make_description(
        func="MikrotikScriptButton",
        data_path="script",
        data_name="name",
        data_uid="name",
        data_reference="name",
    )
    script_data = {"myscript": {"name": "myscript"}}
    coord = _make_coordinator(hass, data={"script": script_data})
    coord.api = MagicMock()
    coord.api.run_script = MagicMock(return_value=False)
    coord.async_refresh = AsyncMock()

    tracker = MagicMock()
    tracker.async_request_refresh = AsyncMock()
    coord.config_entry.runtime_data = MagicMock(tracker_coordinator=tracker)

    button = MikrotikScriptButton(coord, desc, uid="myscript")
    button.hass = hass
    await button.async_press()

    coord.async_refresh.assert_not_awaited()
    tracker.async_request_refresh.assert_not_awaited()
