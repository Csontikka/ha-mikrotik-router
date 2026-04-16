"""Tests for custom exceptions."""

from custom_components.mikrotik_extended.exceptions import ApiEntryNotFound


def test_api_entry_not_found_is_exception():
    """ApiEntryNotFound should be raisable and inherit from Exception."""
    assert issubclass(ApiEntryNotFound, Exception)

    try:
        raise ApiEntryNotFound("missing")
    except ApiEntryNotFound as exc:
        assert str(exc) == "missing"
