"""Tests for update.py — version utilities and changelog fetching."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from packaging.version import Version

# ---------------------------------------------------------------------------
# decrement_version
# ---------------------------------------------------------------------------


class TestDecrementVersion:
    def test_decrement_patch(self):
        from custom_components.mikrotik_extended.update import decrement_version

        result = decrement_version(Version("7.14.3"), Version("7.14.0"))
        assert result == Version("7.14.2")

    def test_decrement_patch_to_zero(self):
        from custom_components.mikrotik_extended.update import decrement_version

        result = decrement_version(Version("7.14.0"), Version("7.13.0"))
        assert result == Version("7.13.999")

    def test_decrement_minor_to_zero(self):
        from custom_components.mikrotik_extended.update import decrement_version

        result = decrement_version(Version("7.0.0"), Version("6.0.0"))
        assert result == Version("6.999.999")

    def test_decrement_single_step(self):
        from custom_components.mikrotik_extended.update import decrement_version

        result = decrement_version(Version("7.14.1"), Version("7.14.0"))
        assert result == Version("7.14.0")

    def test_decrement_micro_boundary(self):
        from custom_components.mikrotik_extended.update import decrement_version

        result = decrement_version(Version("7.1.0"), Version("7.0.0"))
        assert result == Version("7.0.999")


# ---------------------------------------------------------------------------
# generate_version_list
# ---------------------------------------------------------------------------


class TestGenerateVersionList:
    def test_same_version_returns_single(self):
        from custom_components.mikrotik_extended.update import generate_version_list

        result = generate_version_list("7.14.3", "7.14.3")
        assert result == ["7.14.3"]

    def test_patch_range(self):
        from custom_components.mikrotik_extended.update import generate_version_list

        result = generate_version_list("7.14.1", "7.14.3")
        assert "7.14.3" in result
        assert "7.14.2" in result
        assert "7.14.1" in result
        assert result[0] == "7.14.3"  # newest first

    def test_two_versions(self):
        from custom_components.mikrotik_extended.update import generate_version_list

        result = generate_version_list("7.14.2", "7.14.3")
        assert len(result) == 2
        assert result == ["7.14.3", "7.14.2"]

    def test_larger_range_descending(self):
        from custom_components.mikrotik_extended.update import generate_version_list

        result = generate_version_list("7.14.0", "7.14.3")
        assert result[0] == "7.14.3"
        assert result[-1] == "7.14.0"
        assert len(result) == 4


# ---------------------------------------------------------------------------
# fetch_changelog
# ---------------------------------------------------------------------------


class TestFetchChangelog:
    async def test_success_returns_formatted_text(self):
        from custom_components.mikrotik_extended.update import fetch_changelog

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="*) fixed bug\n*) added feature")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await fetch_changelog(mock_session, "7.14.3")
        assert result == "- fixed bug\n- added feature"

    async def test_404_returns_empty(self):
        from custom_components.mikrotik_extended.update import fetch_changelog

        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await fetch_changelog(mock_session, "99.99.99")
        assert result == ""

    async def test_exception_returns_empty(self):
        from custom_components.mikrotik_extended.update import fetch_changelog

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("network error"))

        result = await fetch_changelog(mock_session, "7.14.3")
        assert result == ""

    async def test_replaces_asterisk_bullets(self):
        from custom_components.mikrotik_extended.update import fetch_changelog

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="*) item one\nplain line\n*) item two")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await fetch_changelog(mock_session, "7.14.3")
        assert "*) " not in result
        assert "- item one" in result
        assert "- item two" in result
