# Data Models

All request/response schemas live in `app/models/schemas.py` (Pydantic v2).
Fields use camelCase JSON aliases with `populate_by_name=True`, so Python code
uses snake_case while the wire format uses camelCase.

## Literal types

| Type | Values |
| --- | --- |
| `OperationMode` | `organize`, `normalize` |
| `ItemKind` | `movie`, `series`, `skip` |
| `ScanStatus` | `running`, `completed`, `confirmed`, `failed`, `cancelled` |

## ScanRequest

Input for `POST /scans` and `move new downloads scan`.

| Field | Wire alias | Default | Meaning |
| --- | --- | --- | --- |
| `replace_existing` | `replaceExisting` | `true` | When false, existing targets are planned as `skip`. |
| `operation` | — | `organize` | `organize` (kept for concept compatibility; the normalize path was removed). |

## CandidateItem

A scanned file, produced by `scanner.scan_candidates`.

| Field | Meaning |
| --- | --- |
| `source_root_key` | Key of the download root it came from. |
| `source_root` | Download root path. |
| `source_path` | Absolute path of the file. |
| `name` | Filename. |
| `extension` | File extension. |
| `container_path` | Parent folder path. |
| `relative_path` | Path relative to the container folder (just the filename for top-level files). |
| `file_size` | Size in bytes. |

## ClassificationResult

Output of the classifier (alias `type` for `kind`).

| Field | Meaning |
| --- | --- |
| `type` / `kind` | `movie`, `series`, or `skip`. |
| `title` | Clean series/movie title. |
| `episode_title` | Episode title (series). |
| `series_alias` | Alias mapping if one applies. |
| `year` | Year when parsed. |
| `season` / `episode` | Season / episode numbers. |
| `confidence` | 0.0 – 1.0. |
| `reason` | Human-readable classification reason. |

## ResolvedTarget

Output of the resolver.

| Field | Meaning |
| --- | --- |
| `root_key` | Target root key (`movie_0`, `series_1`, …). |
| `target_dir` | Destination directory. |
| `target_path` | Full destination path. |
| `created_show_folder` / `created_movie_folder` | Whether the folder was created. |
| `existing_match` | Matched existing path when reused. |
| `show_folder_exists` / `season_folder_exists` | Pre-existing folder flags. |
| `phantom_show_folder` | Show dir resolved from in-scan memory only (not on disk). |
| `has_previous_season` / `max_existing_season` | Continuity evidence used by suspect detection. |
| `candidate_targets` | `CandidateTarget[]` — scored alternative destinations (top-N, incl. below-threshold options a user may deliberately pick). |

## CandidateTarget

One alternative destination considered during resolution (produced by the
resolver shortlist / deep re-search).

| Field | Meaning |
| --- | --- |
| `path` | Full target file path (target dir + filename). |
| `label` | Short display label (e.g. `existing folder`, `new folder`). |
| `evidence` | Why it was considered (e.g. `name match`, `year 2020`, `season 4 present`, `arc '<subdir>'`, `episode title match`, `New folder`, `Movie marker present — classify as movie`). |
| `source` | Where it came from: `folder` (existing match / current selection), `new` (default new-folder path), `movie` (reclassify-as-movie destination). |
| `reclassify_as_movie` | Selecting this option also flips the item's `item_type` to `movie` and clears season/episode, not just the path. |

## ScannedItem

One planned item in a scan.

| Field | Wire alias | Meaning |
| --- | --- | --- |
| `confirm_id` | `confirmId` | Stable id used by update/confirm/delete tools. |
| `source_path` | `sourcePath` | Source file. |
| `name` | — | Display name. |
| `item_type` | — | `movie` / `series` / `skip`. |
| `confidence` / `reason` | — | Classification. |
| `target_path` | `targetPath` | Planned destination. |
| `action` | — | `move`, `replace`, or `skip`. |
| `error` | — | Error string when failed. |
| `confirmed` | — | Whether the item was applied. |
| `show_folder_exists` / `season_folder_exists` / `file_exists` | — | Target existence flags. |
| `file_size` | `fileSize` | Size in bytes. |
| `cross_drive` | `crossDrive` | True when source and target are on different drives. |
| `suspect` | — | Continuity signals fired (phantom show folder, season gap, or episode gap). |
| `flags` | — | `phantom_show_folder` \| `season_gap` \| `episode_gap` |
| `corrected` | `corrected` | Auto re-targeted by the deep search (or manually overridden). |
| `correction_note` | `correctionNote` | Explanation when suspect/corrected. |
| `candidate_targets` | `candidateTargets` | `CandidateTarget[]` exposed in report items. |

## ScanCounts

Cumulative scan counters: `total`, `movies`, `series`, `skipped`, `moved`,
`replaced`, `failed`.

## ScanPlan

The scan state machine. Core fields:

- `scan_id`, `status` (ScanStatus), `operation`
- `items: list[ScannedItem]`, `counts: ScanCounts`
- `skipped_in_progress` — candidates skipped because the download was active
- Timing: `created_at`, `started_at`, `finished_at`, `confirmed_at`
- Progress: `total_candidates`, `processed_candidates`, `current_candidate`,
  `current_candidate_index`
- Errors: `error`, `service_errors: dict`
- Confirm state (per-confirm, scoped):
  - `confirm_status` (`idle|running|completed|failed`)
  - `confirm_phase` (`idle|preparing|moving|deleting_source|triggering_jellyfin|completed|failed`; `stopping_seeding` is a legacy literal kept for backwards compat, never emitted)
  - `confirm_current_item`, `confirm_current_target`
  - `confirm_total`, `confirm_processed`
  - baselines `confirm_start_moved/replaced/failed` (snapshotted when a confirm
    starts, so per-batch progress doesn't accumulate across confirms)
  - transfer telemetry: `confirm_current_size_bytes`,
    `confirm_current_copied_bytes`, `confirm_current_speed_bytes`,
    `confirm_current_percent`, `confirm_cross_drive`
  - `confirm_note`, `confirm_last_update_at`
  - `confirm_queue_length` — confirms requested while one is running are
    **queued, not rejected**; this is the currently pending count.
  - `confirm_queue_items` — item count across all queued batches.
- Planned-coverage tracking (per-scan, used by suspect detection):
  `planned_episodes` per `(series_key, season)` and `planned_seasons` per
  `series_key` — so a batch download (S21E01..E13 in one scan) is not flagged
  as a season/episode gap.

## ScanLogEntry

Structured log entry: `timestamp`, `level` (`info|warning|error`), `event`,
`message`, optional `item_path`, and `details` dict.

## Legacy `/runs` endpoints

`GET /runs/current` and `POST /runs` are thin compatibility aliases over
`ScanPlan` / `ScanRequest` (see [api.md](api.md)) — the old `RunState`,
`RunRequest`, and `ProgressCounts` schemas were removed with the legacy run
stack. New integrations should use `/scans`.
