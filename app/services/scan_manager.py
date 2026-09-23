from __future__ import annotations

import logging
import threading
from asyncio import create_task, get_running_loop
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import AppConfig
from app.models.schemas import (
    CandidateItem,
    ClassificationResult,
    ResolvedTarget,
    ScanCounts,
    ScannedItem,
    ScanPlan,
    ScanRequest,
)
from app.services import move_executor, retarget, scan_orchestrator
from app.services.classifier import classify_candidate  # noqa: F401 - re-export for monkeypatch
from app.services.confirm_queue import ConfirmQueue
from app.services.presenters import format_scan_report
from app.services.resolver import PathResolver
from app.services.scan_history import save_report
from app.services.scan_store import ScanStore
from app.services.scanner import ScanPathError, scan_candidates  # noqa: F401

logger = logging.getLogger(__name__)
class ScanManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._resolver = PathResolver(config)
        self._store = ScanStore()
        self._loop = None
        self._confirm_queue = ConfirmQueue()
        # Restore single-report singleton if present (restart recovery)
        try:
            from app.services.scan_history import load_singleton

            restored = load_singleton(self._config.report_dir)
            if restored is not None:
                self._store.current = restored
                logger.info("Restored singleton report %s with %d items from %s", restored.scan_id, len(restored.items), self._config.report_dir)
        except Exception as exc:
            logger.warning("Failed to restore singleton report: %s", exc)

    # ---- state delegates (state lives in ScanStore; call sites stay untouched) ----
    @property
    def _current_scan(self) -> ScanPlan | None:
        return self._store.current

    @_current_scan.setter
    def _current_scan(self, scan: ScanPlan | None) -> None:
        self._store.current = scan

    @property
    def _scan_plans(self) -> dict[str, ScanPlan]:
        return self._store.all_plans()

    @property
    def _scan_cancel_events(self) -> dict[str, threading.Event]:
        return self._store.cancel_events

    @property
    def _scan_tasks(self) -> dict[str, object]:
        return self._store.tasks

    def get_current_scan(self) -> ScanPlan | None:
        return self._current_scan

    def get_scan(self, scan_id: str) -> ScanPlan:
        return self._store.get(scan_id)

    async def create_scan(self, request: ScanRequest) -> ScanPlan:
        self._loop = get_running_loop()
        if getattr(request, "hint_scope", "additive") == "only":
            raise HTTPException(status_code=400, detail="hint_scope='only' is not implemented in v1; use 'additive'.")
        previous_task = None
        if self._current_scan and self._current_scan.status == "running":
            previous_scan = self._current_scan
            logger.info("Scan %s: cancelling previous scan %s", request.operation, previous_scan.scan_id)
            previous_scan.status = "cancelled"
            previous_scan.finished_at = datetime.now(UTC)
            previous_scan.current_candidate = None
            cancel_event = self._scan_cancel_events.get(previous_scan.scan_id)
            if cancel_event:
                cancel_event.set()
            previous_task = self._scan_tasks.get(previous_scan.scan_id)

        now = datetime.now(UTC)
        scan_id = uuid4().hex

        # Single-report incremental: preserve existing report unless fullRescan
        is_full = bool(getattr(request, "full_rescan", False))
        existing = self._current_scan
        if existing and not is_full and existing.status in ("completed", "confirmed", "failed", "cancelled") and existing.items:
            # Incremental: seed new scan with copy of previous items/counts
            seeded_items = [it.model_copy(deep=True) for it in existing.items]
            seeded_counts = existing.counts.model_copy(deep=True)
            seeded_errors = dict(existing.service_errors)
            self._current_scan = ScanPlan(
                scan_id=scan_id,
                status="running",
                operation=request.operation,
                hints=[h.model_copy(deep=True) for h in request.hints],
                items=seeded_items,
                counts=seeded_counts,
                created_at=now,
                started_at=now,
                service_errors=seeded_errors,
            )
            logger.info("Scan %s incremental: seeded %d existing items (fullRescan=%s)", scan_id, len(seeded_items), is_full)
        else:
            # Full rescan or no prior report: archive prior if overwriting
            if existing and is_full and existing.items:
                try:
                    from app.services.presenters import format_scan_report as _fmt2
                    from app.services.scan_history import save_report as _save2

                    _save2(existing.scan_id, _fmt2(existing), self._config.report_dir)
                    logger.info("Scan %s fullRescan: archived previous report %s with %d items", scan_id, existing.scan_id, len(existing.items))
                except Exception as exc:
                    logger.warning("Failed to archive previous report on fullRescan: %s", exc)
            self._current_scan = ScanPlan(
                scan_id=scan_id,
                status="running",
                operation=request.operation,
                hints=[h.model_copy(deep=True) for h in request.hints],
                items=[],
                counts=ScanCounts(),
                created_at=now,
                started_at=now,
            )
        self._scan_plans[scan_id] = self._current_scan
        self._scan_cancel_events[scan_id] = threading.Event()

        logger.info(
            "Scan %s started: operation=%s replace_existing=%s fullRescan=%s",
            scan_id,
            request.operation,
            request.replace_existing,
            is_full,
        )

        self._scan_tasks[scan_id] = create_task(self._run_scan_task(scan_id, request, previous_task))
        return self._current_scan

    async def _run_scan_task(self, scan_id: str, request: ScanRequest, previous_task=None) -> None:
        await scan_orchestrator.run_scan_task(self, scan_id, request, previous_task)

    def _run_scan_sync(self, scan_id: str, request: ScanRequest) -> None:
        return scan_orchestrator.run_scan_sync(self, scan_id, request)

    def _group_retarget_pass(self, scan: ScanPlan, planned_targets: dict[str, tuple[int, int]]) -> None:
        return scan_orchestrator.group_retarget_pass(self, scan, planned_targets)

    @staticmethod
    def _target_episode_tag(target_path: str) -> tuple[int, int] | None:
        return retarget.target_episode_tag(target_path)

    @staticmethod
    def _target_episode_title_from_item(item: ScannedItem) -> str | None:
        return retarget.target_episode_title_from_item(item)

    def _record_scan_errors(self, scan: ScanPlan, errors: list[ScanPathError]) -> None:
        return scan_orchestrator.record_scan_errors(self, scan, errors)

    @staticmethod
    def _extract_revision(name: str) -> int:
        return scan_orchestrator.extract_revision(name)

    def _resolve_sync(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        return scan_orchestrator.resolve_sync(self, candidate, classification)

    def _next_confirm_id(self, scan: ScanPlan) -> str:
        return f"i{len(scan.items) + 1}"

    def update_scan(self, scan_id: str, items: list[dict]) -> ScanPlan:
        result = retarget.update_scan(self, scan_id, items)
        try:
            from app.services.scan_history import save_singleton

            save_singleton(result, self._config.report_dir)
        except Exception:
            pass
        return result

    def retarget_item(
        self,
        scan_id: str,
        confirm_id: str,
        directory: str,
        apply_to_group: bool = False,
        reclassify_as_movie: bool = False,
    ) -> ScanPlan:
        result = retarget.retarget_item(self, scan_id, confirm_id, directory, apply_to_group, reclassify_as_movie)
        try:
            from app.services.scan_history import save_singleton

            save_singleton(result, self._config.report_dir)
        except Exception:
            pass
        return result

    @staticmethod
    def _is_show_level_dir(path: Path) -> bool:
        return retarget.is_show_level_dir(path)

    @staticmethod
    def _source_episode_tag(item: ScannedItem) -> tuple[int, int] | None:
        return retarget.source_episode_tag(item)

    @staticmethod
    def _effective_type(item: ScannedItem, reclassify_as_movie: bool) -> str:
        return retarget.effective_type(item, reclassify_as_movie)

    def _apply_retarget(self, item: ScannedItem, directory: Path, reclassify_as_movie: bool) -> None:
        retarget.apply_retarget(item, directory, reclassify_as_movie, self._resolver)

    def _match_confirm_items(
        self, scan: ScanPlan, item_ids, source_paths, source_prefixes
    ) -> list[ScannedItem]:
        matched = []
        for item in scan.items:
            if item.action == "skip":
                continue
            if item.confirmed:
                continue
            if item_ids is not None and item.confirm_id not in item_ids:
                continue
            if source_paths is not None and item.source_path not in source_paths:
                continue
            if source_prefixes is not None and not any(
                item.source_path.startswith(prefix) for prefix in source_prefixes
            ):
                continue
            matched.append(item)
        return matched

    def _get_confirm_total(self, scan: ScanPlan, item_ids, source_paths, source_prefixes) -> int:
        return len(self._match_confirm_items(scan, item_ids, source_paths, source_prefixes))

    def _update_confirm_state(self, scan: ScanPlan, **fields) -> None:
        for key, value in fields.items():
            setattr(scan, key, value)
        scan.confirm_queue_length = len(self._confirm_queue)
        scan.confirm_queue_items = sum(entry["total"] for entry in self._confirm_queue)
        scan.confirm_queue_item_ids = [
            [item.confirm_id for item in self._match_confirm_items(
                scan, entry.get("item_ids"), entry.get("source_paths"), entry.get("source_prefixes")
            )]
            for entry in self._confirm_queue
        ]
        scan.confirm_last_update_at = datetime.now(UTC)

    async def confirm_scan(
        self,
        scan_id: str,
        item_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        source_prefixes: list[str] | None = None,
    ) -> ScanPlan:
        scan = self.get_scan(scan_id)

        selective = item_ids is not None or source_paths is not None or source_prefixes is not None
        logger.info("Confirm requested for scan %s (selective=%s)", scan_id, selective)

        if scan.status == "confirmed":
            raise HTTPException(status_code=400, detail="Scan already confirmed. Run 'scan library' for a new scan.")

        if scan.status == "running":
            raise HTTPException(status_code=400, detail="Scan is still running. Wait for it to complete before confirming.")

        if scan.status == "failed":
            raise HTTPException(status_code=400, detail="Scan failed. Run 'scan library' for a new scan.")

        confirm_total = self._get_confirm_total(scan, item_ids, source_paths, source_prefixes)
        if confirm_total == 0 and selective:
            matched = [
                item
                for item in scan.items
                if (item_ids is None or item.confirm_id in item_ids)
                and (source_paths is None or item.source_path in source_paths)
                and (
                    source_prefixes is None
                    or any(item.source_path.startswith(prefix) for prefix in source_prefixes)
                )
            ]
            if matched:
                # Duplicate submission: the items exist but are already
                # confirmed/skipped (e.g. Start Move double-clicked — the first
                # request already moved them). Not a stale report.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Those items were already confirmed — the move likely already "
                        "went through (e.g. Start Move was sent twice). Check the "
                        "report/history instead of retrying."
                    ),
                )
            raise HTTPException(
                status_code=400,
                detail="No matching unconfirmed items found for the given itemIds/sourcePaths/sourcePrefixes.",
            )

        if scan.confirm_status == "running":
            # A move is already running. Queue this request instead of rejecting
            # it; it will start automatically when the current move finishes.
            self._confirm_queue.append({
                "scan_id": scan_id,
                "item_ids": item_ids,
                "source_paths": source_paths,
                "source_prefixes": source_prefixes,
                "total": confirm_total,
            })
            self._update_confirm_state(
                scan,
                confirm_note=(
                    f"Confirm queued behind the running move ({confirm_total} item(s), "
                    f"{len(self._confirm_queue)} queued)."
                ),
            )
            logger.info(
                "Confirm queued for scan %s: %d item(s) behind the current move",
                scan_id,
                confirm_total,
            )
            return scan

        self._start_confirm(scan_id, item_ids, source_paths, source_prefixes, confirm_total)
        return scan

    def _start_confirm(
        self,
        scan_id: str,
        item_ids: list[str] | None,
        source_paths: list[str] | None,
        source_prefixes: list[str] | None,
        confirm_total: int,
    ) -> None:
        scan = self.get_scan(scan_id)
        scan.confirm_status = "running"
        scan.confirm_processed = 0
        scan.confirm_start_moved = scan.counts.moved
        scan.confirm_start_replaced = scan.counts.replaced
        scan.confirm_start_failed = scan.counts.failed
        scan.confirm_item_ids = [
            item.confirm_id
            for item in self._match_confirm_items(scan, item_ids, source_paths, source_prefixes)
        ]
        self._update_confirm_state(
            scan,
            confirm_phase="preparing",
            confirm_current_item=None,
            confirm_current_target=None,
            confirm_started_at=datetime.now(UTC),
            confirm_total=confirm_total,
            confirm_current_size_bytes=None,
            confirm_current_copied_bytes=None,
            confirm_current_speed_bytes=None,
            confirm_current_percent=None,
            confirm_cross_drive=None,
            confirm_note="Preparing confirm queue.",
        )

        create_task(self._run_confirm_task(scan_id, item_ids, source_paths, source_prefixes))

    async def _run_confirm_task(
        self,
        scan_id: str,
        item_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        source_prefixes: list[str] | None = None,
    ) -> None:
        await move_executor.run_confirm_task(self, scan_id, item_ids, source_paths, source_prefixes)

    def _start_queued_confirms(self, scan_id: str) -> None:
        while self._confirm_queue:
            entry = self._confirm_queue.popleft()
            if entry is None:
                break
            if entry["scan_id"] != scan_id:
                logger.info("Skipping queued confirm for unrelated scan %s", entry["scan_id"])
                continue
            logger.info(
                "Starting queued confirm for scan %s: %d item(s), %d still queued",
                scan_id,
                entry["total"],
                len(self._confirm_queue),
            )
            self._start_confirm(
                entry["scan_id"],
                entry["item_ids"],
                entry["source_paths"],
                entry["source_prefixes"],
                entry["total"],
            )
            return

    async def _copy_file_with_progress(self, scan: ScanPlan, source_path: Path, target_path: Path, source_size: int) -> None:
        await move_executor.copy_file_with_progress(scan, source_path, target_path, source_size, self._update_confirm_state)

    def _copy_file_worker(self, scan: ScanPlan, source_path: Path, target_path: Path, source_size: int) -> None:
        return move_executor.copy_file_worker(scan, source_path, target_path, source_size, self._update_confirm_state)

    async def _apply_item(self, scan: ScanPlan, item: ScannedItem) -> None:
        await move_executor.apply_item(scan, item, self._update_confirm_state, copy_fn=self._copy_file_with_progress)
        # Post-move cleanup (empty parent dirs) stays in the orchestrator — needs config.
        if item.action != "skip":
            self._cleanup_empty_parents(Path(item.source_path))

    def _cleanup_empty_parents(self, original_path: Path) -> None:
        move_executor.cleanup_empty_parents(self, original_path)

    async def _trigger_jellyfin_scans(self, updated_paths: set[str]) -> None:
        await move_executor.trigger_jellyfin_scans(self, updated_paths)

    async def delete_items(self, scan_id: str, item_ids: list[str]) -> ScanPlan:
        result = await scan_orchestrator.delete_items(self, scan_id, item_ids)
        # Persist singleton after delete
        try:
            from app.services.scan_history import save_singleton

            if self._current_scan:
                save_singleton(self._current_scan, self._config.report_dir)
        except Exception:
            pass
        return result

    def delete_scan(self) -> None:
        self._current_scan = None
        try:
            from app.services.scan_history import singleton_path

            p = singleton_path(self._config.report_dir)
            if p.exists():
                p.unlink()
        except Exception:
            pass

    def undo_scan(self, scan_id: str) -> dict:
        """Undo confirmed moves of a scan (memory first, history fallback)."""
        from app.services import undo as undo_service
        from app.services.scan_history import load_report

        scan = self._store.get_or_none(scan_id)
        if scan is not None:
            result = undo_service.undo_items(undo_service.normalize_schema_items(scan.items))
            if result["restored_count"]:
                scan.counts.moved = max(0, scan.counts.moved - result["restored_count"])
                save_report(scan_id, format_scan_report(scan), self._config.report_dir)
            return {"ok": True, "scan_id": scan_id, **result}

        report = load_report(scan_id, report_dir=self._config.report_dir)
        result = undo_service.undo_from_report(report, report_dir=self._config.report_dir)
        if not result.get("ok"):
            raise KeyError(f"scan {scan_id} not found")
        result["scan_id"] = scan_id
        return result


def asyncio_run_in_thread(coro):
    import asyncio

    return asyncio.run(coro)
