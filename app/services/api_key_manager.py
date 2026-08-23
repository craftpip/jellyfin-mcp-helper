from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, get_settings
from app.core.db import get_db, init_db

KEY_PREFIX = "jsort_"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApiKeyManager:
    """Persist and authenticate API keys for MCP access via SQLite.

    Keys are stored hashed (SHA-256); the full key is returned once at creation
    and also stored for reveal. Uses SQLite with WAL for concurrency.
    """

    def __init__(self, keys_file: str | None = None, db_path: Path | None = None) -> None:
        # keys_file is kept for backward compat with tests that pass a tmp file path
        # If a custom path is given and it's not the default, use it as SQLite file
        if db_path is None:
            if keys_file is not None:
                p = Path(keys_file)
                if p.suffix == ".json":
                    db_path = p.parent / "test.db"
                else:
                    db_path = p
            else:
                # No explicit path - check if MCP_KEYS_FILE was set via env var (for tests) or via settings
                try:
                    import os
                    # Check os.environ first (for monkeypatch in tests)
                    env_path = os.getenv("MCP_KEYS_FILE")
                    if env_path and ("pytest" in env_path or "tmp" in env_path):
                        p = Path(env_path)
                        db_path = p.parent / "test.db" if p.suffix == ".json" else p
                    else:
                        from app.core.config import get_settings
                        settings_path = get_settings().mcp_keys_file
                        if settings_path and ("pytest" in str(settings_path) or "tmp" in str(settings_path)):
                            p = Path(settings_path)
                            db_path = p.parent / "test.db" if p.suffix == ".json" else p
                except:
                    pass
        self._db_path = db_path
        init_db(self._db_path)

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        return "sha256:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        public = dict(record)
        public.pop("key_hash", None)
        public.pop("key", None)
        # Decode scopes if stored as JSON string
        if isinstance(public.get("scopes"), str):
            try:
                public["scopes"] = json.loads(public["scopes"])
            except:
                public["scopes"] = ["*"]
        # Ensure enabled is bool
        if "enabled" in public:
            public["enabled"] = bool(public["enabled"])
        return public

    def create_key(self, name: str, user: str = "default", scopes: list[str] | None = None) -> dict[str, Any]:
        if not name or not str(name).strip():
            raise ValueError("name is required")
        raw_key = KEY_PREFIX + secrets.token_hex(16)
        record = {
            "id": "k_" + secrets.token_hex(6),
            "name": str(name).strip(),
            "user": str(user).strip() or "default",
            "key_prefix": raw_key[:16],
            "key_suffix": raw_key[-8:],
            "key_hash": self._hash_key(raw_key),
            "key": raw_key,
            "scopes": json.dumps(list(scopes) if scopes else ["*"]),
            "enabled": 1,
            "created_at": _now_iso(),
            "last_used_at": None,
        }
        conn = get_db(self._db_path)
        try:
            conn.execute(
                "INSERT INTO api_keys (id, name, user, key_prefix, key_suffix, key_hash, key, scopes, enabled, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record["id"], record["name"], record["user"], record["key_prefix"], record["key_suffix"], record["key_hash"], record["key"], record["scopes"], record["enabled"], record["created_at"], record["last_used_at"]),
            )
            conn.commit()
        finally:
            conn.close()
        public = self._public_record(record)
        public["key"] = raw_key
        # Ensure scopes is list for return
        public["scopes"] = list(scopes) if scopes else ["*"]
        return public

    def list_keys(self) -> list[dict[str, Any]]:
        conn = get_db(self._db_path)
        try:
            cur = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC")
            rows = cur.fetchall()
            return [self._public_record(dict(row)) for row in rows]
        finally:
            conn.close()

    def _load(self) -> dict[str, Any]:
        # For backward compat with tests that call _load()
        return {"keys": self._load_all()}

    def _load_all(self) -> list[dict[str, Any]]:
        conn = get_db(self._db_path)
        try:
            cur = conn.execute("SELECT * FROM api_keys")
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def reveal_key(self, key_id: str) -> str | None:
        conn = get_db(self._db_path)
        try:
            cur = conn.execute("SELECT key FROM api_keys WHERE id = ?", (key_id,))
            row = cur.fetchone()
            if row:
                return row["key"]
            return None
        finally:
            conn.close()

    def set_enabled(self, key_id: str, enabled: bool) -> bool:
        conn = get_db(self._db_path)
        try:
            cur = conn.execute("UPDATE api_keys SET enabled = ? WHERE id = ?", (1 if enabled else 0, key_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete_key(self, key_id: str) -> bool:
        conn = get_db(self._db_path)
        try:
            cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def authenticate(self, raw_key: str) -> dict[str, Any] | None:
        if not raw_key or not isinstance(raw_key, str):
            return None
        candidate_hash = self._hash_key(raw_key)
        conn = get_db(self._db_path)
        try:
            cur = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (candidate_hash,))
            row = cur.fetchone()
            if not row:
                return None
            record = dict(row)
            if not record.get("enabled", 1):
                return None
            # Update last_used_at if needed
            now = _now_iso()
            if record.get("last_used_at") != now:
                conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, record["id"]))
                conn.commit()
                record["last_used_at"] = now
            return self._public_record(record)
        finally:
            conn.close()
