from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.models.schemas import ScanRequest, SortHint
from app.services.scan_manager import ScanManager
from app.services.scan_orchestrator import _extract_hint_bare_number


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


def _tag(target_path: str) -> str | None:
    match = re.search(r"S\d{2}E\d{2}", target_path or "")
    return match.group(0) if match else None


def test_hint_absolute_numbering_season_two(tmp_path) -> None:
    """Bare absolute numbers 13..24 with hint season 2 land on S02E01..E12."""
    names = [f"[RlsGrp] North Beacon - {n}.mkv" for n in range(13, 25)]
    folder = _write(tmp_path / "downloads" / "north.beacon.s02.pack", names)
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(sourcePrefix=folder.name, title="North Beacon", kind="series", season=2)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert len(scan.items) == 12
    tags = []
    for item in scan.items:
        assert item.item_type == "series"
        assert item.action in ("move", "replace"), item.reason
        assert "hint" in item.reason
        assert "hint-episode-ambiguous" not in item.flags
        tag = _tag(item.target_path)
        assert tag is not None
        tags.append(tag)
    assert sorted(tags) == [f"S02E{i:02d}" for i in range(1, 13)]
    # No two files collapsed onto the same target.
    assert len({i.target_path for i in scan.items}) == 12


def test_hint_sxxeyy_control_unchanged(tmp_path) -> None:
    """SxxEyy-tagged files under a hint keep their own numbering exactly."""
    names = [f"North.Beacon.S01E{i:02d}.mkv" for i in range(1, 4)]
    folder = _write(tmp_path / "downloads" / "north.beacon.s01.pack", names)
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(sourcePrefix=folder.name, title="North Beacon", kind="series", season=1)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert len(scan.items) == 3
    tags = sorted(_tag(i.target_path) or "" for i in scan.items)
    assert tags == ["S01E01", "S01E02", "S01E03"]
    for item in scan.items:
        assert "hint" in item.reason
        assert "hint-episode-ambiguous" not in item.flags


def test_hint_codec_decimal_guard(tmp_path) -> None:
    """Codec decimals (Opus 2.0 / DDP2.0) never become episode numbers."""
    names = [
        "[RlsGrp] North Beacon - S01E01 Opus 2.0.mkv",
        "[RlsGrp] North Beacon - S01E02 DDP2.0.mkv",
    ]
    folder = _write(tmp_path / "downloads" / "north.beacon.s01.pack", names)
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(sourcePrefix=folder.name, title="North Beacon", kind="series", season=1)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert len(scan.items) == 2
    tags = sorted(_tag(i.target_path) or "" for i in scan.items)
    assert tags == ["S01E01", "S01E02"]
    for item in scan.items:
        assert item.action in ("move", "replace")
        assert "hint" in item.reason


def test_hint_ambiguous_absolute_kept_and_flagged(tmp_path) -> None:
    """Out-of-range conversion keeps the absolute number, flagged, never collapsed."""
    names = ["[RlsGrp] North Beacon - 01.mkv", "[RlsGrp] North Beacon - 02.mkv"]
    folder = _write(tmp_path / "downloads" / "north.beacon.s02.pack", names)
    manager = ScanManager(_make_config(tmp_path))
    hint = SortHint(sourcePrefix=folder.name, title="North Beacon", kind="series", season=2)
    scan = _run_scan(manager, ScanRequest(hints=[hint]))

    assert scan.status == "completed"
    assert len(scan.items) == 2
    tags = sorted(_tag(i.target_path) or "" for i in scan.items)
    assert tags == ["S02E01", "S02E02"]
    for item in scan.items:
        assert item.action in ("move", "replace")
        assert "hint" in item.reason
        assert item.suspect is True
        assert "hint-episode-ambiguous" in item.flags


def test_extract_hint_bare_number_unit() -> None:
    assert _extract_hint_bare_number("[RlsGrp] North Beacon - 13.mkv") == 13
    assert _extract_hint_bare_number("[RlsGrp] North Beacon - 24.mkv") == 24
    assert _extract_hint_bare_number("North.Beacon.S01E01 Opus 2.0.mkv") is None
    assert _extract_hint_bare_number("[RlsGrp] North Beacon - S01E02 DDP2.0.mkv") is None
    assert _extract_hint_bare_number("North.Beacon.1080p.mkv") is None
