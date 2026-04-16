"""Tests for the device_tracker platform."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    STATE_NOT_HOME,
)
from homeassistant.util.dt import utcnow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_extended.const import DOMAIN
from custom_components.mikrotik_extended.device_tracker import (
    MikrotikDeviceTracker,
    MikrotikHostDeviceTracker,
    async_setup_entry,
)

ENTRY_DATA = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "test",
    CONF_PORT: 0,
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
    CONF_NAME: "TestRouter",
}


def _make_description(**overrides):
    desc = MagicMock()
    desc.key = "host"
    desc.name = ""
    desc.func = "MikrotikHostDeviceTracker"
    desc.data_path = "host"
    desc.data_name = "host-name"
    desc.data_uid = "mac-address"
    desc.data_reference = "mac-address"
    desc.data_attribute = "available"
    desc.data_name_comment = False
    desc.data_attributes_list = []
    desc.ha_group = ""
    desc.ha_connection = None
    desc.ha_connection_value = None
    desc.icon_enabled = "mdi:lan-connect"
    desc.icon_disabled = "mdi:lan-disconnect"
    desc.entity_registry_enabled_default = True
    for k, v in overrides.items():
        setattr(desc, k, v)
    return desc


def _make_coordinator(hass, host_data, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=options or {"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    coord = MagicMock()
    coord.config_entry = entry
    coord.data = {"host": host_data}
    coord.option_zone = "home"
    coord.hass = hass
    return coord


async def test_async_setup_entry_invokes_add_entities(hass):
    """async_setup_entry forwards the dispatcher dict."""
    entry = MagicMock()
    with patch("custom_components.mikrotik_extended.device_tracker.async_add_entities", new=AsyncMock()) as mock_add:
        await async_setup_entry(hass, entry, MagicMock())
    mock_add.assert_awaited_once()
    _, _, dispatcher = mock_add.await_args.args
    assert set(dispatcher.keys()) == {"MikrotikDeviceTracker", "MikrotikHostDeviceTracker"}


async def test_mikrotik_device_tracker_properties(hass):
    """MikrotikDeviceTracker's base properties read from self._data."""
    desc = _make_description(func="MikrotikDeviceTracker")
    data = {"AA:BB:CC:DD:EE:FF": {"mac-address": "AA:BB:CC:DD:EE:FF", "host-name": "laptop", "address": "192.168.88.10", "available": True}}
    coord = _make_coordinator(hass, data)
    tracker = MikrotikDeviceTracker(coord, desc, uid="AA:BB:CC:DD:EE:FF")

    assert tracker.ip_address == "192.168.88.10"
    assert tracker.mac_address == "AA:BB:CC:DD:EE:FF"
    assert tracker.hostname == "laptop"
    assert tracker.is_connected is True
    assert tracker.source_type == SourceType.ROUTER


async def test_mikrotik_device_tracker_missing_fields(hass):
    """Missing mac-address and hostname fields produce empty strings from the ScannerEntity properties."""
    desc = _make_description(func="MikrotikDeviceTracker", data_reference="mac-address", data_name="host-name")
    # host-name present (required for custom_name), but mac-address intentionally missing
    data = {"uid1": {"host-name": "placeholder", "available": False}}
    coord = _make_coordinator(hass, data)
    tracker = MikrotikDeviceTracker(coord, desc, uid="uid1")

    assert tracker.mac_address == ""
    # hostname returns the value when present
    assert tracker.hostname == "placeholder"
    assert tracker.is_connected is False

    # Drop host-name to exercise the empty-string branch of .hostname
    tracker._data = {"available": False}
    assert tracker.hostname == ""


async def test_host_device_tracker_disabled_by_option(hass):
    """When CONF_TRACK_HOSTS is False, is_connected always returns False."""
    desc = _make_description()
    data = {"mac1": {"mac-address": "mac1", "host-name": "h", "source": "wireless", "available": True, "last-seen": utcnow()}}
    coord = _make_coordinator(hass, data, options={"track_network_hosts": False, "track_network_hosts_timeout": 180, "zone": "home"})

    tracker = MikrotikHostDeviceTracker(coord, desc, uid="mac1")
    assert tracker.option_track_network_hosts is False
    assert tracker.is_connected is False
    assert tracker.state == STATE_NOT_HOME


async def test_host_device_tracker_wireless_uses_available_flag(hass):
    """When source is wireless/capsman, is_connected reads 'available' directly."""
    desc = _make_description()
    data = {"mac1": {"mac-address": "mac1", "host-name": "h", "source": "wireless", "available": True, "last-seen": utcnow()}}
    coord = _make_coordinator(hass, data)

    tracker = MikrotikHostDeviceTracker(coord, desc, uid="mac1")
    assert tracker.is_connected is True
    assert tracker.state == "home"
    assert tracker.icon == "mdi:lan-connect"

    # Flip the available flag -> disconnected
    data["mac1"]["available"] = False
    assert tracker.is_connected is False
    assert tracker.icon == "mdi:lan-disconnect"


async def test_host_device_tracker_non_wireless_uses_last_seen(hass):
    """For ARP-based hosts, is_connected compares last-seen against timeout."""
    desc = _make_description()
    data = {
        "mac1": {"mac-address": "mac1", "host-name": "h", "source": "arp", "available": True, "last-seen": utcnow()},
    }
    coord = _make_coordinator(hass, data)

    tracker = MikrotikHostDeviceTracker(coord, desc, uid="mac1")
    assert tracker.is_connected is True
    assert tracker.icon == "mdi:lan-connect"

    # Stale last-seen (older than timeout)
    data["mac1"]["last-seen"] = utcnow() - timedelta(hours=1)
    assert tracker.is_connected is False
    assert tracker.icon == "mdi:lan-disconnect"


async def test_host_device_tracker_extra_state_attributes(hass):
    """extra_state_attributes sets last-seen to 'Now' when connected, 'Unknown' when missing."""
    desc = _make_description(data_attributes_list=["last-seen"])
    data = {"mac1": {"mac-address": "mac1", "host-name": "h", "source": "wireless", "available": True, "last-seen": utcnow()}}
    coord = _make_coordinator(hass, data)

    tracker = MikrotikHostDeviceTracker(coord, desc, uid="mac1")
    attrs = tracker.extra_state_attributes
    assert attrs["last_seen"] == "Now"

    # Disconnect and no last-seen -> 'Unknown'
    data["mac1"]["available"] = False
    data["mac1"]["last-seen"] = None
    attrs = tracker.extra_state_attributes
    assert attrs["last_seen"] == "Unknown"


async def _install_platform_mocks(hass, entries_in_registry=None, platform_entities=None):
    """Build the ep/er mocks needed for async_add_entities to run.

    Returns a tuple (platform_mock, registry_mock, ep_patch, er_patch, async_get_entity_id,
    async_entries_for_config_entry).
    """
    platform_mock = MagicMock()
    platform_mock.platform.SENSOR_SERVICES = [("my_service", None, AsyncMock())]
    from custom_components.mikrotik_extended.device_tracker_types import SENSOR_TYPES

    platform_mock.platform.SENSOR_TYPES = SENSOR_TYPES
    platform_mock.domain = "device_tracker"
    platform_mock.entities = platform_entities or {}
    platform_mock.async_register_entity_service = MagicMock()
    platform_mock.async_add_entities = AsyncMock()

    registry_mock = MagicMock()
    registry_mock.async_get_entity_id = MagicMock(return_value="device_tracker.existing")

    reg_entry = MagicMock()
    reg_entry.disabled = False
    reg_entry.domain = "device_tracker"
    reg_entry.entity_id = "device_tracker.existing"
    registry_mock.async_get = MagicMock(return_value=reg_entry)
    registry_mock.async_remove = MagicMock()

    return platform_mock, registry_mock


async def test_async_add_entities_adds_and_cleans_orphans(hass):
    """async_add_entities creates new entities and removes orphaned registry entries."""
    from custom_components.mikrotik_extended.device_tracker import async_add_entities

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    tracker_coord = MagicMock()
    tracker_coord.data = {
        "host": {
            "AA:BB:CC:DD:EE:FF": {
                "mac-address": "AA:BB:CC:DD:EE:FF",
                "host-name": "laptop",
                "address": "192.168.88.10",
                "available": True,
                "source": "wireless",
                "last-seen": utcnow(),
            }
        }
    }
    tracker_coord.config_entry = entry
    tracker_coord.option_zone = "home"
    entry.runtime_data = MagicMock(tracker_coordinator=tracker_coord)

    platform_mock, registry_mock = await _install_platform_mocks(hass)

    # Make the registry report an orphan entry that no longer maps to a current entity
    orphan = MagicMock()
    orphan.domain = "device_tracker"
    orphan.entity_id = "device_tracker.orphan"
    orphan.disabled = False

    dispatcher = {"MikrotikHostDeviceTracker": MikrotikHostDeviceTracker}

    with (
        patch("custom_components.mikrotik_extended.device_tracker.ep.async_get_current_platform", return_value=platform_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_get", return_value=registry_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_entries_for_config_entry", return_value=[orphan]),
    ):
        # Report no existing entity, forcing add path
        registry_mock.async_get.return_value = None
        await async_add_entities(hass, entry, dispatcher)

    # New entity added
    platform_mock.async_add_entities.assert_awaited()
    # Orphan removed
    registry_mock.async_remove.assert_called_once_with("device_tracker.orphan")


async def test_async_add_entities_skips_disabled_orphan(hass):
    """Disabled registry entries are left alone (not removed)."""
    from custom_components.mikrotik_extended.device_tracker import async_add_entities

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    tracker_coord = MagicMock()
    tracker_coord.data = {"host": {}}
    tracker_coord.config_entry = entry
    entry.runtime_data = MagicMock(tracker_coordinator=tracker_coord)

    platform_mock, registry_mock = await _install_platform_mocks(hass)
    disabled_orphan = MagicMock()
    disabled_orphan.domain = "device_tracker"
    disabled_orphan.entity_id = "device_tracker.orphan"
    disabled_orphan.disabled = True

    with (
        patch("custom_components.mikrotik_extended.device_tracker.ep.async_get_current_platform", return_value=platform_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_get", return_value=registry_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_entries_for_config_entry", return_value=[disabled_orphan]),
    ):
        await async_add_entities(hass, entry, {"MikrotikHostDeviceTracker": MikrotikHostDeviceTracker})

    registry_mock.async_remove.assert_not_called()


async def test_async_add_entities_returns_early_on_none_data(hass):
    """When coordinator.data is None, async_update_controller short-circuits."""
    from custom_components.mikrotik_extended.device_tracker import async_add_entities

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    tracker_coord = MagicMock()
    tracker_coord.data = None
    tracker_coord.config_entry = entry
    entry.runtime_data = MagicMock(tracker_coordinator=tracker_coord)

    platform_mock, registry_mock = await _install_platform_mocks(hass)

    with (
        patch("custom_components.mikrotik_extended.device_tracker.ep.async_get_current_platform", return_value=platform_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_get", return_value=registry_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_entries_for_config_entry", return_value=[]),
    ):
        await async_add_entities(hass, entry, {"MikrotikHostDeviceTracker": MikrotikHostDeviceTracker})

    platform_mock.async_add_entities.assert_not_awaited()


async def test_async_add_entities_handles_no_reference_and_missing_dispatcher(hass):
    """Exercise branches where data_reference is None, or dispatcher has no matching func."""
    from custom_components.mikrotik_extended.device_tracker import async_add_entities

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    tracker_coord = MagicMock()
    tracker_coord.config_entry = entry
    tracker_coord.data = {
        "fixed": {"x": 1},  # used by no-reference description
        "missing_dispatcher": {"id1": {"v": 1}},  # has reference but dispatcher miss
        "skip_all": {"id1": {"v": 1}},  # reference, but _skip_sensor returns True
        "null_attr": {},  # no-reference description, attribute is None
    }
    entry.runtime_data = MagicMock(tracker_coordinator=tracker_coord)

    # Build synthetic descriptions for each branch we want to hit
    d_no_ref_ok = MagicMock()
    d_no_ref_ok.func = "MikrotikHostDeviceTracker"
    d_no_ref_ok.key = "fixed_key"
    d_no_ref_ok.data_path = "fixed"
    d_no_ref_ok.data_attribute = "x"
    d_no_ref_ok.data_reference = None

    d_no_ref_skip = MagicMock()
    d_no_ref_skip.func = "MikrotikHostDeviceTracker"
    d_no_ref_skip.key = "nullkey"
    d_no_ref_skip.data_path = "null_attr"
    d_no_ref_skip.data_attribute = "x"
    d_no_ref_skip.data_reference = None

    d_missing_disp = MagicMock()
    d_missing_disp.func = "NotInDispatcher"
    d_missing_disp.key = "md_key"
    d_missing_disp.data_path = "missing_dispatcher"
    d_missing_disp.data_attribute = "v"
    d_missing_disp.data_reference = "v"

    d_no_ref_no_disp = MagicMock()
    d_no_ref_no_disp.func = "AlsoMissing"
    d_no_ref_no_disp.key = "anrnd"
    d_no_ref_no_disp.data_path = "fixed"
    d_no_ref_no_disp.data_attribute = "x"
    d_no_ref_no_disp.data_reference = None

    platform_mock = MagicMock()
    platform_mock.platform.SENSOR_SERVICES = []
    platform_mock.platform.SENSOR_TYPES = (d_no_ref_ok, d_no_ref_skip, d_missing_disp, d_no_ref_no_disp)
    platform_mock.domain = "device_tracker"
    platform_mock.entities = {}
    platform_mock.async_register_entity_service = MagicMock()
    platform_mock.async_add_entities = AsyncMock()

    registry_mock = MagicMock()
    registry_mock.async_get_entity_id = MagicMock(return_value=None)
    registry_mock.async_get = MagicMock(return_value=None)
    registry_mock.async_remove = MagicMock()

    # Dispatcher with no matching key for d_missing_disp / d_no_ref_no_disp. Use a
    # simple class that swallows the coordinator+description args without raising.
    class _Fake:
        def __init__(self, *args, **kwargs):
            self.entity_description = d_no_ref_ok
            self._data = {"x": 1}

    dispatcher = {"MikrotikHostDeviceTracker": _Fake}

    with (
        patch("custom_components.mikrotik_extended.device_tracker.ep.async_get_current_platform", return_value=platform_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_get", return_value=registry_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_entries_for_config_entry", return_value=[]),
        patch("custom_components.mikrotik_extended.device_tracker._skip_sensor", return_value=True),
    ):
        await async_add_entities(hass, entry, dispatcher)


async def test_async_add_entities_skips_when_path_missing_or_dispatcher_miss(hass):
    """Descriptions whose data_path is absent, or whose func isn't in dispatcher, are skipped silently."""
    from custom_components.mikrotik_extended.device_tracker import async_add_entities

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    tracker_coord = MagicMock()
    tracker_coord.config_entry = entry
    tracker_coord.data = {"present_but_unknown_func": {"id": {"v": 1}}}
    entry.runtime_data = MagicMock(tracker_coordinator=tracker_coord)

    d_missing_path = MagicMock()
    d_missing_path.func = "MikrotikHostDeviceTracker"
    d_missing_path.key = "mp"
    d_missing_path.data_path = "not_in_coordinator_data"
    d_missing_path.data_attribute = "x"
    d_missing_path.data_reference = "v"

    d_uid_unknown_func = MagicMock()
    d_uid_unknown_func.func = "NotInDispatcher"
    d_uid_unknown_func.key = "uf"
    d_uid_unknown_func.data_path = "present_but_unknown_func"
    d_uid_unknown_func.data_attribute = "v"
    d_uid_unknown_func.data_reference = "v"

    platform_mock = MagicMock()
    platform_mock.platform.SENSOR_SERVICES = []
    platform_mock.platform.SENSOR_TYPES = (d_missing_path, d_uid_unknown_func)
    platform_mock.domain = "device_tracker"
    platform_mock.entities = {}
    platform_mock.async_register_entity_service = MagicMock()
    platform_mock.async_add_entities = AsyncMock()

    registry_mock = MagicMock()
    registry_mock.async_get_entity_id = MagicMock(return_value=None)
    registry_mock.async_get = MagicMock(return_value=None)
    registry_mock.async_remove = MagicMock()

    with (
        patch("custom_components.mikrotik_extended.device_tracker.ep.async_get_current_platform", return_value=platform_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_get", return_value=registry_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_entries_for_config_entry", return_value=[]),
        patch("custom_components.mikrotik_extended.device_tracker._skip_sensor", return_value=False),
    ):
        await async_add_entities(hass, entry, {"MikrotikHostDeviceTracker": MikrotikHostDeviceTracker})


async def test_async_add_entities_dispatcher_wrapper_invokes_update(hass):
    """When the dispatcher signal fires, the wrapper re-runs async_update_controller."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from custom_components.mikrotik_extended.device_tracker import async_add_entities

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"track_network_hosts": True, "track_network_hosts_timeout": 180, "zone": "home"},
        unique_id="192.168.88.1",
    )
    entry.add_to_hass(hass)

    tracker_coord = MagicMock()
    tracker_coord.config_entry = entry
    tracker_coord.data = {"host": {}}
    entry.runtime_data = MagicMock(tracker_coordinator=tracker_coord)

    platform_mock, registry_mock = await _install_platform_mocks(hass)

    with (
        patch("custom_components.mikrotik_extended.device_tracker.ep.async_get_current_platform", return_value=platform_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_get", return_value=registry_mock),
        patch("custom_components.mikrotik_extended.device_tracker.er.async_entries_for_config_entry", return_value=[]),
    ):
        await async_add_entities(hass, entry, {"MikrotikHostDeviceTracker": MikrotikHostDeviceTracker})
        # Signal the dispatcher the integration wires up at the end of async_add_entities
        async_dispatcher_send(hass, f"update_sensors_{entry.entry_id}", MagicMock())
        await hass.async_block_till_done()


async def test_host_device_tracker_timeout_option(hass):
    """option_track_network_hosts_timeout returns a timedelta from the config."""
    desc = _make_description()
    data = {"mac1": {"mac-address": "mac1", "host-name": "h", "source": "arp", "available": False, "last-seen": utcnow()}}
    coord = _make_coordinator(hass, data, options={"track_network_hosts": True, "track_network_hosts_timeout": 90, "zone": "home"})
    tracker = MikrotikHostDeviceTracker(coord, desc, uid="mac1")
    assert tracker.option_track_network_hosts_timeout == timedelta(seconds=90)
