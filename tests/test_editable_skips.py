"""Plan 17 — editable skips + Jellyfin-native `samples/` routing.

Only in-progress / source-missing / error rows stay locked (Delete-only).
Every other skip carries a proposed target and can be re-pointed via
Update Paths / Browse, promoting to move/replace on save.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.models.schemas import CandidateItem, ClassificationResult, ScannedItem, ScanPlan
from app.services.classifier import classify_candidate
from app.services.presenters import format_report_items
from app.services.resolver import PathResolver
from app.services.scan_manager import ScanManager


def _candidate(name: str, **kwargs) -> CandidateItem:
    return CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/downloads",
        source_path=f"/data/downloads/{name}",
        name=name,
        **kwargs,
    )


def _make_manager(tmp_path: Path) -> ScanManager:
    movies = tmp_path / "movies"
    series = tmp_path / "series"
    movies.mkdir(exist_ok=True)
    series.mkdir(exist_ok=True)
    logs = tmp_path / "logs"
    reports = tmp_path / "reports"
    logs.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    config = AppConfig(
        paths=PathsConfig(
            downloadRoots=["/data/downloads"],
            movieRoots={"movie_0": str(movies)},
            seriesRoots={"series_0": str(series)},
        ),
        model=ModelConfig(),
        log_dir=logs,
        report_dir=reports,
    )
    return ScanManager(config)


def _make_scan(manager: ScanManager, items: list[ScannedItem]) -> ScanPlan:
    scan = ScanPlan(scan_id="s1", status="completed", operation="organize", items=items, created_at=datetime.now(UTC))
    manager._scan_plans["s1"] = scan
    manager._current_scan = scan
    return scan


# --- classifier: marker vs size-only split ---


def test_sample_marker_routes_to_extra_sample() -> None:
    result = classify_candidate(_candidate("[Group] Show - sample.mkv"))
    assert result.kind == "extra"
    assert result.extra_type == "sample"


def test_size_only_small_movie_stays_editable_movie() -> None:
    result = classify_candidate(_candidate("Show Name.mkv", file_size=1024))
    assert result.kind == "movie"
    assert "sample-size suspect" in result.reason


# --- resolver: samples/ flat ---


def test_resolve_sample_series_extra_is_flat_in_samples(tmp_path: Path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (series_root / "Show Name").mkdir()
    config = AppConfig(
        paths=PathsConfig(
            downloadRoots=["/data/torrents"],
            movieRoots={"movie_0": str(tmp_path / "movies")},
            seriesRoots={"series_0": str(series_root)},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Name/extras/Nested/file-sample.mkv",
        name="file-sample.mkv",
        relative_path="Show Name/extras/Nested/file-sample.mkv",
    )
    classification = ClassificationResult(type="extra", title="Show Name", extra_type="sample")
    result = asyncio.run(resolver._resolve_extra(candidate, classification))
    assert result.target_dir == str(series_root / "Show Name" / "samples")
    assert result.target_path == str(series_root / "Show Name" / "samples" / "file-sample.mkv")


def test_resolve_sample_movie_extra_is_flat_in_samples(tmp_path: Path) -> None:
    movies_root = tmp_path / "movies"
    movies_root.mkdir()
    (tmp_path / "series").mkdir()
    config = AppConfig(
        paths=PathsConfig(
            downloadRoots=["/data/torrents"],
            movieRoots={"movie_0": str(movies_root)},
            seriesRoots={"series_0": str(tmp_path / "series")},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Movie (2020)/featurette/file-sample.mp4",
        name="file-sample.mp4",
        relative_path="Movie (2020)/featurette/file-sample.mp4",
    )
    classification = ClassificationResult(type="extra", title="Movie", year=2020, extra_type="sample")
    result = asyncio.run(resolver._resolve_extra(candidate, classification))
    assert result.target_path == str(movies_root / "Movie (2020)" / "samples" / "file-sample.mp4")


def test_resolve_fresh_sample_without_year_defaults_to_series(tmp_path: Path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (tmp_path / "movies").mkdir()
    config = AppConfig(
        paths=PathsConfig(
            downloadRoots=["/data/torrents"],
            movieRoots={"movie_0": str(tmp_path / "movies")},
            seriesRoots={"series_0": str(series_root)},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Fresh Show/Fresh Show - sample.mkv",
        name="Fresh Show - sample.mkv",
        relative_path="Fresh Show/Fresh Show - sample.mkv",
    )
    classification = ClassificationResult(type="extra", title="Fresh Show", extra_type="sample")
    result = asyncio.run(resolver._resolve_extra(candidate, classification))
    assert result.target_path == str(series_root / "Fresh Show" / "samples" / "Fresh Show - sample.mkv")


def test_resolve_non_sample_extra_still_uses_extras(tmp_path: Path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (series_root / "Show Name").mkdir()
    config = AppConfig(
        paths=PathsConfig(
            downloadRoots=["/data/torrents"],
            movieRoots={"movie_0": str(tmp_path / "movies")},
            seriesRoots={"series_0": str(series_root)},
        ),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Name/trailer.mkv",
        name="trailer.mkv",
        relative_path="Show Name/trailer.mkv",
    )
    classification = ClassificationResult(type="extra", title="Show Name", extra_type="special")
    result = asyncio.run(resolver._resolve_extra(candidate, classification))
    assert "/samples/" not in result.target_path
    assert result.target_path == str(series_root / "Show Name" / "extras" / "trailer.mkv")


# --- update_scan / retarget locked-guard ---


def _skip_item(**kwargs) -> ScannedItem:
    base = {
        "confirmId": "i1",
        "sourcePath": "/data/downloads/file.mkv",
        "name": "file.mkv",
        "item_type": "movie",
        "confidence": 0.5,
        "reason": "low confidence",
        "target_path": "",
        "action": "skip",
    }
    base.update(kwargs)
    return ScannedItem(**base)


def test_update_scan_allows_unlocked_skip_and_promotes_to_move(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    movies = tmp_path / "movies"
    target = str(movies / "Show Name (2020)" / "Show Name (2020).mkv")
    _make_scan(manager, [_skip_item(target_path=target, locked=False)])
    updated = manager.update_scan("s1", [{"confirmId": "i1", "targetPath": target}])
    item = updated.items[0]
    assert item.action == "move"
    assert item.target_path == target


def test_update_scan_rejects_locked_skip(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    movies = tmp_path / "movies"
    target = str(movies / "Show Name (2020)" / "Show Name (2020).mkv")
    _make_scan(manager, [_skip_item(target_path=target, locked=True, reason="In-progress download")])
    with pytest.raises(HTTPException) as exc_info:
        manager.update_scan("s1", [{"confirmId": "i1", "targetPath": target}])
    assert exc_info.value.status_code == 400


def test_retarget_unlocked_extra_skip_keeps_filename_flat(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    series = tmp_path / "series"
    show = series / "Show Name"
    show.mkdir()
    item = _skip_item(
        item_type="extra",
        target_path=str(series / "Show Name" / "samples" / "file-sample.mkv"),
        locked=False,
    )
    _make_scan(manager, [item])
    updated = manager.retarget_item("s1", "i1", str(show))
    assert updated.items[0].target_path == str(show / "file-sample.mkv")
    assert updated.items[0].action in ("move", "replace")


def test_retarget_locked_skip_rejected(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    _make_scan(manager, [_skip_item(locked=True, reason="In-progress download")])
    with pytest.raises(HTTPException) as exc_info:
        manager.retarget_item("s1", "i1", str(tmp_path / "series"))
    assert exc_info.value.status_code == 400


# --- presenters: skip passthrough ---


def test_skip_payload_carries_locked_target_and_candidates() -> None:
    item = _skip_item(
        target_path="/s/Show/samples/f.mkv",
        locked=False,
        candidate_targets=[],
    )
    out = format_report_items(
        ScanPlan(scan_id="s", status="completed", operation="organize", created_at=datetime.now(UTC)),
        {"move": [], "replace": [], "skip": [item]},
    )
    assert out[0]["locked"] is False
    assert out[0]["targetPath"] == "/s/Show/samples/f.mkv"
    assert out[0]["candidateTargets"] == []
