# Data Models

All request/response schemas live in `app/models/schemas.py` (Pydantic v2).
Fields use camelCase JSON aliases with `populate_by_name=True`, so Python code
uses snake_case while the wire format uses camelCase.

## Literal types

| Type | Values |
| --- | --- |
| `OperationMode` | `organize`, `normalize` |
| `NormalizeMode` | `safe`, `full` |
| `ItemKind` | `movie`, `series`, `skip` |
| `ScanStatus` | `running`, `completed`, `confirmed`, `failed`, `cancelled` |
| `RunStatus` | `queued`, `running`, `completed`, `failed`, `cancelled` |

## ScanRequest

Input for `POST /scans` and `move new downloads scan`.

| Field | Wire alias | Default | Meaning |
| --- | --- | --- | --- |
| `replace_existing` | `replaceExisting` | `true` | When false, existing targets are planned as `skip`. |
| `operation` | — | `organize` | `organize` or `normalize`. |
| `allow_medium` | `allowMedium` | `false` | Allow medium confidence classifications. |
| `use_local_ai` | `useLocalAI` | `false` | Use the external LLM classifier. |

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
  - `confirm_phase` (`idle|preparing|stopping_seeding|moving|deleting_source|triggering_jellyfin|completed|failed`)
  - `confirm_current_item`, `confirm_current_target`
  - `confirm_total`, `confirm_processed`
  - baselines `confirm_start_moved/replaced/failed` (snapshotted when a confirm
    starts, so per-batch progress doesn't accumulate across confirms)
  - transfer telemetry: `confirm_current_size_bytes`,
    `confirm_current_copied_bytes`, `confirm_current_speed_bytes`,
    `confirm_current_percent`, `confirm_cross_drive`
  - `confirm_note`, `confirm_last_update_at`

## ScanLogEntry / RunLogEntry

Structured log entries: `timestamp`, `level` (`info|warning|error`), `event`,
`message`, optional `item_path`, and `details` dict.

## Legacy run models

Kept for backward compatibility with the `/runs` endpoints:

- `RunRequest` — `dryRun`, `replace_existing`, `operation`, `normalize_mode`,
  `allow_medium`, `use_local_ai`.
- `ProgressCounts` — `scanned`, `classified`, `moved`, `replaced`, `skipped`,
  `failed`.
- `RunState` — full legacy run state: `run_id`, `status`, flags, `counts`,
  `logs`, `active_step`, `active_item_path`, `ai_thinking`, `ai_output`,
  `summary_path`, `log_path`, `error`.
