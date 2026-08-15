from __future__ import annotations

import logging
import os
import re
import shutil
import threading
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
IN_PROGRESS_LABEL_RE = re.compile(r"[^a-z0-9]+")


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size_bytes} B"


def _is_cross_drive(source_path: str, target_path: str) -> bool:
    try:
        source_dev = os.stat(source_path).st_dev
        target_parent = Path(target_path).parent
        target_dev = os.stat(target_parent).st_dev
        return source_dev != target_dev
    except OSError:
        return False


def _path_mount_label(path: Path) -> str:
    parts = path.parts
    if len(parts) >= 2:
        return f"/{parts[1]}"
    return str(path)


def _normalize_in_progress_label(value: str) -> str:
    lowered = value.casefold()
    return IN_PROGRESS_LABEL_RE.sub(" ", lowered).strip()


def _path_name_labels(path_value: str) -> set[str]:
    path = Path(path_value)
    labels = {
        _normalize_in_progress_label(path.name),
        _normalize_in_progress_label(path.stem),
    }
    return {label for label in labels if label}


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class ScanManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._resolver = PathResolver(config)
        self._current_scan: ScanPlan | None = None
        self._loop = None
        self._scan_plans: dict[str, ScanPlan] = {}
        self._scan_cancel_events: dict[str, threading.Event] = {}
        self._scan_tasks: dict[str, object] = {}
        self._confirm_queue: list[dict] = []

    def get_current_scan(self) -> ScanPlan | None:
        return self._current_scan

    def get_scan(self, scan_id: str) -> ScanPlan:
        if not self._current_scan or self._current_scan.scan_id != scan_id:
            raise HTTPException(status_code=404, detail="Scan not found. Run 'scan library' first.")
        return self._current_scan

    async def create_scan(self, request: ScanRequest) -> ScanPlan:
        self._loop = get_running_loop()
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
        self._scan_plans[scan_id] = self._current_scan
        self._scan_cancel_events[scan_id] = threading.Event()

        logger.info(
            "Scan %s started: operation=%s replace_existing=%s",
            scan_id,
            request.operation,
            request.replace_existing,
        )

        self._scan_tasks[scan_id] = create_task(self._run_scan_task(scan_id, request, previous_task))
        return self._current_scan

    async def _run_scan_task(self, scan_id: str, request: ScanRequest, previous_task=None) -> None:
        try:
            if previous_task:
                await previous_task
            if self._scan_cancel_events[scan_id].is_set():
                return
            await to_thread(self._run_scan_sync, scan_id, request)
            scan = self._scan_plans.get(scan_id)
            if scan and scan.status == "running":
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
            scan = self._scan_plans.get(scan_id)
            if scan:
                scan.status = "failed"
                scan.finished_at = datetime.now(UTC)
                scan.error = str(exc)
                scan.current_candidate = None
            logger.error("Scan %s failed: %s", scan_id, str(exc), exc_info=True)
        finally:
            clear_resolver_cache()
            self._scan_tasks.pop(scan_id, None)
            self._scan_cancel_events.pop(scan_id, None)
            self._scan_plans.pop(scan_id, None)

    def _run_scan_sync(self, scan_id: str, request: ScanRequest) -> None:
        scan = self._scan_plans.get(scan_id)
        cancel_event = self._scan_cancel_events.get(scan_id)
        if not scan or not cancel_event:
            return

        clear_resolver_cache()
        self._resolver.reset_runtime_state()
        self._resolver.prepare_scan(
            list(self._config.paths.movie_roots.values()),
            list(self._config.paths.series_roots.values()),
        )
        in_progress_paths = self._load_in_progress_paths_sync()
        scan.skipped_in_progress = len(in_progress_paths)
        planned_targets: dict[str, tuple[int, int]] = {}
        planned_episodes: dict[tuple[str, int], set[int]] = {}
        planned_seasons: dict[str, set[int]] = {}

        scan_result = scan_candidates(self._config.paths)
        candidates = scan_result.candidates
        scan.total_candidates = len(candidates)
        self._record_scan_errors(scan, scan_result.errors)
        logger.info(
            "Scan %s found %s readable candidates and %s unreadable paths",
            scan.scan_id,
            len(candidates),
            len(scan_result.errors),
        )

        for index, candidate in enumerate(candidates, start=1):
            if cancel_event.is_set():
                logger.info("Scan %s cancelled before candidate %d", scan.scan_id, index)
                return
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
                        file_size=candidate.file_size,
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
                        file_size=candidate.file_size,
                    )
                )
                scan.processed_candidates = index
                continue

            try:
                classification = classify_candidate(candidate, self._config.series_title_aliases)
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
                            file_size=candidate.file_size,
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
                                file_size=candidate.file_size,
                            )
                        )
                        scan.processed_candidates = index
                        continue

                target_exists = target_path.exists()
                action = "replace" if target_exists else "move"
                planned_action = action if request.replace_existing or not target_exists else "skip"
                cross_drive = _is_cross_drive(candidate.source_path, resolved.target_path)

                if classification.kind == "movie":
                    scan.counts.movies += 1
                elif classification.kind == "series":
                    scan.counts.series += 1

                flags: list[str] = []
                if classification.kind == "series" and resolved.season_number and resolved.episode_number:
                    series_key = resolved.series_key or ""
                    if resolved.phantom_show_folder and (resolved.season_number > 1 or resolved.episode_number > 1):
                        flags.append("phantom_show_folder")
                    if (
                        resolved.season_number > 1
                        and not resolved.has_previous_season
                        and (resolved.season_number - 1) not in planned_seasons.get(series_key, set())
                    ):
                        flags.append("season_gap")
                    if (
                        resolved.episode_number > 1
                        and not resolved.has_previous_episode
                        and (resolved.episode_number - 1)
                        not in planned_episodes.get((series_key, resolved.season_number), set())
                    ):
                        flags.append("episode_gap")

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
                        show_folder_exists=resolved.show_folder_exists,
                        season_folder_exists=resolved.season_folder_exists,
                        file_exists=target_exists,
                        file_size=candidate.file_size,
                        cross_drive=cross_drive,
                        suspect=bool(flags),
                        flags=flags,
                        candidate_targets=resolved.candidate_targets,
                    )
                )
                if (
                    planned_action != "skip"
                    and classification.kind == "series"
                    and resolved.series_key
                    and resolved.season_number
                    and resolved.episode_number
                ):
                    planned_episodes.setdefault((resolved.series_key, resolved.season_number), set()).add(resolved.episode_number)
                    planned_seasons.setdefault(resolved.series_key, set()).add(resolved.season_number)
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
                        file_size=candidate.file_size,
                    )
                )
                scan.processed_candidates = index

        self._group_retarget_pass(scan, planned_targets)
        self._resolver.reset_runtime_state()

    def _group_retarget_pass(self, scan: ScanPlan, planned_targets: dict[str, tuple[int, int]]) -> None:
        """Re-target phantom/wrong series groups onto a real continuation folder.

        Runs after the main scan loop (so the disk index + planned coverage are
        complete) but before runtime state is reset.
        """
        groups: dict[str, list[ScannedItem]] = {}
        for item in scan.items:
            if item.action not in ("move", "replace") or item.item_type != "series":
                continue
            show_dir = Path(item.target_path).parent.parent
            groups.setdefault(str(show_dir), []).append(item)

        for show_dir_str, items in groups.items():
            phantom = any("phantom_show_folder" in item.flags for item in items)
            season_gap = any("season_gap" in item.flags for item in items)
            if not (phantom or season_gap):
                continue

            show_dir = Path(show_dir_str)
            year_match = re.search(r"\((\d{4})\)", show_dir.name)
            year = int(year_match.group(1)) if year_match else None
            group_tags = [self._target_episode_tag(item.target_path) for item in items]
            group_tags = [tag for tag in group_tags if tag]
            if not group_tags:
                continue
            target_season = max(tag[0] for tag in group_tags)
            found = self._resolver.find_continuation_show(
                title=show_dir.name,
                year=year,
                season=target_season,
                episode=1,
                episode_title=self._target_episode_title_from_item(items[0]),
            )
            if not found:
                continue

            new_show_dir = Path(found)
            logger.info(
                "Scan %s: group re-target %s -> %s (%d items)",
                scan.scan_id,
                show_dir_str,
                found,
                len(items),
            )
            for item in items:
                tag = self._target_episode_tag(item.target_path)
                if not tag:
                    continue
                season_number, episode_number = tag
                season_dir = (
                    self._resolver._pick_existing_season_dir(new_show_dir, season_number)
                    or new_show_dir / f"Season {season_number:02d}"
                )
                new_target = season_dir / Path(item.target_path).name
                episode_tag = f"s{season_number:02d}e{episode_number:02d}"
                if season_dir.exists():
                    for f in season_dir.iterdir():
                        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                            if re.search(rf"{re.escape(episode_tag)}(?:v\d+)?(?=[^a-z0-9]|$)", f.stem.lower()):
                                new_target = f
                                break
                old_target = item.target_path
                item.target_path = str(new_target)
                item.show_folder_exists = new_show_dir.exists()
                item.season_folder_exists = season_dir.exists()
                item.file_exists = new_target.exists()
                item.action = "replace" if item.file_exists else "move"
                item.suspect = False
                item.flags = []
                item.corrected = True
                item.correction_note = f"Re-targeted to existing show folder '{new_show_dir.name}'"
                if old_target in planned_targets:
                    planned_targets[str(new_target)] = planned_targets.pop(old_target)

    @staticmethod
    def _target_episode_tag(target_path: str) -> tuple[int, int] | None:
        match = re.search(r"S(\d{1,2})E(\d{1,3})\b", Path(target_path).name, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _target_episode_title_from_item(item: ScannedItem) -> str | None:
        stem = Path(item.target_path).stem
        match = re.search(r"S\d{1,2}E\d{1,3}\b", stem, re.IGNORECASE)
        if not match:
            return None
        title = stem[:match.start()].strip(" -._")
        return title or None

    def _record_scan_errors(self, scan: ScanPlan, errors: list[ScanPathError]) -> None:
        if not errors:
            return

        messages: list[str] = []
        for error in errors:
            scan.counts.skipped += 1
            path_name = Path(error.path).name or error.path
            message = f"Filesystem read error while scanning path: {error.error}"
            logger.warning("Scan %s could not read path: %s", scan.scan_id, error.path)
            try:
                err_size = Path(error.path).stat().st_size
            except OSError:
                err_size = None
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
                    file_size=err_size,
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

        allowed_roots = [
            Path(root).resolve(strict=False)
            for root in list(self._config.paths.movie_roots.values()) + list(self._config.paths.series_roots.values())
        ]
        updates_by_id = {u["confirmId"]: u["targetPath"] for u in items}
        updated_count = 0

        for item in scan.items:
            if item.confirm_id not in updates_by_id:
                continue
            new_target = updates_by_id[item.confirm_id]
            if item.action == "skip" or item.item_type == "skip":
                raise HTTPException(status_code=400, detail=f"Item '{item.confirm_id}' is skipped and cannot be redirected")

            target_path_obj = Path(new_target)
            if not target_path_obj.is_absolute():
                raise HTTPException(status_code=400, detail=f"Target path '{new_target}' must be absolute")
            target_path_obj = target_path_obj.resolve(strict=False)

            if not any(_is_path_within(target_path_obj, root) for root in allowed_roots):
                raise HTTPException(
                    status_code=400,
                    detail=f"Target path '{new_target}' is not under any configured movie or series root",
                )

            if target_path_obj.suffix.lower() not in (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Target path '{new_target}' does not have a valid video extension",
                )

            item.target_path = str(target_path_obj)
            target_exists = target_path_obj.exists()
            item.action = "replace" if target_exists else "move"
            parent = target_path_obj.parent
            item.season_folder_exists = parent.exists()
            if item.item_type == "series":
                item.show_folder_exists = parent.parent.exists() if parent.parent else False
            else:
                item.show_folder_exists = parent.exists()
            item.file_exists = target_exists
            item.suspect = False
            item.flags = []
            item.corrected = False
            item.correction_note = None
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

    def retarget_item(
        self,
        scan_id: str,
        confirm_id: str,
        directory: str,
        apply_to_group: bool = False,
        reclassify_as_movie: bool = False,
    ) -> ScanPlan:
        """Recompute an item's target from a chosen directory (browse/retarget UI).

        The client never assembles a target path: it picks a directory under a
        configured root and the server rebuilds the full target (season subdir
        join for series, same filename base, replace/move recompute, flag reset).
        """
        scan = self.get_scan(scan_id)

        if scan.status == "confirmed":
            raise HTTPException(status_code=400, detail="Cannot retarget a confirmed scan")
        if scan.status == "running":
            raise HTTPException(status_code=400, detail="Scan is still running. Wait for it to complete before updating.")
        if scan.status == "failed":
            raise HTTPException(status_code=400, detail="Scan failed. Run a new scan before updating.")

        item = next((i for i in scan.items if i.confirm_id == confirm_id), None)
        if not item:
            raise HTTPException(status_code=400, detail=f"No item found for confirmId '{confirm_id}'")
        if item.action == "skip" or item.item_type == "skip":
            raise HTTPException(status_code=400, detail=f"Item '{confirm_id}' is skipped and cannot be redirected")
        if reclassify_as_movie and apply_to_group:
            raise HTTPException(status_code=400, detail="Cannot apply 'as movie' reclassification to a group")

        directory_obj = Path(directory)
        if not directory_obj.is_absolute():
            raise HTTPException(status_code=400, detail="directory must be an absolute path")
        directory_obj = directory_obj.resolve(strict=False)

        allowed_roots = [
            Path(root).resolve(strict=False)
            for root in list(self._config.paths.movie_roots.values()) + list(self._config.paths.series_roots.values())
        ]
        if not any(_is_path_within(directory_obj, root) for root in allowed_roots):
            raise HTTPException(status_code=400, detail=f"Directory '{directory}' is not under any configured movie or series root")

        target_items = [item]
        if apply_to_group:
            if item.item_type == "series":
                group_key = str(Path(item.target_path).parent.parent)
                group_items = [
                    i for i in scan.items
                    if i.action != "skip" and i.item_type != "skip"
                    and str(Path(i.target_path).parent.parent) == group_key
                ]
            else:
                group_key = str(Path(item.target_path).parent)
                group_items = [
                    i for i in scan.items
                    if i.action != "skip" and i.item_type != "skip"
                    and str(Path(i.target_path).parent) == group_key
                ]
            if group_items:
                target_items = group_items

        if apply_to_group and item.item_type == "series":
            seasons = set()
            for group_item in target_items:
                tag = self._target_episode_tag(group_item.target_path)
                if tag:
                    seasons.add(tag[0])
            if len(seasons) > 1 and not self._is_show_level_dir(directory_obj):
                raise HTTPException(
                    status_code=400,
                    detail="Group spans multiple seasons — pick a show-level folder so each item joins its own season subfolder",
                )

        for target_item in target_items:
            self._apply_retarget(target_item, directory_obj, reclassify_as_movie)

        logger.info(
            "Scan %s retargeted confirmId=%s to %s (group=%s, as_movie=%s) — %d item(s)",
            scan_id, confirm_id, directory, apply_to_group, reclassify_as_movie, len(target_items),
        )
        return scan

    @staticmethod
    def _is_show_level_dir(path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return True
        try:
            entries = list(path.iterdir())
        except OSError:
            return True
        has_video_file = any(e.is_file() and e.suffix.lower() in (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv") for e in entries)
        has_subdir = any(e.is_dir() for e in entries)
        return not has_video_file and has_subdir

    def _apply_retarget(self, item: ScannedItem, directory: Path, reclassify_as_movie: bool) -> None:
        ext = Path(item.target_path).suffix or ".mkv"
        if reclassify_as_movie:
            item.item_type = "movie"
            base_name = directory.name or "Movie"
            target_path = directory / f"{base_name}{ext}"
        elif item.item_type == "movie":
            target_path = directory / Path(item.target_path).name
        else:
            season_number = 1
            tag = self._target_episode_tag(item.target_path)
            if tag:
                season_number = tag[0]
            if self._is_show_level_dir(directory):
                season_dir = (
                    self._resolver._pick_existing_season_dir(directory, season_number)
                    or directory / f"Season {season_number:02d}"
                )
            else:
                season_dir = directory
            target_path = season_dir / Path(item.target_path).name
            episode_tag = f"s{season_number:02d}e{(tag[1] if tag else 1):02d}"
            if season_dir.exists():
                for f in season_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"):
                        if re.search(rf"{re.escape(episode_tag)}(?:v\d+)?(?=[^a-z0-9]|$)", f.stem.lower()):
                            target_path = f
                            break

        item.target_path = str(target_path)
        target_exists = target_path.exists()
        item.action = "replace" if target_exists else "move"
        parent = target_path.parent
        item.season_folder_exists = parent.exists()
        if item.item_type == "series":
            item.show_folder_exists = parent.parent.exists() if parent.parent else False
        else:
            item.show_folder_exists = parent.exists()
        item.file_exists = target_exists
        item.suspect = False
        item.flags = []
        item.corrected = False
        item.correction_note = None

    def _get_confirm_total(self, scan: ScanPlan, item_ids, source_paths, source_prefixes) -> int:
        total = 0
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
            total += 1
        return total

    def _update_confirm_state(self, scan: ScanPlan, **fields) -> None:
        for key, value in fields.items():
            setattr(scan, key, value)
        scan.confirm_queue_length = len(self._confirm_queue)
        scan.confirm_queue_items = sum(entry["total"] for entry in self._confirm_queue)
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
        scan = self.get_scan(scan_id)
        updated_paths: set[str] = set()
        now = datetime.now(UTC)
        try:
            selected_items = [
                item
                for item in scan.items
                if item.action != "skip"
                and not item.confirmed
                and (item_ids is None or item.confirm_id in item_ids)
                and (source_paths is None or item.source_path in source_paths)
                and (
                    source_prefixes is None
                    or any(item.source_path.startswith(prefix) for prefix in source_prefixes)
                )
            ]

            # Recompute the total from the live item state: queued confirms may
            # see fewer unconfirmed items than were counted at queue time.
            scan.confirm_total = len(selected_items)

            if selected_items:
                self._update_confirm_state(
                    scan,
                    confirm_phase="stopping_seeding",
                    confirm_current_item=None,
                    confirm_current_target=None,
                    confirm_current_size_bytes=None,
                    confirm_current_copied_bytes=None,
                    confirm_current_speed_bytes=None,
                    confirm_current_percent=None,
                    confirm_note="Stopping seeding before move.",
                )
                await self._stop_seeding_for_items(selected_items)

            for item in selected_items:

                self._update_confirm_state(
                    scan,
                    confirm_phase="preparing",
                    confirm_current_item=item.source_path,
                    confirm_current_target=item.target_path,
                    confirm_current_size_bytes=None,
                    confirm_current_copied_bytes=None,
                    confirm_current_speed_bytes=None,
                    confirm_current_percent=None,
                    confirm_note="Preparing next item.",
                )
                try:
                    logger.info("Applying %s: %s -> %s", item.action, item.source_path, item.target_path)
                    await self._apply_item(scan, item)
                    item.confirmed = True
                    if item.item_type in ("movie", "series"):
                        updated_paths.add(item.target_path)

                    if item.action == "move":
                        scan.counts.moved += 1
                    elif item.action == "replace":
                        scan.counts.replaced += 1
                    logger.info("Finished %s: %s", item.action, item.target_path)
                except Exception as exc:
                    scan.counts.failed += 1
                    item.error = str(exc)
                    self._update_confirm_state(
                        scan,
                        confirm_note=f"Failed to move item: {exc}",
                    )
                    logger.error("Failed %s for %s: %s", item.action, item.source_path, str(exc), exc_info=True)
                finally:
                    scan.confirm_processed += 1

            self._update_confirm_state(
                scan,
                confirm_phase="triggering_jellyfin",
                confirm_current_item=None,
                confirm_current_target=None,
                confirm_current_size_bytes=None,
                confirm_current_copied_bytes=None,
                confirm_current_speed_bytes=None,
                confirm_current_percent=None,
                confirm_note="Triggering Jellyfin library refresh.",
            )
            await self._trigger_jellyfin_scans(updated_paths)

            all_confirmed = all(
                item.action == "skip" or item.confirmed
                for item in scan.items
            )

            selective = item_ids is not None or source_paths is not None or source_prefixes is not None

            if not selective or all_confirmed:
                scan.status = "confirmed"
                scan.confirmed_at = now

            scan.confirm_status = "completed"
            self._update_confirm_state(
                scan,
                confirm_phase="completed",
                confirm_current_item=None,
                confirm_current_target=None,
                confirm_current_size_bytes=None,
                confirm_current_copied_bytes=None,
                confirm_current_speed_bytes=None,
                confirm_current_percent=100.0 if scan.confirm_total else 0.0,
                confirm_note="Confirm finished.",
            )

            logger.info(
                "Confirm finished for scan %s: moved=%s replaced=%s failed=%s",
                scan_id,
                scan.counts.moved,
                scan.counts.replaced,
                scan.counts.failed,
            )
        except Exception as exc:
            scan.confirm_status = "failed"
            self._update_confirm_state(
                scan,
                confirm_phase="failed",
                confirm_note=f"Confirm failed: {exc}",
            )
            logger.error("Confirm task failed for scan %s: %s", scan_id, str(exc), exc_info=True)
        finally:
            # Start the next queued confirm (if any). This is synchronous: the
            # completed state is only observable between event-loop ticks, so a
            # queued batch resumes the 'running' state immediately.
            self._start_queued_confirms(scan_id)

    def _start_queued_confirms(self, scan_id: str) -> None:
        while self._confirm_queue:
            entry = self._confirm_queue.pop(0)
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
        # Run the blocking copy in a worker thread so the asyncio event loop stays
        # free to serve 'get move new downloads confirm progress' polls. The worker
        # mutates the shared scan object after each chunk; reads from the loop thread
        # are plain attribute reads, so live progress is visible while the copy runs.
        await to_thread(self._copy_file_worker, scan, source_path, target_path, source_size)

    def _copy_file_worker(self, scan: ScanPlan, source_path: Path, target_path: Path, source_size: int) -> None:
        copied_bytes = 0
        chunk_size = 8 * 1024 * 1024
        started_at = time.perf_counter()

        with source_path.open("rb") as src, target_path.open("wb") as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
                copied_bytes += len(chunk)
                elapsed = max(time.perf_counter() - started_at, 0.001)
                speed = copied_bytes / elapsed
                percent = round((copied_bytes / source_size) * 100, 1) if source_size else None
                self._update_confirm_state(
                    scan,
                    confirm_phase="moving",
                    confirm_current_copied_bytes=copied_bytes,
                    confirm_current_speed_bytes=speed,
                    confirm_current_percent=percent,
                    confirm_note="Copying file to target drive.",
                )
            dst.flush()
            os.fsync(dst.fileno())
        shutil.copystat(source_path, target_path, follow_symlinks=True)

    async def _apply_item(self, scan: ScanPlan, item: ScannedItem) -> None:
        source_path = Path(item.source_path)
        target_path = Path(item.target_path)

        if item.action == "skip":
            return

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

        self._update_confirm_state(
            scan,
            confirm_phase="moving",
            confirm_current_item=str(source_path),
            confirm_current_target=str(target_path),
            confirm_current_size_bytes=source_size,
            confirm_current_copied_bytes=0,
            confirm_current_speed_bytes=None,
            confirm_current_percent=0.0,
            confirm_cross_drive=cross_drive,
            confirm_note=(
                "Cross-drive move detected. Copying to target drive first."
                if cross_drive
                else "Moving file on the same drive."
            ),
        )

        started_at = time.perf_counter()
        temp_path: Path | None = None
        try:
            if target_path.exists() and item.action != "replace":
                raise FileExistsError(f"Target file appeared after scan: {target_path}")

            if cross_drive and source_path.is_file():
                temp_path = target_path.parent / f".jellysort-{uuid4().hex}.partial{target_path.suffix}"
                await self._copy_file_with_progress(scan, source_path, temp_path, source_size)
                os.replace(temp_path, target_path)
                self._update_confirm_state(
                    scan,
                    confirm_phase="deleting_source",
                    confirm_current_copied_bytes=source_size,
                    confirm_current_speed_bytes=scan.confirm_current_speed_bytes,
                    confirm_current_percent=100.0,
                    confirm_note="Copy completed. Removing source file.",
                )
                source_path.unlink()
            else:
                os.replace(source_path, target_path)
                self._update_confirm_state(
                    scan,
                    confirm_current_copied_bytes=source_size,
                    confirm_current_percent=100.0,
                    confirm_note="Move completed.",
                )
        except Exception:
            if temp_path and temp_path.exists():
                temp_path.unlink()
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

    async def _stop_seeding_for_items(self, items: list[ScannedItem]) -> None:
        client = QbittorrentClient.from_env(self._config.paths)
        if not client:
            return

        try:
            candidate_paths = [item.source_path for item in items if item.source_path]
            await client.stop_seeding_for_paths(candidate_paths)
            logger.info("Stopped seeding check completed for %d item(s)", len(candidate_paths))
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

    def _candidate_release_labels(self, candidate_path: str) -> set[str]:
        candidate = Path(_to_absolute_path(candidate_path))
        for root in self._config.paths.download_roots:
            root_path = Path(root)
            try:
                relative = candidate.relative_to(root_path)
            except ValueError:
                continue

            if not relative.parts:
                break

            first_part = relative.parts[0]
            return {
                label for label in {
                    _normalize_in_progress_label(first_part),
                    _normalize_in_progress_label(Path(first_part).stem),
                } if label
            }

        return _path_name_labels(str(candidate))

    def _is_in_progress(self, candidate_path: str, in_progress_paths: list[str]) -> bool:
        candidate_norm = str(Path(_to_absolute_path(candidate_path))).rstrip("/")
        candidate_labels = self._candidate_release_labels(candidate_norm)
        for path in in_progress_paths:
            active_norm = str(Path(path)).rstrip("/")
            if candidate_norm == active_norm:
                return True
            if candidate_norm.startswith(active_norm + "/"):
                return True
            if candidate_labels and candidate_labels & _path_name_labels(active_norm):
                return True
        return False

    async def _trigger_jellyfin_scans(self, updated_paths: set[str]) -> None:
        if not updated_paths:
            return

        client = JellyfinClient.from_env()
        if not client:
            return

        try:
            library_names = set()
            for item in (self._current_scan.items if self._current_scan else []):
                if item.confirmed and item.item_type in ("movie", "series"):
                    lib_name = client.library_name_for_kind(item.item_type)
                    if lib_name:
                        library_names.add(lib_name)

            if library_names:
                for lib_name in sorted(library_names):
                    logger.info("Triggering Jellyfin library scan for '%s'", lib_name)
                    await client.scan_library(library_name=lib_name)
                logger.info("Finished Jellyfin library scan(s) for %d library(s)", len(library_names))
            else:
                logger.info("Triggering Jellyfin media update for %d path(s)", len(updated_paths))
                await client.notify_media_updated(sorted(updated_paths))
                logger.info("Finished Jellyfin media update for %d path(s)", len(updated_paths))
        except Exception as exc:
            error_msg = f"Error triggering Jellyfin library scan: {str(exc)}"
            logger.error(error_msg, exc_info=True)
            if self._current_scan:
                if "Jellyfin" not in self._current_scan.service_errors:
                    self._current_scan.service_errors["Jellyfin"] = error_msg
                else:
                    self._current_scan.service_errors["Jellyfin"] += f"; {error_msg}"

    async def delete_items(self, scan_id: str, item_ids: list[str]) -> ScanPlan:
        scan = self.get_scan(scan_id)

        if not item_ids:
            raise HTTPException(status_code=400, detail="itemIds is required")

        if scan.status == "running":
            raise HTTPException(status_code=400, detail="Scan is still running. Wait for it to complete before deleting items.")
        if scan.status == "failed":
            raise HTTPException(status_code=400, detail="Scan failed. Run a new scan before deleting items.")
        if scan.status == "confirmed":
            raise HTTPException(status_code=400, detail="Scan already confirmed. Run a new scan before deleting items.")
        if scan.confirm_status == "running":
            raise HTTPException(status_code=409, detail="Confirm already running. Wait for it to finish before deleting items.")

        selected = [
            item
            for item in scan.items
            if item.confirm_id in item_ids
            and item.action in ("move", "replace", "skip")
            and not item.confirmed
        ]

        if not selected:
            raise HTTPException(
                status_code=400,
                detail="No matching unconfirmed move/replace/skip items found for the given itemIds.",
            )

        await self._stop_seeding_for_items(selected)

        deleted: list[str] = []
        for item in selected:
            source_path = Path(item.source_path)
            if source_path.exists():
                try:
                    source_path.unlink()
                except OSError as exc:
                    raise HTTPException(status_code=500, detail=f"Failed to delete source file: {exc}") from exc

            was_actionable = item.action in ("move", "replace")
            item.action = "skip"
            item.reason = "Source file deleted by user"
            item.target_path = ""
            item.confirmed = True
            if was_actionable:
                if item.item_type == "movie":
                    scan.counts.movies = max(scan.counts.movies - 1, 0)
                elif item.item_type == "series":
                    scan.counts.series = max(scan.counts.series - 1, 0)
                scan.counts.skipped += 1
            deleted.append(item.source_path)
            self._cleanup_empty_parents(source_path)

        logger.info("Scan %s deleted %d source file(s): %s", scan_id, len(deleted), deleted)
        return scan

    def delete_scan(self) -> None:
        self._current_scan = None


def asyncio_run_in_thread(coro):
    import asyncio

    return asyncio.run(coro)
