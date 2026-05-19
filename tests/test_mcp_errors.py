from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


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
