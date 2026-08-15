from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_config
from app.models.schemas import ScanPlan, ScannedItem


EPISODE_TAG_RE = re.compile(r"S\d{2}E\d{2,3}", re.IGNORECASE)


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

    if movies:
        lines.append("## Movies (%d)" % len(movies))
        lines.append("| cid | Title | Source | Path Exists | Target |")
        lines.append("|-----|-------|--------|-------------|--------|")
        for item in movies:
            title = Path(item.target_path).parent.name
            source = item.source_path
            lines.append("| %s | %s | %s | %s | `%s` |" % (item.confirm_id, title, source, format_path_exists(item), item.target_path))
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
            lines.append("| %s | %s | %s | %s | %s | %s | `%s` |" % (item.confirm_id, show, season, ep, source, format_path_exists(item), item.target_path))
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
        result.append({
            "confirmId": item.confirm_id,
            "sourcePath": item.source_path,
            "name": item.name,
            "targetPath": item.target_path,
            "itemType": item.item_type,
            "action": item.action,
            "pathExists": format_path_exists(item),
            "showFolderExists": item.show_folder_exists,
            "seasonFolderExists": item.season_folder_exists,
            "fileExists": item.file_exists,
            "fileSize": item.file_size,
            "crossDrive": item.cross_drive,
            "reason": item.reason,
            "error": item.error,
            "suspect": item.suspect,
            "flags": item.flags,
            "corrected": item.corrected,
            "correctionNote": item.correction_note,
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
        result.append({
            "confirmId": item.confirm_id,
            "sourcePath": item.source_path,
            "name": item.name,
            "itemType": item.item_type,
            "action": "skip",
            "fileSize": item.file_size,
            "reason": item.reason,
            "error": item.error,
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
            f"{unconfirmed} items pending. Review each item below.",
            "Check that target paths are correct and roots match the content description before confirming.",
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

    next_step = "Confirm finished. Call 'get move new downloads scan report' to see results."
    if scan.confirm_status == "running":
        next_step = "Confirm is running. Call 'get move new downloads confirm progress' again later."
        if scan.confirm_queue_length:
            next_step = (
                f"Confirm is running. {scan.confirm_queue_length} more confirm(s) "
                f"({scan.confirm_queue_items} item(s)) are queued and will start "
                "automatically when the current move finishes."
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

    next_step = "Scan is complete. Call 'get move new downloads scan report' to review planned moves before confirming."
    if scan.status == "running":
        next_step = "Scan is still running. Tell the user and ask if they want to check progress again later."
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


def format_scan_report(scan: ScanPlan) -> dict:
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
                "Do not review or summarize the full report yet because the scan is still running.",
                "Tell the user the scan is still running and ask if they want to check progress.",
                "If the user says yes, call 'get move new downloads scan progress' with this scanId.",
                "If still running, tell the user and ask if they want to check again later.",
                "After progress status is completed, call this report tool again to review planned actions.",
                "Do not confirm/apply anything until the completed report has been reviewed and the user explicitly approves.",
            ],
            "next": "Scan is still running. Tell the user and ask if they want progress.",
        }

    items_by_action = {"move": [], "replace": [], "skip": []}
    for item in scan.items:
        if item.confirmed:
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
        "action_required": len(items_by_action["move"]) + len(items_by_action["replace"]),
    }

    if movie_roots_info:
        summary["movie_roots"] = movie_roots_info
    if series_roots_info:
        summary["series_roots"] = series_roots_info

    report = {
        "summary": summary,
        "report_md": format_report_md(items_by_action, movie_roots_info, series_roots_info),
        "items": format_report_items(scan, items_by_action),
    }

    if scan.service_errors:
        report["service_errors"] = scan.service_errors

    report["llm_instructions"] = report_llm_instructions(scan, movie_roots_info, series_roots_info)
    report["next"] = report_next_step(scan)
    return report
