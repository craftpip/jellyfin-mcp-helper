from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, get_settings

KEY_PREFIX = "jsort_"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApiKeyManager:
    """Persist and authenticate API keys for MCP access.

    Keys are stored hashed (SHA-256, "sha256:<hex>"); the full key is returned
    exactly once at creation. The JSON file is read fresh per operation and
    writes are guarded by a lock, so key changes apply without a restart.
    """

    def __init__(self, keys_file: str | os.PathLike | None = None) -> None:
        if keys_file is None:
            keys_file = get_settings().mcp_keys_file
        path = Path(keys_file)
        if not path.is_absolute():
            path = BASE_DIR / path
        self._keys_file = path
        self._lock = threading.Lock()
        self._ensure_file()

    # ── persistence ─────────────────────────────────────────────────
    def _ensure_file(self) -> None:
        if not self._keys_file.exists():
            self._keys_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_locked({"keys": []})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._keys_file.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
            data = {"keys": []}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._save_locked(data)

    def _save_locked(self, data: dict[str, Any]) -> None:
        tmp = self._keys_file.with_suffix(self._keys_file.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._keys_file)

    # ── helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _hash_key(raw_key: str) -> str:
        return "sha256:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        public = dict(record)
        public.pop("key_hash", None)
        return public

    def _get_record(self, data: dict[str, Any], key_id: str) -> dict[str, Any] | None:
        for record in data.get("keys", []):
            if record.get("id") == key_id:
                return record
        return None

    # ── API ─────────────────────────────────────────────────────────
    def create_key(self, name: str, user: str = "default", scopes: list[str] | None = None) -> dict[str, Any]:
        if not name or not str(name).strip():
            raise ValueError("name is required")
        raw_key = KEY_PREFIX + secrets.token_hex(16)
        record = {
            "id": "k_" + secrets.token_hex(6),
            "name": str(name).strip(),
            "user": str(user).strip() or "default",
            "key_prefix": raw_key[:12],
            "key_suffix": raw_key[-4:],
            "key_hash": self._hash_key(raw_key),
            "scopes": list(scopes) if scopes else ["*"],
            "enabled": True,
            "created_at": _now_iso(),
            "last_used_at": None,
        }
        with self._lock:
            data = self._load()
            data["keys"].append(record)
            self._save_locked(data)
        public = self._public_record(record)
        public["key"] = raw_key
        return public

    def list_keys(self) -> list[dict[str, Any]]:
        data = self._load()
        return [self._public_record(record) for record in data.get("keys", [])]

    def set_enabled(self, key_id: str, enabled: bool) -> bool:
        with self._lock:
            data = self._load()
            record = self._get_record(data, key_id)
            if record is None:
                return False
            record["enabled"] = bool(enabled)
            self._save_locked(data)
        return True

    def delete_key(self, key_id: str) -> bool:
        with self._lock:
            data = self._load()
            records = data.get("keys", [])
            remaining = [record for record in records if record.get("id") != key_id]
            if len(remaining) == len(records):
                return False
            data["keys"] = remaining
            self._save_locked(data)
        return True

    def authenticate(self, raw_key: str) -> dict[str, Any] | None:
        if not raw_key or not isinstance(raw_key, str):
            return None
        data = self._load()
        candidate_hash = self._hash_key(raw_key)
        for record in data.get("keys", []):
            stored_hash = record.get("key_hash") or ""
            if stored_hash and hmac.compare_digest(stored_hash, candidate_hash):
                if not record.get("enabled", True):
                    return None
                if record.get("last_used_at") != _now_iso():
                    with self._lock:
                        refreshed = self._load()
                        target = self._get_record(refreshed, record.get("id", ""))
                        if target is not None:
                            target["last_used_at"] = _now_iso()
                            self._save_locked(refreshed)
                return self._public_record(record)
        return None
