from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_config
from app.models.schemas import ScannedItem, ScanPlan

EPISODE_TAG_RE = re.compile(r"S\d{2}E\d{2,3}", re.IGNORECASE)


def _live_exists_flags(item: ScannedItem) -> tuple[bool, bool, bool]:
    """Live Show/Season/File flags from real disk state (read-only).

    Stored flags snapshot scan time, so pills go stale when folders/files
    appear afterwards (e.g. confirming E01 creates the show + season
    folders that E02-E12 point into, or the user manually places files).
    Folders and the exact target are cheap ``Path.exists()`` stats; the
    stored item is never mutated, so scan-time ``action``/counts and the
    confirm-time "Target file appeared after scan" guard stay intact.
    A stored movie ``file_exists`` from a replaceable sibling is kept only
    while that sibling is still there — a read never flips move→replace.
    """
    try:
        target = Path(item.target_path) if item.target_path else None
        if target is None:
            return item.show_folder_exists, item.season_folder_exists, item.file_exists
        parent = target.parent
        if item.item_type == "series":
            show = parent.parent.exists() if parent.parent else item.show_folder_exists
            season = parent.exists()
            file = target.exists()
            return show, season, file
        folder = parent.exists()
        try:
            file = target.exists()
        except OSError:
            file = item.file_exists
        if not file and item.file_exists:
            try:
                from app.services.resolver import find_existing_movie_file

                sib = find_existing_movie_file(parent, parent.name)
                file = sib is not None
            except OSError:
                file = item.file_exists
        return folder, item.season_folder_exists, file
    except OSError:
        return item.show_folder_exists, item.season_folder_exists, item.file_exists


def _live_path_exists(item: ScannedItem) -> str:
    show, season, file = _live_exists_flags(item)
    if item.item_type == "series":
        return "Show %s, Season %s, File %s" % (
            "\u2713" if show else "\u2717",
            "\u2713" if season else "\u2717",
            "\u2713" if file else "\u2717",
        )
    return "Folder %s, File %s" % (
        "\u2713" if show else "\u2717",
        "\u2713" if file else "\u2717",
    )


def format_path_exists(item: ScannedItem) -> str:
    if item.item_type == "series":
        return "Show %s, Season %s, File %s" % (
            "\u2713" if item.show_folder_exists else "\u2717",
            "\u2713" if item.season_folder_exists else "\u2717",
            "\u2713" if item.file_exists else "\u2717",
        )
    else:
        return "Folder %s, File %s" % (
            "\u2713" if item.show_folder_exists else "\u2717",
            "\u2713" if item.file_exists else "\u2717",
        )


def _candidates_md(item: ScannedItem) -> list[str]:
    if not item.candidate_targets:
        return []
    if item.item_type == "series":
        current_show = str(Path(item.target_path).parent.parent)
    else:
        current_show = str(Path(item.target_path).parent)
    lines = []
    for idx, ct in enumerate(item.candidate_targets, 1):
        if ct.reclassify_as_movie:
            lines.append("   %d. [as movie] `%s` (%s)" % (idx, ct.path, ct.evidence))
        elif ct.path == current_show:
            lines.append("   %d. [current] `%s` (%s)" % (idx, ct.path, ct.evidence))
        else:
            lines.append("   %d. [alt] `%s` (%s)" % (idx, ct.path, ct.evidence))
    return lines


def format_report_md(
    items_by_action: dict[str, list[ScannedItem]],
    movie_roots_info: list[dict],
    series_roots_info: list[dict],
) -> str:
    lines = []
    movies = [i for i in items_by_action["move"] + items_by_action["replace"] if i.item_type == "movie"]
    series = [i for i in items_by_action["move"] + items_by_action["replace"] if i.item_type == "series"]
    extras = [i for i in items_by_action["move"] + items_by_action["replace"] if i.item_type == "extra"]

    if movies:
        lines.append("## Movies (%d)" % len(movies))
        lines.append("| cid | Title | Source | Path Exists | Target |")
        lines.append("|-----|-------|--------|-------------|--------|")
        for item in movies:
            title = Path(item.target_path).parent.name
            source = item.source_path
            lines.append("| %s | %s | %s | %s | `%s` |" % (item.confirm_id, title, source, _live_path_exists(item), item.target_path))
        lines.append("")
        movie_candidate_blocks: list[tuple[str, tuple[str, ...], list[str]]] = []
        for item in movies:
            blocks = _candidates_md(item)
            if blocks:
                key = (Path(item.target_path).parent.name, tuple(ct.path for ct in item.candidate_targets))
                if key not in {b[1] for b in movie_candidate_blocks}:
                    movie_candidate_blocks.append((key[0], key[1], blocks))
        for title, _, blocks in movie_candidate_blocks:
            lines.append("### %s candidates" % title)
            lines.extend(blocks)
            lines.append("")

    if series:
        lines.append("## Series (%d)" % len(series))
        lines.append("| cid | Show | Season | Ep | Source | Path Exists | Target |")
        lines.append("|-----|------|--------|----|--------|-------------|--------|")
        for item in series:
            p = Path(item.target_path)
            show = p.parent.parent.name if p.parent.parent else p.parent.name
            season = p.parent.name
            tag_match = EPISODE_TAG_RE.search(p.name)
            ep = tag_match.group(0) if tag_match else p.stem
            source = item.source_path
            lines.append("| %s | %s | %s | %s | %s | %s | `%s` |" % (item.confirm_id, show, season, ep, source, _live_path_exists(item), item.target_path))
        lines.append("")
        series_candidate_blocks: list[tuple[str, tuple[str, ...], list[str]]] = []
        for item in series:
            blocks = _candidates_md(item)
            if blocks:
                key = (Path(item.target_path).parent.parent.name, tuple(ct.path for ct in item.candidate_targets))
                if key not in {b[1] for b in series_candidate_blocks}:
                    series_candidate_blocks.append((key[0], key[1], blocks))
        for title, _, blocks in series_candidate_blocks:
            lines.append("### %s candidates" % title)
            lines.extend(blocks)
            lines.append("")

    if extras:
        lines.append("## Extras (%d)" % len(extras))
        lines.append("| cid | Source | Path Exists | Target |")
        lines.append("|-----|--------|-------------|--------|")
        for item in extras:
            source = item.source_path
            lines.append("| %s | %s | %s | `%s` |" % (item.confirm_id, source, _live_path_exists(item), item.target_path))
        lines.append("")

    if items_by_action["skip"]:
        by_reason: dict[str, list[str]] = {}
        for item in items_by_action["skip"]:
            key = item.reason[:120]
            by_reason.setdefault(key, []).append(item.source_path)

        lines.append("## Skipped (%d)" % len(items_by_action["skip"]))
        for reason, paths in by_reason.items():
            lines.append("- [%d] %s" % (len(paths), reason))
            for p in paths[:2]:
                lines.append("  - `%s`" % p)
            if len(paths) > 2:
                lines.append("  - ... and %d more" % (len(paths) - 2))
        lines.append("")

    return "\n".join(lines).strip()


def format_report_items(scan: ScanPlan, items_by_action: dict[str, list[ScannedItem]]) -> list[dict]:
    """Return structured items (actionable + skipped) for the Web UI."""
    result = []
    for item in items_by_action.get("move", []) + items_by_action.get("replace", []):
        live_show, live_season, live_file = _live_exists_flags(item)
        result.append({
            "confirmId": item.confirm_id,
            "id": item.confirm_id,
            "sourcePath": item.source_path,
            "name": item.name,
            "targetPath": item.target_path,
            "itemType": item.item_type,
            "item_type": item.item_type,
            "action": item.action,
            "pathExists": _live_path_exists(item),
            "showFolderExists": live_show,
            "seasonFolderExists": live_season,
            "fileExists": live_file,
            "fileSize": item.file_size,
            "crossDrive": item.cross_drive,
            "reason": item.reason,
            "error": item.error,
            "suspect": item.suspect,
            "flags": item.flags,
            "corrected": item.corrected,
            "correctionNote": item.correction_note,
            "containerPath": item.container_path,
            "sourceFolder": item.source_folder,
            "extraType": item.extra_type,
            "extra_type": item.extra_type,
            "candidateTargets": [
                {
                    "path": ct.path,
                    "label": ct.label,
                    "evidence": ct.evidence,
                    "source": ct.source,
                    "reclassifyAsMovie": ct.reclassify_as_movie,
                }
                for ct in item.candidate_targets
            ],
        })
    for item in items_by_action.get("skip", []):
        live_show, live_season, live_file = _live_exists_flags(item)
        result.append({
            "confirmId": item.confirm_id,
            "id": item.confirm_id,
            "sourcePath": item.source_path,
            "name": item.name,
            "targetPath": item.target_path,
            "itemType": item.item_type,
            "item_type": item.item_type,
            "action": "skip",
            "locked": bool(getattr(item, "locked", False)),
            "pathExists": _live_path_exists(item),
            "showFolderExists": live_show,
            "seasonFolderExists": live_season,
            "fileExists": live_file,
            "fileSize": item.file_size,
            "crossDrive": item.cross_drive,
            "reason": item.reason,
            "error": item.error,
            "suspect": item.suspect,
            "flags": item.flags,
            "corrected": item.corrected,
            "correctionNote": item.correction_note,
            "containerPath": item.container_path,
            "sourceFolder": item.source_folder,
            "extraType": item.extra_type,
            "extra_type": item.extra_type,
            "candidateTargets": [
                {
                    "path": ct.path,
                    "label": ct.label,
                    "evidence": ct.evidence,
                    "source": ct.source,
                    "reclassifyAsMovie": ct.reclassify_as_movie,
                }
                for ct in item.candidate_targets
            ],
        })
    return result


def report_llm_instructions(scan: ScanPlan, movie_roots_info: list[dict], series_roots_info: list[dict]) -> list[str]:
    unconfirmed = scan.counts.movies + scan.counts.series
    if unconfirmed == 0 or scan.status == "confirmed":
        return []

    roots = []
    for label, info in [("movies", movie_roots_info), ("series", series_roots_info)]:
        for r in info:
            roots.append(f"  {r['path']} → {r['description']}")

    instructions = [
        "You are curating the library, not just moving files.",
        "pathExists shows granular path status: Show/Movie ✓/✗, Season ✓/✗, File ✓/✗",
        "showFolderExists/seasonFolderExists/fileExists give individual booleans",
    ]

    suspect_count = len([i for i in scan.items if i.suspect])
    corrected_count = len([i for i in scan.items if i.corrected])
    if suspect_count:
        instructions.append(
            f"{suspect_count} item(s) are flagged suspect (flags: phantom_show_folder, season_gap, episode_gap). "
            "Review their targets: a suspect item may point at a newly created show folder when an existing "
            "continuation folder already exists."
        )
    if corrected_count:
        instructions.append(
            f"{corrected_count} item(s) were auto-corrected during the scan. Verify the correction made sense "
            "before confirming."
        )
    instructions.append(
        "Each actionable item exposes candidateTargets (existing folders with evidence, a new-folder default, "
        "and optionally an 'as movie' option). If the assigned target is wrong, pick a candidate directory "
        "via the retarget endpoint instead of hand-building a path."
    )

    if roots:
        instructions.append("Available roots:\n" + "\n".join(roots))

    instructions.extend([
        "Path validation: compare each item's Source filename with its targetPath. "
        "If the show or movie folder names in targetPath look wrong or don't match "
        "the source, update them using the update tool below.",
        "Root curation: each root has a description. "
        "Check whether each item's content belongs in its assigned root based on the root descriptions. "
        "If another root is a better fit, redirect the item there.",
    ])

    instructions.append(
        "To redirect an item, call 'update move new downloads scan' "
        "with items=[{\"confirmId\": \"...\", \"targetPath\": \"<new full path>\"}]. "
        "Then fetch this report again, then confirm."
    )

    return instructions


def report_next_step(scan: ScanPlan) -> str:
    unconfirmed = len([item for item in scan.items if not item.confirmed and item.action in ("move", "replace")])

    if unconfirmed == 0 or scan.status == "confirmed":
        parts = ["All items done. Run 'move new downloads scan' for a new scan."]
    else:
        parts = [
            f"{unconfirmed} items pending.",
            "If the user asked to move/organize these downloads, that request IS the approval: sanity-check the "
            "target paths and roots yourself, fix any wrong target with 'update move new downloads scan', then "
            "call 'confirm move new downloads scan' right away (use sourcePrefixes or confirmIds to limit it to "
            "the release the user asked for). Do not ask the user to approve; only ask if a target is genuinely "
            "ambiguous and none of the candidateTargets fit.",
        ]

    next_step = " ".join(parts)
    if "Filesystem" in scan.service_errors:
        next_step += " Some paths could not be scanned; check skipped items."
    return next_step


def format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds_int = max(int(seconds), 0)
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_transfer_speed(bytes_per_second: float | None) -> str | None:
    if bytes_per_second is None or bytes_per_second <= 0:
        return None
    size = float(bytes_per_second)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s", "TB/s"):
        if size < 1024 or unit == "TB/s":
            return f"{size:.1f} {unit}" if unit != "B/s" else f"{int(size)} B/s"
        size /= 1024
    return None


def _transfer_group_title(item_type: str, target_path: str, name: str) -> str:
    """Group label for transfer-panel sections.

    Mirrors the frontend ``mapReportItems`` title rule (``report.js``): series
    groups by the show folder (third-from-last target part), everything else by
    the enclosing folder (second-from-last).
    """
    parts = [p for p in (target_path or "").split("/") if p]
    if item_type == "series" and target_path:
        return parts[-3] if len(parts) >= 3 else (parts[0] if parts else name)
    if target_path:
        return parts[-2] if len(parts) >= 2 else (parts[0] if parts else name)
    return name


def _transfer_queue_groups(scan: ScanPlan) -> list[dict]:
    """Per-file grouped payload for the transfer panel (``queue_groups``).

    Running batch first (from ``confirm_item_ids``), then one section per
    queued batch (from ``confirm_queue_item_ids``), each sub-grouped by the
    show/movie title. ``failed`` mirrors ``bool(item.error)`` — failed items
    keep ``confirmed=False``.
    """
    by_id = {item.confirm_id: item for item in scan.items}

    def section(ids: list[str], batch: str) -> list[dict]:
        groups: dict[str, dict] = {}
        order: list[str] = []
        for cid in ids:
            item = by_id.get(cid)
            if item is None:
                continue
            title = _transfer_group_title(item.item_type, item.target_path, item.name)
            if title not in groups:
                groups[title] = {"group": title, "kind": item.item_type, "batch": batch, "items": []}
                order.append(title)
            source_name = (item.source_path or "").split("/")[-1] if item.source_path else item.name
            groups[title]["items"].append(
                {
                    "confirm_id": item.confirm_id,
                    "source_path": item.source_path,
                    "source_name": source_name or item.name,
                    "target_path": item.target_path,
                    "kind": item.item_type,
                    "confirmed": item.confirmed,
                    "failed": bool(item.error),
                }
            )
        return [groups[t] for t in order]

    groups = section(list(scan.confirm_item_ids), "running")
    for batch_ids in scan.confirm_queue_item_ids:
        groups.extend(section(list(batch_ids), "queued"))
    return groups


def format_confirm_progress(scan: ScanPlan) -> dict:
    now = datetime.now(UTC)
    started_at = scan.confirm_started_at or now
    elapsed_seconds = max((now - started_at).total_seconds(), 0.0)
    processed = scan.confirm_processed
    total = scan.confirm_total
    percent = round((processed / total) * 100, 1) if total else 0.0
    eta_seconds = None
    current_speed = scan.confirm_current_speed_bytes
    file_eta_seconds = None
    if (
        scan.confirm_status == "running"
        and scan.confirm_current_size_bytes
        and scan.confirm_current_copied_bytes is not None
        and current_speed
        and current_speed > 0
        and scan.confirm_current_copied_bytes < scan.confirm_current_size_bytes
    ):
        remaining = scan.confirm_current_size_bytes - scan.confirm_current_copied_bytes
        file_eta_seconds = remaining / current_speed
    if scan.confirm_status == "running" and processed > 0 and total > processed:
        seconds_per_item = elapsed_seconds / processed
        eta_seconds = seconds_per_item * (total - processed)

    next_step = (
        "Confirm finished. Jellyfin library scans were triggered automatically for the moved items. "
        "Tell the user the result (what moved where, and any failures). The task is complete."
    )
    if scan.confirm_status == "running":
        next_step = (
            "Confirm is running. Do not ask the user. Immediately call 'get move new downloads confirm progress' "
            "again (it waits up to waitSeconds for the move to finish) and repeat until confirm_status is not running."
        )
        if scan.confirm_queue_length:
            next_step = (
                f"Confirm is running. {scan.confirm_queue_length} more confirm(s) "
                f"({scan.confirm_queue_items} item(s)) are queued and will start "
                "automatically when the current move finishes. Keep calling "
                "'get move new downloads confirm progress' until everything is done; do not ask the user."
            )
    elif scan.confirm_status == "idle":
        next_step = "No confirm has been started. Use 'confirm move new downloads scan' first."

    return {
        "tool_purpose": "Reports progress for a running confirm operation. This tool is read-only and does not move files.",
        "scan_id": scan.scan_id,
        "status": scan.confirm_status,
        "phase": scan.confirm_phase,
        "processed": processed,
        "total": total,
        "percent": percent,
        "current_file": scan.confirm_current_item,
        "current_target": scan.confirm_current_target,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "elapsed": format_duration(elapsed_seconds),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        "eta": format_duration(eta_seconds),
        "current_size_bytes": scan.confirm_current_size_bytes,
        "current_copied_bytes": scan.confirm_current_copied_bytes,
        "current_speed_bytes": round(current_speed, 1) if current_speed is not None else None,
        "current_speed": format_transfer_speed(current_speed),
        "current_percent": scan.confirm_current_percent,
        "current_eta_seconds": round(file_eta_seconds, 1) if file_eta_seconds is not None else None,
        "current_eta": format_duration(file_eta_seconds),
        "cross_drive": scan.confirm_cross_drive,
        "note": scan.confirm_note,
        "queue_length": scan.confirm_queue_length,
        "queue_items": scan.confirm_queue_items,
        "queue_groups": _transfer_queue_groups(scan),
        "last_update_at": scan.confirm_last_update_at.isoformat() if scan.confirm_last_update_at else None,
        "counts": {
            "moved": scan.counts.moved - scan.confirm_start_moved,
            "replaced": scan.counts.replaced - scan.confirm_start_replaced,
            "failed": scan.counts.failed - scan.confirm_start_failed,
        },
        "next": next_step,
    }


def is_cross_drive_transfer() -> bool:
    config = get_config()
    download_paths = [Path(p) for p in config.paths.download_roots if Path(p).exists()]
    media_paths = [Path(p) for p in list(config.paths.movie_roots.values()) + list(config.paths.series_roots.values()) if Path(p).exists()]
    if not download_paths or not media_paths:
        return False
    devices: set[int] = set()
    for p in download_paths:
        try:
            devices.add(p.stat().st_dev)
        except OSError:
            pass
    for p in media_paths:
        try:
            if p.stat().st_dev not in devices:
                return True
        except OSError:
            pass
    return False


def format_scan_progress(scan: ScanPlan) -> dict:
    now = datetime.now(UTC)
    started_at = scan.started_at or scan.created_at
    finished_at = scan.finished_at or now
    elapsed_seconds = max((finished_at - started_at).total_seconds(), 0.0)
    processed = scan.processed_candidates
    total = scan.total_candidates
    percent = round((processed / total) * 100, 1) if total else 0.0
    eta_seconds = None
    if scan.status == "running" and processed > 0 and total > processed:
        seconds_per_item = elapsed_seconds / processed
        eta_seconds = seconds_per_item * (total - processed)

    next_step = (
        "Scan is complete. Now call 'get move new downloads scan report' (pass search=<release/show name> to "
        "fetch only the release the user cares about), then continue to confirm without asking the user."
    )
    if scan.status == "running":
        next_step = (
            "Scan is still running. Do not ask the user. Immediately call 'get move new downloads scan progress' "
            "again (it waits up to waitSeconds for the scan to finish) and repeat until status is completed."
        )
    elif scan.status == "cancelled":
        next_step = "Scan was cancelled because a newer scan was started. Check progress for the newer scan."
    elif scan.status == "failed":
        next_step = "Scan failed. Review the error, then run 'move new downloads scan' again after fixing the issue."

    return {
        "tool_purpose": "Reports progress for a background download-organizer scan. This progress tool is read-only and does not move files.",
        "scan_id": scan.scan_id,
        "status": scan.status,
        "processed": processed,
        "total": total,
        "current_index": scan.current_candidate_index,
        "current_file": scan.current_candidate,
        "percent": percent,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "elapsed": format_duration(elapsed_seconds),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        "eta": format_duration(eta_seconds),
        "counts": scan.counts.model_dump(mode="json"),
        "available_information": {
            "current_file": "The file path currently being processed, or null if the scan is not actively processing a file.",
            "processed": "How many candidate files have been processed so far.",
            "total": "How many candidate files were found for this scan.",
            "eta": "Estimated remaining time based on elapsed time and processed candidate count. It is approximate.",
        },
        "next": next_step,
    }


GENERIC_SOURCE_FOLDERS = frozenset({"downloads", "torrents", "download", "complete", "incomplete"})


def format_report_grouped(items_by_action: dict[str, list[ScannedItem]]) -> list[dict]:
    """Group actionable+skipped items by sourceFolder (download folder)."""
    grouped: dict[str, dict] = {}
    for bucket in ("move", "replace", "skip"):
        for item in items_by_action.get(bucket, []):
            key = item.source_folder or (Path(item.container_path).name if item.container_path else None) or item.source_path
            # Fallback for generic download root names -> use source_path basename
            if key and key.lower() in GENERIC_SOURCE_FOLDERS:
                key = Path(item.source_path).name or key
            if not key:
                key = "Unknown"
            entry = grouped.get(key)
            if not entry:
                grouped[key] = {
                    "sourceFolder": key,
                    "containerPath": item.container_path or "",
                    "count": 0,
                    "totalSize": 0,
                    "items": [],
                }
                entry = grouped[key]
            entry["count"] += 1
            if item.file_size:
                entry["totalSize"] += int(item.file_size)
            live_show, live_season, live_file = _live_exists_flags(item)
            entry["items"].append({
                "confirmId": item.confirm_id,
                "id": item.confirm_id,
                "sourcePath": item.source_path,
                "name": item.name,
                "targetPath": item.target_path,
                "itemType": item.item_type,
                "item_type": item.item_type,
                "action": item.action,
                "fileSize": item.file_size,
                "pathExists": _live_path_exists(item),
                "showFolderExists": live_show,
                "seasonFolderExists": live_season,
                "fileExists": live_file,
                "crossDrive": item.cross_drive,
                "reason": item.reason,
                "error": item.error,
                "suspect": item.suspect,
                "flags": item.flags,
                "corrected": item.corrected,
                "correctionNote": item.correction_note,
                "containerPath": item.container_path,
                "sourceFolder": item.source_folder,
                "extraType": item.extra_type,
                "extra_type": item.extra_type,
                "candidateTargets": [
                    {"path": ct.path, "label": ct.label, "evidence": ct.evidence, "source": ct.source, "reclassifyAsMovie": ct.reclassify_as_movie}
                    for ct in item.candidate_targets
                ],
            })
    # Newest groups/items first so incremental scans surface new files at the top
    for g in grouped.values():
        try:
            g["items"].sort(key=lambda it: int(str(it["confirmId"]).lstrip("i") or 0), reverse=True)
        except Exception:
            pass
    def _group_max_id(g):
        try:
            return max(int(str(it["confirmId"]).lstrip("i") or 0) for it in g["items"])
        except Exception:
            return 0
    return sorted(grouped.values(), key=lambda g: _group_max_id(g), reverse=True)


def _item_matches_search(item, search: str) -> bool:
    """Case-insensitive token match against an item's name, source and target paths.

    Punctuation is ignored so ``neutral show s01`` matches ``Neutral.Show.S01E01...``.
    Every search token must appear somewhere in the haystack.
    """
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower())

    haystack = norm(" ".join(filter(None, [
        item.name, item.source_path, item.target_path, item.source_folder, item.container_path,
    ])))
    compact = haystack.replace(" ", "")
    return all(tok in haystack or tok in compact for tok in norm(search).split())


def format_scan_report(scan: ScanPlan, format: str = "markdown", group_by: str = "sourceFolder", search: str | None = None) -> dict:
    if scan.status == "running":
        progress = format_scan_progress(scan)
        return {
            "tool_purpose": "Returns the completed scan report. While a scan is running, this response is intentionally compact and redirects the LLM to the progress tool.",
            "summary": {
                "scan_id": scan.scan_id,
                "status": scan.status,
            },
            "progress": progress,
            "llm_instructions": [
                "The scan is still running, so there is no report yet. Do not ask the user anything.",
                "Call 'get move new downloads scan progress' with this scanId (it waits up to waitSeconds); repeat until status is completed.",
                "Then call this report tool again and continue the workflow.",
            ],
            "next": "Scan is still running. Do not ask the user; keep calling 'get move new downloads scan progress' until it completes.",
        }

    items_by_action = {"move": [], "replace": [], "skip": []}
    search = (search or "").strip()
    for item in scan.items:
        if item.confirmed:
            continue
        if search and not _item_matches_search(item, search):
            continue
        if item.action in items_by_action:
            items_by_action[item.action].append(item)

    config = get_config()
    movie_roots_info = [
        {
            "path": path,
            "description": config.paths.movie_root_descriptions.get(key, ""),
        }
        for key, path in config.paths.movie_roots.items()
    ]
    series_roots_info = [
        {
            "path": path,
            "description": config.paths.series_root_descriptions.get(key, ""),
        }
        for key, path in config.paths.series_roots.items()
    ]

    summary = {
        "scan_id": scan.scan_id,
        "status": scan.status,
        "total": scan.counts.total,
        "movies": scan.counts.movies,
        "series": scan.counts.series,
        "skipped": scan.counts.skipped,
        "moved": scan.counts.moved,
        "replaced": scan.counts.replaced,
        "failed": scan.counts.failed,
        "action_required": len(items_by_action["move"]) + len(items_by_action["replace"]),
    }

    if movie_roots_info:
        summary["movie_roots"] = movie_roots_info
    if series_roots_info:
        summary["series_roots"] = series_roots_info

    report: dict = {
        "summary": summary,
        "items": format_report_items(scan, items_by_action),
    }
    if format == "json" and group_by == "sourceFolder":
        report["groups"] = format_report_grouped(items_by_action)
    else:
        report["report_md"] = format_report_md(items_by_action, movie_roots_info, series_roots_info)

    if search:
        report["search"] = search
        report["summary"]["matched"] = sum(len(v) for v in items_by_action.values())
        if not report["summary"]["matched"]:
            report["search_hint"] = (
                f"No unconfirmed items match '{search}'. Try a shorter search (just the show name), or check "
                "whether it was already moved. If the download finished after this scan, run "
                "'move new downloads scan' again."
            )

    if scan.service_errors:
        report["service_errors"] = scan.service_errors

    report["llm_instructions"] = report_llm_instructions(scan, movie_roots_info, series_roots_info)
    report["next"] = report_next_step(scan)
    return report
