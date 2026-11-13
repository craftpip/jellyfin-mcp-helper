"""The MCP hints must drive an agent through scan -> report -> confirm without asking the user.

Previously every step told the LLM to "ask the user if they want to check progress" and
"Do not call any tool automatically", so agents stopped after each tool call.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import (
    MCP_PROGRESS_MAX_WAIT_SECONDS,
    _progress_wait_seconds,
    _wait_while_running,
    app,
)
from app.models.schemas import ScanPlan, ScannedItem
from app.services.presenters import (
    format_confirm_progress,
    format_scan_progress,
    format_scan_report,
    report_next_step,
)


def _scan(**overrides) -> ScanPlan:
    defaults = dict(scan_id="s", status="completed", operation="organize", created_at=datetime.now(UTC))
    defaults.update(overrides)
    return ScanPlan(**defaults)


def _item(confirm_id: str, source: str, target: str) -> ScannedItem:
    return ScannedItem(
        confirmId=confirm_id,
        sourcePath=source,
        name=source.rsplit("/", 1)[-1],
        item_type="series",
        confidence=0.9,
        reason="test",
        target_path=target,
        action="move",
    )


def _asks_user(text: str) -> bool:
    lowered = text.lower()
    return "ask if they want" in lowered or "ask the user if" in lowered or "do not call any tool automatically" in lowered


def test_initialize_returns_autonomous_workflow_instructions() -> None:
    with TestClient(app) as client:
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    instructions = resp.json()["result"]["instructions"]
    assert "Work autonomously" in instructions
    assert "get move new downloads scan progress" in instructions
    assert "confirm move new downloads scan" in instructions


def test_progress_and_report_hints_never_ask_user_to_continue() -> None:
    running = _scan(status="running", total_candidates=10, processed_candidates=2)
    assert not _asks_user(format_scan_progress(running)["next"])
    assert "get move new downloads scan progress" in format_scan_progress(running)["next"]

    running_report = format_scan_report(running)
    assert not _asks_user(running_report["next"])
    assert not any(_asks_user(line) for line in running_report["llm_instructions"])

    done = _scan()
    assert "get move new downloads scan report" in format_scan_progress(done)["next"]

    confirming = _scan(confirm_status="running", confirm_total=3)
    assert not _asks_user(format_confirm_progress(confirming)["next"])

    pending = _scan(items=[_item("i1", "/dl/Show/Show S01E01.mkv", "/series/Show/Season 01/Show - S01E01.mkv")])
    step = report_next_step(pending)
    assert "IS the approval" in step
    assert "confirm move new downloads scan" in step


def test_report_search_filters_items_case_and_punctuation_insensitive() -> None:
    scan = _scan(items=[
        _item("i1", "/dl/Alpha.Show.S01.1080p/Alpha.Show.S01E01.mkv", "/series/Alpha Show/Season 01/Alpha Show - S01E01.mkv"),
        _item("i2", "/dl/Alpha.Show.S01.1080p/Alpha.Show.S01E02.mkv", "/series/Alpha Show/Season 01/Alpha Show - S01E02.mkv"),
        _item("i3", "/dl/Other Thing - 05.mkv", "/series/Other Thing/Season 01/Other Thing - S01E05.mkv"),
    ])
    report = format_scan_report(scan, search="alpha show s01")
    ids = {it["confirmId"] for it in report["items"]}
    assert ids == {"i1", "i2"}
    assert report["summary"]["matched"] == 2

    # glued spelling still matches dotted/spaced names
    assert {it["confirmId"] for it in format_scan_report(scan, search="AlphaShow")["items"]} == {"i1", "i2"}

    empty = format_scan_report(scan, search="nonexistent")
    assert empty["items"] == []
    assert "search_hint" in empty

    assert len(format_scan_report(scan)["items"]) == 3


def test_progress_wait_seconds_is_clamped() -> None:
    assert _progress_wait_seconds({}) == 30
    assert _progress_wait_seconds({"waitSeconds": 0}) == 0
    assert _progress_wait_seconds({"waitSeconds": -5}) == 0
    assert _progress_wait_seconds({"waitSeconds": 999}) == MCP_PROGRESS_MAX_WAIT_SECONDS
    assert _progress_wait_seconds({"waitSeconds": "junk"}) == 30


def test_wait_while_running_returns_early_when_done() -> None:
    scan = _scan(status="running")
    calls = {"n": 0}

    def get_scan():
        calls["n"] += 1
        if calls["n"] >= 3:
            scan.status = "completed"
        return scan

    start = time.monotonic()
    result = asyncio.run(_wait_while_running(get_scan, lambda s: s.status == "running", 10, interval=0.01))
    assert result.status == "completed"
    assert time.monotonic() - start < 2


def test_wait_while_running_times_out_and_returns_running_scan() -> None:
    scan = _scan(status="running")
    start = time.monotonic()
    result = asyncio.run(_wait_while_running(lambda: scan, lambda s: s.status == "running", 0.05, interval=0.01))
    assert result.status == "running"
    assert time.monotonic() - start < 1


def test_wait_zero_does_not_sleep() -> None:
    scan = _scan(status="running")
    result = asyncio.run(_wait_while_running(lambda: scan, lambda s: s.status == "running", 0))
    assert result is scan
