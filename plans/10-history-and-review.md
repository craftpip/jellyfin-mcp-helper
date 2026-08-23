# 10 — Confirm History & Review (per-group)

> **Problem:** Once a group is confirmed, there’s no way to see what happened, fix a mistake, or undo. The current `reports/history/*.json` is per-scan and overwritten, not per-group, and the UI only shows the last scan’s Dashboard strip with a tiny “Undo” button.

> **Goal:** Every confirmed group goes into a durable, reviewable history where you can see *which file → which folder*, when, and edit/undo from there. Keep `source` + `target` for each file, forever (or until pruned).

---

## 1. Angles & Requirements

### 1.1 What to record (per file, per group, per confirm)

* `history_id` (e.g. `h_…`), `scan_id`, `group_title` (e.g. `Nimbus`), `group_key` (show folder), `confirmed_at` (ISO), `confirmed_by` (panel user or `mcp_user`), `action`, `item_type`, `sourcePath`, `sourceFolder`, `targetPath`, `fileSize`, `crossDrive`, `replaced` flag
* Keep the **full path history** per file — an array `pathHistory` for display: initially `[sourcePath, targetPath]`; every later rename/move via the history page appends the new `targetPath`, so the UI can show `source → target → target2 → …` as the file’s journey. The array is **display-only**; the current location is `pathHistory[−1]`.
* Also store `status`: `moved` / `replaced` / `failed` + `error` if any, so the history can show failures.

### 1.2 How long & how much

* **Durable across restarts** — file on disk, not just in-memory `ScanPlan`. Survives `docker restart` and `docker compose up -d`.
* **Pruning:** Keep last 200 groups or 90 days, whichever is hit first. Configurable via `HISTORY_MAX_GROUPS` env. Prune on write, never on read.
* **Privacy:** Paths are on the user’s own disk; no extra anonymization needed beyond what’s already in `reports/`.

### 1.3 When to write

* Write **once per confirm batch** (which is already per-group when the user confirms a group). The `ScanManager` already knows `selected_items` for that batch; after the move loop finishes and Jellyfin is notified, append those items to the history file.
* For one-by-one confirms, that’s one history entry per file but with the same `group_title` — the UI can collapse by group.
* For queued confirms, each batch is a separate history entry with its own `history_id` and `confirmed_at`.

### 1.4 Where to store

* New file `config/history.json` (or `reports/history_log.json`) — **append-only JSON lines or a JSON array with atomic rewrite** (like `mcp_keys.json` and `ongoing_releases.json`). Keep it separate from `reports/history/*.json` which is per-scan and gets overwritten.
* Alternative: `reports/history/` per-group files `h_*.json` — but a single file is easier to list and prune. Choose single file with lock.

### 1.5 How to read / undo / edit

* **Read:** `GET /api/history?limit=50&group=Nimbus` → paginated, newest first. Also `GET /api/history/{history_id}` for detail. The UI will have a new **History** page (or tab in Scan & Move) that lists groups, expandable to files.
* **Undo (per history entry):** `POST /api/history/{history_id}/undo` — moves each `targetPath` back to `sourcePath` if `source` doesn’t exist (never clobber). For `replace` actions, the old library file is gone (overwritten via `os.replace`), so undo can only move the new file back, leaving the library missing that file — we must warn and require confirmation. For `move`, it’s lossless.
* **Edit (re-target after confirm):** The history group looks **exactly like the “Completed” section** — same grouped view. The user can rename folders via input boxes for each file/group (e.g. fix a show folder name that already existed). On **Update & Confirm**, the backend moves each file from its **current `targetPath` (last element of `pathHistory`) to the new `targetPath`** and **appends the new `targetPath` to that file’s `pathHistory` array** (so the array becomes `[source, target1, target2]`). The UI then shows the full trail. The history entry itself is updated in place (or a new version is appended — either way the `pathHistory` is what’s displayed).

### 1.6 Concurrency & failures

* **Cross-drive copies:** History is written only after the copy+delete succeeds. If a file fails, it’s still recorded with `status: failed` and `error`.
* **Queued confirms:** Each batch is its own history entry; the UI must not show “completed” until the queue is drained (we already have that invariant from the confirm queue).
* **Concurrent scans:** History is per-confirm, not per-scan, so a new scan starting while an old confirm is still writing must not interleave. Use the same file lock as `api_key_manager`.

### 1.7 UI

* **New top nav:** `Scan & Move | History | Settings | API Keys` — History is a full page, not just the Dashboard strip.
* **History page:** Same grouped view as the “Completed” section. Each group (e.g. `Nimbus`) shows its files in a table: `Source → Target | Size | Status` with editable **folder name inputs** for the target (like the completed section). Actions per group: **View**, **Undo**, **Save & Move Again** (renames). The `pathHistory` array is rendered as `source → target → target2` for each file. Undo and re-target work per group.
* **ReportPanel after confirm:** Keep the current “Last scan”/history strip, but add a **“View in History”** link that jumps to that group in the History page.
* **Empty state:** “No confirms yet — scan and confirm a group to see it here.”

### 1.8 Auth & API

* All history endpoints are `require_panel_auth` (same as settings). MCP does not need history for now; if the orchestrator needs it later, we can add MCP tools `list history` / `undo history entry`.
* The existing `POST /api/scans/{id}/undo` stays for “undo the last scan’s moves” (per-scan). The new `POST /api/history/{id}/undo` is per-group/per-batch and is the one the History page uses.

### 1.9 Migration & back-compat

* Existing `reports/history/*.json` files stay as they are — they are per-scan snapshots. The new `config/history.json` starts empty and only gets new confirms. No migration of old data needed; old scans will not appear in the new History page until they are re-confirmed.
* If we later want to backfill, we can scan `reports/history/*.json` for `confirmed` items and import them as history entries with `confirmed_at = saved_at`.

### 1.10 Testing & verification

* **Backend:** `tests/test_history.py` — create a scan, confirm a group, assert `history.json` has an entry with correct `sourcePath`/`targetPath`; undo restores the file and marks the history entry as `undone`; re-target moves it again and appends a new entry.
* **Frontend:** `History.test.jsx` — list shows groups, expand shows files, Undo per group works, “View in History” link from Dashboard jumps correctly.
* **Manual:** Confirm a group in the UI, check `config/history.json` on disk, refresh → History page shows it, click Undo → file moves back, `ls` confirms.

---

## 2. Data Model (sketch)

```json
{
  "history": [
    {
      "history_id": "h_a1b2c3",
      "scan_id": "s_…",
      "group_title": "Nimbus",
      "group_key": "/media1/series/Nimbus",
      "confirmed_at": "2026-08-23T12:00:00+00:00",
      "confirmed_by": "panel:user",
      "items": [
        {
          "confirmId": "i1",
          "sourcePath": "/media1/torrents/Nimbus S01E01 …",
          "sourceFolder": "Nimbus S01E01 …",
          "targetPath": "/media1/series/Nimbus/Season 01/Nimbus - S01E01.mkv",
          "pathHistory": [
            "/media1/torrents/Nimbus S01E01 …",
            "/media1/series/Nimbus/Season 01/Nimbus - S01E01.mkv"
          ],
          "action": "move",
          "item_type": "series",
          "fileSize": 123456789,
          "status": "moved",
          "error": null
        }
      ]
      // After the user renames the show folder from history and confirms again:
      // pathHistory becomes [source, target1, target2] e.g.
      // ["/media1/torrents/...", "/media1/series/Nimbus/...", "/media1/series/Correct Name/..."]
    }
  ]
}
```

---

## 0. Prerequisite — Phase 1: SQLite first (see `11-sqlite-migration.md`)

> This whole plan **depends on SQLite being ready first**. Do **not** start the history code until `config/app.db` exists and all JSON stores (`mcp_keys.json`, `ongoing_releases.json`, `reports/history/*.json`) have been migrated to SQLite. Phase 1 is `11-sqlite-migration.md`.

## 3. Implementation Steps (in order — Phase 2, after SQLite)

1. **Backend store** `app/services/history_store.py` — `HistoryStore` now uses **SQLite** (`config/app.db`, tables `history_groups`/`history_items` from Phase 1) with `append(group)`, `list(limit, group)`, `get(id)`, `mark_undone(id)`, `retarget(id, newTargets)` (moves from current `targetPath` to new and appends to `pathHistory`), prune logic, transaction.
2. **ScanManager hook** — after `_run_confirm_task` succeeds for a batch, call `history_store.append(...)` with that batch’s `selected_items` and initial `pathHistory: [sourcePath, targetPath]`.
3. **API** in `app/ui/server.py` — `GET /api/history`, `GET /api/history/{id}`, `POST /api/history/{id}/undo` (moves back to `sourcePath` if possible), `POST /api/history/{id}/retarget` (takes edited folder names, moves `targetPath → newTarget`, appends to `pathHistory`).
4. **Frontend** — new `HistoryPage.jsx` + route `/history` + nav entry, uses `apiGet`/`apiPost`, reuses `ReportPanel` table for file list. Add “View in History” link in `Dashboard.jsx`.
5. **Tests** — backend + frontend as above, plus `ruff`/`mypy` and `500` handling for missing `targetPath`.
6. **Docs** — update `docs/backend/*` and `README.md` with the new History page and its retention.

---

**Status:** Draft — tell me “looks good” or what to change, and I’ll mark it Ready and not touch code until you say `go`.
