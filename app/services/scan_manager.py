from __future__ import annotations

import json
import logging
import re
import shutil
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
from app.services.resolver import PathResolver
from app.services.scanner import ScanPathError, scan_candidates, _to_absolute_path

logger = logging.getLogger(__name__)
REVISION_RE = re.compile(r"\bv(\d+)\b", re.IGNORECASE)


class ScanManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._resolver = PathResolver(config)
        self._current_scan: ScanPlan | None = None

    def get_current_scan(self) -> ScanPlan | None:
        return self._current_scan

    def get_scan(self, scan_id: str) -> ScanPlan:
        if not self._current_scan or self._current_scan.scan_id != scan_id:
            raise HTTPException(status_code=404, detail="Scan not found. Run 'scan library' first.")
        return self._current_scan

    async def create_scan(self, request: ScanRequest) -> ScanPlan:
        now = datetime.now(UTC)
        scan_id = uuid4().hex

        self._current_scan = ScanPlan(
            scan_id=scan_id,
            status="pending",
            operation=request.operation,
            items=[],
            counts=ScanCounts(),
            skipped_in_progress=0,
            created_at=now,
        )

        logger.info(
            "Scan %s started: operation=%s replace_existing=%s",
            scan_id,
            request.operation,
            request.replace_existing,
        )

        await self._run_scan(request)

        logger.info(
            "Scan %s finished: %s planned actions, %s skipped, %s filesystem/service issues",
            scan_id,
            sum(1 for item in self._current_scan.items if item.action in ("move", "replace")),
            self._current_scan.counts.skipped,
            len(self._current_scan.service_errors),
        )

        return self._current_scan

    async def _run_scan(self, request: ScanRequest) -> None:
        scan = self._current_scan
        if not scan:
            return

        in_progress_paths = await self._load_in_progress_paths()
        scan.skipped_in_progress = len(in_progress_paths)
        planned_targets: dict[str, tuple[int, int]] = {}

        scan_result = scan_candidates(self._config.paths)
        candidates = scan_result.candidates
        self._record_scan_errors(scan_result.errors)
        logger.info(
            "Scan %s found %s readable candidates and %s unreadable paths",
            scan.scan_id,
            len(candidates),
            len(scan_result.errors),
        )

        for candidate in candidates:
            if in_progress_paths and self._is_in_progress(candidate.source_path, in_progress_paths):
                scan.counts.skipped += 1
                logger.warning("Scan %s skipped in-progress download: %s", scan.scan_id, candidate.source_path)
                scan.items.append(
                    ScannedItem(
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type="skip",
                        confidence=1.0,
                        reason="In-progress download",
                        target_path="",
                        action="skip",
                    )
                )
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
                            source_path=candidate.source_path,
                            name=candidate.name,
                            item_type=classification.kind,
                            confidence=classification.confidence,
                            reason=classification.reason,
                            target_path="",
                            action="skip",
                        )
                    )
                    continue

                logger.info("Scan %s resolving target for candidate %d/%d: %s", scan.scan_id, scan.counts.total, len(candidates), candidate.source_path)
                resolved = await self._resolver.resolve(candidate, classification)
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
                                source_path=candidate.source_path,
                                name=candidate.name,
                                item_type="skip",
                                confidence=classification.confidence,
                                reason=f"Lower revision v{revision} skipped; keeping v{existing_revision} for same episode",
                                target_path="",
                                action="skip",
                            )
                        )
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
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type=classification.kind,
                        confidence=classification.confidence,
                        reason=classification.reason,
                        target_path=resolved.target_path,
                        action=planned_action,
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

            except Exception as exc:
                logger.error("Scan %s failed to process %s: %s", scan.scan_id, candidate.source_path, str(exc), exc_info=True)
                scan.items.append(
                    ScannedItem(
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

    async def confirm_scan(self, scan_id: str) -> ScanPlan:
        scan = self.get_scan(scan_id)

        logger.info("Confirm started for scan %s", scan_id)

        if scan.status == "confirmed":
            raise HTTPException(status_code=400, detail="Scan already confirmed. Run 'scan library' for a new scan.")

        if scan.status == "failed":
            raise HTTPException(status_code=400, detail="Scan failed. Run 'scan library' for a new scan.")

        touched_libraries: set[str] = set()
        now = datetime.now(UTC)

        for item in scan.items:
            if item.action == "skip":
                continue

            try:
                logger.info("Applying %s: %s -> %s", item.action, item.source_path, item.target_path)
                await self._apply_item(item)
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

        await self._trigger_jellyfin_scans(touched_libraries)

        scan.status = "confirmed"
        scan.confirmed_at = now

        logger.info(
            "Confirm finished for scan %s: moved=%s replaced=%s failed=%s",
            scan_id,
            scan.counts.moved,
            scan.counts.replaced,
            scan.counts.failed,
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

        if item.action == "replace" and target_path.exists():
            target_path.unlink()

        shutil.move(str(source_path), str(target_path))

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
