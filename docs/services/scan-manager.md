# Scan Manager — `app/services/scan_manager.py`

Owns the modern **scan → plan → confirm** workflow and the actual file moves. It
is the service behind the `downloads_scan_start` / `confirm move new
downloads scan` MCP tools and the `/scans` REST endpoints.

## `ScanManager`

Holds the current scan plus a map of scan plans, cancel events, and background
tasks. Constructed with an `AppConfig` and a shared `PathResolver`.

### `create_scan(request) -> ScanPlan`

- `ScanRequest` is `replaceExisting` + `fullRescan` (`false` = incremental).
  Incremental pre-fills the new run with a deep copy of the live singleton’s
  `items`/`counts`/`service_errors`; `fullRescan=true` archives the live report
  via `save_report` before replacing.
- Singleton persistence: `reports/current.json` via `save_singleton`/`load_singleton` (`app/services/scan_history.py`) + `app.db scans` table (`ON CONFLICT DO UPDATE`). Restored on `ScanManager` init for restart recovery. History pruned to `MAX_HISTORY=200`.
- **Cancels any currently running scan first** (sets its cancel event and marks
  it `cancelled`) so only one scan runs at a time.
- Spawns `_run_scan_task` as a background task and returns immediately. On completion the singleton is re-saved so the live report survives restarts.

### `_run_scan_sync` — the scan loop

1. Clears resolver caches, resets resolver runtime state.
2. `scan_candidates` over the download roots; unreadable paths are recorded as
   items with reason `Filesystem read error…` and counted as skipped.
3. For each candidate:
   - Skipped if in-progress download (a sibling/own-name incomplete-file marker
     — see [download-client.md](download-client.md)) or zero-byte file.
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
4. **Planned-coverage tracking:** feeds `planned_episodes`
   (`(series_key, season) → set[episode]`) and `planned_seasons`
   (`series_key → set[season]`) as items are planned; these combine with
   on-disk coverage for suspect detection. In-progress (skipped) downloads are
   excluded from planned coverage.
5. **Continuity detection + group re-target:** after planning, group series
   items by series_key; for groups whose base show dir is phantom or wrong
   (suspect signals), run the resolver's deep search (`find_continuation_show`)
   and re-target the whole group to the found show dir — `corrected=True`,
   `correction_note` set, `file_exists`/`action` recomputed (see
   [resolver.md](resolver.md)).
6. Marks the scan `completed` (or `failed`), clears caches.

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
- Resets `suspect`/`flags`/`corrected` on the item — a human or LLM edit means
  the human/LLM has taken over (manual override clears the flags).

### `retarget_item(scan_id, confirm_id, directory, apply_to_group, reclassify_as_movie)`

Backs the browse/retarget UI (see [web-ui/overview](../web-ui/overview.md)):
recomputes the full target for a folder picked in the browser, with the
filename logic **always server-side**:

- **The source filename is ground truth.** `_effective_type(item,
  reclassify_as_movie)` decides the item kind from three inputs, in order:
  1. `reclassify_as_movie` — explicit user request → `movie`;
  2. an `SxxEyy` tag in `item.source_path` → `series` (the source name is
     immutable, so a type mutated by an earlier reclassify cannot hide that the
     file is an episode);
  3. `item.item_type` — fallback for genuine movies / already-series items.
- Series → show dir + existing season subdir (`_pick_existing_season_dir`) or
  `Season {ss:02d}`; the episode filename is rebuilt as
  `{show_name} - S{ss}E{ee}{ext}` from the **source** tag
  (`_source_episode_tag`), never a stale target tag — so a
  series→movie→series round-trip fully restores the Season subdir and `SxxEyy`
  filename (a movie basename never leaks in). The show name is the parent when
  a season-level folder is picked, the folder itself when show-level.
- Movie → `directory / directory.name + ext`; `reclassify_as_movie` →
  `item_type="movie"`, `season/episode=None`.
- The effective type is persisted back onto `item.item_type` when done.
- `apply_to_group` re-targets every row of the title group (grouped by the
  same effective type); a season-level pick with a **multi-season** group is
  rejected (400) — the pick must be show-level so each item joins its own
  season.
- Validates the directory is under a configured root; 400 for confirmed/
  running scans, skipped items, or `reclassify + applyToGroup` combos. Reuses
  the `update_scan` recompute (action/exists + flag reset).

### `confirm_scan(scan_id, item_ids, source_paths, source_prefixes)`

Guards: scan must be `completed` (not confirmed/running/failed). Optional
selectors (`itemIds`, `sourcePaths`, `sourcePrefixes`) limit which items are
confirmed; omitting all confirms the whole remaining plan.

**Confirms are queued, not rejected.** When a confirm is already running, the
request is appended to `_confirm_queue` (scan_id, item_ids, source_paths,
source_prefixes, total) and returns immediately with a "was queued" message
(`confirm_queue_length` > 0) — the UI shows the queued state instead of an
error. Batches run strictly one at a time:

- `_start_confirm(...)` starts a batch: resets `confirm_processed` and the
  per-confirm baselines (`confirm_start_moved/replaced/failed`), sets
  `confirm_status="running"`, spawns the task.
- `_run_confirm_task` ends with `finally: _start_queued_confirms(scan_id)`,
  which pops the next queued batch and starts it synchronously — the frontend
  never sees a `completed` state while batches remain queued (the backend flips
  straight back to `running`).
- Each batch recomputes `scan.confirm_total = len(selected_items)` so queued
  batches whose items were already confirmed show accurate totals.

### `confirm_scan` — queued batches (continued)

The frontend mirrors the queue: Start Move always POSTs; a `queue_length > 0`
response adds the batch to a `pendingBatches` ref (no transfer-queue rebuild)
and toasts "Added to queue"; `pollConfirmProgress` detects the next batch
starting (`status === 'running'` with a reset `processed`) and rebuilds the
transfer queue. `format_confirm_progress` exposes `queue_length`/`queue_items`
and mentions the queue in `next`. See [web-ui/store](../web-ui/store.md).

### `_run_confirm_task`

1. Per item (`preparing` → `moving`):
   - `_apply_item` performs the move (see below).
   - Success → `item.confirmed = True`, `counts.moved`/`counts.replaced`
     incremented, target added to `updated_paths`.
   - Failure → `counts.failed` incremented and the error stored on the item.
   - `confirm_processed` increments in a `finally` block.
2. `triggering_jellyfin` — `_trigger_jellyfin_scans(updated_paths)` refreshes
   affected libraries.
3. Marks the scan `confirmed` (when not selective or everything is confirmed)
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
the plan (backing `downloads_scan_delete_items`).

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

Confirm phases: `preparing`, `moving`, `deleting_source`, `triggering_jellyfin`,
`completed`, `failed` (plus `idle`). The legacy `stopping_seeding` literal
remains in the schema for backwards compatibility but is never emitted.
See [backend/models.md](../backend/models.md) for the `ScanPlan` fields backing
per-confirm progress.
