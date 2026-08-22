from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import AppConfig, ModelConfig, PathsConfig
from app.models.schemas import CandidateTarget, ScanCounts, ScanPlan, ScannedItem
from app.services.presenters import (
    format_confirm_progress,
    format_duration,
    format_path_exists,
    format_report_items,
    format_scan_progress,
    format_transfer_speed,
    report_llm_instructions,
    report_next_step,
)


def _scan_plan(**overrides) -> ScanPlan:
    defaults = dict(
        scan_id="test-scan",
        status="completed",
        operation="organize",
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return ScanPlan(**defaults)


def _movie_item(**overrides) -> ScannedItem:
    defaults = dict(
        confirmId="m1",
        sourcePath="/downloads/Movie.2024.mkv",
        name="Movie.2024.mkv",
        item_type="movie",
        confidence=0.9,
        reason="test",
        target_path="/movies/Movie (2024)/Movie (2024).mkv",
        action="move",
    )
    defaults.update(overrides)
    return ScannedItem(**defaults)


def _series_item(**overrides) -> ScannedItem:
    defaults = dict(
        confirmId="s1",
        sourcePath="/downloads/Show - S01E01.mkv",
        name="Show - S01E01.mkv",
        item_type="series",
        confidence=0.9,
        reason="test",
        target_path="/series/Show/Season 01/Show - S01E01.mkv",
        action="move",
    )
    defaults.update(overrides)
    return ScannedItem(**defaults)


def _skip_item(**overrides) -> ScannedItem:
    defaults = dict(
        confirmId="k1",
        sourcePath="/downloads/Skipped.mkv",
        name="Skipped.mkv",
        item_type="skip",
        confidence=0.5,
        reason="In-progress download",
        target_path="",
        action="skip",
    )
    defaults.update(overrides)
    return ScannedItem(**defaults)


# ---------------------------------------------------------------------------
# format_path_exists
# ---------------------------------------------------------------------------

class TestFormatPathExists:
    def test_series_all_exist(self) -> None:
        item = _series_item(showFolderExists=True, seasonFolderExists=True, fileExists=True)
        result = format_path_exists(item)
        assert "Show ✓" in result
        assert "Season ✓" in result
        assert "File ✓" in result

    def test_series_none_exist(self) -> None:
        item = _series_item(showFolderExists=False, seasonFolderExists=False, fileExists=False)
        result = format_path_exists(item)
        assert "Show ✗" in result
        assert "Season ✗" in result
        assert "File ✗" in result

    def test_movie_all_exist(self) -> None:
        item = _movie_item(showFolderExists=True, fileExists=True)
        result = format_path_exists(item)
        assert "Folder ✓" in result
        assert "File ✓" in result

    def test_movie_none_exist(self) -> None:
        item = _movie_item(showFolderExists=False, fileExists=False)
        result = format_path_exists(item)
        assert "Folder ✗" in result
        assert "File ✗" in result


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_none(self) -> None:
        assert format_duration(None) is None

    def test_seconds_only(self) -> None:
        assert format_duration(30) == "30s"

    def test_minutes_and_seconds(self) -> None:
        assert format_duration(90) == "1m 30s"

    def test_hours_minutes_seconds(self) -> None:
        assert format_duration(3661) == "1h 1m 1s"

    def test_zero(self) -> None:
        assert format_duration(0) == "0s"

    def test_negative_clamps_to_zero(self) -> None:
        assert format_duration(-5) == "0s"

    def test_fractional(self) -> None:
        result = format_duration(2.7)
        assert result is not None
        assert "2s" in result or "3s" in result


# ---------------------------------------------------------------------------
# format_transfer_speed
# ---------------------------------------------------------------------------

class TestFormatTransferSpeed:
    def test_none(self) -> None:
        assert format_transfer_speed(None) is None

    def test_zero(self) -> None:
        assert format_transfer_speed(0) is None

    def test_bytes_per_second(self) -> None:
        assert format_transfer_speed(50) == "50 B/s"

    def test_kilobytes(self) -> None:
        result = format_transfer_speed(2048)
        assert "KB/s" in result

    def test_megabytes(self) -> None:
        result = format_transfer_speed(5 * 1024 * 1024)
        assert "MB/s" in result

    def test_gigabytes(self) -> None:
        result = format_transfer_speed(2 * 1024 * 1024 * 1024)
        assert "GB/s" in result


# ---------------------------------------------------------------------------
# format_scan_progress
# ---------------------------------------------------------------------------

class TestFormatScanProgress:
    def test_completed_scan(self) -> None:
        scan = _scan_plan(
            status="completed",
            total_candidates=10,
            processed_candidates=10,
        )
        result = format_scan_progress(scan)
        assert result["status"] == "completed"
        assert result["percent"] == 100.0
        assert "complete" in result["next"].lower()

    def test_running_scan(self) -> None:
        scan = _scan_plan(
            status="running",
            total_candidates=10,
            processed_candidates=5,
            current_candidate="/data/file.mkv",
            current_candidate_index=6,
            started_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        result = format_scan_progress(scan)
        assert result["status"] == "running"
        assert result["processed"] == 5
        assert result["total"] == 10
        assert result["current_file"] == "/data/file.mkv"
        assert "still running" in result["next"].lower()

    def test_cancelled_scan(self) -> None:
        scan = _scan_plan(status="cancelled")
        result = format_scan_progress(scan)
        assert "cancelled" in result["next"].lower()

    def test_failed_scan(self) -> None:
        scan = _scan_plan(status="failed")
        result = format_scan_progress(scan)
        assert "failed" in result["next"].lower()

    def test_eta_calculation(self) -> None:
        scan = _scan_plan(
            status="running",
            total_candidates=10,
            processed_candidates=5,
            started_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        result = format_scan_progress(scan)
        assert result["eta_seconds"] is not None
        assert result["eta_seconds"] > 0

    def test_zero_total_no_eta(self) -> None:
        scan = _scan_plan(
            status="running",
            total_candidates=0,
            processed_candidates=0,
        )
        result = format_scan_progress(scan)
        assert result["percent"] == 0.0
        assert result["eta_seconds"] is None


# ---------------------------------------------------------------------------
# format_confirm_progress
# ---------------------------------------------------------------------------

class TestFormatConfirmProgress:
    def test_idle_status(self) -> None:
        scan = _scan_plan(confirm_status="idle")
        result = format_confirm_progress(scan)
        assert result["status"] == "idle"
        assert "no confirm" in result["next"].lower()

    def test_running_status(self) -> None:
        scan = _scan_plan(
            confirm_status="running",
            confirm_phase="moving",
            confirm_total=5,
            confirm_processed=2,
            confirm_started_at=datetime.now(UTC) - timedelta(seconds=10),
            counts=ScanCounts(moved=2),
        )
        result = format_confirm_progress(scan)
        assert result["status"] == "running"
        assert result["phase"] == "moving"
        assert result["processed"] == 2
        assert result["total"] == 5
        assert result["percent"] == 40.0

    def test_completed_status(self) -> None:
        scan = _scan_plan(confirm_status="completed")
        result = format_confirm_progress(scan)
        assert result["status"] == "completed"
        assert "confirm finished" in result["next"].lower()

    def test_counts_are_per_confirm(self) -> None:
        scan = _scan_plan(
            confirm_status="running",
            confirm_total=3,
            confirm_processed=1,
            confirm_start_moved=5,
            counts=ScanCounts(moved=6),
            confirm_started_at=datetime.now(UTC),
        )
        result = format_confirm_progress(scan)
        assert result["counts"]["moved"] == 1

    def test_queue_info(self) -> None:
        scan = _scan_plan(
            confirm_status="running",
            confirm_queue_length=2,
            confirm_queue_items=4,
        )
        result = format_confirm_progress(scan)
        assert "queued" in result["next"].lower()

    def test_cross_drive_note(self) -> None:
        scan = _scan_plan(
            confirm_status="running",
            confirm_cross_drive=True,
            confirm_note="Copying to target drive",
        )
        result = format_confirm_progress(scan)
        assert result["cross_drive"] is True
        assert result["note"] == "Copying to target drive"

    def test_file_eta_when_copying(self) -> None:
        scan = _scan_plan(
            confirm_status="running",
            confirm_current_size_bytes=1000,
            confirm_current_copied_bytes=250,
            confirm_current_speed_bytes=100.0,
            confirm_started_at=datetime.now(UTC),
        )
        result = format_confirm_progress(scan)
        assert result["current_eta_seconds"] == pytest.approx(7.5, abs=0.5)
        assert result["current_speed"] is not None

    def test_no_file_eta_when_complete(self) -> None:
        scan = _scan_plan(
            confirm_status="running",
            confirm_current_size_bytes=1000,
            confirm_current_copied_bytes=1000,
            confirm_current_speed_bytes=100.0,
            confirm_started_at=datetime.now(UTC),
        )
        result = format_confirm_progress(scan)
        assert result["current_eta_seconds"] is None


# ---------------------------------------------------------------------------
# report_next_step
# ---------------------------------------------------------------------------

class TestReportNextStep:
    def test_all_items_done(self) -> None:
        scan = _scan_plan(status="confirmed")
        result = report_next_step(scan)
        assert "all items done" in result.lower()

    def test_pending_items(self) -> None:
        scan = _scan_plan(
            status="completed",
            items=[_movie_item()],
        )
        result = report_next_step(scan)
        assert "1 items pending" in result.lower()

    def test_filesystem_error_mentioned(self) -> None:
        scan = _scan_plan(
            status="completed",
            service_errors={"Filesystem": "Some paths broken"},
        )
        result = report_next_step(scan)
        assert "check skipped items" in result.lower()


# ---------------------------------------------------------------------------
# report_llm_instructions
# ---------------------------------------------------------------------------

class TestReportLlmInstructions:
    def test_empty_when_nothing_to_do(self) -> None:
        scan = _scan_plan(status="confirmed")
        result = report_llm_instructions(scan, [], [])
        assert result == []

    def test_empty_when_zero_counts(self) -> None:
        scan = _scan_plan(
            status="completed",
            counts=ScanCounts(movies=0, series=0),
        )
        result = report_llm_instructions(scan, [], [])
        assert result == []

    def test_includes_root_info(self) -> None:
        scan = _scan_plan(
            status="completed",
            counts=ScanCounts(movies=1),
        )
        roots = [{"path": "/movies", "description": "Film library"}]
        result = report_llm_instructions(scan, roots, [])
        assert any("/movies" in i for i in result)

    def test_mentions_suspects(self) -> None:
        item = _movie_item(suspect=True)
        scan = _scan_plan(
            status="completed",
            counts=ScanCounts(movies=1),
            items=[item],
        )
        result = report_llm_instructions(scan, [], [])
        assert any("suspect" in i.lower() for i in result)

    def test_mentions_corrected(self) -> None:
        item = _movie_item(corrected=True)
        scan = _scan_plan(
            status="completed",
            counts=ScanCounts(movies=1),
            items=[item],
        )
        result = report_llm_instructions(scan, [], [])
        assert any("corrected" in i.lower() for i in result)


# ---------------------------------------------------------------------------
# format_report_items
# ---------------------------------------------------------------------------

class TestFormatReportItems:
    def test_actionable_items(self) -> None:
        scan = _scan_plan()
        items_by_action = {
            "move": [_movie_item()],
            "replace": [],
            "skip": [],
        }
        result = format_report_items(scan, items_by_action)
        assert len(result) == 1
        assert result[0]["action"] == "move"
        assert "targetPath" in result[0]
        assert "candidateTargets" in result[0]

    def test_skipped_items(self) -> None:
        scan = _scan_plan()
        items_by_action = {
            "move": [],
            "replace": [],
            "skip": [_skip_item()],
        }
        result = format_report_items(scan, items_by_action)
        assert len(result) == 1
        assert result[0]["action"] == "skip"
        assert result[0]["reason"] == "In-progress download"

    def test_empty(self) -> None:
        scan = _scan_plan()
        items_by_action = {"move": [], "replace": [], "skip": []}
        result = format_report_items(scan, items_by_action)
        assert result == []

    def test_replaced_items_included(self) -> None:
        item = _movie_item(action="replace")
        scan = _scan_plan()
        items_by_action = {"move": [], "replace": [item], "skip": []}
        result = format_report_items(scan, items_by_action)
        assert len(result) == 1
        assert result[0]["action"] == "replace"

    def test_candidate_targets_passthrough(self) -> None:
        ct = CandidateTarget(
            path="/movies/Alt",
            label="Alternative",
            evidence="folder exists",
        )
        item = _movie_item(candidateTargets=[ct])
        scan = _scan_plan()
        items_by_action = {"move": [item], "replace": [], "skip": []}
        result = format_report_items(scan, items_by_action)
        assert len(result[0]["candidateTargets"]) == 1
        assert result[0]["candidateTargets"][0]["path"] == "/movies/Alt"
