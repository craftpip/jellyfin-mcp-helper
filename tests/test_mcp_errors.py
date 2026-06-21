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
