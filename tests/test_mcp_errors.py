from __future__ import annotations

import json
from datetime import UTC, datetime

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
    tool_names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert "get move new downloads scan progress" in tool_names
    assert "get jellyfin library items" in tool_names
    assert "get ongoing jellyfin series latest episodes" in tool_names


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


def test_jellyfin_series_status_continuing_is_treated_as_ongoing() -> None:
    from app.services.jellyfin import JellyfinClient

    assert JellyfinClient._is_ongoing_series(
        {
            "Status": "Continuing",
            "EndDate": "2025-07-26T18:30:00.0000000Z",
        }
    ) is True


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
            status="confirmed",
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
    assert payload["items"][0]["confirmId"] == "i1"
    assert payload["items"][0]["sourcePath"] == "/data/torrents/Show/S01E01.mkv"
    assert "source_path" not in payload["items"][0]


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
