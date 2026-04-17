"""Tests that import the *_types.py modules to exercise their definitions.

These modules are mostly static dataclasses and tuples; coverage just needs
them to be imported so every module-level statement runs.
"""

from custom_components.mikrotik_extended import (
    binary_sensor_types,
    button_types,
    device_tracker_types,
    sensor_types,
    switch_types,
    update_types,
)


def test_binary_sensor_types_definitions():
    assert binary_sensor_types.SENSOR_TYPES
    seen_keys = set()
    for desc in binary_sensor_types.SENSOR_TYPES:
        assert desc.key not in seen_keys, f"Duplicate binary sensor key: {desc.key}"
        seen_keys.add(desc.key)


def test_button_types_definitions():
    assert button_types.SENSOR_TYPES
    for desc in button_types.SENSOR_TYPES:
        assert desc.key
        assert isinstance(desc.data_attributes_list, list)


def test_device_tracker_types_definitions():
    assert device_tracker_types.SENSOR_TYPES
    for desc in device_tracker_types.SENSOR_TYPES:
        assert desc.key
        assert desc.data_path


def test_sensor_types_definitions():
    assert sensor_types.SENSOR_TYPES
    seen_keys = set()
    for desc in sensor_types.SENSOR_TYPES:
        assert desc.key not in seen_keys, f"Duplicate sensor key: {desc.key}"
        seen_keys.add(desc.key)


def test_switch_types_definitions():
    assert switch_types.SENSOR_TYPES
    for desc in switch_types.SENSOR_TYPES:
        assert desc.key
        assert desc.data_path


def test_update_types_definitions():
    assert update_types.SENSOR_TYPES
    seen_keys = set()
    for desc in update_types.SENSOR_TYPES:
        assert desc.key not in seen_keys, f"Duplicate update key: {desc.key}"
        seen_keys.add(desc.key)
        assert desc.data_path
