from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from app.core.config import PathsConfig
from app.services.download_client import (
    QbittorrentClient,
    _extract_paths,
    _is_incomplete,
    _item_matches_paths,
    _item_paths,
    _normalize_qbt_path,
)


# ---------------------------------------------------------------------------
# _is_incomplete
# ---------------------------------------------------------------------------

class TestIsIncomplete:
    def test_zero_progress(self) -> None:
        assert _is_incomplete({"progress": 0}) is True

    def test_half_progress(self) -> None:
        assert _is_incomplete({"progress": 0.5}) is True

    def test_near_complete(self) -> None:
        assert _is_incomplete({"progress": 0.998}) is True

    def test_complete(self) -> None:
        assert _is_incomplete({"progress": 1.0}) is False

    def test_missing_progress(self) -> None:
        assert _is_incomplete({}) is True

    def test_none_progress(self) -> None:
        assert _is_incomplete({"progress": None}) is True

    def test_string_progress(self) -> None:
        assert _is_incomplete({"progress": "abc"}) is True

    def test_string_number_progress(self) -> None:
        assert _is_incomplete({"progress": "0.5"}) is True


# ---------------------------------------------------------------------------
# _normalize_qbt_path
# ---------------------------------------------------------------------------

class TestNormalizeQbtPath:
    def test_no_config_returns_as_is(self) -> None:
        assert _normalize_qbt_path("/remote/downloads/Show", None) == "/remote/downloads/Show"

    def test_finds_folder_in_download_root(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        folder = root / "My Show Season 01"
        folder.mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        result = _normalize_qbt_path("/config/Downloads/My Show Season 01", config)
        assert result == str(folder)

    def test_finds_nested_folder(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        folder = root / "Show Name"
        folder.mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        result = _normalize_qbt_path("/remote/path/deep/Show Name/file.mkv", config)
        assert str(folder) in result

    def test_no_match_returns_original(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        result = _normalize_qbt_path("/completely/different/path", config)
        assert result == "/completely/different/path"

    def test_skips_hidden_parts(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        result = _normalize_qbt_path("/config/.hidden/Show", config)
        assert result == "/config/.hidden/Show"


# ---------------------------------------------------------------------------
# _item_paths
# ---------------------------------------------------------------------------

class TestItemPaths:
    def test_content_path(self, tmp_path: Path) -> None:
        paths = _item_paths({"content_path": "/data/show/file.mkv"}, None)
        assert "/data/show/file.mkv" in paths

    def test_root_path(self, tmp_path: Path) -> None:
        paths = _item_paths({"root_path": "/data/show"}, None)
        assert "/data/show" in paths

    def test_download_path(self, tmp_path: Path) -> None:
        paths = _item_paths({"download_path": "/data/show"}, None)
        assert "/data/show" in paths

    def test_save_path_plus_name(self) -> None:
        paths = _item_paths({"save_path": "/downloads", "name": "My Show"}, None)
        assert any("My Show" in p for p in paths)

    def test_empty_values_skipped(self) -> None:
        paths = _item_paths({"content_path": "", "root_path": "  "}, None)
        assert paths == []

    def test_download_root_fallback(self, tmp_path: Path) -> None:
        root = tmp_path / "torrents"
        root.mkdir()
        config = PathsConfig(downloadRoots=[str(root)])
        paths = _item_paths({"name": "My Torrent"}, config)
        assert str(root / "My Torrent") in paths

    def test_multiple_keys_combined(self) -> None:
        paths = _item_paths(
            {"content_path": "/a/b", "root_path": "/c", "save_path": "/d", "name": "file"},
            None,
        )
        assert len(paths) >= 3

    def test_non_string_values_skipped(self) -> None:
        paths = _item_paths({"content_path": 123, "name": None}, None)
        assert paths == []


# ---------------------------------------------------------------------------
# _extract_paths
# ---------------------------------------------------------------------------

class TestExtractPaths:
    def test_deduplicates_paths(self) -> None:
        items = [
            {"content_path": "/data/show/file.mkv"},
            {"root_path": "/data/show/file.mkv"},
        ]
        result = _extract_paths(items, None)
        assert len(result) == 1

    def test_strips_trailing_slash(self) -> None:
        items = [{"content_path": "/data/show/file.mkv/"}]
        result = _extract_paths(items, None)
        assert result[0] == "/data/show/file.mkv"

    def test_empty_items(self) -> None:
        assert _extract_paths([], None) == []


# ---------------------------------------------------------------------------
# _item_matches_paths
# ---------------------------------------------------------------------------

class TestItemMatchesPaths:
    def test_exact_match(self) -> None:
        item = {"content_path": "/data/show/file.mkv"}
        assert _item_matches_paths(item, {"/data/show/file.mkv"}, None) is True

    def test_candidate_is_parent(self) -> None:
        item = {"content_path": "/data/show/file.mkv"}
        assert _item_matches_paths(item, {"/data/show"}, None) is True

    def test_item_is_parent_of_candidate(self) -> None:
        item = {"content_path": "/data/show"}
        assert _item_matches_paths(item, {"/data/show/file.mkv"}, None) is True

    def test_no_match(self) -> None:
        item = {"content_path": "/data/other/file.mkv"}
        assert _item_matches_paths(item, {"/data/show/file.mkv"}, None) is False

    def test_empty_candidates(self) -> None:
        item = {"content_path": "/data/show/file.mkv"}
        assert _item_matches_paths(item, set(), None) is False


# ---------------------------------------------------------------------------
# QbittorrentClient.from_env
# ---------------------------------------------------------------------------

class TestQbittorrentClientFromEnv:
    def test_returns_none_when_check_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_DOWNLOAD_CLIENT_CHECK", "false")
        assert QbittorrentClient.from_env() is None

    def test_returns_none_when_not_qbittorrent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_DOWNLOAD_CLIENT_CHECK", "true")
        monkeypatch.setenv("DOWNLOAD_CLIENT", "transmission")
        assert QbittorrentClient.from_env() is None

    def test_returns_none_when_no_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_DOWNLOAD_CLIENT_CHECK", "true")
        monkeypatch.setenv("DOWNLOAD_CLIENT", "qbittorrent")
        monkeypatch.setenv("QBT_WEBUI_URL", "")
        monkeypatch.setenv("QBT_MCP_URL", "")
        assert QbittorrentClient.from_env() is None

    def test_returns_client_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_DOWNLOAD_CLIENT_CHECK", "true")
        monkeypatch.setenv("DOWNLOAD_CLIENT", "qbittorrent")
        monkeypatch.setenv("QBT_WEBUI_URL", "http://localhost:8080")
        monkeypatch.setenv("QBT_WEBUI_USER", "admin")
        monkeypatch.setenv("QBT_WEBUI_PASS", "pass")
        client = QbittorrentClient.from_env()
        assert client is not None
        assert client._base_url == "http://localhost:8080"
        assert client._username == "admin"

    def test_returns_none_when_url_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_DOWNLOAD_CLIENT_CHECK", "true")
        monkeypatch.setenv("DOWNLOAD_CLIENT", "qbittorrent")
        monkeypatch.setenv("QBT_WEBUI_URL", "  ")
        monkeypatch.setenv("QBT_MCP_URL", "  ")
        assert QbittorrentClient.from_env() is None


# ---------------------------------------------------------------------------
# QbittorrentClient auth headers
# ---------------------------------------------------------------------------

class TestQbittorrentClientAuth:
    def test_api_key_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = QbittorrentClient(
            base_url="http://localhost:8080",
            username="my-user",
            password="my-pass",
        )
        assert client._username == "my-user"
        assert client._password == "my-pass"

    def test_basic_auth_when_no_api_key(self) -> None:
        user = "admin"
        password = "secret"
        client = QbittorrentClient(
            base_url="http://localhost:8080",
            username=user,
            password=password,
        )
        assert client._username == user
        assert client._password == password


# ---------------------------------------------------------------------------
# QbittorrentClient.stop_seeding_for_paths
# ---------------------------------------------------------------------------

class TestStopSeeding:
    def test_empty_candidates_returns_empty(self, tmp_path: Path) -> None:
        client = QbittorrentClient(
            base_url="http://localhost:8080",
            username="admin",
            password="pass",
        )
        result = asyncio_run(client.stop_seeding_for_paths([]))
        assert result == []

    def test_filters_incomplete_items(self) -> None:
        assert _is_incomplete({"progress": 0.5}) is True
        assert _is_incomplete({"progress": 1.0}) is False


# ---------------------------------------------------------------------------
# list_items parsing
# ---------------------------------------------------------------------------

class TestListItemsParsing:
    def test_empty_content_returns_empty_list(self) -> None:
        data = {"result": {"content": []}}
        assert data["result"]["content"] == []

    def test_parses_json_text(self) -> None:
        items = [{"hash": "abc", "name": "test.mkv", "progress": 1.0}]
        data = {"result": {"content": [{"text": json.dumps(items)}]}}
        parsed = json.loads(data["result"]["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["name"] == "test.mkv"


import asyncio


def asyncio_run(coro):
    return asyncio.run(coro)
