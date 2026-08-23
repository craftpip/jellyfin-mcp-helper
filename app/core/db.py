from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import BASE_DIR

DB_PATH = BASE_DIR / "config" / "app.db"


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with WAL and foreign keys enabled."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL for concurrent reads/writers and foreign keys
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they don't exist and run migrations from JSON files."""
    conn = get_db(db_path)
    try:
        # API keys
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                user TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_suffix TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                key TEXT,
                scopes TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
            """
        )
        # Add key column for existing DBs
        try:
            conn.execute("ALTER TABLE api_keys ADD COLUMN key TEXT")
        except:
            pass
        # Ongoing releases
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ongoing_releases (
                series_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                last_episode TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Scan history (replaces reports/history/*.json)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                scan_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                operation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                counts_json TEXT NOT NULL,
                service_errors_json TEXT,
                report_json TEXT,
                saved_at TEXT NOT NULL
            )
            """
        )
        # Per-group confirm history
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history_groups (
                history_id TEXT PRIMARY KEY,
                scan_id TEXT NOT NULL,
                group_title TEXT NOT NULL,
                group_key TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                confirmed_by TEXT,
                FOREIGN KEY(scan_id) REFERENCES scans(scan_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id TEXT NOT NULL,
                confirm_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_folder TEXT,
                target_path TEXT NOT NULL,
                path_history_json TEXT NOT NULL,
                action TEXT NOT NULL,
                item_type TEXT NOT NULL,
                file_size INTEGER,
                status TEXT NOT NULL,
                error TEXT,
                FOREIGN KEY(history_id) REFERENCES history_groups(history_id) ON DELETE CASCADE
            )
            """
        )
        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_groups_scan_id ON history_groups(scan_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_groups_title ON history_groups(group_title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_items_history_id ON history_items(history_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_saved_at ON scans(saved_at)")

        # Run migration from JSON files if DB is empty
        _migrate_if_needed(conn, db_path or DB_PATH)
    finally:
        conn.close()


def _migrate_if_needed(conn: sqlite3.Connection, db_path: Path) -> None:
    """One-time migration from JSON files to SQLite if tables are empty."""
    import json

    # Check if already fully migrated - only skip if all three main tables have data
    # or if the JSON files no longer exist
    try:
        # Use a more granular check: only skip migrating a specific table if it already has data
        # Don't return early if just one table has data
        pass
    except Exception:
        pass

    # Migrate api_keys
    mcp_keys_path = BASE_DIR / "config" / "mcp_keys.json"
    if mcp_keys_path.exists():
        try:
            data = json.loads(mcp_keys_path.read_text(encoding="utf-8") or "{}")
            for record in data.get("keys", []):
                try:
                    # Check if already exists
                    cur = conn.execute("SELECT 1 FROM api_keys WHERE id = ?", (record.get("id"),))
                    if cur.fetchone():
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO api_keys (id, name, user, key_prefix, key_suffix, key_hash, key, scopes, enabled, created_at, last_used_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.get("id"),
                            record.get("name"),
                            record.get("user", "default"),
                            record.get("key_prefix", ""),
                            record.get("key_suffix", ""),
                            record.get("key_hash", ""),
                            record.get("key", ""),
                            json.dumps(record.get("scopes", ["*"])),
                            1 if record.get("enabled", True) else 0,
                            record.get("created_at"),
                            record.get("last_used_at"),
                        ),
                    )
                except Exception:
                    continue
            # Backup old file
            try:
                mcp_keys_path.rename(mcp_keys_path.with_suffix(".json.bak"))
            except Exception:
                pass
        except Exception:
            pass

    # Migrate ongoing_releases
    ongoing_path = BASE_DIR / "config" / "ongoing_releases.json"
    if ongoing_path.exists():
        try:
            data = json.loads(ongoing_path.read_text(encoding="utf-8") or "{}")
            for key, val in data.items():
                if isinstance(val, dict):
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO ongoing_releases (series_key, title, last_episode, updated_at) VALUES (?, ?, ?, ?)",
                            (key, val.get("title", key), val.get("last_episode"), val.get("updated_at", "")),
                        )
                    except Exception:
                        continue
            try:
                ongoing_path.rename(ongoing_path.with_suffix(".json.bak"))
            except Exception:
                pass
        except Exception:
            pass

    # Migrate reports/history/*.json
    history_dir = BASE_DIR / "reports" / "history"
    if history_dir.exists():
        for f in history_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8") or "{}")
                scan_id = data.get("scan_id") or f.stem
                # Check if already exists
                cur = conn.execute("SELECT 1 FROM scans WHERE scan_id = ?", (scan_id,))
                if cur.fetchone():
                    continue
                counts = data.get("summary") or data.get("counts") or {}
                conn.execute(
                    "INSERT OR IGNORE INTO scans (scan_id, status, operation, created_at, finished_at, counts_json, service_errors_json, report_json, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        scan_id,
                        data.get("status", "completed"),
                        data.get("operation", "organize"),
                        data.get("created_at") or data.get("saved_at") or "",
                        data.get("finished_at") or "",
                        json.dumps(counts),
                        json.dumps(data.get("service_errors", {})),
                        json.dumps(data),
                        data.get("saved_at", ""),
                    ),
                )
            except Exception:
                continue
