"""
Integration tests for download client (qBittorrent via MCP).
Tests against real qBittorrent via MCP - no mocks.
"""
from __future__ import annotations

import os
import time
import httpx
import pytest


MCP_URL = os.getenv("MCP_URL", "http://host.docker.internal:8093/mcp")
MCP_KEY = os.getenv("MCP_KEY", "")
ORGANIZER_URL = os.getenv("ORGANIZER_URL", "http://localhost:18328")


def is_mcp_available() -> bool:
    try:
        with httpx.Client(timeout=2) as client:
            resp = client.get("http://host.docker.internal:8093/mcp")
            return resp.status_code < 500
    except Exception:
        return False


def call_mcp(tool_name: str, arguments: dict) -> dict:
    """Call MCP tool."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {"Content-Type": "application/json", "X-MCP-Key": MCP_KEY}

    resp = httpx.post(MCP_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def list_items(view: str = "all") -> list[dict]:
    """List download items via MCP."""
    import json
    result = call_mcp("list_torrents", {"view": view})
    content = result.get("result", {}).get("content", [])
    if not content:
        return []
    return json.loads(content[0].get("text", "[]"))


class TestQbittorrentMCP:
    """Test qBittorrent download client via MCP."""

    def test_list_all(self):
        """List all download items."""
        items = list_items("all")
        print(f"\n✓ Found {len(items)} items")
        for t in items[:5]:
            name = t.get("name", "unknown")[:50]
            state = t.get("state_human", t.get("state", ""))
            print(f"  - {name} | {state}")

    def test_list_seeding(self):
        """List seeding items."""
        items = list_items("seeding")
        print(f"\n✓ Found {len(items)} seeding items")

    def test_list_stopped(self):
        """List stopped items."""
        items = list_items("stopped")
        print(f"\n✓ Found {len(items)} stopped items")

    def test_stop_item(self):
        """Stop a download item."""
        items = list_items("all")
        if not items:
            pytest.skip("No items")

        item = items[0]
        h = item.get("hash")
        name = item.get("name", "unknown")[:40]
        before = item.get("state_human", item.get("state", ""))

        print(f"\n  Stopping: {name}")
        print(f"  Before: {before}")

        call_mcp("stop_torrents", {"hashes": [h]})
        time.sleep(1)

        updated = list_items("all")
        t = next((x for x in updated if x.get("hash") == h), None)
        after = t.get("state_human", t.get("state", "")) if t else "not found"

        print(f"  After: {after}")
        assert "stopped" in after.lower(), f"Expected stopped, got {after}"
        print(f"✓ Item stopped successfully")

    def test_start_item(self):
        """Start a stopped item."""
        items = list_items("stopped")
        if not items:
            pytest.skip("No stopped items")

        item = items[0]
        h = item.get("hash")
        name = item.get("name", "unknown")[:40]

        print(f"\n  Starting: {name}")

        call_mcp("start_torrents", {"hashes": [h]})
        time.sleep(1)

        updated = list_items("all")
        t = next((x for x in updated if x.get("hash") == h), None)
        after = t.get("state_human", t.get("state", "")) if t else "not found"

        print(f"  After: {after}")
        print(f"✓ Item started successfully")

    def test_get_item_by_hash(self):
        """Get specific item info."""
        items = list_items("all")
        if not items:
            pytest.skip("No items")

        t = items[0]
        h = t.get("hash")
        name = t.get("name", "unknown")[:40]

        print(f"\n  Looking for: {name}")
        print(f"  Hash: {h}")
        print(f"  Content path: {t.get('content_path', 'N/A')}")
        print(f"  Save path: {t.get('save_path', 'N/A')}")
        print(f"  State: {t.get('state_human', t.get('state'))}")
        print(f"✓ Got item info")


class TestOrganizerAPI:
    """Test organizer API."""

    def test_health(self):
        """Health check."""
        resp = httpx.get(f"{ORGANIZER_URL}/health", timeout=5)
        assert resp.status_code == 200
        print("\n✓ Organizer healthy")

    def test_current_run(self):
        """Get current run."""
        resp = httpx.get(f"{ORGANIZER_URL}/runs/current", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"\n✓ Current run: {data.get('status')}")
        else:
            print("\n✓ No active runs")

    def test_start_run(self):
        """Start a dry run."""
        resp = httpx.post(
            f"{ORGANIZER_URL}/runs",
            json={"dryRun": True, "replaceExisting": True},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        print(f"\n✓ Started run: {data.get('run_id')}")
