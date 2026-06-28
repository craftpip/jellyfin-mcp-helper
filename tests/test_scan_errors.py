from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.main import _format_scan_progress, _format_scan_report
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
                    path="/data/torrents/Corrupted-Show/Show Season 01",
                    error="[Errno 5] Input/output error",
                )
            ],
        ),
    )

    async def run_scan():
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        return scan

    scan = asyncio.run(run_scan())
    report = _format_scan_report(scan)

    assert "Filesystem" in scan.service_errors
    assert "/data/torrents/Corrupted-Show/Show Season 01" in scan.service_errors["Filesystem"]
    assert len(scan.items) == 1
    assert scan.items[0].source_path == "/data/torrents/Corrupted-Show/Show Season 01"
    assert scan.items[0].error == "[Errno 5] Input/output error"
    assert "/data/torrents/Corrupted-Show/Show Season 01" in report["report_md"]
    assert "[Errno 5] Input/output error" in report["report_md"]
    assert "check skipped items" in report["next"]


def test_create_scan_skips_zero_byte_media_files(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    zero_file = root / "Rick and Morty S09E01.mkv"
    zero_file.write_bytes(b"")
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    async def fake_load_in_progress_paths() -> list[str]:
        return []

    monkeypatch.setattr(manager, "_load_in_progress_paths", fake_load_in_progress_paths)

    async def run_scan():
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        return scan

    scan = asyncio.run(run_scan())

    assert scan.counts.skipped == 1
    assert scan.counts.total == 0
    assert scan.items[0].source_path == str(zero_file)
    assert scan.items[0].reason == "Zero-byte file; download is incomplete or invalid"


def test_create_scan_returns_running_immediately(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)
    def fake_run_scan(scan_id, request) -> None:
        return None

    monkeypatch.setattr(manager, "_run_scan_sync", fake_run_scan)

    async def run_test():
        scan = await manager.create_scan(ScanRequest())
        assert scan.status == "running"
        assert scan.started_at is not None
        while scan.status == "running":
            await asyncio.sleep(0)
        return scan

    scan = asyncio.run(run_test())
    assert scan.status == "completed"


def test_create_scan_rejects_second_running_scan(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    def fake_run_scan(scan_id, request) -> None:
        return None

    monkeypatch.setattr(manager, "_run_scan_sync", fake_run_scan)

    async def run_test():
        scan = await manager.create_scan(ScanRequest())
        try:
            await manager.create_scan(ScanRequest())
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
        else:
            raise AssertionError("Expected duplicate running scan to be rejected")
        while scan.status == "running":
            await asyncio.sleep(0)

    asyncio.run(run_test())


def test_progress_and_report_while_scan_running(tmp_path) -> None:
    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )
    scan = asyncio.run(manager.create_scan(ScanRequest()))
    scan.status = "running"
    scan.total_candidates = 10
    scan.processed_candidates = 5
    scan.current_candidate_index = 6
    scan.current_candidate = "/data/torrents/Show/S01E06.mkv"

    progress = _format_scan_progress(scan)
    report = _format_scan_report(scan)

    assert progress["status"] == "running"
    assert progress["processed"] == 5
    assert progress["total"] == 10
    assert progress["current_file"] == "/data/torrents/Show/S01E06.mkv"
    assert "progress" in report
    assert "still running" in report["next"]


def test_confirm_rejects_running_scan(tmp_path) -> None:
    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test():
        scan = await manager.create_scan(ScanRequest())
        try:
            await manager.confirm_scan(scan.scan_id)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 400
            assert "still running" in str(getattr(exc, "detail", ""))
        else:
            raise AssertionError("Expected running scan confirmation to be rejected")
        scan.status = "completed"
        while scan.status == "running":
            await asyncio.sleep(0)

    asyncio.run(run_test())
