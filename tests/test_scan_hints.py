from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.main import _mcp_tools, _parse_sort_hints
from app.models.schemas import ScanRequest, SortHint
from app.services.scan_manager import ScanManager


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            downloadRoots=[str(tmp_path / "downloads")],
            movieRoots={"m": str(tmp_path / "movies")},
            seriesRoots={"s": str(tmp_path / "series")},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )


def _write(folder: Path, names: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x" * 1024)
    return folder


def _run_scan(manager: ScanManager, request: ScanRequest):
    async def run():
        scan = await manager.create_scan(request)
        while scan.status == "running":
            await asyncio.sleep(0)
        return scan

    return asyncio.run(run())


def test_strict_hint_overrides_kind_and_title(tmp_path) -> None:
    """A file guessit reads as series (SxxEyy) becomes a movie under a strict hint."""
    folder = _write(
        tmp_path / "downloads" / "harbor.lights.s01.1080p.pack",
        ["Harbor.Lights.S01E01.1080p.mkv"],
    )
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(sourcePrefix=folder.name, title="Stone Harbor", kind="movie", year=2021)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert scan.hints and scan.hints[0].title == "Stone Harbor"
    assert len(scan.items) == 1
    item = scan.items[0]
    assert item.item_type == "movie"
    assert "hint" in item.reason
    assert "Stone Harbor" in (item.target_path or "")
    assert item.source_folder == folder.name


def test_hint_preserves_filename_episode_parsing(tmp_path) -> None:
    folder = _write(
        tmp_path / "downloads" / "north.beacon.s01.pack",
        ["North.Beacon.S01E01.mkv", "North.Beacon.S01E02.mkv", "North.Beacon.S01E03.mkv"],
    )
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(source_prefix=folder.name, title="North Beacon", kind="series", season=1)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert len(scan.items) == 3
    tags = set()
    for item in scan.items:
        assert item.item_type == "series"
        assert "hint" in item.reason
        assert "North Beacon" in (item.target_path or "")
        assert item.source_folder == folder.name
        for tag in ("S01E01", "S01E02", "S01E03"):
            if tag in item.target_path:
                tags.add(tag)
    assert tags == {"S01E01", "S01E02", "S01E03"}


def test_new_episode_without_previous_episode_is_not_suspect(tmp_path) -> None:
    source = _write(
        tmp_path / "downloads" / "coral.beacon",
        ["Coral.Beacon.2026.S01E08.1080p.WEB.mkv"],
    )
    season = tmp_path / "series" / "Coral Beacon (2026)" / "Season 01"
    season.mkdir(parents=True)
    manager = ScanManager(_make_config(tmp_path))

    scan = _run_scan(manager, ScanRequest())

    item = next(item for item in scan.items if item.source_path.startswith(str(source)))
    assert item.item_type == "series"
    assert item.suspect is False
    assert "episode_gap" not in item.flags


def test_hint_season_mismatch_flags_suspect(tmp_path) -> None:
    folder = _write(
        tmp_path / "downloads" / "north.beacon.s01.pack",
        ["North.Beacon.S02E01.mkv"],
    )
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(sourcePrefix=folder.name, title="North Beacon", kind="series", season=1)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert len(scan.items) == 1
    item = scan.items[0]
    assert item.item_type == "series"
    assert item.suspect is True
    assert "hint-season-mismatch" in item.flags
    # The file's own tag still drives numbering.
    assert "S02E01" in (item.target_path or "")


def test_additive_unhinted_folder_classifies_as_before(tmp_path) -> None:
    hinted = _write(
        tmp_path / "downloads" / "north.beacon.s01.pack",
        ["North.Beacon.S01E01.mkv"],
    )
    plain = _write(
        tmp_path / "downloads" / "lone.pine.s01.pack",
        ["Lone.Pine.S01E01.1080p.mkv"],
    )

    def config_with(report_dir: Path) -> AppConfig:
        base = _make_config(tmp_path)
        base.report_dir = report_dir
        return base

    control_dir = tmp_path / "control"
    control_dir.mkdir()
    control = _run_scan(ScanManager(config_with(control_dir)), ScanRequest())
    hinted_dir = tmp_path / "hinted"
    hinted_dir.mkdir()
    hint = SortHint(sourcePrefix=hinted.name, title="North Beacon", kind="series", season=1)
    with_hints = _run_scan(ScanManager(config_with(hinted_dir)), ScanRequest(hints=[hint]))

    assert control.status == "completed" and with_hints.status == "completed"
    control_item = next(i for i in control.items if plain.name in i.source_path)
    hinted_item = next(i for i in with_hints.items if plain.name in i.source_path)
    assert hinted_item.item_type == control_item.item_type
    assert hinted_item.reason == control_item.reason
    assert hinted_item.target_path == control_item.target_path
    # The hinted folder itself followed the hint.
    beacon_item = next(i for i in with_hints.items if hinted.name in i.source_path)
    assert "hint" in beacon_item.reason


def test_mcp_scan_tool_accepts_hints_and_hint_scope() -> None:
    tools = _mcp_tools()
    tool = next(t for t in tools if t["name"] == "downloads_scan_start")
    props = tool["inputSchema"]["properties"]
    assert "hints" in props
    assert props["hintScope"]["enum"] == ["additive", "only"]
    item_props = props["hints"]["items"]["properties"]
    for key in ("sourcePrefix", "title", "kind"):
        assert key in item_props

    hints = _parse_sort_hints([
        {"sourcePrefix": "north.beacon.s01.pack", "title": "North Beacon", "kind": "series", "season": 1},
    ])
    request = ScanRequest(hints=hints, hintScope="additive")
    assert request.hints[0].source_prefix == "north.beacon.s01.pack"
    assert request.hints[0].strict is True
    assert request.hint_scope == "additive"


def test_hint_scope_only_is_rejected(tmp_path) -> None:
    manager = ScanManager(_make_config(tmp_path))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(manager.create_scan(ScanRequest(hintScope="only")))
    assert exc.value.status_code == 400
