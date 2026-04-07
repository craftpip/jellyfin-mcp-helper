from __future__ import annotations

import json
import logging
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
from app.services.scanner import scan_candidates, _to_absolute_path

logger = logging.getLogger(__name__)


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

        await self._run_scan(request)

        return self._current_scan

    async def _run_scan(self, request: ScanRequest) -> None:
        scan = self._current_scan
        if not scan:
            return

        in_progress_paths = await self._load_in_progress_paths()
        scan.skipped_in_progress = len(in_progress_paths)

        candidates = scan_candidates(self._config.paths)

        for candidate in candidates:
            if in_progress_paths and self._is_in_progress(candidate.source_path, in_progress_paths):
                scan.counts.skipped += 1
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

                if classification.kind == "skip" or classification.confidence < self._config.model.classify_confidence_threshold:
                    scan.counts.skipped += 1
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

                resolved = await self._resolver.resolve(candidate, classification)

                target_path = Path(resolved.target_path)
                target_exists = target_path.exists()
                action = "replace" if target_exists else "move"

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
                        action=action if request.replace_existing or not target_exists else "skip",
                    )
                )

            except Exception as exc:
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

    async def confirm_scan(self, scan_id: str) -> ScanPlan:
        scan = self.get_scan(scan_id)

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
                await self._apply_item(item)
                if item.item_type in ("movie", "series"):
                    touched_libraries.add(item.item_type)

                if item.action == "move":
                    scan.counts.moved += 1
                elif item.action == "replace":
                    scan.counts.replaced += 1
            except Exception as exc:
                scan.counts.failed += 1
                item.error = str(exc)

        await self._trigger_jellyfin_scans(touched_libraries)

        scan.status = "confirmed"
        scan.confirmed_at = now

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
        except Exception:
            pass

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
            logger.warning("No qBittorrent client configured")
            return []

        try:
            paths = await client.list_in_progress_paths()
            logger.info(f"Found {len(paths)} in-progress paths: {paths}")
            return paths
        except Exception as exc:
            logger.error(f"Error loading in-progress paths: {exc}", exc_info=True)
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

        for library_name in sorted(touched_libraries):
            try:
                await client.scan_library(library_name)
            except Exception:
                pass

    def delete_scan(self) -> None:
        self._current_scan = None
