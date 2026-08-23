# 14 — Single Report (Incremental Scan) + Full Rescan + JSON Grouped Report

> **Goal:** One report only, scans are incremental by default, plus an explicit full-rescan that overwrites. MCP report gains a JSON mode grouped by source folder.

---

## 1. Current Behavior

- `ScanManager.create_scan()` generates a new `ScanPlan(scan_id=uuid, status=running)` and sets it as `_current_scan`, discarding the previous plan. `ScanStore.current` is replaced, history is saved separately via `save_report()` but the live report is tied to the scan lifecycle.
- `POST /mcp tools/call move new downloads scan` always does a full filesystem scan (`scan_candidates()` over all download roots) and builds a fresh `scan.items` list. Previous `targetPath` overrides from `update_scan`/`retarget_item`, deletes, and `confirmed` flags are lost on next scan.
- `GET /mcp tools/call get move new downloads scan report` (`format_scan_report` in `app/services/presenters.py:414`) returns `{summary, report_md (markdown tables), items: flat list, llm_instructions, next}`. No JSON-grouped alternative. `report_md` is markdown-built by `format_report_md`.
- REST mirrors this: `POST /api/scans` → new scan, `GET /api/scans/current/report` → that scan's report.

## 2. Desired Behavior (per user)

### 2.1 Single report, incremental by default

- **Exactly one live report** exists in memory (and persisted). It is **not** replaced when a new scan starts.
- `scanId` is no longer the report identity. Keep an internal run id for progress tracking if needed, but the **report id is fixed** (e.g. `current` / `singleton`). `ScanPlan.scan_id` becomes an optional run marker, not the report key. Alternatively keep `scan_id` for history snapshots but the live report has a constant key like `"current"`.
- Starting a scan **by default = incremental**:
  - Enumerate candidates as today.
  - Compare each candidate's `source_path` (canonical absolute path) against the existing live report's items.
  - **Already in report** → skip adding (preserve any user edits: `targetPath`, `action` override, `confirmed` state, retarget history). Do not reclassify/re-resolve. Optionally refresh `fileExists` / `fileSize` metadata but do not reset user fields.
  - **New file** → classify + resolve + create `ScannedItem` and **append** to the live report.
  - **Gone file** (in report but no longer on disk and not confirmed/moved) → keep it but mark `missing` or move to `skip` with `reason="Source no longer on disk"` — or optionally prune after N scans. Decision: keep as `skip/missing` so user sees it rather than silent drop.
  - Scan counts (`summary`) are recomputed from the merged list after the append.
- User edits survive: `update_scan`, `retarget_item`, `delete_items`, `confirm_scan` all mutate the single report. A subsequent incremental scan does not reset them.

### 2.2 Full rescan option (overwrite)

- Add an explicit flag to force a **full rescan that overwrites the report**:
  - MCP: `move new downloads scan` gains `fullRescan?: boolean` (default `false`). When `true`, behavior is today's full rebuild: fresh `ScannedItem` list replaces the live report.
  - REST: `POST /api/scans` gains `fullRescan` / `mode: "incremental" | "full"` (default incremental). Encapsulated in `ScanRequest` (`app/models/schemas.py:13`).
  - Also expose via UI: "Scan new only" (default) vs "Rescan all (overwrite)" with a confirmation dialog because it discards edits.
- Full rescan should snapshot the overwritten report to history before replacing (so undo / history retains it).

### 2.3 MCP report JSON grouped by source folder

- `get move new downloads scan report` today emits markdown (`report_md`). Add an option to return **structured JSON grouped by source folder**.
- Proposal (backward compatible):
  ```json
  {
    "name": "get move new downloads scan report",
    "inputSchema": {
      "properties": {
        "scanId": {"type": "string", "description": "Deprecated/optional. Single report now; omit to get current."},
        "format": {"type": "string", "enum": ["markdown", "json"], "default": "markdown", "description": "Output format. markdown = current report_md + flat items. json = grouped JSON, no markdown."},
        "groupBy": {"type": "string", "enum": ["sourceFolder"], "default": "sourceFolder", "description": "Grouping key when format=json"}
      }
    }
  }
  ```
- `format=markdown` (default) → unchanged output for existing clients.
- `format=json` → omit `report_md`, return:
  ```json
  {
    "summary": {"total": 42, "movies": 4, "series": 36, "skipped": 2, "action_required": 40, "moved": 0, "...": "..."},
    "groups": [
      {
        "sourceFolder": "Show.S01.1080p-GROUP",
        "containerPath": "/downloads/Show.S01.1080p-GROUP",
        "count": 12,
        "totalSize": 123456789,
        "items": [ { "confirmId":"i1","sourcePath":"...","targetPath":"...","itemType":"series","action":"move","fileSize":...,"showFolderExists":true,"seasonFolderExists":true,"fileExists":false,"candidateTargets":[...] }, ... ]
      },
      {
        "sourceFolder": "Movie.2024.2160p-GROUP",
        "containerPath": "/downloads/Movie.2024.2160p-GROUP",
        "count": 1,
        "totalSize": 987654321,
        "items": [ ... ]
      }
    ],
    "items": [ ... flat list, kept for compat or omitted when grouped ],
    "service_errors": {...},
    "llm_instructions": [...],
    "next": "..."
  }
  ```
- Grouping key is `sourceFolder` (and `containerPath`), the torrent folder — same grouping used in plan 12 UI (`groupItems` in `app/ui/react/src/utils/report.js`). Each group header is the source folder name; single-file torrents group by file's parent or file itself.
- REST parity: `GET /api/scans/current/report?format=json&groupBy=sourceFolder` and `GET /api/scans/{scanId}/report?...` same.
- Presenter change: `format_scan_report(scan, format="markdown"|"json", group_by="sourceFolder")` builds `groups` via existing `sourceFolder`/`containerPath` on `ScannedItem` (no new scan needed). Add `format_report_grouped(items_by_action)` helper.

---

## 3. Design Decisions & Edge Cases

- **Identity:** dedup key is canonical `source_path` (`Path.resolve(strict=False)` / absolute). If a file is renamed on disk it appears as new (old entry becomes missing/skip) — acceptable; file-rename tracking is out of scope.
- **Missing files:** incremental scan will not silently prune. Item whose `source_path` no longer exists and `confirmed==false` becomes `action=skip, reason="Source missing on disk", error="missing"` and stays visible until user deletes it or runs full rescan. Confirmed/moved items are already hidden from `format_scan_report` (they remain in store but filtered from `items_by_action`).
- **In-progress / zero-byte handling:** same skip rules apply to new candidates only; existing report entries are not re-evaluated.
- **Concurrency:** if a scan is running, second `create_scan(incremental)` queues or rejects with 409 as today; singleton report is locked during mutation. `scan_orchestrator.run_scan_sync` must hold the merge lock.
- **Persistence:** singleton report persisted to `reports/history/current.json` or `reports/report.json` plus SQLite `scans` table with fixed id `current`. On startup `ScanManager` loads it into `ScanStore.current`. History snapshots still use per-run ids.
- **Compatibility:** `scanId` param deprecated but accepted; when omitted, operates on singleton. Old clients passing last `scanId` still resolve to current report (log deprecation warning).
- **Counts & summary:** recomputed from live `scan.items` after merge: `total/movies/series/skipped/action_required` reflect the merged set.

---

## 4. Implementation Steps

1. **Schemas** `app/models/schemas.py:ScanRequest` — add `full_rescan: bool = Field(default=False, alias="fullRescan")` and optional `mode` alias; add `format/groupBy` to a new `ReportRequest` if needed. `ScanPlan` gains `report_id: Literal["current"] = "current"` or make `scan_id` constant; keep `scan_id` for history compatibility but document it as run id.
2. **Store** `app/services/scan_store.py` — add singleton load/save: `load_singleton()`, `save_singleton()`, `merge_items(new_items, existing)` helper. `ScanStore` holds one live `ScanPlan` under key `current`; rest of dict is history. On `create_scan(fullRescan=false)` allocate a temporary run plan for progress but do not replace live report until merge at `completed`. On `fullRescan=true` archive current to history, then replace.
3. **Orchestrator** `app/services/scan_orchestrator.py:run_scan_sync` — after candidate enumeration, partition into `existing_source_paths = {i.source_path for i in live.items}`. Only classify/resolve new ones. Append to `live.items`, recompute `live.counts`, call `group_retarget_pass` on the delta or full set. Track `missing_on_disk` for existing items and mark skipped. Persist via `save_singleton`.
4. **Manager** `app/services/scan_manager.py:create_scan` — branch on `request.full_rescan`. Incremental path creates ephemeral progress scan, merges on success; full path does today's overwrite but first `save_report(current_report, history_dir)` as snapshot. Update `get_scan`/`get_current_scan` to return singleton when scanId omitted or `"current"`.
5. **Presenters** `app/services/presenters.py` — add `format_report_grouped(items_by_action) -> list[dict]` grouping by `item.source_folder or Path(item.container_path).name` (reuse `GENERIC_FOLDERS` fallback from `report.js:groupItems`). Change `format_scan_report(scan, format="markdown")` to emit `report_md` only when markdown, and `groups` when json. Keep flat `items` for compat or gate on format.
6. **MCP** `app/main.py:_mcp_tools()` — add `fullRescan` to `move new downloads scan` inputSchema and `format`/`groupBy` to `get move new downloads scan report`. Handlers map `format` to presenter mode and include `groups` in response. Default `format=markdown` keeps existing prompts/logs stable (`RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS` unchanged).
7. **REST** `app/ui/server.py` — `POST /api/scans` and `GET /api/scans/current/report` accept `?format=json&groupBy=sourceFolder` and `fullRescan` body field. Call new manager/presenter signatures. Keep `GET /api/scans/{scan_id}/report` for history (reads from `scan_history.load_report`).
8. **UI** `app/ui/react/src/store/AppStore.jsx` + `ReportPanel` + `TopBar` — Scan button becomes split: "Scan new" (incremental, default) and "Rescan all" (with confirm modal explaining overwrite). `apiClient.fetchReport({format:"json"})` option for future JSON view. Store's report polling merges via `handleScanProgress` without discarding edits.
9. **History** `app/services/scan_history.py` — `save_report` now also writes `current.json` / upserts `scans.current`. Full rescan archives previous current with its old `scan_id` before overwrite.
10. **Tests** — extend `tests/test_scan_errors.py::TestCreateScan` (incremental append, dedup, missing marking, fullRescan overwrite), add presenter test for `format_scan_report(..., format=json)` grouping, MCP tests for `format=json` returns `groups` key and no `report_md`, and a store test for singleton persistence across `ScanManager` restarts.

---

## 5. Verification

- `python3 -m pytest tests/` — new tests green, existing 390+ green (scanId deprecation still passes).
- `npm test` in `app/ui/react` — report fetch with `?format=json` renders grouped view.
- Live: `POST /api/scans {"fullRescan": false}` with pre-edited report → edits preserved, new file appended, count +1; `POST /api/scans {"fullRescan": true}` → report replaced, previous snapshot in history. `POST /mcp tools/call get move new downloads scan report {"format":"json","groupBy":"sourceFolder"}` → JSON with `groups[].sourceFolder` keys.
- `docker compose build && docker compose restart && curl /health` — singleton report survives restart via file/DB.

**Status:** Implemented 2026-08-24 — core incremental + fullRescan + JSON grouped report + singleton persistence + UI dropdown + tests. Verified: `407 passed` (`docker exec jellysort python3 -m pytest`), `104 passed` (`npm test` in `app/ui/react`), MCP `tools/list` advertises `fullRescan`/`format`/`groupBy`, manual incremental test preserved retarget, singleton `reports/current.json` created and restored on `ScanManager` restart.
