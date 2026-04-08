"""Tests for coordinator helper functions and computation methods."""

from __future__ import annotations

import re

from custom_components.mikrotik_extended.coordinator import (
    _parse_duration_seconds,
    is_valid_ip,
)

# ---------------------------------------------------------------------------
# _parse_duration_seconds
# ---------------------------------------------------------------------------


class TestParseDurationSeconds:
    def test_simple_seconds(self):
        assert _parse_duration_seconds("30s") == 30

    def test_simple_minutes(self):
        assert _parse_duration_seconds("3m") == 180

    def test_minutes_and_seconds(self):
        assert _parse_duration_seconds("3m45s") == 225

    def test_hours(self):
        assert _parse_duration_seconds("2h") == 7200

    def test_days(self):
        assert _parse_duration_seconds("1d") == 86400

    def test_weeks(self):
        assert _parse_duration_seconds("1w") == 604800

    def test_all_units(self):
        # 1w + 2d + 3h + 4m + 5s
        expected = 604800 + 2 * 86400 + 3 * 3600 + 4 * 60 + 5
        assert _parse_duration_seconds("1w2d3h4m5s") == expected

    def test_empty_string(self):
        assert _parse_duration_seconds("") == 0

    def test_never(self):
        assert _parse_duration_seconds("never") == 0

    def test_none_value(self):
        assert _parse_duration_seconds(None) == 0

    def test_large_values(self):
        assert _parse_duration_seconds("52w") == 52 * 604800

    def test_days_and_hours(self):
        assert _parse_duration_seconds("1d12h") == 86400 + 43200


# ---------------------------------------------------------------------------
# is_valid_ip
# ---------------------------------------------------------------------------


class TestIsValidIp:
    def test_valid_ipv4(self):
        assert is_valid_ip("192.168.1.1") is True

    def test_valid_ipv4_localhost(self):
        assert is_valid_ip("127.0.0.1") is True

    def test_valid_ipv6(self):
        assert is_valid_ip("::1") is True

    def test_valid_ipv6_full(self):
        assert is_valid_ip("fe80::1") is True

    def test_invalid_string(self):
        assert is_valid_ip("not.an.ip") is False

    def test_empty_string(self):
        assert is_valid_ip("") is False

    def test_hostname(self):
        assert is_valid_ip("router.local") is False

    def test_ipv4_out_of_range(self):
        assert is_valid_ip("256.1.1.1") is False

    def test_partial_ip(self):
        assert is_valid_ip("192.168") is False


# ---------------------------------------------------------------------------
# Memory/HDD usage calculation logic (tested via dict manipulation)
# ---------------------------------------------------------------------------


class TestResourceCalculations:
    """Test the memory and HDD usage calculation logic from get_system_resource."""

    @staticmethod
    def _calc_memory_usage(total, free):
        """Replicate the coordinator's memory usage calculation."""
        if total > 0:
            return round(((total - free) / total) * 100)
        return "unknown"

    @staticmethod
    def _calc_hdd_usage(total, free):
        """Replicate the coordinator's HDD usage calculation."""
        if total > 0:
            return round(((total - free) / total) * 100)
        return "unknown"

    def test_memory_usage_normal(self):
        assert self._calc_memory_usage(1024, 256) == 75

    def test_memory_usage_half(self):
        assert self._calc_memory_usage(1000, 500) == 50

    def test_memory_usage_zero_total(self):
        assert self._calc_memory_usage(0, 0) == "unknown"

    def test_memory_usage_all_used(self):
        assert self._calc_memory_usage(1024, 0) == 100

    def test_memory_usage_none_used(self):
        assert self._calc_memory_usage(1024, 1024) == 0

    def test_hdd_usage_normal(self):
        assert self._calc_hdd_usage(16384, 4096) == 75

    def test_hdd_usage_zero_total(self):
        assert self._calc_hdd_usage(0, 0) == "unknown"

    def test_hdd_usage_rounding(self):
        # 1000 total, 333 free -> (667/1000)*100 = 66.7 -> rounds to 67
        assert self._calc_hdd_usage(1000, 333) == 67


# ---------------------------------------------------------------------------
# Firmware version parsing logic
# ---------------------------------------------------------------------------


class TestFirmwareVersionParsing:
    """Test the firmware version parsing logic from get_firmware_update."""

    @staticmethod
    def _parse_fw_version(full_version):
        """Replicate the coordinator's firmware version parsing."""
        split_end = min(len(full_version), 4)
        version = re.sub("[^0-9\\.]", "", full_version[0:split_end])
        major = int(version.split(".")[0])
        minor = int(version.split(".")[1])
        return major, minor

    def test_parse_v7_14(self):
        major, minor = self._parse_fw_version("7.14.3")
        assert major == 7
        assert minor == 14

    def test_parse_v6_49(self):
        major, minor = self._parse_fw_version("6.49.10")
        assert major == 6
        assert minor == 49

    def test_parse_v7_1(self):
        major, minor = self._parse_fw_version("7.1")
        assert major == 7
        assert minor == 1

    def test_parse_v7_0(self):
        major, minor = self._parse_fw_version("7.0")
        assert major == 7
        assert minor == 0


# ---------------------------------------------------------------------------
# Traffic rate calculation logic
# ---------------------------------------------------------------------------


class TestTrafficRateCalculation:
    """Test the interface traffic rate calculation logic from get_interface."""

    @staticmethod
    def _calc_rate(current, previous, interval_seconds):
        """Replicate the coordinator's traffic rate calculation."""
        prev = previous or current
        delta = max(0, current - prev)
        return round(delta / interval_seconds)

    def test_normal_rate(self):
        # 1000 bytes in 30 seconds = 33 bytes/sec
        assert self._calc_rate(2000, 1000, 30) == 33

    def test_first_poll_zero_previous(self):
        # previous=0 means first poll, should use current as previous -> delta=0
        result = self._calc_rate(5000, 0, 30)
        # previous=0 is falsy, so prev=current=5000, delta=0
        assert result == 0

    def test_counter_reset(self):
        # current < previous (counter wrap) -> max(0, negative) = 0
        assert self._calc_rate(100, 5000, 30) == 0

    def test_no_change(self):
        assert self._calc_rate(1000, 1000, 30) == 0

    def test_high_throughput(self):
        # 1GB in 30s
        assert self._calc_rate(2_000_000_000, 1_000_000_000, 30) == 33333333

    def test_none_previous(self):
        # None is falsy, same as 0 -> prev=current, delta=0
        assert self._calc_rate(5000, None, 30) == 0


# ---------------------------------------------------------------------------
# Duplicate rule dedup logic
# ---------------------------------------------------------------------------


class TestDuplicateRuleDedup:
    """Test the duplicate rule dedup pattern used in NAT/mangle/filter."""

    @staticmethod
    def _dedup_rules(data):
        """Replicate the coordinator's duplicate rule dedup logic."""
        seen = {}
        for uid in data:
            data[uid]["comment"] = str(data[uid]["comment"])
            tmp_name = data[uid]["uniq-id"]
            if tmp_name not in seen:
                seen[tmp_name] = [uid]
            else:
                seen[tmp_name].append(uid)

        for tmp_name, uids in seen.items():
            if len(uids) > 1:
                for uid in uids:
                    router_id = data[uid].get(".id", uid)
                    data[uid]["uniq-id"] = f"{tmp_name} ({router_id})"
        return data

    def test_unique_entries_unchanged(self):
        data = {
            "*1": {"uniq-id": "rule_a", "comment": "A", "name": "A", ".id": "*1"},
            "*2": {"uniq-id": "rule_b", "comment": "B", "name": "B", ".id": "*2"},
        }
        result = self._dedup_rules(data)
        assert result["*1"]["uniq-id"] == "rule_a"
        assert result["*2"]["uniq-id"] == "rule_b"

    def test_duplicate_entries_get_suffix(self):
        data = {
            "*1": {"uniq-id": "same_rule", "comment": "Rule", "name": "Rule", ".id": "*1"},
            "*2": {"uniq-id": "same_rule", "comment": "Rule", "name": "Rule", ".id": "*2"},
        }
        result = self._dedup_rules(data)
        assert result["*1"]["uniq-id"] == "same_rule (*1)"
        assert result["*2"]["uniq-id"] == "same_rule (*2)"

    def test_triple_duplicate(self):
        data = {
            "*1": {"uniq-id": "dup", "comment": "", "name": "X", ".id": "*1"},
            "*2": {"uniq-id": "dup", "comment": "", "name": "X", ".id": "*2"},
            "*3": {"uniq-id": "dup", "comment": "", "name": "X", ".id": "*3"},
        }
        result = self._dedup_rules(data)
        assert result["*1"]["uniq-id"] == "dup (*1)"
        assert result["*2"]["uniq-id"] == "dup (*2)"
        assert result["*3"]["uniq-id"] == "dup (*3)"

    def test_mixed_unique_and_duplicate(self):
        data = {
            "*1": {"uniq-id": "dup", "comment": "", "name": "X", ".id": "*1"},
            "*2": {"uniq-id": "dup", "comment": "", "name": "X", ".id": "*2"},
            "*3": {"uniq-id": "unique_one", "comment": "Y", "name": "Y", ".id": "*3"},
        }
        result = self._dedup_rules(data)
        assert result["*1"]["uniq-id"] == "dup (*1)"
        assert result["*2"]["uniq-id"] == "dup (*2)"
        assert result["*3"]["uniq-id"] == "unique_one"

    def test_comment_converted_to_string(self):
        data = {
            "*1": {"uniq-id": "rule", "comment": None, "name": "R", ".id": "*1"},
        }
        result = self._dedup_rules(data)
        assert result["*1"]["comment"] == "None"
