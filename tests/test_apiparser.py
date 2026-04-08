"""Tests for apiparser functions."""

from custom_components.mikrotik_extended.apiparser import (
    can_skip,
    from_entry,
    from_entry_bool,
    generate_keymap,
    matches_only,
    parse_api,
)

# ---- from_entry ----


class TestFromEntry:
    def test_simple_key(self):
        assert from_entry({"name": "router1"}, "name") == "router1"

    def test_missing_key_returns_default(self):
        assert from_entry({"name": "router1"}, "missing") == ""

    def test_missing_key_custom_default(self):
        assert from_entry({"name": "router1"}, "missing", default="N/A") == "N/A"

    def test_nested_key_with_slash(self):
        assert from_entry({"a": {"b": "val"}}, "a/b") == "val"

    def test_nested_key_missing(self):
        assert from_entry({"a": {"c": "val"}}, "a/b") == ""

    def test_int_value(self):
        assert from_entry({"cpu": 42}, "cpu", default=0) == 42

    def test_float_value_rounded(self):
        result = from_entry({"temp": 55.678}, "temp", default=0.0)
        assert result == 55.68

    def test_long_string_truncated_to_255(self):
        long_str = "x" * 300
        result = from_entry({"val": long_str}, "val", default="")
        assert len(result) == 255

    def test_string_exactly_255_not_truncated(self):
        s = "x" * 255
        result = from_entry({"val": s}, "val", default="")
        assert len(result) == 255

    def test_empty_default_no_type_coercion(self):
        """When default is empty string, no type coercion happens."""
        result = from_entry({"val": [1, 2]}, "val")
        assert result == [1, 2]


# ---- from_entry_bool ----


class TestFromEntryBool:
    def test_true_value(self):
        assert from_entry_bool({"enabled": True}, "enabled") is True

    def test_false_value(self):
        assert from_entry_bool({"enabled": False}, "enabled") is False

    def test_string_yes(self):
        assert from_entry_bool({"status": "yes"}, "status") is True

    def test_string_no(self):
        assert from_entry_bool({"status": "no"}, "status") is False

    def test_string_on(self):
        assert from_entry_bool({"status": "on"}, "status") is True

    def test_string_off(self):
        assert from_entry_bool({"status": "off"}, "status") is False

    def test_string_up(self):
        assert from_entry_bool({"status": "up"}, "status") is True

    def test_string_down(self):
        assert from_entry_bool({"status": "down"}, "status") is False

    def test_missing_key_returns_default(self):
        assert from_entry_bool({"x": True}, "missing") is False

    def test_missing_key_custom_default(self):
        assert from_entry_bool({"x": True}, "missing", default=True) is True

    def test_reverse_true_becomes_false(self):
        assert from_entry_bool({"enabled": True}, "enabled", reverse=True) is False

    def test_reverse_false_becomes_true(self):
        assert from_entry_bool({"enabled": False}, "enabled", reverse=True) is True

    def test_reverse_missing_reverses_default(self):
        assert from_entry_bool({}, "missing", default=False, reverse=True) is True

    def test_nested_key_with_slash(self):
        assert from_entry_bool({"a": {"b": True}}, "a/b") is True

    def test_nested_key_missing(self):
        assert from_entry_bool({"a": {"c": True}}, "a/b") is False

    def test_non_bool_non_string_returns_default(self):
        assert from_entry_bool({"val": 42}, "val") is False


# ---- parse_api ----


class TestParseApi:
    def test_empty_source_returns_data(self):
        result = parse_api(data={"existing": "val"}, source=None, key=".id")
        assert result == {"existing": "val"}

    def test_none_data_creates_empty_dict(self):
        result = parse_api(data=None, source=None, key=".id")
        assert result == {}

    def test_single_dict_source_wrapped(self):
        """A single dict source is treated as [dict]."""
        source = {"name": "eth0", ".id": "*1"}
        result = parse_api(
            data={},
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
        )
        assert "*1" in result
        assert result["*1"]["name"] == "eth0"

    def test_list_source_with_key(self):
        source = [
            {"name": "eth0", ".id": "*1"},
            {"name": "eth1", ".id": "*2"},
        ]
        result = parse_api(
            data={},
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
        )
        assert result["*1"]["name"] == "eth0"
        assert result["*2"]["name"] == "eth1"

    def test_source_without_key_fills_flat(self):
        source = [{"cpu": "50", "memory": "75"}]
        result = parse_api(
            data={},
            source=source,
            vals=[
                {"name": "cpu", "source": "cpu"},
                {"name": "memory", "source": "memory"},
            ],
        )
        assert result["cpu"] == "50"
        assert result["memory"] == "75"

    def test_only_filter(self):
        source = [
            {"name": "eth0", ".id": "*1", "type": "ether"},
            {"name": "wlan0", ".id": "*2", "type": "wlan"},
        ]
        result = parse_api(
            data={},
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            only=[{"key": "type", "value": "ether"}],
        )
        assert "*1" in result
        assert "*2" not in result

    def test_skip_filter(self):
        source = [
            {"name": "eth0", ".id": "*1", "type": "ether"},
            {"name": "loopback", ".id": "*2", "type": "loopback"},
        ]
        result = parse_api(
            data={},
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            skip=[{"name": "type", "value": "loopback"}],
        )
        assert "*1" in result
        assert "*2" not in result

    def test_ensure_vals_adds_missing_keys(self):
        source = [{"name": "eth0", ".id": "*1"}]
        result = parse_api(
            data={},
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            ensure_vals=[{"name": "tx_bytes", "default": 0}],
        )
        assert result["*1"]["tx_bytes"] == 0
        assert result["*1"]["name"] == "eth0"

    def test_key_secondary_fallback(self):
        source = [{"alt_id": "backup1", "name": "backup"}]
        result = parse_api(
            data={},
            source=source,
            key=".id",
            key_secondary="alt_id",
            vals=[{"name": "name", "source": "name"}],
        )
        assert "backup1" in result

    def test_empty_source_list(self):
        result = parse_api(data={}, source=[], key=".id")
        assert result == {}

    def test_bool_val_type(self):
        source = [{"name": "eth0", ".id": "*1", "enabled": True}]
        result = parse_api(
            data={},
            source=source,
            key=".id",
            vals=[{"name": "enabled", "source": "enabled", "type": "bool"}],
        )
        assert result["*1"]["enabled"] is True


# ---- prune_stale ----


class TestPruneStale:
    def test_stale_not_pruned_before_3_polls(self):
        """Items missing from source should survive 2 polls."""
        data = {"*1": {"name": "eth0"}, "*2": {"name": "eth1"}}
        counters = {}

        # Poll 1: only *1 seen
        source = [{"name": "eth0", ".id": "*1"}]
        data = parse_api(
            data=data,
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            prune_stale=True,
            stale_counters=counters,
        )
        assert "*2" in data
        assert counters["*2"] == 1

        # Poll 2: only *1 seen again
        data = parse_api(
            data=data,
            source=source,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            prune_stale=True,
            stale_counters=counters,
        )
        assert "*2" in data
        assert counters["*2"] == 2

    def test_stale_pruned_after_3_polls(self):
        """Items missing for 3 consecutive polls should be removed."""
        data = {"*1": {"name": "eth0"}, "*2": {"name": "eth1"}}
        counters = {}
        source = [{"name": "eth0", ".id": "*1"}]

        for _ in range(3):
            data = parse_api(
                data=data,
                source=source,
                key=".id",
                vals=[{"name": "name", "source": "name"}],
                prune_stale=True,
                stale_counters=counters,
            )

        assert "*1" in data
        assert "*2" not in data
        assert "*2" not in counters

    def test_stale_counter_reset_when_seen(self):
        """If item reappears, its stale counter resets."""
        data = {"*1": {"name": "eth0"}, "*2": {"name": "eth1"}}
        counters = {}

        # Poll 1: only *1
        source1 = [{"name": "eth0", ".id": "*1"}]
        data = parse_api(
            data=data,
            source=source1,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            prune_stale=True,
            stale_counters=counters,
        )
        assert counters["*2"] == 1

        # Poll 2: both seen — counter should reset
        source2 = [
            {"name": "eth0", ".id": "*1"},
            {"name": "eth1", ".id": "*2"},
        ]
        data = parse_api(
            data=data,
            source=source2,
            key=".id",
            vals=[{"name": "name", "source": "name"}],
            prune_stale=True,
            stale_counters=counters,
        )
        assert "*2" not in counters

    def test_prune_disabled_by_default(self):
        """Without prune_stale=True, stale items stay forever."""
        data = {"*1": {"name": "eth0"}, "*2": {"name": "eth1"}}
        source = [{"name": "eth0", ".id": "*1"}]

        for _ in range(5):
            data = parse_api(
                data=data,
                source=source,
                key=".id",
                vals=[{"name": "name", "source": "name"}],
            )

        assert "*2" in data

    def test_prune_without_counters_dict_noop(self):
        """prune_stale=True but stale_counters=None does nothing."""
        data = {"*1": {"name": "eth0"}, "*2": {"name": "eth1"}}
        source = [{"name": "eth0", ".id": "*1"}]

        for _ in range(5):
            data = parse_api(
                data=data,
                source=source,
                key=".id",
                vals=[{"name": "name", "source": "name"}],
                prune_stale=True,
                stale_counters=None,
            )

        assert "*2" in data

    def test_prune_without_key_noop(self):
        """prune_stale only works when key or key_search is set."""
        data = {"cpu": "50"}
        counters = {}
        source = [{"cpu": "60"}]

        data = parse_api(
            data=data,
            source=source,
            vals=[{"name": "cpu", "source": "cpu"}],
            prune_stale=True,
            stale_counters=counters,
        )
        assert "cpu" in data


# ---- matches_only / can_skip ----


class TestFilters:
    def test_matches_only_all_match(self):
        entry = {"type": "ether", "running": "yes"}
        only = [{"key": "type", "value": "ether"}, {"key": "running", "value": "yes"}]
        assert matches_only(entry, only) is True

    def test_matches_only_partial_match(self):
        entry = {"type": "ether", "running": "no"}
        only = [{"key": "type", "value": "ether"}, {"key": "running", "value": "yes"}]
        assert matches_only(entry, only) is False

    def test_matches_only_missing_key(self):
        entry = {"type": "ether"}
        only = [{"key": "type", "value": "ether"}, {"key": "running", "value": "yes"}]
        assert matches_only(entry, only) is False

    def test_can_skip_matching(self):
        entry = {"type": "loopback"}
        skip = [{"name": "type", "value": "loopback"}]
        assert can_skip(entry, skip) is True

    def test_can_skip_no_match(self):
        entry = {"type": "ether"}
        skip = [{"name": "type", "value": "loopback"}]
        assert can_skip(entry, skip) is False

    def test_can_skip_missing_key_empty_value(self):
        """Skip when key is absent and value is empty string."""
        entry = {"name": "eth0"}
        skip = [{"name": "comment", "value": ""}]
        assert can_skip(entry, skip) is True


# ---- generate_keymap ----


class TestGenerateKeymap:
    def test_generates_reverse_map(self):
        data = {
            "*1": {"name": "eth0"},
            "*2": {"name": "eth1"},
        }
        keymap = generate_keymap(data, "name")
        assert keymap == {"eth0": "*1", "eth1": "*2"}

    def test_no_key_search_returns_none(self):
        assert generate_keymap({"*1": {}}, None) is None

    def test_missing_key_in_entry_skipped(self):
        data = {
            "*1": {"name": "eth0"},
            "*2": {},
        }
        keymap = generate_keymap(data, "name")
        assert keymap == {"eth0": "*1"}
