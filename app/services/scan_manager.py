from __future__ import annotations

import logging
import re
import shutil
import time
from asyncio import create_task, get_running_loop, to_thread
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
    ScanLogEntry,
    ScanPlan,
    ScanRequest,
    ScannedItem,
)
from app.services.classifier import classify_candidate
from app.services.jellyfin import JellyfinClient
from app.services.download_client import QbittorrentClient
from app.services.resolver import PathResolver, clear_resolver_cache
from app.services.scanner import ScanPathError, scan_candidates, _to_absolute_path

logger = logging.getLogger(__name__)
REVISION_RE = re.compile(r"\bv(\d+)\b", re.IGNORECASE)


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size_bytes} B"


def _path_mount_label(path: Path) -> str:
    parts = path.parts
    if len(parts) >= 2:
        return f"/{parts[1]}"
    return str(path)


class ScanManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._resolver = PathResolver(config)
        self._current_scan: ScanPlan | None = None
        self._loop = None

    def get_current_scan(self) -> ScanPlan | None:
        return self._current_scan

    def get_scan(self, scan_id: str) -> ScanPlan:
        if not self._current_scan or self._current_scan.scan_id != scan_id:
            raise HTTPException(status_code=404, detail="Scan not found. Run 'scan library' first.")
        return self._current_scan

    async def create_scan(self, request: ScanRequest) -> ScanPlan:
        self._loop = get_running_loop()
        if self._current_scan and self._current_scan.status == "running":
            raise HTTPException(status_code=409, detail="Scan already running. Check scan progress instead of starting a new scan.")

        now = datetime.now(UTC)
        scan_id = uuid4().hex

        self._current_scan = ScanPlan(
            scan_id=scan_id,
            status="running",
            operation=request.operation,
            items=[],
            counts=ScanCounts(),
            skipped_in_progress=0,
            created_at=now,
            started_at=now,
        )

        logger.info(
            "Scan %s started: operation=%s replace_existing=%s",
            scan_id,
            request.operation,
            request.replace_existing,
        )

        create_task(self._run_scan_task(scan_id, request))
        return self._current_scan

    async def _run_scan_task(self, scan_id: str, request: ScanRequest) -> None:
        try:
            await to_thread(self._run_scan_sync, scan_id, request)
            scan = self._current_scan
            if scan and scan.scan_id == scan_id and scan.status == "running":
                scan.status = "completed"
                scan.finished_at = datetime.now(UTC)
                scan.current_candidate = None
                logger.info(
                    "Scan %s finished: %s planned actions, %s skipped, %s filesystem/service issues",
                    scan_id,
                    sum(1 for item in scan.items if item.action in ("move", "replace")),
                    scan.counts.skipped,
                    len(scan.service_errors),
                )
        except Exception as exc:
            scan = self._current_scan
            if scan and scan.scan_id == scan_id:
                scan.status = "failed"
                scan.finished_at = datetime.now(UTC)
                scan.error = str(exc)
                scan.current_candidate = None
            logger.error("Scan %s failed: %s", scan_id, str(exc), exc_info=True)
        finally:
            clear_resolver_cache()

    def _run_scan_sync(self, scan_id: str, request: ScanRequest) -> None:
        scan = self._current_scan
        if not scan or scan.scan_id != scan_id:
            return

        clear_resolver_cache()
        self._resolver.reset_runtime_state()
        in_progress_paths = self._load_in_progress_paths_sync()
        scan.skipped_in_progress = len(in_progress_paths)
        planned_targets: dict[str, tuple[int, int]] = {}

        scan_result = scan_candidates(self._config.paths)
        candidates = scan_result.candidates
        scan.total_candidates = len(candidates)
        self._record_scan_errors(scan_result.errors)
        logger.info(
            "Scan %s found %s readable candidates and %s unreadable paths",
            scan.scan_id,
            len(candidates),
            len(scan_result.errors),
        )

        for index, candidate in enumerate(candidates, start=1):
            scan.current_candidate_index = index
            scan.current_candidate = candidate.source_path
            if in_progress_paths and self._is_in_progress(candidate.source_path, in_progress_paths):
                scan.counts.skipped += 1
                logger.warning("Scan %s skipped in-progress download: %s", scan.scan_id, candidate.source_path)
                scan.items.append(
                    ScannedItem(
                        confirm_id=self._next_confirm_id(scan),
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type="skip",
                        confidence=1.0,
                        reason="In-progress download",
                        target_path="",
                        action="skip",
                    )
                )
                scan.processed_candidates = index
                continue

            if candidate.file_size is not None and candidate.file_size <= 0:
                scan.counts.skipped += 1
                logger.warning(
                    "Scan %s skipped zero-byte media file: %s",
                    scan.scan_id,
                    candidate.source_path,
                )
                scan.items.append(
                    ScannedItem(
                        confirm_id=self._next_confirm_id(scan),
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type="skip",
                        confidence=1.0,
                        reason="Zero-byte file; download is incomplete or invalid",
                        target_path="",
                        action="skip",
                    )
                )
                scan.processed_candidates = index
                continue

            try:
                classification = classify_candidate(candidate)
                scan.counts.total += 1
                logger.info("Scan %s processing candidate %d/%d: %s", scan.scan_id, scan.counts.total, len(candidates), candidate.source_path)

                if classification.kind == "skip" or classification.confidence < self._config.model.classify_confidence_threshold:
                    scan.counts.skipped += 1
                    logger.info(
                        "Scan %s skipped %s: %s",
                        scan.scan_id,
                        candidate.source_path,
                        classification.reason,
                    )
                    scan.items.append(
                        ScannedItem(
                            confirm_id=self._next_confirm_id(scan),
                            source_path=candidate.source_path,
                            name=candidate.name,
                            item_type=classification.kind,
                            confidence=classification.confidence,
                            reason=classification.reason,
                            target_path="",
                            action="skip",
                        )
                    )
                    scan.processed_candidates = index
                    continue

                logger.info("Scan %s resolving target for candidate %d/%d: %s", scan.scan_id, scan.counts.total, len(candidates), candidate.source_path)
                resolved = self._resolve_sync(candidate, classification)
                logger.info("Scan %s resolved target for %s -> %s", scan.scan_id, candidate.source_path, resolved.target_path)

                target_path = Path(resolved.target_path)
                revision = self._extract_revision(candidate.name)

                existing_plan = planned_targets.get(resolved.target_path)
                if existing_plan:
                    existing_index, existing_revision = existing_plan
                    if revision > existing_revision:
                        previous_item = scan.items[existing_index]
                        if previous_item.action != "skip":
                            if previous_item.item_type == "movie":
                                scan.counts.movies = max(scan.counts.movies - 1, 0)
                            elif previous_item.item_type == "series":
                                scan.counts.series = max(scan.counts.series - 1, 0)
                            scan.counts.skipped += 1

                        previous_item.action = "skip"
                        previous_item.reason = f"Superseded by higher revision v{revision} for same episode"
                        previous_item.target_path = ""
                        planned_targets.pop(resolved.target_path, None)
                    else:
                        scan.counts.skipped += 1
                        logger.info(
                            "Scan %s skipped lower revision for %s",
                            scan.scan_id,
                            candidate.source_path,
                        )
                        scan.items.append(
                            ScannedItem(
                                confirm_id=self._next_confirm_id(scan),
                                source_path=candidate.source_path,
                                name=candidate.name,
                                item_type="skip",
                                confidence=classification.confidence,
                                reason=f"Lower revision v{revision} skipped; keeping v{existing_revision} for same episode",
                                target_path="",
                                action="skip",
                            )
                        )
                        scan.processed_candidates = index
                        continue

                target_exists = target_path.exists()
                action = "replace" if target_exists else "move"
                planned_action = action if request.replace_existing or not target_exists else "skip"

                if classification.kind == "movie":
                    scan.counts.movies += 1
                elif classification.kind == "series":
                    scan.counts.series += 1

                scan.items.append(
                    ScannedItem(
                        confirm_id=self._next_confirm_id(scan),
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type=classification.kind,
                        confidence=classification.confidence,
                        reason=classification.reason,
                        target_path=resolved.target_path,
                        action=planned_action,
                        folder_exists=resolved.folder_exists,
                    )
                )
                if planned_action == "skip":
                    logger.info(
                        "Scan %s skipped %s because target already exists and replace is disabled",
                        scan.scan_id,
                        candidate.source_path,
                    )
                else:
                    logger.info(
                        "Scan %s planned %s: %s -> %s",
                        scan.scan_id,
                        planned_action,
                        candidate.source_path,
                        resolved.target_path,
                    )
                if planned_action != "skip":
                    planned_targets[resolved.target_path] = (len(scan.items) - 1, revision)
                scan.processed_candidates = index

            except Exception as exc:
                logger.error("Scan %s failed to process %s: %s", scan.scan_id, candidate.source_path, str(exc), exc_info=True)
                scan.items.append(
                    ScannedItem(
                        confirm_id=self._next_confirm_id(scan),
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type="skip",
                        confidence=0.0,
                        reason=f"Error: {exc}",
                        target_path="",
                        action="skip",
                        error=str(exc),
                    )
                )
                scan.processed_candidates = index

        self._resolver.reset_runtime_state()

    def _record_scan_errors(self, errors: list[ScanPathError]) -> None:
        scan = self._current_scan
        if not scan or not errors:
            return

        messages: list[str] = []
        for error in errors:
            scan.counts.skipped += 1
            path_name = Path(error.path).name or error.path
            message = f"Filesystem read error while scanning path: {error.error}"
            logger.warning("Scan %s could not read path: %s", scan.scan_id, error.path)
            scan.items.append(
                ScannedItem(
                    confirm_id=self._next_confirm_id(scan),
                    source_path=error.path,
                    name=path_name,
                    item_type="skip",
                    confidence=0.0,
                    reason=message,
                    target_path="",
                    action="skip",
                    error=error.error,
                )
            )
            messages.append(f"{error.path} ({error.error})")

        summary = "; ".join(messages)
        if "Filesystem" in scan.service_errors:
            scan.service_errors["Filesystem"] += f"; {summary}"
        else:
            scan.service_errors["Filesystem"] = summary

    @staticmethod
    def _extract_revision(name: str) -> int:
        matches = REVISION_RE.findall(name)
        if not matches:
            return 0
        return max(int(value) for value in matches)

    def _resolve_sync(self, candidate: CandidateItem, classification: ClassificationResult) -> ResolvedTarget:
        return asyncio_run_in_thread(self._resolver.resolve(candidate, classification))

    def _next_confirm_id(self, scan: ScanPlan) -> str:
        return f"i{len(scan.items) + 1}"

    def update_scan(self, scan_id: str, items: list[dict]) -> ScanPlan:
        scan = self.get_scan(scan_id)

        if scan.status == "confirmed":
            raise HTTPException(status_code=400, detail="Cannot update a confirmed scan")
        if scan.status == "running":
            raise HTTPException(status_code=400, detail="Scan is still running. Wait for it to complete before updating.")
        if scan.status == "failed":
            raise HTTPException(status_code=400, detail="Scan failed. Run a new scan before updating.")

        allowed_roots = list(self._config.paths.movie_roots.values()) + list(self._config.paths.series_roots.values())
        updates_by_id = {u["confirmId"]: u["targetPath"] for u in items}
        updated_count = 0

        for item in scan.items:
            if item.confirm_id not in updates_by_id:
                continue
            new_target = updates_by_id[item.confirm_id]

            if not any(new_target.startswith(root) for root in allowed_roots):
                raise HTTPException(
                    status_code=400,
                    detail=f"Target path '{new_target}' is not under any configured movie or series root",
                )

            if not new_target.endswith((".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv")):
                raise HTTPException(
                    status_code=400,
                    detail=f"Target path '{new_target}' does not have a valid video extension",
                )

            item.target_path = new_target
            target_exists = Path(new_target).exists()
            item.action = "replace" if target_exists else "move"
            item.folder_exists = Path(new_target).parent.exists()
            updated_count += 1

        if not updated_count:
            raise HTTPException(
                status_code=400,
                detail=f"No matching items found for the given confirmIds: {list(updates_by_id.keys())}",
            )

        logger.info(
            "Scan %s updated %d items: %s",
            scan_id,
            updated_count,
            {uid: updates_by_id[uid] for uid in updates_by_id},
        )
        return scan

    async def confirm_scan(
        self,
        scan_id: str,
        item_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        source_prefixes: list[str] | None = None,
    ) -> ScanPlan:
        scan = self.get_scan(scan_id)

        selective = item_ids is not None or source_paths is not None or source_prefixes is not None
        logger.info("Confirm started for scan %s (selective=%s)", scan_id, selective)

        if scan.status == "confirmed":
            raise HTTPException(status_code=400, detail="Scan already confirmed. Run 'scan library' for a new scan.")

        if scan.status == "running":
            raise HTTPException(status_code=400, detail="Scan is still running. Wait for it to complete before confirming.")

        if scan.status == "failed":
            raise HTTPException(status_code=400, detail="Scan failed. Run 'scan library' for a new scan.")

        touched_libraries: set[str] = set()
        now = datetime.now(UTC)
        applied = 0

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

            try:
                logger.info("Applying %s: %s -> %s", item.action, item.source_path, item.target_path)
                await self._apply_item(item)
                item.confirmed = True
                applied += 1
                if item.item_type in ("movie", "series"):
                    touched_libraries.add(item.item_type)

                if item.action == "move":
                    scan.counts.moved += 1
                elif item.action == "replace":
                    scan.counts.replaced += 1
                logger.info("Finished %s: %s", item.action, item.target_path)
            except Exception as exc:
                scan.counts.failed += 1
                item.error = str(exc)
                logger.error("Failed %s for %s: %s", item.action, item.source_path, str(exc), exc_info=True)

        if applied == 0 and selective:
            raise HTTPException(
                status_code=400,
                detail="No matching unconfirmed items found for the given itemIds/sourcePaths/sourcePrefixes.",
            )

        await self._trigger_jellyfin_scans(touched_libraries)

        all_confirmed = all(
            item.action == "skip" or item.confirmed
            for item in scan.items
        )

        if not selective or all_confirmed:
            scan.status = "confirmed"
            scan.confirmed_at = now

        logger.info(
            "Confirm finished for scan %s: moved=%s replaced=%s failed=%s confirmed=%s",
            scan_id,
            scan.counts.moved,
            scan.counts.replaced,
            scan.counts.failed,
            scan.status,
        )

        return scan

    async def _apply_item(self, item: ScannedItem) -> None:
        source_path = Path(item.source_path)
        target_path = Path(item.target_path)

        if item.action == "skip":
            return

        candidate = CandidateItem(
            source_root_key="",
            source_root=str(source_path.parent),
            source_path=str(source_path),
            name=item.name,
        )

        await self._stop_seeding(candidate)

        target_path.parent.mkdir(parents=True, exist_ok=True)

        source_size = source_path.stat().st_size
        source_mount = _path_mount_label(source_path)
        target_mount = _path_mount_label(target_path)
        source_device = source_path.stat().st_dev
        target_device = target_path.parent.stat().st_dev
        cross_drive = source_device != target_device
        move_kind = "cross-drive copy+delete" if cross_drive else "same-drive rename/move"

        logger.info(
            "MOVE START [%s] action=%s size=%s from=%s to=%s source=%s target=%s",
            move_kind,
            item.action,
            _format_size(source_size),
            source_mount,
            target_mount,
            source_path,
            target_path,
        )
        if cross_drive:
            logger.info(
                "MOVE NOTE cross-drive move detected: this can take longer because the file is copied to the target drive and then removed from the source drive."
            )

        if item.action == "replace" and target_path.exists():
            logger.info("MOVE REPLACE removing existing target before copy: %s", target_path)
            target_path.unlink()

        started_at = time.perf_counter()
        try:
            shutil.move(str(source_path), str(target_path))
        except Exception:
            elapsed = time.perf_counter() - started_at
            logger.exception(
                "MOVE FAILED [%s] elapsed=%.1fs source=%s target=%s",
                move_kind,
                elapsed,
                source_path,
                target_path,
            )
            raise

        elapsed = time.perf_counter() - started_at
        logger.info(
            "MOVE DONE [%s] elapsed=%.1fs size=%s target=%s",
            move_kind,
            elapsed,
            _format_size(source_size),
            target_path,
        )

        self._cleanup_empty_parents(source_path)

    async def _stop_seeding(self, candidate: CandidateItem) -> None:
        client = QbittorrentClient.from_env(self._config.paths)
        if not client:
            return

        candidate_paths = [candidate.source_path]
        if candidate.container_path:
            candidate_paths.append(candidate.container_path)

        try:
            await client.stop_seeding_for_paths(candidate_paths)
            logger.info("Stopped seeding check completed for %s", candidate.source_path)
        except Exception as exc:
            error_msg = f"Error stopping seeding in qBittorrent: {str(exc)}"
            logger.error(error_msg, exc_info=True)
            if self._current_scan:
                if "qBittorrent" not in self._current_scan.service_errors:
                    self._current_scan.service_errors["qBittorrent"] = error_msg
                else:
                    self._current_scan.service_errors["qBittorrent"] += f"; {error_msg}"

    def _cleanup_empty_parents(self, original_path: Path) -> None:
        if not self._config.paths.download_roots:
            return

        root_paths = [Path(p) for p in self._config.paths.download_roots]
        for root_path in root_paths:
            if root_path in original_path.parents:
                current = original_path.parent
                while current != root_path and current.exists():
                    try:
                        current.rmdir()
                    except OSError:
                        break
                    current = current.parent
                break

    async def _load_in_progress_paths(self) -> list[str]:
        client = QbittorrentClient.from_env(self._config.paths)
        if not client:
            logger.warning("qBittorrent integration is not configured; skipping in-progress download check")
            return []

        try:
            paths = await client.list_in_progress_paths()
            logger.info("Checked qBittorrent: found %s in-progress paths", len(paths))
            return paths
        except Exception as exc:
            error_msg = f"Error loading in-progress paths from qBittorrent: {str(exc)}"
            logger.error(error_msg, exc_info=True)
            if self._current_scan:
                self._current_scan.service_errors["qBittorrent"] = str(exc)
            return []

    def _load_in_progress_paths_sync(self) -> list[str]:
        return asyncio_run_in_thread(self._load_in_progress_paths())

    @staticmethod
    def _is_in_progress(candidate_path: str, in_progress_paths: list[str]) -> bool:
        candidate_norm = str(Path(_to_absolute_path(candidate_path))).rstrip("/")
        for path in in_progress_paths:
            active_norm = str(Path(path)).rstrip("/")
            if candidate_norm == active_norm:
                return True
            if candidate_norm.startswith(active_norm + "/"):
                return True
        return False

    async def _trigger_jellyfin_scans(self, touched_libraries: set[str]) -> None:
        if not touched_libraries:
            return

        client = JellyfinClient.from_env()
        if not client:
            return

        for item_type in sorted(touched_libraries):
            try:
                library_name = client.library_name_for_kind(item_type)
                if not library_name:
                    logger.warning("No Jellyfin library configured for item type: %s", item_type)
                    continue
                
                logger.info("Triggering Jellyfin scan for library: %s", library_name)
                await client.scan_library(library_name)
                logger.info("Finished Jellyfin scan trigger for library: %s", library_name)
            except Exception as exc:
                error_msg = f"Error triggering Jellyfin scan for item type '{item_type}': {str(exc)}"
                logger.error(error_msg, exc_info=True)
                if self._current_scan:
                    if "Jellyfin" not in self._current_scan.service_errors:
                        self._current_scan.service_errors["Jellyfin"] = error_msg
                    else:
                        self._current_scan.service_errors["Jellyfin"] += f"; {error_msg}"

    def delete_scan(self) -> None:
        self._current_scan = None


def asyncio_run_in_thread(coro):
    import asyncio

    return asyncio.run(coro)
