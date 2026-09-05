# Components — `app/ui/react/src/components/`

`App.jsx` composes the top-level layout from these components.

| Component | Role |
| --- | --- |
| `TopBar` | Header: connection status, auth-aware "Log out" button, scan/report/confirm actions, nav tabs (Scan & Move / Settings). |
| `ActionsPanel` | Scan start, "Get Report", library list with per-library "Scan" buttons. |
| `ScanProgressPanel` | Live scan progress (percent, processed/total, current file). |
| `ReportPanel` | The report table: grouped rows, filters, selection, path editing, per-row target path state. |
| `ConfirmModal` | Confirm flow modal with a preflight view and a live progress view. |
| `LogPanel` | In-memory event log. |
| `Toasts` | Transient toast notifications + the per-file transfer queue (with queued-batch section). |
| `PathPills` | Reusable path/source/target rendering with drive-root highlighting. |
| `LoginScreen` | Password gate shown when `authRequired && !authed` (also after a 401). |
| `SettingsPage` | env-var editor: grouped by `ENV_SPEC` section, secret masking + reveal, live vs recreate badges, "Recreate required" banner with the exact command. |
| `BrowseModal` | Smart-correction folder browser for re-targeting: search box, combined "All libraries" root view, breadcrumb/`..`, season badges, "Select this folder". |
| `HistoryPage` | Confirm history: per-`history_id` `▼/▶` cards (`group_title`, `N files`, `confirmed_at`), expanded table `Action` (Cross-drive/Suspect/Corrected + `PathPills`) / `Source → Target Path` (editable + `Browse…` via `FolderPicker`) / `Size` / `Trail` (compact `N hops • M paths` → 920px table popup with per-hop `move`/`replaced`) / `Status` / `Delete` (when `source_exists`), `Undo` + `Save & Move Again`. Shows **only** `history_items` for that confirm (not whole scan report), no summary pills/search/filter chips. |

## ReportPanel

The main table (`ReportGroup` / `ReportRow`):

- Groups by title; each group header shows the count and total size, and offers
  select-all / confirm-group / apply-edits actions.
- **While a path edit is pending (`hasPathEdits`) the group toolbar renders
  "Update Paths" instead of "Confirm"** — the user applies or discards the edit
  before confirming.
- Rows show source name, source path, target path, type, action, file size,
  cross-drive indicator, and status pills. The `Type` column shows `SxxEyy` for
  episodes, `Movie` for movies, and `Extra` (+ extra kind when known) for
  extras; rows within a group are ordered ascending (S01E01 first).
- Suspect rows show a warning badge + flags + `correctionNote`; corrected rows
  show a "Corrected" badge; each row has a "Browse…" button that opens
  `BrowseModal` for re-targeting (per row or per title group).
- Target paths are **editable**; edits go through `onTargetInputChange` (smart
  sync) and are submitted per group via `applyGroupTargetEdits`.
- Filtering (`all`/`move`/`replace`/`existing`/`new`) via `matchesFilter`;
  selection modes via `setCheckedItems`.

## BrowseModal

Opens on a combined **"All libraries"** view (no root/kind chips — the user may
not know which library a show belongs to): all media roots are listed as folder
rows; clicking one browses into it, and the breadcrumb/`..` return to the
combined view. Search (`/api/browse/search`) already searches every movie +
series root. Selecting a folder for a series item joins the matching season
subdir server-side (or `Season {ss}`); "apply to group" re-targets the whole
title group (400 for a season-level pick over a multi-season group). Selecting
an "as movie" candidate flips the item type to movie. On select → POST
`/api/scans/{scan_id}/items/retarget` → `fetchReport`.

## ConfirmModal

- `PreflightView` — shows what will happen: item list, counts of moves vs
  replaces, cross-drive count, total size, and a warning when cross-drive
  transfers will take longer.
- `ProgressView` — renders the confirm progress payload (status, phase label via
  `formatConfirmPhase`, processed/total, elapsed, ETA, per-file copied/speed/%).
- When a move is already running (`confirmActive`), a warn box explains the
  batch will be **added to the queue** — it auto-starts when the current move
  finishes.

## Toasts

`TransferToasts` renders per-file state for the active batch
(`deriveTransferQueue`: queued/copying/done/failed). When batches are queued
behind the active move, the header appends `· N batch(es) queued` and a
"Queued" section lists each pending batch (`title — N item(s)`).

## PathPills

Renders a path with the drive root styled separately (`splitDrive`); `StatusPill`
renders exists/type/action hints with tooltips.

## HistoryPage

`HistoryPage.jsx:5` fetches `GET /api/history?limit=50` → `history_groups` + `history_items`
(`app.db` `history_groups`/`history_items`, written by `ScanManager.confirm_scan` →
`history_store.append_history_group`). One Confirm = one card; two Confirms on same
`sourceFolder` = two cards (`history_id` per Confirm, not per folder).

* **Data:** `history_items` carry `suspect`/`corrected`/`correction_note`/`cross_drive`
  (migrated via `ALTER TABLE` in `app/core/db.py`), `path_history_json` (`[source, target, …]`)
  for the full movement trail, plus live `source_exists`/`target_exists`/`pathExists`
  computed by `history_store.list_history_groups`/`get_history_group` for `PathPills`.
* **Expanded row parity with `ReportPanel`:** `Action` badge + `Cross-drive`/`Suspect`/`Corrected`
  badges + `PathPills`, `Type` column (`SxxEyy` / `Movie` / `Extra`, ascending
  row order), editable target input with `Browse…` (`BrowseModal.jsx:FolderPicker`
  extracted presentational picker), `Size` (`formatBytes`), `Trail` (compact summary button →
  modal table `#/Path/Action` with per-hop badge: first hop reflects stored `action` (`move` vs
  `replaced`), later hops are retargets), `Status`, `Delete` when `source_exists` (`POST
  /api/history/{id}/delete-source`, 404 unknown item, `deleted: false` if file already gone).
* **Actions:** `Undo` (`POST /api/history/{id}/undo`) and `Save & Move Again`
  (`POST /api/history/{id}/retarget` with `updates`).
* **Scan history is not History:** `GET /api/scans/history` (`reports/history/*.json` + `app.db`
  `scans`, `MAX_HISTORY=200` in `app/services/scan_history.py:12`, merged DB+files via
  `list_history`) stays on Dashboard `Recent:` and `GET /api/scans/history`, **not** in
  `/history`. When `0` confirms, History shows `No confirms yet`.
* **DB note:** `scans` upsert uses `ON CONFLICT DO UPDATE` (`app/services/scan_history.py:89`)
  not `INSERT OR REPLACE`, so the `history_groups.scan_id` FK cascade is not triggered on
  scan progress updates.
