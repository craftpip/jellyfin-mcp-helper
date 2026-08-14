# Scan Manager — `app/services/scan_manager.py`

Owns the modern **scan → plan → confirm** workflow and the actual file moves. It
is the service behind the `move new downloads scan` / `confirm move new
downloads scan` MCP tools and the `/scans` REST endpoints.

## `ScanManager`

Holds the current scan plus a map of scan plans, cancel events, and background
tasks. Constructed with an `AppConfig` and a shared `PathResolver`.

### `create_scan(request) -> ScanPlan`

- Records the running loop and builds a new `ScanPlan` (status `running`).
- **Cancels any currently running scan first** (sets its cancel event and marks
  it `cancelled`) so only one scan runs at a time.
- Spawns `_run_scan_task` as a background task and returns immediately.

### `_run_scan_sync` — the scan loop

1. Clears resolver caches, resets resolver runtime state.
2. Loads qBittorrent in-progress paths (when configured).
3. `scan_candidates` over the download roots; unreadable paths are recorded as
   items with reason `Filesystem read error…` and counted as skipped.
4. For each candidate:
   - Skipped if in-progress download or zero-byte file.
   - `classify_candidate`; skipped if `kind == "skip"` or confidence below
     `classify_confidence_threshold`.
   - Resolves the target (`_resolve_sync` runs the resolver in a thread).
   - **Revision handling:** when two candidates resolve to the same target
     (`planned_targets`), the higher `v\d+` revision wins; lower revisions are
     skipped, higher ones supersede the existing plan item.
   - Plans `replace` when the target exists, `move` otherwise; if
     `replace_existing` is false, existing targets become `skip`.
   - Records `cross_drive`, folder-existence flags, and the counts
     (`movies`/`series`).
   - Per-candidate failures become `skip` items with the error in `reason`.
5. Marks the scan `completed` (or `failed`), clears caches.

### `update_scan(scan_id, items)` — redirect targets

Rejects confirmed/running/failed scans. For each update
`{confirmId, targetPath}`:

- Rejects skipped items.
- Requires an **absolute** target path with a valid video extension
  (`.mkv/.mp4/.avi/.mov/.m4v/.wmv/.flv`).
- Requires the target to be **under a configured movie or series root**
  (`_is_path_within`).
- Recomputes the action (`replace` if the target now exists) and the
  folder-existence flags.

### `confirm_scan(scan_id, item_ids, source_paths, source_prefixes)`

Guards: scan must be `completed` (not confirmed/running/failed) and no confirm
may already be running (`409`). Optional selectors (`itemIds`, `sourcePaths`,
`sourcePrefixes`) limit which items are confirmed; omitting all confirms the
whole remaining plan. Sets per-confirm baseline counters
(`confirm_start_moved/replaced/failed`) and spawns `_run_confirm_task`.

### `_run_confirm_task`

1. `stopping_seeding` — `QbittorrentClient.stop_seeding_for_paths` for the
   selected source files (when configured; failures are recorded in
   `service_errors["qBittorrent"]`).
2. Per item (`preparing` → `moving`):
   - `_apply_item` performs the move (see below).
   - Success → `item.confirmed = True`, `counts.moved`/`counts.replaced`
     incremented, target added to `updated_paths`.
   - Failure → `counts.failed` incremented and the error stored on the item.
   - `confirm_processed` increments in a `finally` block.
3. `triggering_jellyfin` — `_trigger_jellyfin_scans(updated_paths)` refreshes
   affected libraries.
4. Marks the scan `confirmed` (when not selective or everything is confirmed)
   and the confirm `completed`; on exception, confirm `failed`.

### `_apply_item` — the move

- Creates the target parent directory.
- Detects **real** cross-drive by comparing `st_dev` of source and target
  (`_path_mount_label` logs the mount points).
- **Same drive:** `os.replace(source, target)` (atomic rename).
- **Cross drive:** chunked copy (8 MB chunks, `fsync`, `copystat`) to a hidden
  `.jellysort-{uuid}.partial{ext}` temp file in the target directory, then
  `os.replace(temp, target)` and `source.unlink()`. Progress (copied bytes,
  speed, percent) is written to the scan's confirm fields after each chunk. The
  copy runs in a worker thread (`to_thread`) so the event loop keeps serving
  progress polls.
- On failure the temp file is removed and the exception re-raised.
- Cleans up empty parent folders under the download roots afterwards
  (`_cleanup_empty_parents`).

### `delete_items(scan_id, item_ids)`

Permanently deletes the source files for the given items and removes them from
the plan (backing `delete move new downloads scan items`).

### `delete_scan()`

Clears the current scan.

## Helpers

- `_is_cross_drive(source, target)` — root-prefix comparison used during
  planning.
- `_format_size(bytes)` — human-readable size.
- `_extract_revision(name)` — highest `v\d+`/`REPACK\d*` value in the filename.
- `_next_confirm_id(scan)` — stable ids `i1`, `i2`, ….
- `asyncio_run_in_thread(coro)` — runs a coroutine in a thread, used to call
  async service code from the sync scan loop.

## Phase model

Confirm phases: `preparing`, `stopping_seeding`, `moving`,
`deleting_source`, `triggering_jellyfin`, `completed`, `failed` (plus `idle`).
See [backend/models.md](../backend/models.md) for the `ScanPlan` fields backing
per-confirm progress.
