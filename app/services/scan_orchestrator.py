# mypy: ignore-errors
"""Scan orchestration — extracted from ScanManager for long-horizon maintainability.

Phase 1.1 slice C: the scan classification loop and post-scan group retarget.
This module is stateless; ScanManager owns ScanPlan state.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.constants import VIDEO_EXTENSIONS
from app.models.schemas import ClassificationResult, ScannedItem, SortHint

logger = logging.getLogger(__name__)


def _normalize_hint_key(value: str | None) -> str:
    return (value or "").casefold().strip()


def _build_hint_index(hints: list[SortHint] | None) -> dict[str, SortHint]:
    """Index strict hints by normalized source_prefix (torrent folder basename)."""
    index: dict[str, SortHint] = {}
    for hint in hints or []:
        if hint is not None and getattr(hint, "strict", True):
            index.setdefault(_normalize_hint_key(hint.source_prefix), hint)
    return index


def _hint_for_candidate(candidate, hint_index: dict[str, SortHint]) -> SortHint | None:
    """Match a candidate to a hint by download container dirname (JellyJake truth)."""
    if not hint_index:
        return None
    if candidate.container_path:
        folder_name = Path(candidate.container_path).name
    else:
        folder_name = Path(candidate.source_path).parent.name
    return hint_index.get(_normalize_hint_key(folder_name))


# Trailing bare absolute number in a strict-hint filename ("Show - 13.mkv" -> 13).
# Anchored to the end of the stem so mid-name codec decimals (Opus 2.0 / DDP2.0)
# and resolutions (1080p) never match; _HINT_TRAILING_DECIMAL_RE rejects a
# decimal tail outright. 4+-digit runs (1080) can't match \d{1,3}$ fully.
_HINT_TRAILING_NUMBER_RE = re.compile(r"[\s\-_.]+(?P<num>\d{1,3})(?:v\d+)?\s*$", re.IGNORECASE)
_HINT_TRAILING_DECIMAL_RE = re.compile(r"\d\.\d+\s*$")
# Upper bound for a sane per-season episode number after absolute->relative
# conversion (N - 12*(S-1)).
_HINT_MAX_EPISODE = 99


def _extract_hint_bare_number(name: str) -> int | None:
    """Bare trailing episode number for the strict-hint path only.

    Returns None for decimal tails (codec versions like 2.0) or when no
    standalone trailing number exists. SxxEyy-tagged files never reach here
    (handled before this is called), so their numbering is untouched.
    """
    stem = Path(name).stem
    if _HINT_TRAILING_DECIMAL_RE.search(stem):
        return None
    match = _HINT_TRAILING_NUMBER_RE.search(stem)
    if not match:
        return None
    try:
        return int(match.group("num"))
    except (TypeError, ValueError):
        return None


def _classification_from_hint(candidate, hint: SortHint) -> tuple[ClassificationResult, list[str]]:
    """Strict hint bypass: hint title/kind are authoritative; season/episode still
    parsed from the filename's SxxEyy tag as today (hint.season is the default
    only when the filename has no tag). Bare trailing absolute numbers
    ("Show - 13.mkv") map to distinct episodes: with hint season S, convert
    absolute->relative via N - 12*(S-1) when that yields 1.._HINT_MAX_EPISODE;
    otherwise keep N as the episode of the hint season and flag ambiguous."""
    from app.services.classifier import _extract_season_episode

    file_season, file_episode = _extract_season_episode(candidate.name)
    season = file_season if file_season is not None else hint.season
    episode = file_episode
    flags: list[str] = []
    reason = "JellyJake hint (strict)"
    if hint.kind == "movie":
        season = None
        episode = None
    elif file_episode is None:
        bare = _extract_hint_bare_number(candidate.name)
        if bare is not None and hint.kind == "series":
            hint_season = hint.season or 1
            if hint_season == 1:
                episode = bare
                reason = f"JellyJake hint (strict): bare episode {bare}"
            else:
                relative = bare - 12 * (hint_season - 1)
                if 1 <= relative <= _HINT_MAX_EPISODE:
                    episode = relative
                    reason = f"JellyJake hint (strict): absolute {bare} -> S{hint_season:02d}E{episode:02d}"
                else:
                    episode = bare
                    flags.append("hint-episode-ambiguous")
                    reason = f"JellyJake hint (strict): absolute {bare} kept as episode (ambiguous)"
    if hint.season is not None and file_season is not None and file_season != hint.season:
        flags.append("hint-season-mismatch")
    return (
        ClassificationResult(
            type=hint.kind,
            title=hint.title,
            year=hint.year,
            season=season,
            episode=episode,
            confidence=1.0,
            reason=reason,
        ),
        flags,
    )


def _incomplete_detection_enabled() -> bool:
    try:
        from app.core.config import get_settings

        return bool(get_settings().enable_incomplete_download_detection)
    except Exception:
        return True

REVISION_RE = re.compile(r"\bv(\d+)\b", re.IGNORECASE)


def target_episode_tag(target_path: str) -> tuple[int, int] | None:
    match = re.search(r"S(\d{1,2})E(\d{1,3})\b", Path(target_path).name, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def target_episode_title_from_item(item: ScannedItem) -> str | None:
    stem = Path(item.target_path).stem
    match = re.search(r"S\d{1,2}E\d{1,3}\b", stem, re.IGNORECASE)
    if not match:
        return None
    title = stem[:match.start()].strip(" -._")
    return title or None


def extract_revision(name: str) -> int:
    matches = REVISION_RE.findall(name)
    if not matches:
        return 0
    return max(int(value) for value in matches)


def is_cross_drive(source_path: str, target_path: str) -> bool:
    import os

    try:
        source_dev = os.stat(source_path).st_dev
        target_parent = Path(target_path).parent
        target_dev = os.stat(target_parent).st_dev
        return source_dev != target_dev
    except OSError:
        return False


def _completed_path_for_marker_rename(source_path: str) -> str | None:
    """Completed path when *source_path* is itself a renamed in-progress file.

    Mirrors ``scanner._renamed_marker_suffix`` / ``_renamed_prefix`` but
    returns the stripped filesystem path (original case preserved) instead of
    a boolean. Returns None when the name is not a marker rename, when
    stripping leaves a non-video extension, or for hidden sidecars (.aria2)
    which never become report items.
    """
    from app.services.scanner import (
        HIDDEN_SIDECAR_SUFFIXES,
        PARTIAL_FILE_MARKERS,
        PARTIAL_FILE_PREFIXES,
    )

    path = Path(source_path)
    name_lower = path.name.lower()
    for marker in sorted(PARTIAL_FILE_MARKERS, key=len, reverse=True):
        if marker in HIDDEN_SIDECAR_SUFFIXES:
            continue
        if name_lower.endswith(marker):
            stripped = path.name[: -len(marker)]
            if Path(stripped).suffix.lower() in VIDEO_EXTENSIONS:
                return str(path.parent / stripped)
    for prefix in PARTIAL_FILE_PREFIXES:
        if name_lower.startswith(prefix) and Path(name_lower[len(prefix):]).suffix in VIDEO_EXTENSIONS:
            return str(path.parent / path.name[len(prefix):])
    return None


def record_scan_errors(manager, scan, errors) -> None:
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
        err_container = None
        err_source_folder = Path(error.path).parent.name or Path(error.path).name
        scan.items.append(
            ScannedItem(
                confirm_id=manager._next_confirm_id(scan),
                source_path=error.path,
                name=path_name,
                item_type="skip",
                confidence=0.0,
                reason=message,
                target_path="",
                action="skip",
                error=error.error,
                file_size=err_size,
                container_path=err_container,
                source_folder=err_source_folder,
            )
        )
        messages.append(f"{error.path} ({error.error})")
    summary = "; ".join(messages)
    if "Filesystem" in scan.service_errors:
        scan.service_errors["Filesystem"] += f"; {summary}"
    else:
        scan.service_errors["Filesystem"] = summary


def group_retarget_pass(manager, scan, planned_targets: dict[str, tuple[int, int]]) -> None:
    """Re-target phantom/wrong series groups onto a real continuation folder."""
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
        group_tags = [target_episode_tag(item.target_path) for item in items]
        group_tags = [tag for tag in group_tags if tag]
        if not group_tags:
            continue
        target_season = max(tag[0] for tag in group_tags)
        found = manager._resolver.find_continuation_show(
            title=show_dir.name,
            year=year,
            season=target_season,
            episode=1,
            episode_title=target_episode_title_from_item(items[0]),
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
        group_tags_all = [target_episode_tag(i.target_path) for i in items]
        group_tags_all = [t for t in group_tags_all if t]
        group_seasons = {t[0] for t in group_tags_all}
        group_episodes = set(group_tags_all)
        existing_seasons = manager._resolver._existing_seasons(new_show_dir)
        for item in items:
            tag = target_episode_tag(item.target_path)
            if not tag:
                continue
            season_number, episode_number = tag
            season_dir = (
                manager._resolver._pick_existing_season_dir(new_show_dir, season_number)
                or new_show_dir / f"Season {season_number:02d}"
            )
            new_target = season_dir / Path(item.target_path).name
            episode_tag = f"s{season_number:02d}e{episode_number:02d}"
            if season_dir.exists():
                for f in season_dir.iterdir():
                    if f.name.startswith(".") or not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    if re.search(rf"{re.escape(episode_tag)}(?:v\d+)?(?=[^a-z0-9]|$)", f.stem.lower()):
                        new_target = f
                        break
            old_target = item.target_path
            item.target_path = str(new_target)
            item.show_folder_exists = new_show_dir.exists()
            item.season_folder_exists = season_dir.exists()
            item.file_exists = new_target.exists()
            item.action = "replace" if item.file_exists else "move"
            # The retarget resolves the phantom show, but continuity gaps at
            # the new location still count (e.g. S05E12 with no S04 on disk
            # and no E11). Recompute instead of blindly clearing suspect.
            regrouped_flags: list[str] = []
            if season_number > 1 and (season_number - 1) not in existing_seasons and (season_number - 1) not in group_seasons:
                regrouped_flags.append("season_gap")
            existing_episodes = manager._resolver._existing_episodes_in_season(season_dir)
            if (
                episode_number > 1
                and (episode_number - 1) not in existing_episodes
                and (season_number, episode_number - 1) not in group_episodes
            ):
                regrouped_flags.append("episode_gap")
            item.suspect = bool(regrouped_flags)
            item.flags = regrouped_flags
            item.corrected = True
            item.correction_note = f"Re-targeted to existing show folder '{new_show_dir.name}'"
            if old_target in planned_targets:
                planned_targets[str(new_target)] = planned_targets.pop(old_target)


async def run_scan_task(manager, scan_id: str, request, previous_task=None) -> None:
    from asyncio import to_thread
    from datetime import UTC, datetime

    from app.services.presenters import format_scan_report
    from app.services.scan_history import save_report

    try:
        if previous_task:
            await previous_task
        if manager._scan_cancel_events[scan_id].is_set():
            return
        await to_thread(run_scan_sync, manager, scan_id, request)
        scan = manager._scan_plans.get(scan_id)
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
            try:
                report = format_scan_report(scan)
                await to_thread(save_report, scan_id, report, manager._config.report_dir)
            except Exception as save_exc:
                logger.warning("Failed to save scan %s to history: %s", scan_id, save_exc)
            # Persist singleton for restart recovery (plan 14)
            try:
                from app.services.scan_history import save_singleton

                logger.info("Saving singleton for scan %s to %s", scan_id, manager._config.report_dir)
                p = await to_thread(save_singleton, scan, manager._config.report_dir)
                logger.info("Singleton saved to %s exists=%s", p, p.exists())
            except Exception as singleton_exc:
                logger.warning("Failed to save singleton for scan %s: %s", scan_id, singleton_exc, exc_info=True)
    except Exception as exc:
        scan = manager._scan_plans.get(scan_id)
        if scan:
            scan.status = "failed"
            scan.finished_at = datetime.now(UTC)
            scan.error = str(exc)
            scan.current_candidate = None
        logger.error("Scan %s failed: %s", scan_id, str(exc), exc_info=True)
    finally:
        from app.services.resolver import clear_resolver_cache as _clear

        _clear()
        manager._scan_tasks.pop(scan_id, None)
        manager._scan_cancel_events.pop(scan_id, None)
        manager._scan_plans.pop(scan_id, None)


def run_scan_sync(manager, scan_id: str, request) -> None:
    from app.services.resolver import clear_resolver_cache
    from app.services.scan_manager import classify_candidate, scan_candidates

    scan = manager._scan_plans.get(scan_id)
    cancel_event = manager._scan_cancel_events.get(scan_id)
    if not scan or not cancel_event:
        return

    clear_resolver_cache()
    manager._resolver.reset_runtime_state()
    manager._resolver.prepare_scan(
        list(manager._config.paths.movie_roots.values()),
        list(manager._config.paths.series_roots.values()),
    )
    # Incremental: seed from existing items present at scan start
    initial_source_paths: set[str] = set()
    initial_items_snapshot: list = []
    # Undo revival: a confirmed item whose source file exists on disk again
    # (history undo moved target->source) must become actionable, otherwise
    # its stale planned_targets entry blocks the restored file as
    # "Lower revision v0 skipped; keeping v0 for same episode" and the item
    # only reappears normally on a full rescan.
    if not getattr(request, "full_rescan", False) and scan.items:
        revived_sources: set[str] = set()
        for it in scan.items:
            if it.confirmed and it.action in ("move", "replace") and it.source_path:
                try:
                    if Path(it.source_path).is_file():
                        it.confirmed = False
                        it.error = None
                        revived_sources.add(it.source_path)
                        if it.action == "move":
                            scan.counts.moved = max(scan.counts.moved - 1, 0)
                        elif it.action == "replace":
                            scan.counts.replaced = max(scan.counts.replaced - 1, 0)
                        logger.info(
                            "Scan %s revived undone item %s (source restored on disk)",
                            scan.scan_id,
                            it.source_path,
                        )
                except OSError:
                    pass
        if revived_sources:
            # Drop stale revision-dedup skips shadowing a revived source so the
            # report shows the actionable item, not a duplicate skip row.
            kept = []
            for it in scan.items:
                reason = it.reason or ""
                if (
                    it.action == "skip"
                    and it.source_path in revived_sources
                    and ("Lower revision" in reason or "Superseded by higher revision" in reason)
                ):
                    scan.counts.skipped = max(scan.counts.skipped - 1, 0)
                    logger.info(
                        "Scan %s dropped stale dedup skip for revived %s",
                        scan.scan_id,
                        it.source_path,
                    )
                    continue
                kept.append(it)
            scan.items[:] = kept
    if not getattr(request, "full_rescan", False) and scan.items:
        initial_source_paths = {it.source_path for it in scan.items if not it.confirmed}
        initial_items_snapshot = list(scan.items)
    planned_targets: dict[str, tuple[int, int]] = {}
    planned_episodes: dict[tuple[str, int], set[int]] = {}
    planned_seasons: dict[str, set[int]] = {}
    # Seed dedup structures from existing report items
    for idx, it in enumerate(scan.items):
        if it.action in ("move", "replace") and it.target_path:
            rev = extract_revision(it.name or Path(it.source_path).name)
            # keep highest revision per target
            existing = planned_targets.get(it.target_path)
            if not existing or rev >= existing[1]:
                planned_targets[it.target_path] = (idx, rev)
        if it.item_type == "series" and it.target_path:
            tag = target_episode_tag(it.target_path)
            if tag and it.action in ("move", "replace"):
                # Derive series_key from resolver if available, else use show folder
                try:
                    sk = Path(it.target_path).parent.parent.name
                except Exception:
                    sk = it.target_path
                # Add season/episode for gap detection (best-effort)
                season_num, ep_num = tag
                planned_seasons.setdefault(sk, set()).add(season_num)
                planned_episodes.setdefault((sk, season_num), set()).add(ep_num)

    scan_result = scan_candidates(manager._config.paths)
    candidates = scan_result.candidates
    scan.total_candidates = len(candidates)
    record_scan_errors(manager, scan, scan_result.errors)
    hint_index = _build_hint_index(getattr(request, "hints", None))
    if hint_index:
        logger.info("Scan %s using %d JellyJake sort hint(s)", scan.scan_id, len(hint_index))
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
        # Incremental dedup: already in report -> preserve existing entry, skip re-adding
        if candidate.source_path in initial_source_paths:
            scan.processed_candidates = index
            continue
        _detect_incomplete = _incomplete_detection_enabled()
        if candidate.in_progress and _detect_incomplete:
            scan.counts.skipped += 1
            logger.warning("Scan %s skipped in-progress download: %s", scan.scan_id, candidate.source_path)
            _cp = candidate.container_path
            _sf = Path(_cp).name if _cp else Path(candidate.source_path).parent.name or candidate.name
            scan.items.append(
                ScannedItem(
                    confirm_id=manager._next_confirm_id(scan),
                    source_path=candidate.source_path,
                    name=candidate.name,
                    item_type="skip",
                    confidence=1.0,
                    reason="In-progress download",
                    target_path="",
                    action="skip",
                    locked=True,
                    file_size=candidate.file_size,
                    container_path=_cp,
                    source_folder=_sf,
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
            _cp2 = candidate.container_path
            _sf2 = Path(_cp2).name if _cp2 else Path(candidate.source_path).parent.name or candidate.name
            scan.items.append(
                ScannedItem(
                    confirm_id=manager._next_confirm_id(scan),
                    source_path=candidate.source_path,
                    name=candidate.name,
                    item_type="skip",
                    confidence=1.0,
                    reason="Zero-byte file; download is incomplete or invalid",
                    target_path="",
                    action="skip",
                    locked=True,
                    file_size=candidate.file_size,
                    container_path=_cp2,
                    source_folder=_sf2,
                )
            )
            scan.processed_candidates = index
            continue

        try:
            hint = _hint_for_candidate(candidate, hint_index)
            hint_flags: list[str] = []
            if hint is not None:
                classification, hint_flags = _classification_from_hint(candidate, hint)
                logger.info(
                    "Scan %s using JellyJake hint for %s: kind=%s title=%s",
                    scan.scan_id,
                    candidate.source_path,
                    classification.kind,
                    classification.title,
                )
            else:
                classification = classify_candidate(candidate, manager._config.series_title_aliases)
            scan.counts.total += 1
            logger.info("Scan %s processing candidate %d/%d: %s", scan.scan_id, scan.counts.total, len(candidates), candidate.source_path)

            if classification.kind == "skip" or classification.confidence < manager._config.model.classify_confidence_threshold:
                scan.counts.skipped += 1
                logger.info(
                    "Scan %s skipped %s: %s",
                    scan.scan_id,
                    candidate.source_path,
                    classification.reason,
                )
                _cp3 = candidate.container_path
                _sf3 = Path(_cp3).name if _cp3 else Path(candidate.source_path).parent.name or candidate.name
                # Plan 17: unlocked skip — still resolve a proposed target so the
                # row is editable (Update Paths / Browse) instead of Delete-only.
                # Only in-progress / missing / error rows stay locked.
                _resolved_target = ""
                _resolved_candidates: list = []
                _show_exists = False
                _season_exists = False
                if classification.kind in ("movie", "series", "extra"):
                    try:
                        _resolved = manager._resolve_sync(candidate, classification)
                        _resolved_target = _resolved.target_path
                        _resolved_candidates = _resolved.candidate_targets
                        _show_exists = _resolved.show_folder_exists
                        _season_exists = _resolved.season_folder_exists
                    except Exception as resolve_exc:
                        logger.warning(
                            "Scan %s could not resolve editable skip target for %s: %s",
                            scan.scan_id,
                            candidate.source_path,
                            resolve_exc,
                        )
                scan.items.append(
                    ScannedItem(
                        confirm_id=manager._next_confirm_id(scan),
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type=classification.kind,
                        confidence=classification.confidence,
                        reason=classification.reason,
                        target_path=_resolved_target,
                        action="skip",
                        locked=False,
                        show_folder_exists=_show_exists,
                        season_folder_exists=_season_exists,
                        file_size=candidate.file_size,
                        container_path=_cp3,
                        source_folder=_sf3,
                        candidate_targets=_resolved_candidates,
                        extra_type=classification.extra_type,
                    )
                )
                scan.processed_candidates = index
                continue

            logger.info("Scan %s resolving target for candidate %d/%d: %s", scan.scan_id, scan.counts.total, len(candidates), candidate.source_path)
            resolved = manager._resolve_sync(candidate, classification)
            logger.info("Scan %s resolved target for %s -> %s", scan.scan_id, candidate.source_path, resolved.target_path)

            target_path = Path(resolved.target_path)
            revision = extract_revision(candidate.name)

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
                    # Plan 17: keep the proposed target so the row stays editable
                    # (re-point and confirm) instead of Delete-only.
                    previous_item.locked = False
                    planned_targets.pop(resolved.target_path, None)
                else:
                    scan.counts.skipped += 1
                    logger.info(
                        "Scan %s skipped lower revision for %s",
                        scan.scan_id,
                        candidate.source_path,
                    )
                    _cp4 = candidate.container_path
                    _sf4 = Path(_cp4).name if _cp4 else Path(candidate.source_path).parent.name or candidate.name
                    scan.items.append(
                        ScannedItem(
                            confirm_id=manager._next_confirm_id(scan),
                            source_path=candidate.source_path,
                            name=candidate.name,
                            item_type=classification.kind,
                            confidence=classification.confidence,
                            reason=f"Lower revision v{revision} skipped; keeping v{existing_revision} for same episode",
                            target_path=resolved.target_path,
                            action="skip",
                            locked=False,
                            show_folder_exists=resolved.show_folder_exists,
                            season_folder_exists=resolved.season_folder_exists,
                            file_size=candidate.file_size,
                            container_path=_cp4,
                            source_folder=_sf4,
                            candidate_targets=resolved.candidate_targets,
                            extra_type=classification.extra_type,
                        )
                    )
                    scan.processed_candidates = index
                    continue

            target_exists = target_path.exists()
            if not target_exists and classification.kind == "movie":
                # Same movie, different container (library .mp4 vs source .mkv):
                # target keeps the source ext (.mkv), old file deleted on confirm.
                from app.services.resolver import find_existing_movie_file

                _sibling = find_existing_movie_file(
                    target_path.parent, target_path.parent.name
                )
                if _sibling is not None and _sibling != target_path:
                    target_exists = True
            action = "replace" if target_exists else "move"
            planned_action = action if request.replace_existing or not target_exists else "skip"
            cross_drive = is_cross_drive(candidate.source_path, resolved.target_path)

            if classification.kind == "movie":
                scan.counts.movies += 1
            elif classification.kind == "series":
                scan.counts.series += 1

            flags: list[str] = list(hint_flags)
            if classification.kind == "movie":
                # Plan 17: size-only sample guess (no `sample` marker) stays an
                # editable movie, flagged suspect so the user double-checks it.
                try:
                    from app.classification.patterns import SAMPLE_MARKERS
                    from app.core.constants import SAMPLE_SIZE_THRESHOLD

                    _label = candidate.relative_path or candidate.name or ""
                    if (
                        candidate.file_size is not None
                        and candidate.file_size < SAMPLE_SIZE_THRESHOLD
                        and not SAMPLE_MARKERS.search(_label)
                    ):
                        flags.append("small-file-sample-suspect")
                except Exception:
                    pass
            if classification.kind == "series" and resolved.season_number and resolved.episode_number:
                series_key = resolved.series_key or ""
                base_key = series_key.split("::")[0] if "::" in series_key else series_key
                has_base_planned = any((k.split("::")[0] if "::" in k else k) == base_key for k in planned_seasons)
                if (
                    resolved.phantom_show_folder
                    and (resolved.season_number > 1 or resolved.episode_number > 1)
                    and series_key not in planned_seasons
                    and not has_base_planned
                ):
                    flags.append("phantom_show_folder")
                # collect seasons for base title to handle year-variant seasons of same show (e.g. Krypton S01 2018 vs S02 2019)
                base_seasons: set[int] = set()
                for k, v in planned_seasons.items():
                    if (k.split("::")[0] if "::" in k else k) == base_key:
                        base_seasons.update(v)
                if (
                    resolved.season_number > 1
                    and not resolved.has_previous_season
                    and (resolved.season_number - 1) not in planned_seasons.get(series_key, set())
                    and (resolved.season_number - 1) not in base_seasons
                ):
                    flags.append("season_gap")
                if (
                    resolved.episode_number > 1
                    and not resolved.has_previous_episode
                    and (resolved.episode_number - 1)
                    not in planned_episodes.get((series_key, resolved.season_number), set())
                ):
                    flags.append("episode_gap")

            # Derive source folder for grouping (per plan 12)
            container_path = candidate.container_path
            if container_path:
                source_folder = Path(container_path).name
            else:
                # Single file or no container: use parent folder name or file name
                source_folder = Path(candidate.source_path).parent.name or Path(candidate.source_path).name
            scan.items.append(
                ScannedItem(
                    confirm_id=manager._next_confirm_id(scan),
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
                    container_path=container_path,
                    source_folder=source_folder,
                    extra_type=classification.extra_type,
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
            _cp5 = candidate.container_path
            _sf5 = Path(_cp5).name if _cp5 else Path(candidate.source_path).parent.name or candidate.name
            scan.items.append(
                    ScannedItem(
                        confirm_id=manager._next_confirm_id(scan),
                        source_path=candidate.source_path,
                        name=candidate.name,
                        item_type="skip",
                        confidence=0.0,
                        reason=f"Error: {exc}",
                        target_path="",
                        action="skip",
                        locked=True,
                        error=str(exc),
                    file_size=candidate.file_size,
                    container_path=_cp5,
                    source_folder=_sf5,
                )
            )
            scan.processed_candidates = index

    # Incremental: mark initial items whose source vanished as missing (preserve but flag).
    # Exception: a renamed in-progress marker (Show.mkv.!qB, incomplete.Show.mkv)
    # whose download has since completed. The client renames marker -> video, so
    # the old marker path is gone and the completed file is a new candidate.
    # Keeping the stale marker as "Source missing" duplicates every finished
    # episode (ready + missing). Drop it instead when the completed file exists
    # on disk or arrived as a new candidate.
    if initial_items_snapshot:
        existing_paths_now = {c.source_path for c in candidates}
        drop_confirm_ids: set[str] = set()
        for old_item in initial_items_snapshot:
            if old_item.confirmed:
                continue
            if old_item.source_path not in existing_paths_now:
                # Verify on disk (candidates may have missed due to filter, but path may still exist as skip)
                # Only mark missing if the file truly no longer exists
                if not Path(old_item.source_path).exists():
                    completed = _completed_path_for_marker_rename(old_item.source_path)
                    if completed is not None and (
                        completed in existing_paths_now or Path(completed).is_file()
                    ):
                        drop_confirm_ids.add(old_item.confirm_id)
                        logger.info(
                            "Scan %s dropped completed in-progress marker %s (now %s)",
                            scan.scan_id,
                            old_item.source_path,
                            completed,
                        )
                        continue
                    if old_item.action != "skip" or "Source missing" not in old_item.reason:
                        was_actionable = old_item.action in ("move", "replace")
                        old_item.action = "skip"
                        old_item.reason = "Source missing on disk"
                        old_item.target_path = ""
                        old_item.error = "missing"
                        old_item.locked = True
                        if was_actionable:
                            if old_item.item_type == "movie":
                                scan.counts.movies = max(scan.counts.movies - 1, 0)
                            elif old_item.item_type == "series":
                                scan.counts.series = max(scan.counts.series - 1, 0)
                            scan.counts.skipped += 1
        if drop_confirm_ids:
            kept = [it for it in scan.items if it.confirm_id not in drop_confirm_ids]
            dropped = len(scan.items) - len(kept)
            scan.items[:] = kept
            scan.counts.skipped = max(scan.counts.skipped - dropped, 0)

    group_retarget_pass(manager, scan, planned_targets)
    manager._resolver.reset_runtime_state()

def resolve_sync(manager, candidate, classification):
    from app.services.scan_manager import asyncio_run_in_thread
    return asyncio_run_in_thread(manager._resolver.resolve(candidate, classification))

async def delete_items(manager, scan_id: str, item_ids: list[str]):
    from pathlib import Path

    from fastapi import HTTPException
    scan = manager.get_scan(scan_id)
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
        item.locked = True
        if was_actionable:
            if item.item_type == "movie":
                scan.counts.movies = max(scan.counts.movies - 1, 0)
            elif item.item_type == "series":
                scan.counts.series = max(scan.counts.series - 1, 0)
            scan.counts.skipped += 1
        deleted.append(item.source_path)
        manager._cleanup_empty_parents(source_path)
    logger.info("Scan %s deleted %d source file(s): %s", scan_id, len(deleted), deleted)
    return scan

