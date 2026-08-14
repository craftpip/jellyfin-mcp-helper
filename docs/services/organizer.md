# Organizer — `app/services/organizer.py`

The **legacy** organizer flow: scans, classifies, resolves, and **applies moves
immediately** inside a `RunState` (no plan/review step). Kept for backward
compatibility with `/runs`; new integrations should use
[scan-manager](scan-manager.md).

## `OrganizerService.execute(run_state) -> RunState`

1. Clears resolver caches and resets resolver runtime state.
2. `scan_candidates` over the download roots; unreadable paths are logged as
   `scan.path_unreadable` and counted as failed.
3. Loads qBittorrent in-progress paths (`_load_in_progress_paths`); failures are
   logged as warnings, not fatal.
4. For each candidate (logs to the run via `_log`):
   - `candidate.in_progress` — skipped when the download is active.
   - `candidate.classified` — `_classify_candidate` runs the classifier (and
     records AI thinking/output via `_update_ai_output` when the LLM is used).
   - skipped when `kind == "skip"` or below the confidence threshold.
   - `target.resolved` — `resolver.resolve`.
   - `_apply_action` performs the move/replace immediately (with dry-run support).
   - `candidate.failed` — per-item exceptions are caught and logged.
5. `_trigger_jellyfin_scans` refreshes affected libraries after the run.
6. Resets resolver runtime state and caches.

## `_apply_action`

- Skips in dry-run mode.
- Stops seeding first if needed (`_stop_seeding_if_needed`, qBittorrent).
- Creates the target directory, then moves:
  - same drive → `os.replace`
  - cross drive → copy then delete
- Cleans up empty parent folders under the download roots
  (`_cleanup_empty_parents`).

## Notes

- `bind_run_state` binds a run for logging; `_log` appends `RunLogEntry`s and
  updates `updated_at`.
- `_classify_candidate` uses the classifier directly, with AI
  (`use_local_ai`) handled through the run's AI fields.
