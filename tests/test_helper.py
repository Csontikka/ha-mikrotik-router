"""Tests for helper functions."""

from custom_components.mikrotik_extended.helper import format_attribute, format_value


def test_format_attribute_replaces_hyphens():
    assert format_attribute("tx-byte") == "tx_byte"


def test_format_attribute_replaces_spaces():
    assert format_attribute("tx byte") == "tx_byte"


def test_format_attribute_lowercases():
    assert format_attribute("TX-Byte") == "tx_byte"


def test_format_attribute_combined():
    assert format_attribute("My Cool-Attribute") == "my_cool_attribute"


def test_format_attribute_empty():
    assert format_attribute("") == ""


def test_format_attribute_no_changes():
    assert format_attribute("already_formatted") == "already_formatted"


def test_format_value_dhcp():
    assert format_value("dhcp") == "DHCP"


def test_format_value_dns():
    assert format_value("dns") == "DNS"


def test_format_value_capsman():
    assert format_value("capsman") == "CAPsMAN"


def test_format_value_wireless():
    assert format_value("wireless") == "Wireless"


def test_format_value_restored():
    assert format_value("restored") == "Restored"


def test_format_value_no_match():
    assert format_value("something") == "something"


def test_format_value_multiple_replacements():
    assert format_value("dhcp dns") == "DHCP DNS"
