# mypy: ignore-errors
"""Move execution helpers — extracted from ScanManager for long-horizon maintainability.

Phase 1.1: Move the blocking file-system work out of the orchestrator so
ScanManager stays ~400 LOC and is easy to test. This module is deliberately
stateless; ScanManager still owns ScanPlan state and progress bookkeeping.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from uuid import uuid4

from app.core.constants import VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)

# Keep _is_hidden logic local to avoid circular imports
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

def _is_cross_drive(source_path: str, target_path: str) -> bool:
    try:
        source_dev = os.stat(source_path).st_dev
        target_parent = Path(target_path).parent
        target_dev = os.stat(target_parent).st_dev
        return source_dev != target_dev
    except OSError:
        return False

def copy_file_worker(scan, source_path: Path, target_path: Path, source_size: int, update_state) -> None:
    """Blocking worker — runs in `to_thread` so the event loop stays free for progress polls."""
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
            update_state(
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

async def copy_file_with_progress(scan, source_path: Path, target_path: Path, source_size: int, update_state) -> None:
    from asyncio import to_thread
    await to_thread(copy_file_worker, scan, source_path, target_path, source_size, update_state)

async def apply_item(scan, item, update_state, copy_fn=None) -> None:
    """Apply a single ScannedItem: mkdir, copy/rename, delete source, update progress.

    Robust version (temp file + atomic replace) — mirrors ScanManager._apply_item
    so the orchestrator can delegate without behavior change. Caller handles
    post-move cleanup (empty parent dirs) and Jellyfin notification.

    copy_fn is injected for testability (monkeypatches on ScanManager._copy_file_with_progress).
    When None, uses the local copy_file_with_progress with the provided update_state.
    """
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

    update_state(
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
            if copy_fn is not None:
                await copy_fn(scan, source_path, temp_path, source_size)
            else:
                await copy_file_with_progress(scan, source_path, temp_path, source_size, update_state)
            os.replace(temp_path, target_path)
            update_state(
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
            update_state(
                scan,
                confirm_current_copied_bytes=source_size,
                confirm_current_percent=100.0,
                confirm_note="Move completed.",
            )
    except Exception:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        elapsed = time.perf_counter() - started_at
        logger.exception(
            "MOVE FAILED [%s] elapsed=%.1fs source=%s target=%s",
            move_kind,
            elapsed,
            source_path,
            target_path,
        )
        raise

    # Movie container swap: target kept the source ext (.mkv), so an old
    # sibling (.mp4, same stem) survives the os.replace above — delete it so
    # replace really replaces instead of leaving two files behind.
    if getattr(item, "action", None) == "replace" and getattr(item, "item_type", None) == "movie":
        try:
            from app.services.resolver import normalize_text as _norm

            _wanted = _norm(target_path.stem)
            if target_path.parent.exists():
                for _candidate in sorted(target_path.parent.iterdir(), key=lambda p: p.name.lower()):
                    if (
                        _candidate.is_file()
                        and _candidate != target_path
                        and not _candidate.name.startswith(".")
                        and _candidate.suffix.lower() in VIDEO_EXTENSIONS
                        and _norm(_candidate.stem) == _wanted
                    ):
                        _candidate.unlink()
                        logger.info("MOVE CLEANUP deleted replaced sibling: %s", _candidate)
        except OSError:
            pass

    elapsed = time.perf_counter() - started_at
    logger.info(
        "MOVE DONE [%s] elapsed=%.1fs size=%s target=%s",
        move_kind,
        elapsed,
        _format_size(source_size),
        target_path,
    )


# ── Confirm runtime (plan 1.1 slice B) ──────────────────────────────
# These functions take `manager` (ScanManager) as first param: they drive
# confirm state, counts and queues which stay owned by ScanManager.


def cleanup_empty_parents(manager, original_path: Path) -> None:
    if not manager._config.paths.download_roots:
        return

    root_paths = [Path(p) for p in manager._config.paths.download_roots]
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


async def trigger_jellyfin_scans(manager, updated_paths: set[str]) -> None:
    from app.services.jellyfin import JellyfinClient

    if not updated_paths:
        return

    client = JellyfinClient.from_env()
    if not client:
        return

    try:
        # Prefer path-based auto-detection (no manual library names needed).
        # Only the final folder name is compared, as host vs container paths differ.
        paths_list = sorted(updated_paths)
        movie_roots = []
        series_roots = []
        try:
            cfg_paths = manager._config.paths
            # movie_roots / series_roots are dicts like {"movie_0": "/media1/movies", ...}
            movie_roots = list(getattr(cfg_paths, "movie_roots", {}).values()) if hasattr(cfg_paths, "movie_roots") else []
            series_roots = list(getattr(cfg_paths, "series_roots", {}).values()) if hasattr(cfg_paths, "series_roots") else []
            # Fallback for older config shapes
            if not movie_roots and hasattr(cfg_paths, "movieRoots"):
                movie_roots = list(getattr(cfg_paths, "movieRoots", {}).values())
            if not series_roots and hasattr(cfg_paths, "seriesRoots"):
                series_roots = list(getattr(cfg_paths, "seriesRoots", {}).values())
        except Exception:
            pass

        libs = await client.libraries_for_paths(paths_list, movie_roots, series_roots)
        if libs:
            for lib in sorted(libs, key=lambda x: x["name"]):
                logger.info("Triggering Jellyfin library scan for '%s' (path-based)", lib["name"])
                await client.scan_library(library_name=lib["name"])
            logger.info("Finished Jellyfin library scan(s) for %d library(s) (path-based)", len(libs))
            return

        # Fallback: old single-name per kind (kept for compat if auto-detection finds nothing)
        library_names = set()
        for item in (manager._current_scan.items if manager._current_scan else []):
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
        if manager._current_scan:
            if "Jellyfin" not in manager._current_scan.service_errors:
                manager._current_scan.service_errors["Jellyfin"] = error_msg
            else:
                manager._current_scan.service_errors["Jellyfin"] += f"; {error_msg}"


async def run_confirm_task(
    manager,
    scan_id: str,
    item_ids: list[str] | None = None,
    source_paths: list[str] | None = None,
    source_prefixes: list[str] | None = None,
) -> None:
    from asyncio import to_thread
    from datetime import UTC, datetime

    from app.services.presenters import format_scan_report
    from app.services.scan_history import save_report, save_singleton

    scan = manager.get_scan(scan_id)
    updated_paths: set[str] = set()
    acted_items: list = []
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

        for item in selected_items:

            manager._update_confirm_state(
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
                # Idempotency guard: a restart used to resurrect already-moved
                # items as actionable (stale singleton), so a re-confirm hit a
                # missing source and wrote a spurious "failed" history entry
                # even though the file was already at its target. When the
                # source is gone but the target exists with the expected size,
                # treat it as already moved: mark confirmed, count nothing.
                if not Path(item.source_path).is_file() and Path(item.target_path).is_file():
                    try:
                        size_ok = item.file_size is None or Path(item.target_path).stat().st_size == item.file_size
                    except OSError:
                        size_ok = False
                    if size_ok:
                        logger.info(
                            "Skipping already-moved %s -> %s (source gone, target present with expected size)",
                            item.source_path,
                            item.target_path,
                        )
                        item.confirmed = True
                        item.error = None
                        continue
                logger.info("Applying %s: %s -> %s", item.action, item.source_path, item.target_path)
                await manager._apply_item(scan, item)
                item.confirmed = True
                acted_items.append(item)
                if item.item_type in ("movie", "series"):
                    updated_paths.add(item.target_path)
                    updated_paths.add(item.source_path)

                if item.action == "move":
                    scan.counts.moved += 1
                elif item.action == "replace":
                    scan.counts.replaced += 1
                logger.info("Finished %s: %s", item.action, item.target_path)
            except Exception as exc:
                scan.counts.failed += 1
                acted_items.append(item)
                item.error = str(exc)
                manager._update_confirm_state(
                    scan,
                    confirm_note=f"Failed to move item: {exc}",
                )
                logger.error("Failed %s for %s: %s", item.action, item.source_path, str(exc), exc_info=True)
            finally:
                scan.confirm_processed += 1

        # Write to history (SQLite) for per-group review.
        # Only items actually acted on are recorded: already-moved skips were
        # confirmed by an earlier batch and must not create duplicate groups.
        if acted_items:
            try:
                from app.services.history_store import append_history_group

                # Group by target for display: for series, it's the show folder; for movies, it's the movie folder
                # Use the first item to determine group
                first = acted_items[0]
                first_target = Path(first.target_path)
                if first.item_type == "movie":
                    # For movies, each movie is its own group: use the movie folder
                    group_key = str(first_target.parent)
                    group_title = first_target.parent.name or first_target.name
                else:
                    # For series, group by show folder (parent of season)
                    group_key = str(first_target.parent.parent) if first_target.parent.parent and first_target.parent.parent.name else str(first_target.parent)
                    group_title = first_target.parent.parent.name if first_target.parent.parent and first_target.parent.parent.name else first_target.parent.name
                # Fallback to scan_id if no title
                if not group_title or group_title in ("/", "."):
                    group_title = f"Batch {scan_id[:6]}"

                history_items = []
                for it in acted_items:
                    # Determine status
                    status = "moved" if it.action == "move" else "replaced" if it.action == "replace" else "failed" if it.error else "moved"
                    if it.error:
                        status = "failed"
                    history_items.append(
                        {
                            "confirmId": it.confirm_id,
                            "sourcePath": it.source_path,
                            "sourceFolder": Path(it.source_path).parent.name if it.source_path else "",
                            "targetPath": it.target_path,
                            "pathHistory": [it.source_path, it.target_path],
                            "action": it.action,
                            "item_type": it.item_type,
                            "fileSize": it.file_size,
                            "status": status,
                            "error": it.error,
                            "suspect": bool(it.suspect),
                            "corrected": bool(it.corrected),
                            "correctionNote": it.correction_note,
                            # Prefer the scan-time flag: re-statting the source
                            # fails once it has been moved away, which used to
                            # misreport cross-drive moves as same-drive.
                            "crossDrive": bool(getattr(it, "cross_drive", False)) or _is_cross_drive(it.source_path, it.target_path),
                            "extraType": it.extra_type,
                            "extra_type": it.extra_type,
                        }
                    )
                history_id = append_history_group(
                    scan_id=scan_id,
                    group_title=group_title,
                    group_key=group_key,
                    items=history_items,
                    confirmed_by=getattr(manager, "_current_user", None) or "panel",
                )["history_id"]
                logger.info("Wrote history %s for scan %s group %s (%d items)", history_id, scan_id, group_title, len(history_items))
            except Exception as e:
                logger.warning("Failed to write history for scan %s: %s", scan_id, e, exc_info=True)

        manager._update_confirm_state(
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
        await manager._trigger_jellyfin_scans(updated_paths)

        all_confirmed = all(
            item.action == "skip" or item.confirmed
            for item in scan.items
        )

        selective = item_ids is not None or source_paths is not None or source_prefixes is not None

        if not selective or all_confirmed:
            scan.status = "confirmed"
            scan.confirmed_at = now

        scan.confirm_status = "completed"
        manager._update_confirm_state(
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
        manager._update_confirm_state(
            scan,
            confirm_phase="failed",
            confirm_note=f"Confirm failed: {exc}",
        )
        logger.error("Confirm task failed for scan %s: %s", scan_id, str(exc), exc_info=True)
    finally:
        # Start the next queued confirm (if any). This is synchronous: the
        # completed state is only observable between event-loop ticks, so a
        # queued batch resumes the 'running' state immediately.
        manager._start_queued_confirms(scan_id)
        # Re-persist so history reflects post-confirm counts, not just
        # the initial scan-completion snapshot. Runs after queue-start so
        # callers never observe a terminal state with batches pending;
        # partial moves from a failed batch are kept truthful too.
        try:
            await to_thread(save_report, scan_id, format_scan_report(scan), manager._config.report_dir)
        except Exception:
            logger.warning("Could not persist post-confirm report for scan %s", scan_id)
        # Persist the singleton too: restart recovery loads current.json, and
        # without this a restart resurrects confirmed items as actionable,
        # allowing double-confirms that fail with ENOENT on the gone source.
        try:
            await to_thread(save_singleton, scan, manager._config.report_dir)
        except Exception:
            logger.warning("Could not persist post-confirm singleton for scan %s", scan_id)
