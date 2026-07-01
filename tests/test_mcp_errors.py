from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import ScanCounts, ScanPlan, ScannedItem


def test_mcp_scan_report_invalid_scan_id_returns_http_200_with_jsonrpc_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get move new downloads scan report",
                    "arguments": {"scanId": "missing-scan"},
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32000
    assert payload["error"]["message"] == "Scan not found. Run 'scan library' first."


def test_mcp_confirm_missing_scan_id_returns_http_200_with_jsonrpc_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "confirm move new downloads scan",
                    "arguments": {},
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32602
    assert payload["error"]["message"] == "scanId is required"


def test_mcp_tools_list_includes_scan_progress_tool() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        )

    assert response.status_code == 200
    payload = response.json()["result"]
    tool_names = [tool["name"] for tool in payload["tools"]]
    assert "get move new downloads scan progress" in tool_names
    assert "get jellyfin library items" in tool_names
    assert "get ongoing jellyfin series latest episodes" in tool_names
    assert "store ongoing series next release" in tool_names
    assert "get ongoing series next release" in tool_names
    assert "get due ongoing series releases" in tool_names
    assert "get ongoing series next releases" in tool_names
    assert "Release Tracker answers questions about what is stored" in payload["llm_instructions"][0]


def test_mcp_get_jellyfin_library_items_formats_compact_response(monkeypatch) -> None:
    class FakeJellyfinClient:
        async def list_library_items(self, library_name: str, search=None, limit=10, ongoing_only=False):
            assert library_name == "Shows"
            assert search == "Bleach"
            assert limit == 10
            assert ongoing_only is True
            return {
                "library_name": "Shows",
                "returned_items": 1,
                "search": "Bleach",
                "ongoing_only": True,
                "items": [
                    {
                        "name": "Bleach",
                        "type": "series",
                        "ongoing": True,
                        "season_count": 3,
                        "episode_count": 39,
                        "seasons": [
                            {"season": 1, "episodes": 13},
                            {"season": 2, "episodes": 13},
                            {"season": 3, "episodes": 13},
                        ],
                    }
                ],
            }

    monkeypatch.setattr("app.main.JellyfinClient.from_env", lambda: FakeJellyfinClient())

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {
                    "name": "get jellyfin library items",
                    "arguments": {
                        "libraryName": "Shows",
                        "search": "Bleach",
                        "ongoingOnly": True,
                        "limit": 10,
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["library_name"] == "Shows"
    assert payload["returned_items"] == 1
    assert payload["ongoing_only"] is True
    assert payload["items"][0]["season_count"] == 3
    assert payload["items"][0]["seasons"][0] == {"season": 1, "episodes": 13}
    assert "ongoingOnly" in payload["next"]


FUZZY_SCORE_CASES: list[tuple[str, str, float]] = [
    ("One Piece", "One Piece", 1.0),
    ("Bleach", "Bleach: Thousand-Year Blood War", 0.85),
    ("attack titan", "Attack on Titan", 0.8),
    ("one peice", "One Piece", 0.65),
    ("spider man", "Spider-Man: No Way Home", 0.55),
    ("dragon ball", "Dragon Ball Z", 0.8),
]


@pytest.mark.parametrize("query,name,min_expected", FUZZY_SCORE_CASES)
def test_fuzzy_score(query: str, name: str, min_expected: float) -> None:
    from app.services.jellyfin import JellyfinClient

    score = JellyfinClient._fuzzy_score(query, name)
    assert score >= min_expected, f"_fuzzy_score({query!r}, {name!r}) = {score} < {min_expected}"


def test_fuzzy_score_empty_returns_zero() -> None:
    from app.services.jellyfin import JellyfinClient

    assert JellyfinClient._fuzzy_score("", "One Piece") == 0.0
    assert JellyfinClient._fuzzy_score("One Piece", "") == 0.0


def test_fuzzy_score_unrelated_is_low() -> None:
    from app.services.jellyfin import JellyfinClient

    score = JellyfinClient._fuzzy_score("star wars", "The Office")
    assert score < 0.3


def test_jellyfin_list_library_items_fuzzy_search(monkeypatch) -> None:
    from app.services.jellyfin import JellyfinClient

    api_calls: list[dict] = []

    async def fake_api_get(self, path: str, params: dict[str, str] | None = None) -> dict:
        api_calls.append({"path": path, "params": params or {}})
        return {
            "Items": [
                {"Name": "One Piece", "Type": "Series", "Id": "s1", "Status": "Continuing"},
                    {"Name": "One-Punch Man", "Type": "Series", "Id": "s2", "Status": "Ended", "EndDate": "2020-01-01T00:00:00.0000000Z"},
                    {"Name": "Mushoku Tensei", "Type": "Series", "Id": "s3", "Status": "Continuing"},
                    {"Name": "Attack on Titan", "Type": "Series", "Id": "s4", "Status": "Ended", "EndDate": "2024-01-01T00:00:00.0000000Z"},
            ]
        }

    async def fake_api_get_user(self) -> str:
        return "user-1"

    async def fake_get_series_seasons(slf, series_id: str, user_id: str) -> dict:
        return {"total_seasons": 1, "total_episodes": 12, "seasons": [{"season": 1, "episodes": 12}]}

    async def fake_resolve_library(slf, name: str) -> dict:
        return {"name": name, "id": "lib-1"}

    monkeypatch.setattr(JellyfinClient, "_api_get", fake_api_get)
    monkeypatch.setattr(JellyfinClient, "_get_user_id", fake_api_get_user)
    monkeypatch.setattr(JellyfinClient, "_get_series_seasons", fake_get_series_seasons)
    monkeypatch.setattr(JellyfinClient, "_resolve_library", fake_resolve_library)

    client = JellyfinClient("http://jellyfin.local:8096", "secret", "Movies", "Shows")
    result = asyncio.run(client.list_library_items(library_name="Shows", search="one peice", limit=5))

    assert result["search"] == "one peice"
    assert result["returned_items"] > 0

    item_names = [item["name"] for item in result["items"]]
    assert "One Piece" in item_names
    assert "One-Punch Man" in item_names

    assert "api_calls" not in result  # no internals leaked

    assert len(api_calls) == 1
    params = api_calls[0]["params"]
    assert "SearchTerm" not in params, "should not pass SearchTerm to Jellyfin API"
    assert int(params.get("Limit", "0")) == 200


def test_jellyfin_series_status_continuing_is_treated_as_ongoing() -> None:
    from app.services.jellyfin import JellyfinClient

    assert JellyfinClient._is_ongoing_series(
        {
            "Status": "Continuing",
            "EndDate": "2025-07-26T18:30:00.0000000Z",
        }
    ) is True


def test_jellyfin_notify_media_updated_posts_path_payload(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url: str, json=None, headers=None, params=None):
            calls["url"] = url
            calls["json"] = json
            calls["headers"] = headers
            calls["params"] = params
            return FakeResponse()

    monkeypatch.setattr("app.services.jellyfin.httpx.AsyncClient", FakeAsyncClient)

    from app.services.jellyfin import JellyfinClient

    client = JellyfinClient("http://jellyfin.local:8096", "secret", "Movies", "Shows")
    result = asyncio.run(client.notify_media_updated(["/media/shows/episode1.mkv", "/media/shows/episode1.mkv"]))

    assert result == {"updated_paths": ["/media/shows/episode1.mkv"]}
    assert calls["url"] == "http://jellyfin.local:8096/Library/Media/Updated"
    assert calls["json"] == {"updates": [{"path": "/media/shows/episode1.mkv"}]}
    assert calls["headers"] == {"X-Emby-Token": "secret"}


def test_mcp_get_jellyfin_library_items_requires_library_name() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 32,
                "method": "tools/call",
                "params": {
                    "name": "get jellyfin library items",
                    "arguments": {},
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32602
    assert payload["error"]["message"] == "libraryName is required"


def test_mcp_trigger_jellyfin_library_scan_calls_jellyfin_scan(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeJellyfinClient:
        async def scan_library(self, **kwargs):
            calls.update(kwargs)
            return {"name": "Shows", "id": "library-1"}

    monkeypatch.setattr("app.main.JellyfinClient.from_env", lambda: FakeJellyfinClient())

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 35,
                "method": "tools/call",
                "params": {
                    "name": "trigger jellyfin library scan",
                    "arguments": {
                        "libraryName": "Shows",
                        "itemNames": ["Bleach"],
                        "recursive": False,
                        "metadataRefreshMode": "FullRefresh",
                        "imageRefreshMode": "Default",
                        "replaceAllMetadata": True,
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert calls == {
        "library_name": "Shows",
        "item_ids": None,
        "item_names": ["Bleach"],
        "recursive": False,
        "metadata_refresh_mode": "FullRefresh",
        "image_refresh_mode": "Default",
        "replace_all_metadata": True,
        "replace_all_images": False,
    }
    assert payload["message"] == "Triggered Jellyfin library scan for 'Shows'"
    assert payload["library"] == {"name": "Shows", "id": "library-1"}


def test_mcp_get_ongoing_jellyfin_series_latest_episodes_formats_response(monkeypatch) -> None:
    class FakeJellyfinClient:
        async def list_ongoing_series_latest_episodes(self, library_name: str, search=None, limit=10):
            assert library_name == "Shows"
            assert search == "rick"
            assert limit == 10
            return {
                "library_name": "Shows",
                "returned_items": 1,
                "search": "rick",
                "items": [
                    {
                        "seriesId": "series-123",
                        "name": "Rick and Morty",
                        "type": "series",
                        "ongoing": True,
                        "latest_episode": {
                            "season": 9,
                            "episode": 3,
                            "title": "The Rick, The Mort & The Ugly",
                        },
                    }
                ],
            }

    monkeypatch.setattr("app.main.JellyfinClient.from_env", lambda: FakeJellyfinClient())

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 33,
                "method": "tools/call",
                "params": {
                    "name": "get ongoing jellyfin series latest episodes",
                    "arguments": {
                        "libraryName": "Shows",
                        "search": "rick",
                        "limit": 10,
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["library_name"] == "Shows"
    assert payload["returned_items"] == 1
    assert payload["items"][0]["seriesId"] == "series-123"
    assert payload["items"][0]["latest_episode"] == {
        "season": 9,
        "episode": 3,
        "title": "The Rick, The Mort & The Ugly",
    }
    assert "all ongoing series" in payload["next"]


def test_mcp_get_ongoing_jellyfin_series_latest_episodes_requires_library_name() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 34,
                "method": "tools/call",
                "params": {
                    "name": "get ongoing jellyfin series latest episodes",
                    "arguments": {},
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32602
    assert payload["error"]["message"] == "libraryName is required"


def test_mcp_store_ongoing_series_next_release(monkeypatch, tmp_path) -> None:
    tracker_path = tmp_path / "ongoing_releases.json"
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tracker_path)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 35,
                "method": "tools/call",
                "params": {
                    "name": "store ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "One Piece",
                        "seriesId": "series-1",
                        "nextReleaseDate": "2026-06-28",
                        "nextSeason": 22,
                        "nextEpisode": 1124,
                        "timezone": "Asia/Tokyo",
                        "source": "llm",
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["record"]["libraryName"] == "Shows"
    assert payload["record"]["seriesName"] == "One Piece"
    assert payload["record"]["seriesId"] == "series-1"
    assert payload["record"]["nextReleaseDate"] == "2026-06-28T00:00:00+09:00"
    assert payload["record"]["nextSeason"] == 22
    assert payload["record"]["nextEpisode"] == 1124


def test_mcp_get_due_ongoing_series_releases(monkeypatch, tmp_path) -> None:
    tracker_path = tmp_path / "ongoing_releases.json"
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tracker_path)

    with TestClient(app) as client:
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 36,
                "method": "tools/call",
                "params": {
                    "name": "store ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "One Piece",
                        "nextReleaseDate": "2026-06-28T18:00:00+09:00",
                        "nextEpisode": 1124,
                        "source": "llm",
                    },
                },
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 37,
                "method": "tools/call",
                "params": {
                    "name": "get due ongoing series releases",
                    "arguments": {
                        "libraryName": "Shows",
                        "before": "2026-06-29T00:00:00+09:00",
                        "limit": 50,
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["due_count"] == 1
    assert payload["items"][0]["seriesName"] == "One Piece"
    assert payload["items"][0]["nextEpisode"] == 1124
    assert "daysOverdue" in payload["items"][0] or "hoursOverdue" in payload["items"][0]
    assert payload["dataOrigin"] == "release_tracker"
    assert payload["authorityScope"] == "stored_tracker_value"


def test_mcp_get_due_ongoing_series_releases_excludes_not_due(monkeypatch, tmp_path) -> None:
    tracker_path = tmp_path / "ongoing_releases.json"
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tracker_path)

    with TestClient(app) as client:
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 38,
                "method": "tools/call",
                "params": {
                    "name": "store ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "Dandadan",
                        "nextReleaseDate": "2026-07-05T18:00:00+09:00",
                    },
                },
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 39,
                "method": "tools/call",
                "params": {
                    "name": "get due ongoing series releases",
                    "arguments": {
                        "libraryName": "Shows",
                        "before": "2026-07-01T00:00:00+09:00",
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["due_count"] == 0
    assert payload["items"] == []


def test_mcp_get_ongoing_series_next_releases(monkeypatch, tmp_path) -> None:
    tracker_path = tmp_path / "ongoing_releases.json"
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tracker_path)

    with TestClient(app) as client:
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 40,
                "method": "tools/call",
                "params": {
                    "name": "store ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "One Piece",
                        "nextReleaseDate": "2026-06-28T18:00:00+09:00",
                    },
                },
            },
        )
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 41,
                "method": "tools/call",
                "params": {
                    "name": "store ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "Dandadan",
                        "nextReleaseDate": "2026-06-27T18:00:00+09:00",
                    },
                },
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {
                    "name": "get ongoing series next releases",
                    "arguments": {
                        "libraryName": "Shows",
                        "limit": 100,
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["tracked_count"] == 2
    assert [item["seriesName"] for item in payload["items"]] == ["Dandadan", "One Piece"]
    assert payload["dataOrigin"] == "release_tracker"
    assert payload["authorityScope"] == "stored_tracker_value"


def test_mcp_get_ongoing_series_next_release_returns_exact_stored_record(monkeypatch, tmp_path) -> None:
    tracker_path = tmp_path / "ongoing_releases.json"
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tracker_path)

    with TestClient(app) as client:
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 43,
                "method": "tools/call",
                "params": {
                    "name": "store ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "One Piece",
                        "seriesId": "series-1",
                        "nextReleaseDate": "2026-06-28T18:00:00+09:00",
                        "nextSeason": 22,
                        "nextEpisode": 1124,
                        "source": "manual",
                    },
                },
            },
        )

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 44,
                "method": "tools/call",
                "params": {
                    "name": "get ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "One Piece",
                        "seriesId": "series-1",
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["found"] is True
    assert payload["dataOrigin"] == "release_tracker"
    assert payload["authorityScope"] == "stored_tracker_value"
    assert payload["record"]["seriesName"] == "One Piece"
    assert payload["record"]["seriesId"] == "series-1"
    assert payload["record"]["nextEpisode"] == 1124
    assert "answer from this stored Release Tracker value" in payload["next"]


def test_mcp_get_ongoing_series_next_release_returns_not_found(monkeypatch, tmp_path) -> None:
    tracker_path = tmp_path / "ongoing_releases.json"
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tracker_path)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 45,
                "method": "tools/call",
                "params": {
                    "name": "get ongoing series next release",
                    "arguments": {
                        "libraryName": "Shows",
                        "seriesName": "Dandadan",
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["found"] is False
    assert payload["record"] is None
    assert payload["dataOrigin"] == "release_tracker"
    assert "store ongoing series next release" in payload["next"]


def test_mcp_scan_start_response_instructs_llm_to_use_progress_tool(monkeypatch) -> None:
    def fake_run_scan(self, scan_id, request) -> None:
        return None

    monkeypatch.setattr("app.services.scan_manager.ScanManager._run_scan_sync", fake_run_scan)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "move new downloads scan",
                    "arguments": {"replaceExisting": True},
                },
            },
        )

    assert response.status_code == 200
    content = response.json()["result"]["content"][0]["text"]
    payload = json.loads(content)
    instructions = " ".join(payload["llm_instructions"])
    assert payload["status"] == "running"
    assert "get move new downloads scan progress" in instructions
    assert "get move new downloads scan report" in instructions
    assert "Do not call the confirm tool" in instructions


def test_mcp_confirm_response_uses_source_path_alias(monkeypatch) -> None:
    async def fake_confirm_scan(self, scan_id, item_ids=None, source_paths=None, source_prefixes=None):
        return ScanPlan(
            scan_id=scan_id,
            status="completed",
            confirm_status="running",
            confirm_total=1,
            confirm_started_at=datetime.now(UTC),
            operation="organize",
            counts=ScanCounts(),
            created_at=datetime.now(UTC),
            items=[
                ScannedItem(
                    confirm_id="i1",
                    source_path="/data/torrents/Show/S01E01.mkv",
                    name="Show - S01E01.mkv",
                    item_type="series",
                    confidence=1.0,
                    reason="Matched series episode",
                    target_path="/media/series/Show/Season 01/Show - S01E01.mkv",
                    action="move",
                    confirmed=True,
                )
            ],
        )

    monkeypatch.setattr("app.services.scan_manager.ScanManager.confirm_scan", fake_confirm_scan)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "confirm move new downloads scan",
                    "arguments": {
                        "scanId": "scan-123",
                        "sourcePaths": ["/data/torrents/Show/S01E01.mkv"],
                    },
                },
            },
        )

    assert response.status_code == 200
    content = response.json()["result"]["content"][0]["text"]
    payload = json.loads(content)
    assert payload["scan_id"] == "scan-123"
    assert payload["status"] == "running"
    assert payload["total"] == 1


def test_mcp_confirm_forwards_item_ids(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_confirm_scan(self, scan_id, item_ids=None, source_paths=None, source_prefixes=None):
        captured["scan_id"] = scan_id
        captured["item_ids"] = item_ids
        captured["source_paths"] = source_paths
        captured["source_prefixes"] = source_prefixes
        return ScanPlan(
            scan_id=scan_id,
            status="completed",
            operation="organize",
            counts=ScanCounts(),
            created_at=datetime.now(UTC),
            items=[],
        )

    monkeypatch.setattr("app.services.scan_manager.ScanManager.confirm_scan", fake_confirm_scan)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "confirm move new downloads scan",
                    "arguments": {
                        "scanId": "scan-456",
                        "itemIds": ["i23", "i24"],
                    },
                },
            },
        )

    assert response.status_code == 200
    assert captured == {
        "scan_id": "scan-456",
        "item_ids": ["i23", "i24"],
        "source_paths": None,
        "source_prefixes": None,
    }
