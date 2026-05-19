from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.main import _format_scan_report
from app.models.schemas import ScanRequest
from app.services.scan_manager import ScanManager
from app.services.scanner import ScanCandidatesResult, ScanPathError, scan_candidates


def test_scan_candidates_collects_filesystem_errors_and_continues(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    good_dir = root / "Good Show Season 01"
    bad_dir = root / "Broken Show"
    good_dir.mkdir(parents=True)
    bad_dir.mkdir(parents=True)
    good_file = good_dir / "Good Show - S01E01.mkv"
    good_file.write_bytes(b"video")

    real_walk = os.walk

    def fake_walk(top, *args, **kwargs):
        onerror = kwargs.get("onerror")
        if Path(top) == bad_dir:
            def broken_walk():
                if onerror:
                    onerror(OSError(5, "Input/output error", str(bad_dir / "episode-02")))
                yield from ()

            return broken_walk()
        return real_walk(top, *args, **kwargs)

    monkeypatch.setattr("app.services.scanner.os.walk", fake_walk)

    result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))

    assert [candidate.source_path for candidate in result.candidates] == [str(good_file)]
    assert len(result.errors) == 1
    assert result.errors[0].path == str(bad_dir / "episode-02")
    assert "Input/output error" in result.errors[0].error


def test_create_scan_returns_filesystem_errors_to_user(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    async def fake_load_in_progress_paths() -> list[str]:
        return []

    monkeypatch.setattr(manager, "_load_in_progress_paths", fake_load_in_progress_paths)
    monkeypatch.setattr(
        "app.services.scan_manager.scan_candidates",
        lambda _: ScanCandidatesResult(
            candidates=[],
            errors=[
                ScanPathError(
                    path="/media1/torrents/CORRUPTED-One-Piece/One Piece Season 14",
                    error="[Errno 5] Input/output error",
                )
            ],
        ),
    )

    scan = asyncio.run(manager.create_scan(ScanRequest()))
    report = _format_scan_report(scan)

    assert "Filesystem" in scan.service_errors
    assert "/media1/torrents/CORRUPTED-One-Piece/One Piece Season 14" in scan.service_errors["Filesystem"]
    assert len(scan.items) == 1
    assert scan.items[0].source_path == "/media1/torrents/CORRUPTED-One-Piece/One Piece Season 14"
    assert scan.items[0].error == "[Errno 5] Input/output error"
    assert report["skipped"][0]["source_path"] == "/media1/torrents/CORRUPTED-One-Piece/One Piece Season 14"
    assert report["skipped"][0]["error"] == "[Errno 5] Input/output error"
    assert "review skipped items for the exact paths" in report["next"]
