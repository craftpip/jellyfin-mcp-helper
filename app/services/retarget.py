# mypy: ignore-errors
"""Retarget / plan-edit domain (plan 1.1 slice A).

Houses the "edit a completed scan plan" logic: update paths, browse-retarget
with group propagation and movie reclassification. ScanManager keeps thin
delegates so every call site and test stays untouched.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import HTTPException

from app.core.constants import VIDEO_EXTENSIONS
from app.models.schemas import ScannedItem, ScanPlan
from app.services.path_validator import validate_directory, validate_target_path

logger = logging.getLogger(__name__)

_EPISODE_TAG_RE = re.compile(r"S(\d{1,2})E(\d{1,3})", re.IGNORECASE)


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


def is_show_level_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return True
    try:
        entries = [e for e in path.iterdir() if not e.name.startswith(".")]
    except OSError:
        return True
    has_video_file = any(e.is_file() and e.suffix.lower() in VIDEO_EXTENSIONS for e in entries)
    has_subdir = any(e.is_dir() for e in entries)
    return not has_video_file and has_subdir


def source_episode_tag(item: ScannedItem) -> tuple[int, int] | None:
    """Extract (season, episode) from the source filename."""
    match = _EPISODE_TAG_RE.search(Path(item.source_path).name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def effective_type(item: ScannedItem, reclassify_as_movie: bool) -> str:
    """Return the effective item kind, using the source path as ground truth.

    The source filename is immutable — an ``SxxEyy`` tag means the file is
    a series episode regardless of what ``item.item_type`` currently says
    (it may have been mutated by a prior reclassify retarget).
    """
    if reclassify_as_movie:
        return "movie"
    if _EPISODE_TAG_RE.search(Path(item.source_path).name):
        return "series"
    return item.item_type


def apply_retarget(item: ScannedItem, directory: Path, reclassify_as_movie: bool, resolver) -> None:
    """Recompute an item's target path from a chosen directory.

    The *effective* item type is derived from three inputs:
    1. ``reclassify_as_movie`` — explicit user request to treat as movie.
    2. ``item.source_path`` — the immutable source filename.  An ``SxxEyy``
       tag in the source name means the file is a series episode regardless
       of what ``item.item_type`` currently says (it may have been changed
       by a prior reclassify retarget).
    3. ``item.item_type`` — fallback when neither of the above applies
       (genuine movie, already-series, etc.).

    Using the source path as ground truth means a series→movie→series
    round-trip always recovers the correct season subdirectory and episode
    filename.
    """
    ext = Path(item.target_path).suffix or ".mkv"
    eff_type = effective_type(item, reclassify_as_movie)
    source_tag = source_episode_tag(item)

    # --- compute target path by effective type ---
    if eff_type == "movie":
        base_name = directory.name or "Movie"
        target_path = directory / f"{base_name}{ext}"
    else:
        season_number = source_tag[0] if source_tag else 1
        # Prefer source tag for episode number too; fall back to target
        # tag (which may be stale after a prior reclassify).
        episode_number = source_tag[1] if source_tag else None

        # The show name for the episode filename.  When the user picks a
        # season-level folder the show is the parent; when they pick a
        # show-level folder it is the directory itself.
        if is_show_level_dir(directory):
            show_name = directory.name
            season_dir = (
                resolver._pick_existing_season_dir(directory, season_number)
                or directory / f"Season {season_number:02d}"
            )
        else:
            show_name = directory.parent.name
            season_dir = directory

        if source_tag:
            target_path = season_dir / f"{show_name} - S{season_number:02d}E{episode_number:02d}{ext}"
        else:
            target_path = season_dir / Path(item.target_path).name

        # Check for an existing file matching this episode in the season dir.
        ep_num = episode_number or (target_episode_tag(item.target_path) or (1, 1))[1]
        episode_tag = f"s{season_number:02d}e{ep_num:02d}"
        if season_dir.exists():
            for f in season_dir.iterdir():
                if f.name.startswith(".") or not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                if re.search(rf"{re.escape(episode_tag)}(?:v\d+)?(?=[^a-z0-9]|$)", f.stem.lower()):
                    target_path = f
                    break

    # --- persist ---
    item.item_type = eff_type
    item.target_path = str(target_path)
    _refresh_item_flags(item, target_path)


def refresh_item_after_target_change(item: ScannedItem, target_path: Path) -> None:
    """Recompute exists/action/flags after any target change."""
    item.action = "replace" if target_path.exists() else "move"
    parent = target_path.parent
    item.season_folder_exists = parent.exists()
    if item.item_type == "series":
        item.show_folder_exists = parent.parent.exists() if parent.parent else False
    else:
        item.show_folder_exists = parent.exists()
    item.file_exists = target_path.exists()


def _refresh_item_flags(item: ScannedItem, target_path: Path) -> None:
    refresh_item_after_target_change(item, target_path)
    item.suspect = False
    item.flags = []
    item.corrected = False
    item.correction_note = None


def _allowed_roots(manager) -> list[Path]:
    return [
        Path(root).resolve(strict=False)
        for root in list(manager._config.paths.movie_roots.values())
        + list(manager._config.paths.series_roots.values())
    ]


def _ensure_editable(scan: ScanPlan) -> None:
    if scan.status == "confirmed":
        raise HTTPException(status_code=400, detail="Cannot update a confirmed scan")
    if scan.status == "running":
        raise HTTPException(status_code=400, detail="Scan is still running. Wait for it to complete before updating.")
    if scan.status == "failed":
        raise HTTPException(status_code=400, detail="Scan failed. Run a new scan before updating.")


def update_scan(manager, scan_id: str, items: list[dict]) -> ScanPlan:
    scan = manager.get_scan(scan_id)
    _ensure_editable(scan)

    updates_by_id = {u["confirmId"]: u["targetPath"] for u in items}
    allowed_roots = _allowed_roots(manager)
    updated_count = 0

    for item in scan.items:
        if item.confirm_id not in updates_by_id:
            continue
        new_target = updates_by_id[item.confirm_id]
        if item.action == "skip" or item.item_type == "skip":
            raise HTTPException(status_code=400, detail=f"Item '{item.confirm_id}' is skipped and cannot be redirected")

        target_path_obj = validate_target_path(new_target, allowed_roots)

        item.target_path = str(target_path_obj)
        refresh_item_after_target_change(item, target_path_obj)
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
    manager,
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
    scan = manager.get_scan(scan_id)
    _ensure_editable(scan)

    item = next((i for i in scan.items if i.confirm_id == confirm_id), None)
    if not item:
        raise HTTPException(status_code=400, detail=f"No item found for confirmId '{confirm_id}'")
    if item.action == "skip" or item.item_type == "skip":
        raise HTTPException(status_code=400, detail=f"Item '{confirm_id}' is skipped and cannot be redirected")
    if reclassify_as_movie and apply_to_group:
        raise HTTPException(status_code=400, detail="Cannot apply 'as movie' reclassification to a group")

    allowed_roots = _allowed_roots(manager)
    directory_obj = validate_directory(directory, allowed_roots)

    target_items = [item]
    if apply_to_group:
        item_eff_type = effective_type(item, reclassify_as_movie)
        if item_eff_type == "series":
            group_key = str(Path(item.target_path).parent.parent)
            group_items = [
                i for i in scan.items
                if i.action != "skip" and i.item_type != "skip"
                and effective_type(i, False) == "series"
                and str(Path(i.target_path).parent.parent) == group_key
            ]
        else:
            group_key = str(Path(item.target_path).parent)
            group_items = [
                i for i in scan.items
                if i.action != "skip" and i.item_type != "skip"
                and effective_type(i, False) != "series"
                and str(Path(i.target_path).parent) == group_key
            ]
        if group_items:
            target_items = group_items

    if apply_to_group and effective_type(item, reclassify_as_movie) == "series":
        seasons = set()
        for group_item in target_items:
            tag = target_episode_tag(group_item.target_path)
            if tag:
                seasons.add(tag[0])
        if len(seasons) > 1 and not is_show_level_dir(directory_obj):
            raise HTTPException(
                status_code=400,
                detail="Group spans multiple seasons — pick a show-level folder so each item joins its own season subfolder",
            )

    for target_item in target_items:
        apply_retarget(target_item, directory_obj, reclassify_as_movie, manager._resolver)

    logger.info(
        "Scan %s retargeted confirmId=%s to %s (group=%s, as_movie=%s) — %d item(s)",
        scan_id, confirm_id, directory, apply_to_group, reclassify_as_movie, len(target_items),
    )
    return scan
