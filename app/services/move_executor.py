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


async def stop_seeding_for_items(manager, items) -> None:
    from app.services.download_client import QbittorrentClient

    client = QbittorrentClient.from_env(manager._config.paths)
    if not client:
        return

    try:
        candidate_paths = [item.source_path for item in items if item.source_path]
        await client.stop_seeding_for_paths(candidate_paths)
        logger.info("Stopped seeding check completed for %d item(s)", len(candidate_paths))
    except Exception as exc:
        error_msg = f"Error stopping seeding in qBittorrent: {str(exc)}"
        logger.error(error_msg, exc_info=True)
        if manager._current_scan:
            if "qBittorrent" not in manager._current_scan.service_errors:
                manager._current_scan.service_errors["qBittorrent"] = error_msg
            else:
                manager._current_scan.service_errors["qBittorrent"] += f"; {error_msg}"


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
    from app.services.scan_history import save_report

    scan = manager.get_scan(scan_id)
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
            manager._update_confirm_state(
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
            await manager._stop_seeding_for_items(selected_items)

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
                logger.info("Applying %s: %s -> %s", item.action, item.source_path, item.target_path)
                await manager._apply_item(scan, item)
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
                manager._update_confirm_state(
                    scan,
                    confirm_note=f"Failed to move item: {exc}",
                )
                logger.error("Failed %s for %s: %s", item.action, item.source_path, str(exc), exc_info=True)
            finally:
                scan.confirm_processed += 1

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
