from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.main import _format_confirm_progress, _format_scan_progress, _format_scan_report
from app.models.schemas import ScanPlan, ScanRequest, ScannedItem
from app.services.scan_history import load_report
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
    zero_file = root / "Zero Byte Show S09E01.mkv"
    zero_file.write_bytes(b"")
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

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


def test_create_scan_skips_incomplete_download_by_marker(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    partial_file = root / "Show.S01E01.mkv.!qB"
    partial_file.write_bytes(b"partial")
    real_file = root / "Show.S01E01.mkv"
    real_file.write_bytes(b"video")
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    async def run_scan():
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        return scan

    scan = asyncio.run(run_scan())

    assert scan.counts.skipped == 1
    assert scan.counts.total == 0
    assert scan.items[0].source_path == str(real_file)
    assert scan.items[0].reason == "In-progress download"


def test_create_scan_skips_none_incomplete_when_toggle_off(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    partial_file = root / "Show.S01E01.mkv.!qB"
    partial_file.write_bytes(b"partial")
    real_file = root / "Show.S01E01.mkv"
    real_file.write_bytes(b"video")
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)]),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)
    from app.services import scan_orchestrator
    monkeypatch.setattr(scan_orchestrator, "_incomplete_detection_enabled", lambda: False)

    async def run_scan():
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        return scan

    scan = asyncio.run(run_scan())

    assert scan.counts.skipped == 0
    assert len(scan.items) == 1


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


def test_create_scan_cancels_previous_running_scan(tmp_path, monkeypatch) -> None:
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
        first_scan = await manager.create_scan(ScanRequest(replaceExisting=False))
        second_scan = await manager.create_scan(ScanRequest(replaceExisting=False))
        assert first_scan.status == "cancelled"
        while second_scan.status == "running":
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


def test_format_confirm_progress_includes_phase_and_transfer_metrics(tmp_path) -> None:
    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )
    scan = asyncio.run(manager.create_scan(ScanRequest()))
    scan.status = "completed"
    scan.confirm_status = "running"
    scan.confirm_phase = "moving"
    scan.confirm_started_at = datetime.now(UTC) - timedelta(seconds=10)
    scan.confirm_total = 4
    scan.confirm_processed = 1
    scan.counts.moved = 1
    scan.confirm_current_item = "/downloads/show.mkv"
    scan.confirm_current_target = "/media/show.mkv"
    scan.confirm_current_size_bytes = 1000
    scan.confirm_current_copied_bytes = 250
    scan.confirm_current_speed_bytes = 50.0
    scan.confirm_current_percent = 25.0
    scan.confirm_cross_drive = True
    scan.confirm_note = "Copying file to target drive."
    scan.confirm_last_update_at = datetime.now(UTC)

    progress = _format_confirm_progress(scan)

    assert progress["status"] == "running"
    assert progress["phase"] == "moving"
    assert progress["processed"] == 1
    assert progress["total"] == 4
    assert progress["counts"]["moved"] == 1
    assert progress["counts"]["replaced"] == 0
    assert progress["counts"]["failed"] == 0
    assert progress["current_file"] == "/downloads/show.mkv"
    assert progress["current_target"] == "/media/show.mkv"
    assert progress["current_size_bytes"] == 1000
    assert progress["current_copied_bytes"] == 250
    assert progress["current_percent"] == 25.0
    assert progress["current_speed"] == "50 B/s"
    assert progress["current_eta"] == "15s"
    assert progress["cross_drive"] is True
    assert progress["note"] == "Copying file to target drive."


def test_copy_file_with_progress_updates_scan_metrics(tmp_path) -> None:
    source = tmp_path / "source.mkv"
    source.write_bytes(b"x" * 1024)
    target = tmp_path / "target.mkv"

    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )
    scan = ScanPlan(
        scan_id="scan-1",
        status="completed",
        operation="organize",
        items=[],
        created_at=datetime.now(UTC),
    )

    asyncio.run(manager._copy_file_with_progress(scan, source, target, source.stat().st_size))

    assert target.read_bytes() == b"x" * 1024
    assert scan.confirm_phase == "moving"
    assert scan.confirm_current_copied_bytes == 1024
    assert scan.confirm_current_percent == 100.0
    assert scan.confirm_current_speed_bytes is not None
    assert scan.confirm_note == "Copying file to target drive."


def test_confirm_uses_tracked_copy_for_cross_drive_file(tmp_path, monkeypatch) -> None:
    source = tmp_path / "download.mkv"
    source.write_bytes(b"video-bytes")
    target_dir = tmp_path / "library"
    target = target_dir / "download.mkv"

    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test() -> None:
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(source),
                name=source.name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(target),
                action="move",
            )
        ]
        scan.counts.movies = 1

        async def fake_trigger_jellyfin(updated_paths) -> None:
            return None

        real_path_stat = Path.stat
        copied = {"called": False, "target": None}

        class FakeStat:
            def __init__(self, real_stat, st_dev=None):
                self._real_stat = real_stat
                self.st_dev = real_stat.st_dev if st_dev is None else st_dev

            def __getattr__(self, name):
                return getattr(self._real_stat, name)

        def fake_path_stat(path_obj, *args, **kwargs):
            stat_result = real_path_stat(path_obj, *args, **kwargs)
            if path_obj == target_dir:
                return FakeStat(stat_result, st_dev=stat_result.st_dev + 1)
            return stat_result

        def fake_copy(scan_obj, source_path, target_path, source_size):
            copied["called"] = True
            copied["target"] = target_path
            target_path.write_bytes(source_path.read_bytes())
            manager._update_confirm_state(
                scan_obj,
                confirm_phase="moving",
                confirm_current_copied_bytes=source_size,
                confirm_current_speed_bytes=1024.0,
                confirm_current_percent=100.0,
                confirm_note="Copying file to target drive.",
            )

        async def fake_async_copy(scan_obj, source_path, target_path, source_size):
            fake_copy(scan_obj, source_path, target_path, source_size)

        monkeypatch.setattr(manager, "_trigger_jellyfin_scans", fake_trigger_jellyfin)
        monkeypatch.setattr(manager, "_copy_file_with_progress", fake_async_copy)
        monkeypatch.setattr("pathlib.Path.stat", fake_path_stat)

        await manager.confirm_scan(scan.scan_id)
        while scan.confirm_status == "running":
            await asyncio.sleep(0)

        assert copied["called"] is True
        assert copied["target"].name.startswith(".jellysort-")
        assert ".partial" in copied["target"].name
        assert copied["target"].exists() is False
        assert source.exists() is False
        assert target.read_bytes() == b"video-bytes"
        assert scan.confirm_status == "completed"
        assert scan.confirm_phase == "completed"
        assert scan.confirm_cross_drive is True
        assert scan.counts.moved == 1

    asyncio.run(run_test())


def test_cross_drive_replace_preserves_existing_target_when_copy_fails(tmp_path, monkeypatch) -> None:
    source = tmp_path / "download.mkv"
    source.write_bytes(b"new-video")
    target_dir = tmp_path / "library"
    target_dir.mkdir()
    target = target_dir / "download.mkv"
    target.write_bytes(b"old-video")
    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )
    scan = ScanPlan(
        scan_id="scan",
        status="completed",
        operation="organize",
        created_at=datetime.now(UTC),
    )
    item = ScannedItem(
        confirmId="i1",
        sourcePath=str(source),
        name=source.name,
        item_type="movie",
        confidence=1.0,
        reason="test",
        target_path=str(target),
        action="replace",
    )
    real_path_stat = Path.stat

    class FakeStat:
        def __init__(self, real_stat, st_dev=None):
            self._real_stat = real_stat
            self.st_dev = real_stat.st_dev if st_dev is None else st_dev

        def __getattr__(self, name):
            return getattr(self._real_stat, name)

    def fake_path_stat(path_obj, *args, **kwargs):
        stat_result = real_path_stat(path_obj, *args, **kwargs)
        if path_obj == target_dir:
            return FakeStat(stat_result, st_dev=stat_result.st_dev + 1)
        return stat_result

    def fail_copy(*args, **kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr("pathlib.Path.stat", fake_path_stat)
    monkeypatch.setattr(manager, "_copy_file_with_progress", fail_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        asyncio.run(manager._apply_item(scan, item))

    assert source.read_bytes() == b"new-video"
    assert target.read_bytes() == b"old-video"



async def _wait_for_history(scan_id: str, report_dir, expect=None):
    """Poll for the async history write; returns report dict or None."""
    for _ in range(200):
        saved = load_report(scan_id, report_dir=report_dir)
        if saved is not None and (expect is None or saved.get("summary", {}).get(expect[0]) == expect[1]):
            return saved
        await asyncio.sleep(0.01)
    return load_report(scan_id, report_dir=report_dir)


def test_confirm_queues_batch_behind_running_move(tmp_path, monkeypatch) -> None:
    sources = []
    targets = []
    for i in range(1, 4):
        src = tmp_path / f"download-{i}.mkv"
        src.write_bytes(f"video-{i}".encode())
        sources.append(src)
        targets.append(tmp_path / "library" / f"download-{i}.mkv")
    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test() -> None:
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        scan.items = [
            ScannedItem(
                confirmId=f"c{i}",
                sourcePath=str(sources[i - 1]),
                name=sources[i - 1].name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(targets[i - 1]),
                action="move",
            )
            for i in range(1, 4)
        ]
        scan.counts.movies = 3

        async def fake_trigger_jellyfin(updated_paths) -> None:
            return None

        monkeypatch.setattr(manager, "_trigger_jellyfin_scans", fake_trigger_jellyfin)

        # First confirm: only c1. This batch starts immediately.
        await manager.confirm_scan(scan.scan_id, item_ids=["c1"])
        assert scan.confirm_status == "running"

        # A second confirm while the first is still running must be queued, not rejected.
        queued = await manager.confirm_scan(scan.scan_id, item_ids=["c2", "c3"])
        assert queued.confirm_queue_length == 1
        assert queued.confirm_queue_items == 2

        # Wait for both batches to run to completion (the queued one starts automatically).
        while scan.confirm_status == "running":
            await asyncio.sleep(0)

        assert scan.confirm_status == "completed"
        assert scan.confirm_queue_length == 0
        assert scan.counts.moved == 3
        assert all(item.confirmed for item in scan.items)
        assert all(target.exists() for target in targets)

        # History must reflect post-confirm counts (report re-persisted).
        saved = await _wait_for_history(scan.scan_id, tmp_path, expect=("moved", 3))
        assert saved is not None
        assert saved["summary"]["moved"] == 3

    asyncio.run(run_test())


def test_confirm_repersists_history_with_post_confirm_counts(tmp_path, monkeypatch) -> None:
    source = tmp_path / "download.mkv"
    source.write_bytes(b"video")
    target = tmp_path / "library" / "download.mkv"

    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test() -> None:
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(source),
                name=source.name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(target),
                action="move",
            )
        ]
        scan.counts.movies = 1

        async def fake_trigger_jellyfin(updated_paths) -> None:
            return None

        monkeypatch.setattr(manager, "_trigger_jellyfin_scans", fake_trigger_jellyfin)

        # Snapshot before confirm: the completion-time report has moved=0.
        pre = await _wait_for_history(scan.scan_id, tmp_path)
        assert pre is not None
        assert pre["summary"]["moved"] == 0

        await manager.confirm_scan(scan.scan_id, item_ids=["c1"])
        while scan.confirm_status == "running":
            await asyncio.sleep(0)

        assert scan.confirm_status == "completed"
        assert scan.counts.moved == 1
        assert target.exists()

        saved = await _wait_for_history(scan.scan_id, tmp_path, expect=("moved", 1))
        assert saved is not None
        assert saved["summary"]["moved"] == 1

    asyncio.run(run_test())


def test_delete_items_removes_source_and_updates_counts(tmp_path, monkeypatch) -> None:
    source = tmp_path / "downloads" / "Unwanted.Movie.2026.mkv"
    source.parent.mkdir(parents=True)

    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(
                downloadRoots=[str(tmp_path / "downloads")],
                movieRoots={"default": str(tmp_path / "movies")},
            ),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test() -> None:
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        source.write_bytes(b"video-bytes")
        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(source),
                name=source.name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(tmp_path / "movies" / "Unwanted.Movie.2026.mkv"),
                action="move",
            )
        ]
        scan.counts.movies = 1

        updated = await manager.delete_items(scan.scan_id, ["c1"])

        assert source.exists() is False
        item = updated.items[0]
        assert item.action == "skip"
        assert item.confirmed is True
        assert item.reason == "Source file deleted by user"
        assert item.target_path == ""
        assert updated.counts.movies == 0
        assert updated.counts.skipped == 1

        report = _format_scan_report(updated)
        assert all(i["action"] != "move" for i in report["items"])
        assert report["summary"]["action_required"] == 0

    asyncio.run(run_test())


def test_delete_items_rejects_running_scan_and_unknown_ids(tmp_path, monkeypatch) -> None:
    source = tmp_path / "downloads" / "Keep.Movie.2026.mkv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video-bytes")

    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(downloadRoots=[str(tmp_path / "downloads")]),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test() -> None:
        scan = await manager.create_scan(ScanRequest())
        try:
            await manager.delete_items(scan.scan_id, ["c1"])
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 400
            assert "still running" in str(getattr(exc, "detail", ""))
        else:
            raise AssertionError("Expected delete while running to be rejected")
        while scan.status == "running":
            await asyncio.sleep(0)

        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(source),
                name=source.name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(tmp_path / "movies" / source.name),
                action="move",
            )
        ]

        try:
            await manager.delete_items(scan.scan_id, ["nope"])
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 400
            assert "No matching" in str(getattr(exc, "detail", ""))
        else:
            raise AssertionError("Expected unknown itemIds to be rejected")

        assert source.exists() is True

    asyncio.run(run_test())


def test_delete_items_allows_already_skipped_items(tmp_path, monkeypatch) -> None:
    source = tmp_path / "downloads" / "In.Progress.Download.mkv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"partial-bytes")

    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(
                downloadRoots=[str(tmp_path / "downloads")],
                movieRoots={"default": str(tmp_path / "movies")},
            ),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )

    async def run_test() -> None:
        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        scan.items = [
            ScannedItem(
                confirmId="s1",
                sourcePath=str(source),
                name=source.name,
                item_type="skip",
                confidence=1.0,
                reason="In-progress download",
                target_path="",
                action="skip",
            )
        ]
        scan.counts.skipped = 1

        report_before = _format_scan_report(scan)
        assert any(i["confirmId"] == "s1" and i["action"] == "skip" for i in report_before["items"])

        updated = await manager.delete_items(scan.scan_id, ["s1"])

        assert source.exists() is False
        item = updated.items[0]
        assert item.action == "skip"
        assert item.confirmed is True
        assert item.reason == "Source file deleted by user"
        assert updated.counts.movies == 0
        assert updated.counts.series == 0
        assert updated.counts.skipped == 1

        report = _format_scan_report(updated)
        assert all(i["confirmId"] != "s1" for i in report["items"])

    asyncio.run(run_test())



def test_update_scan_rejects_target_path_traversal(tmp_path) -> None:
    movie_root = tmp_path / "movies"
    manager = ScanManager(
        AppConfig(
            paths=PathsConfig(movieRoots={"default": str(movie_root)}),
            model=ModelConfig(),
            log_dir=tmp_path,
            report_dir=tmp_path,
        )
    )
    now = datetime.now(UTC)
    scan = ScanPlan(scan_id="scan", status="completed", operation="organize", created_at=now)
    scan.items = [
        ScannedItem(
            confirmId="i1",
            sourcePath=str(tmp_path / "download.mkv"),
            name="download.mkv",
            item_type="movie",
            confidence=1.0,
            reason="test",
            target_path=str(movie_root / "Movie" / "Movie.mkv"),
            action="move",
        )
    ]
    manager._current_scan = scan

    with pytest.raises(Exception, match="not under any configured"):
        manager.update_scan("scan", [{"confirmId": "i1", "targetPath": str(movie_root / ".." / "outside.mkv")}])


def test_incremental_scan_preserves_edits_and_adds_new(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    f1 = root / "Movie.A.2020.1080p.mkv"
    f1.write_bytes(b"x" * 1024)
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)], movieRoots={"m": str(tmp_path / "movies")}, seriesRoots={"s": str(tmp_path / "series")}),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    async def run():
        s1 = await manager.create_scan(ScanRequest())
        while s1.status == "running":
            await asyncio.sleep(0)
        # Edit target of first item
        assert len(s1.items) >= 1
        s1.items[0].target_path = str(tmp_path / "movies" / "Custom" / "Movie.A.mkv")
        # Add new file
        f2 = root / "Movie.B.2021.1080p.mkv"
        f2.write_bytes(b"y" * 1024)
        s2 = await manager.create_scan(ScanRequest(fullRescan=False))
        while s2.status == "running":
            await asyncio.sleep(0)
        return s1, s2

    s1, s2 = asyncio.run(run())
    # Incremental should keep edited target and have both files
    first = next(i for i in s2.items if "Movie.A" in i.source_path)
    assert "Custom" in first.target_path
    assert any("Movie.B" in i.source_path for i in s2.items)
    assert len(s2.items) == len(s1.items) + 1


def test_full_rescan_overwrites_and_discards_edits(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    f1 = root / "Movie.A.2020.1080p.mkv"
    f1.write_bytes(b"x" * 1024)
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)], movieRoots={"m": str(tmp_path / "movies")}, seriesRoots={"s": str(tmp_path / "series")}),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    async def run():
        s1 = await manager.create_scan(ScanRequest())
        while s1.status == "running":
            await asyncio.sleep(0)
        s1.items[0].target_path = str(tmp_path / "movies" / "Custom" / "Movie.A.mkv")
        s2 = await manager.create_scan(ScanRequest(fullRescan=True))
        while s2.status == "running":
            await asyncio.sleep(0)
        return s1, s2

    s1, s2 = asyncio.run(run())
    first = next(i for i in s2.items if "Movie.A" in i.source_path)
    assert "Custom" not in first.target_path


def test_report_json_grouped_by_source_folder(tmp_path) -> None:
    scan = ScanPlan(
        scan_id="scan-json",
        status="completed",
        operation="organize",
        items=[
            ScannedItem(confirmId="i1", sourcePath="/dl/Show.S01/E01.mkv", name="E01.mkv", item_type="series", confidence=1.0, reason="test", target_path="/series/Show/Season 01/Show - S01E01.mkv", action="move", file_size=100, container_path="/dl/Show.S01", source_folder="Show.S01"),
            ScannedItem(confirmId="i2", sourcePath="/dl/Show.S01/E02.mkv", name="E02.mkv", item_type="series", confidence=1.0, reason="test", target_path="/series/Show/Season 01/Show - S01E02.mkv", action="move", file_size=100, container_path="/dl/Show.S01", source_folder="Show.S01"),
            ScannedItem(confirmId="i3", sourcePath="/dl/Movie.2024/Movie.mkv", name="Movie.mkv", item_type="movie", confidence=1.0, reason="test", target_path="/movies/Movie (2024)/Movie.mkv", action="move", file_size=200, container_path="/dl/Movie.2024", source_folder="Movie.2024"),
        ],
        counts=__import__("app.models.schemas", fromlist=["ScanCounts"]).ScanCounts(total=3, movies=1, series=2),
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    md = _format_scan_report(scan, format="markdown")
    js = _format_scan_report(scan, format="json", group_by="sourceFolder")
    assert "report_md" in md and "groups" not in md
    assert "groups" in js and "report_md" not in js
    assert len(js["groups"]) == 2
    show_group = next(g for g in js["groups"] if g["sourceFolder"] == "Show.S01")
    assert show_group["count"] == 2 and show_group["totalSize"] == 200
    assert len(show_group["items"]) == 2


def test_singleton_persists_across_manager_restart(tmp_path, monkeypatch) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    f1 = root / "Show.S01E01.mkv"
    f1.write_bytes(b"x" * 1024)
    config = AppConfig(
        paths=PathsConfig(downloadRoots=[str(root)], movieRoots={"m": str(tmp_path / "movies")}, seriesRoots={"s": str(tmp_path / "series")}),
        model=ModelConfig(),
        log_dir=tmp_path,
        report_dir=tmp_path,
    )
    manager = ScanManager(config)

    async def run_first():
        s = await manager.create_scan(ScanRequest())
        while s.status == "running":
            await asyncio.sleep(0.05)
        # Wait for singleton save (background task after status->completed)
        from app.services.scan_history import singleton_path

        for _ in range(20):
            if singleton_path(tmp_path).exists():
                break
            await asyncio.sleep(0.05)
        return s

    s1 = asyncio.run(run_first())
    from app.services.scan_history import singleton_path, load_singleton

    # Fallback if background task was cancelled on loop close (asyncio.run edge)
    if not singleton_path(tmp_path).exists():
        from app.services.scan_history import save_singleton

        save_singleton(s1, tmp_path)
    assert singleton_path(tmp_path).exists()
    loaded = load_singleton(tmp_path)
    assert loaded is not None and len(loaded.items) == len(s1.items)
    # New manager should restore it
    manager2 = ScanManager(config)
    assert manager2.get_current_scan() is not None
    assert len(manager2.get_current_scan().items) == len(s1.items)


def test_confirm_persists_singleton_with_confirmed_flags(tmp_path, monkeypatch) -> None:
    """Regression: a confirm must persist current.json.

    Restart recovery loads the singleton; without a post-confirm save it
    resurrects already-moved items as actionable, so a re-confirm fails with
    ENOENT on the gone source and writes a spurious "failed" history group
    even though the file is already at its target.
    """
    source = tmp_path / "download.mkv"
    source.write_bytes(b"video-bytes")
    target = tmp_path / "library" / "download.mkv"

    recorded: dict = {}

    def fake_history(scan_id, group_title, group_key, items, confirmed_by=None):
        recorded["items"] = items
        return {"history_id": "h_test"}

    monkeypatch.setattr("app.services.history_store.append_history_group", fake_history)

    def make_manager() -> ScanManager:
        return ScanManager(
            AppConfig(
                paths=PathsConfig(downloadRoots=[]),
                model=ModelConfig(),
                log_dir=tmp_path,
                report_dir=tmp_path,
            )
        )

    manager = make_manager()

    async def run_test():
        from app.services.scan_history import load_singleton

        scan = await manager.create_scan(ScanRequest())
        while scan.status == "running":
            await asyncio.sleep(0)
        # Wait for the scan-completion singleton write to land first so it
        # cannot overwrite the post-confirm state afterwards.
        for _ in range(200):
            singleton = load_singleton(tmp_path)
            if singleton is not None and singleton.scan_id == scan.scan_id:
                break
            await asyncio.sleep(0.01)
        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(source),
                name=source.name,
                item_type="movie",
                confidence=1.0,
                reason="test",
                target_path=str(target),
                action="move",
                crossDrive=True,
            )
        ]
        scan.counts.movies = 1

        async def fake_trigger_jellyfin(updated_paths) -> None:
            return None

        monkeypatch.setattr(manager, "_trigger_jellyfin_scans", fake_trigger_jellyfin)

        await manager.confirm_scan(scan.scan_id, item_ids=["c1"])
        while scan.confirm_status == "running":
            await asyncio.sleep(0)
        assert scan.confirm_status == "completed"
        assert scan.counts.moved == 1
        assert target.exists()
        assert not source.exists()

        loaded = None
        for _ in range(200):
            loaded = load_singleton(tmp_path)
            if loaded is not None and loaded.items and loaded.items[0].confirmed and loaded.counts.moved == 1:
                break
            await asyncio.sleep(0.01)
        return loaded

    loaded = asyncio.run(run_test())
    assert loaded is not None and loaded.items and loaded.items[0].confirmed
    assert loaded.counts.moved == 1
    # Stored cross-drive flag survives the gone source in history metadata.
    assert recorded["items"][0]["crossDrive"] is True
    # A fresh manager restores the confirmed state (no resurrection).
    restored = make_manager().get_current_scan()
    assert restored is not None and restored.items and restored.items[0].confirmed


def test_reconfirm_already_moved_item_is_skipped_not_failed(tmp_path, monkeypatch) -> None:
    """Regression for the spurious failed history group: source gone but target
    present with the expected size must mark confirmed without failed counts
    and without writing a duplicate history group."""
    from fastapi import HTTPException

    target = tmp_path / "library" / "Show - S01E08.mkv"
    target.parent.mkdir(parents=True)
    payload = b"v" * 4096
    target.write_bytes(payload)
    missing_source = tmp_path / "downloads" / "Show.S01E08.mkv"

    calls: list = []

    def fake_history(scan_id, group_title, group_key, items, confirmed_by=None):
        calls.append(items)
        return {"history_id": "h_test"}

    monkeypatch.setattr("app.services.history_store.append_history_group", fake_history)

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
        while scan.status == "running":
            await asyncio.sleep(0)
        scan.items = [
            ScannedItem(
                confirmId="c1",
                sourcePath=str(missing_source),
                name=missing_source.name,
                item_type="series",
                confidence=1.0,
                reason="test",
                target_path=str(target),
                action="move",
                fileSize=len(payload),
            )
        ]

        async def fake_trigger_jellyfin(updated_paths) -> None:
            return None

        monkeypatch.setattr(manager, "_trigger_jellyfin_scans", fake_trigger_jellyfin)

        await manager.confirm_scan(scan.scan_id, item_ids=["c1"])
        while scan.confirm_status == "running":
            await asyncio.sleep(0)
        # A further confirm now has nothing to do (400, not another group).
        with pytest.raises(HTTPException):
            await manager.confirm_scan(scan.scan_id, item_ids=["c1"])
        return scan

    scan = asyncio.run(run_test())
    assert scan.confirm_status == "completed"
    assert scan.counts.failed == 0
    assert scan.counts.moved == 0
    assert scan.items[0].confirmed
    assert scan.items[0].error is None
    assert calls == []
