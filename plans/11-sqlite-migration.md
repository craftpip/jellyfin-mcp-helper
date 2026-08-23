# 11 — SQLite Migration (replace all JSON files) — Phase 1

> **Goal:** Replace every JSON-file store with a single SQLite database *before* building the History feature. No more `*.json` on disk for runtime state — everything lives in `config/app.db` (bind-mounted, survives restarts). This is **Phase 1**; `10-history-and-review.md` is **Phase 2** and depends on this.

---

## 1. Current JSON stores to replace

| File | What it holds | Current code |
|------|---------------|--------------|
| `config/mcp_keys.json` | API keys (hashed) — `ApiKeyManager` | `app/services/api_key_manager.py` |
| `config/ongoing_releases.json` | Ongoing series tracking — `ReleaseTracker` | `app/services/release_tracker.py` |
| `config/history.json` (new, not yet built) | Per-group confirm history with `pathHistory` | `app/services/history_store.py` (planned) |
| `reports/history/*.json` | Per-scan snapshots (20 files) | `app/services/scan_history.py` |
| `reports/report.json` / `config/report.json`? | Current scan report (in-memory + file) | `ScanManager` + `presenters` |

> Note: `logs/` stays as text files; `reports/` may keep the last scan’s JSON for debugging, but not as the source of truth.

## 2. New SQLite location & setup

* **File:** `config/app.db` (SQLite, single file, `a+` WAL mode for concurrent reads/writes, `PRAGMA journal_mode=WAL`, `foreign_keys=ON`)
* **Bind-mount:** `config/` is already `.:/app` bind-mounted, so `config/app.db` survives `docker restart` / `docker compose up -d` just like the JSON files did.
* **Init:** `app/core/db.py` — `get_db()` returns a `sqlite3.Connection` (or `aiosqlite` if we go async), creates tables if not exist, handles migrations via `user_version` PRAGMA.

## 3. Schema (sketch)

```sql
-- API keys (replaces mcp_keys.json)
CREATE TABLE IF NOT EXISTS api_keys (
  id TEXT PRIMARY KEY,          -- k_…
  name TEXT NOT NULL,
  user TEXT NOT NULL,
  key_prefix TEXT NOT NULL,     -- first 16 chars
  key_suffix TEXT NOT NULL,     -- last 8 chars
  key_hash TEXT NOT NULL,       -- sha256:…
  scopes TEXT NOT NULL,         -- JSON array
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,     -- ISO
  last_used_at TEXT
);

-- Ongoing releases (replaces ongoing_releases.json)
CREATE TABLE IF NOT EXISTS ongoing_releases (
  series_key TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  last_episode TEXT,
  updated_at TEXT NOT NULL
);

-- Scan history (replaces reports/history/*.json)
CREATE TABLE IF NOT EXISTS scans (
  scan_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  operation TEXT NOT NULL,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  counts_json TEXT NOT NULL,    -- JSON of ScanCounts
  service_errors_json TEXT,     -- JSON
  report_json TEXT              -- Full report for debugging (optional)
);

-- Per-group confirm history with pathHistory (replaces config/history.json)
CREATE TABLE IF NOT EXISTS history_groups (
  history_id TEXT PRIMARY KEY,
  scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
  group_title TEXT NOT NULL,
  group_key TEXT NOT NULL,
  confirmed_at TEXT NOT NULL,
  confirmed_by TEXT,
  FOREIGN KEY(scan_id) REFERENCES scans(scan_id)
);

CREATE TABLE IF NOT EXISTS history_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  history_id TEXT NOT NULL REFERENCES history_groups(history_id) ON DELETE CASCADE,
  confirm_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_folder TEXT,
  target_path TEXT NOT NULL,
  path_history_json TEXT NOT NULL, -- JSON array [source, target, target2, ...]
  action TEXT NOT NULL,
  item_type TEXT NOT NULL,
  file_size INTEGER,
  status TEXT NOT NULL, -- moved / replaced / failed
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_groups_scan_id ON history_groups(scan_id);
CREATE INDEX IF NOT EXISTS idx_history_groups_title ON history_groups(group_title);
CREATE INDEX IF NOT EXISTS idx_history_items_history_id ON history_items(history_id);
```

*Alternative: Keep `scans.report_json` as a JSON column for the full report, or normalize further — but the sketch above is enough for the History page’s needs.*

## 4. Migration

* **On first run with an existing install:** If `config/app.db` does not exist but JSON files do, run a one-time migration:
  1. For each `config/mcp_keys.json` → insert into `api_keys`
  2. For each `config/ongoing_releases.json` → insert into `ongoing_releases`
  3. For each `reports/history/*.json` → insert into `scans` (and if it has `confirmed` items, also into `history_groups`/`history_items` with `pathHistory: [source, target]`)
  4. For `config/history.json` if it already exists (from a previous run of plan 10) → migrate similarly
* **After migration:** Delete the old JSON files or keep them as `.bak` for one release, then remove.
* **Fresh install:** No migration, just create empty tables.

## 5. Code changes

* **New:** `app/core/db.py` — connection factory, `init_db()`, migration runner, `get_db()`.
* **Modify:**
  * `app/services/api_key_manager.py` → use `sqlite3` instead of `json.load`/`_save_locked`
  * `app/services/release_tracker.py` → same
  * `app/services/history_store.py` (new) → use `sqlite3` (already planned to do so, now it’s the only store)
  * `app/services/scan_history.py` → either remove (if `scans` table replaces it) or make it a thin wrapper over `scans` table for backward compat
  * `app/services/scan_manager.py` / `app/services/scan_orchestrator.py` → after confirm, write to `history_groups`/`history_items` via `history_store`
  * `app/ui/server.py` — history endpoints (`GET /api/history`, etc.) now query SQLite
  * `app/core/config.py` — no change, still reads `.env`
* **Tests:** Update `tests/test_api_key_manager.py`, `test_history.py`, `test_scan_history.py` to use a temporary SQLite file (`tmp_path / "test.db"`) instead of `tmp_path / "mcp_keys.json"`.

## 6. Concurrency & locking

* SQLite with WAL allows concurrent reads and one writer at a time. Use `with get_db() as conn:` and `conn.execute("BEGIN IMMEDIATE")` for writes, or rely on `sqlite3`’s default locking.
* All previous file-lock (`threading.Lock`) logic is replaced by SQLite’s own locking.

## 7. Backup & ops

* The DB is a single file `config/app.db` — backup is `cp config/app.db config/app.db.bak` or `sqlite3 config/app.db .dump > backup.sql`.
* On `docker compose down`, the file persists because `config/` is bind-mounted.
* Provide a CLI or admin endpoint to dump/restore if needed (future).

## 8. Verification

* **Unit:** `pytest tests/` with a fresh `tmp_path` DB — create keys, confirm groups, undo, retarget, check `pathHistory` appends.
* **Manual:** Start with existing JSON files, run the app, check `config/app.db` exists and `SELECT count(*) FROM api_keys` matches old JSON count, and old JSON files are renamed to `.bak`.
* **Rollback:** If the DB is corrupted or missing, the app should log and re-create empty tables (or restore from `.bak`).

---

**Status:** Draft — tell me “looks good” or what to change, and I’ll mark it Ready and not touch code until you say `go`.

**Open question:** Do you want me to keep the `reports/history/*.json` per-scan snapshots as well (for debugging), or truly delete all JSON and only keep `config/app.db`?
