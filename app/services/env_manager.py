from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.config import BASE_DIR, Settings, get_settings, reset_settings

# ── ENV manifest ─────────────────────────────────────────────────────
# Every setting surfaced in the Web UI Settings page.
#   key         env var name
#   section     grouping shown in the UI
#   type        str | int | float | bool
#   secret      value is masked in the UI / never echoed back
#   apply       "live" (reload_settings makes it effective without a restart)
#               or "restart" (baked into the ScanManager config snapshot or the
#               startup lifespan; needs `docker compose up -d --force-recreate`)
#   description UI help text
#
# apply was verified against the actual call sites (Aug 2026):
#   - JellyfinClient.from_env() / QbittorrentClient.from_env() read os.environ
#     per call  -> live.
#   - MCP auth + ApiKeyManager read get_settings() per request -> live.
#   - ScanManager holds AppConfig at startup (paths, thresholds, model config)
#     and presenters use the cached get_config() -> model/path vars are restart.

ENV_SPEC: list[dict[str, Any]] = [
    # ── Classification ──
    {"key": "MODEL_CLASSIFY_CONFIDENCE_THRESHOLD", "section": "ai", "type": "float", "secret": False, "apply": "restart", "description": "Confidence threshold for classification (0.0 - 1.0)."},
    {"key": "MODEL_PATH_CONFIDENCE_THRESHOLD", "section": "ai", "type": "float", "secret": False, "apply": "restart", "description": "Confidence threshold for path resolution (0.0 - 1.0)."},

    # ── Download Client ──
    {"key": "ENABLE_DOWNLOAD_CLIENT_CHECK", "section": "download", "type": "bool", "secret": False, "apply": "live", "description": "Enable download client checks (stop seeding before moves)."},
    {"key": "DOWNLOAD_CLIENT", "section": "download", "type": "str", "secret": False, "apply": "live", "description": "Download client type.", "options": ["", "qbittorrent", "transmission", "deluge"]},
    {"key": "QBT_WEBUI_URL", "section": "download", "type": "str", "secret": False, "apply": "live", "description": "qBittorrent WebUI URL (e.g. http://10.69.1.164:8080).", "showWhen": {"DOWNLOAD_CLIENT": "qbittorrent"}},
    {"key": "QBT_WEBUI_USER", "section": "download", "type": "str", "secret": False, "apply": "live", "description": "qBittorrent WebUI username.", "showWhen": {"DOWNLOAD_CLIENT": "qbittorrent"}},
    {"key": "QBT_WEBUI_PASS", "section": "download", "type": "str", "secret": True, "apply": "live", "description": "qBittorrent WebUI password.", "showWhen": {"DOWNLOAD_CLIENT": "qbittorrent"}},
    {"key": "TRANSMISSION_URL", "section": "download", "type": "str", "secret": False, "apply": "live", "description": "Transmission RPC URL (e.g. http://10.69.1.164:9091/transmission/rpc).", "showWhen": {"DOWNLOAD_CLIENT": "transmission"}},
    {"key": "TRANSMISSION_USER", "section": "download", "type": "str", "secret": False, "apply": "live", "description": "Transmission username (if auth enabled).", "showWhen": {"DOWNLOAD_CLIENT": "transmission"}},
    {"key": "TRANSMISSION_PASS", "section": "download", "type": "str", "secret": True, "apply": "live", "description": "Transmission password.", "showWhen": {"DOWNLOAD_CLIENT": "transmission"}},
    {"key": "DELUGE_URL", "section": "download", "type": "str", "secret": False, "apply": "live", "description": "Deluge WebUI URL (e.g. http://10.69.1.164:8112).", "showWhen": {"DOWNLOAD_CLIENT": "deluge"}},
    {"key": "DELUGE_PASSWORD", "section": "download", "type": "str", "secret": True, "apply": "live", "description": "Deluge password.", "showWhen": {"DOWNLOAD_CLIENT": "deluge"}},

    # ── Web UI ──
    {"key": "UI_PANEL_PASSWORD", "section": "web", "type": "str", "secret": True, "apply": "live", "description": "Panel login password. Empty = direct login."},

    # ── Jellyfin Integration ──
    {"key": "ENABLE_JELLYFIN_INTEGRATION", "section": "jellyfin", "type": "bool", "secret": False, "apply": "live", "description": "Auto-scan Jellyfin libraries after moving files."},
    {"key": "JELLYFIN_BASE_URL", "section": "jellyfin", "type": "str", "secret": False, "apply": "live", "description": "Jellyfin server URL."},
    {"key": "JELLYFIN_API_KEY", "section": "jellyfin", "type": "str", "secret": True, "apply": "live", "description": "Jellyfin API key (Dashboard > API Keys)."},


    # ── Storage Paths ──
    {"key": "DOWNLOAD_ROOTS", "section": "paths", "type": "str", "secret": False, "apply": "restart", "description": "Comma-separated paths where torrent downloads reside."},
    {"key": "MOVIE_ROOTS", "section": "paths", "type": "str", "secret": False, "apply": "restart", "description": "Comma-separated movie roots. Optional '::description' per entry."},
    {"key": "SERIES_ROOTS", "section": "paths", "type": "str", "secret": False, "apply": "restart", "description": "Comma-separated series roots. Optional '::description' per entry."},
    {"key": "SERIES_TITLE_ALIASES", "section": "paths", "type": "str", "secret": False, "apply": "restart", "description": "Series title aliases: 'alias::canonical' entries separated by commas."},

    # ── MCP Access Control ──
    {"key": "MCP_ALLOW_UNAUTHENTICATED", "section": "mcp", "type": "bool", "secret": False, "apply": "live", "description": "Allow unauthenticated MCP requests. Set false to require an API key or MCP_DEFAULT_TOKEN."},
    {"key": "MCP_KEYS_FILE", "section": "mcp", "type": "str", "secret": False, "apply": "live", "description": "JSON file holding hashed MCP API keys."},
    {"key": "MCP_DEFAULT_TOKEN", "section": "mcp", "type": "str", "secret": True, "apply": "live", "description": "MCP master key — bypasses per-client keys for API use."},
]

ENV_SPEC_KEYS = {item["key"] for item in ENV_SPEC}
ENV_FILE = BASE_DIR / ".env"

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _parse_env_file(env_path: Path | None = None) -> dict[str, str]:
    """Parse KEY=value lines from .env (comments and blanks skipped)."""
    path = env_path or ENV_FILE
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        result[key] = value
    return result


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_value(value: str) -> str:
    if "\n" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if value != value.strip() or "#" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _field_for_key(key: str) -> str | None:
    for field_name, field_info in Settings.model_fields.items():
        if field_info.alias == key:
            return field_name
    return None


def _effective_value(key: str) -> Any:
    field = _field_for_key(key)
    if field is not None:
        return getattr(get_settings(), field)
    # Fallback for spec keys that are read via os.getenv directly (e.g. legacy)
    return os.getenv(key)


def list_env() -> dict[str, Any]:
    """Return the spec plus saved (from .env) and effective (running) values.

    Secrets are masked. `pending` lists keys where saved != effective (needs a
    recreate, or was edited on disk but not yet applied).
    """
    saved = _parse_env_file()
    entries = []
    pending = []
    for item in ENV_SPEC:
        key = item["key"]
        saved_value = saved.get(key, "")
        effective_value = _stringify(_effective_value(key))
        if item["secret"]:
            saved_display = "********" if saved_value else ""
            effective_display = "********" if effective_value else ""
        else:
            saved_display = saved_value
            effective_display = effective_value
        entry = dict(item)
        entry["saved"] = saved_display
        entry["effective"] = effective_display
        entries.append(entry)
        # Only flag pending when the key is actually present in .env; missing
        # keys using defaults (e.g. deprecated WEB_UI_PORT) should not show as
        # pending after a restart/recreate.
        if key in saved and saved_value != effective_value:
            pending.append(key)
    return {
        "spec": entries,
        "saved": {item["key"]: item["saved"] for item in entries},
        "effective": {item["key"]: item["effective"] for item in entries},
        "pending": pending,
    }


def _rewrite_env(updates: dict[str, str]) -> None:
    """Line-wise edit of .env preserving comments; atomic write."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        match = _LINE_RE.match(line)
        if match and match.group(1) in remaining:
            key, value = match.group(1), remaining.pop(match.group(1))
            output.append(f"{key}={_format_value(value)}")
        else:
            output.append(line)
    for key, value in remaining.items():
        output.append(f"{key}={_format_value(value)}")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ENV_FILE.with_suffix(".env.tmp")
    tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(tmp, ENV_FILE)


def reload_settings() -> None:
    """Reset the settings cache so fresh readers pick up the rewritten .env.

    .env is authoritative: get_settings() feeds the parsed file entries as
    init kwargs (highest pydantic precedence), which replaced the old
    os.environ patching. `apply: "live"` variables are therefore effective on
    the next per-request read without a restart.
    """
    reset_settings()


def update_env(changes: dict[str, str]) -> dict[str, list[str]]:
    """Validate and persist env changes.

    Secret fields left blank are treated as "keep unchanged". Returns the list
    of changed vars that are `apply: "restart"` so the UI can show the recreate
    banner.
    """
    if not isinstance(changes, dict):
        raise ValueError("changes must be an object of KEY -> value")
    spec_by_key = {item["key"]: item for item in ENV_SPEC}
    unknown = [key for key in changes if key not in spec_by_key]
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}")

    updates: dict[str, str] = {}
    for key, value in changes.items():
        if value is None:
            continue
        item = spec_by_key[key]
        text = str(value).strip()
        if item["secret"] and text == "":
            if key == "UI_PANEL_PASSWORD":
                updates[key] = ""
            # else: blank secret = keep unchanged for other secrets
            continue
        updates[key] = text

    if not updates:
        return {"appliedLive": [], "needsRecreate": []}

    # Validate by constructing Settings from the merged .env (authoritative).
    from app.core.config import _read_dotenv

    merged = {**_read_dotenv(), **updates}
    try:
        Settings(**merged)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            messages.append(f"{err.get('loc', [])}: {err.get('msg', 'invalid value')}")
        raise ValueError("Invalid setting(s): " + "; ".join(messages)) from exc

    _rewrite_env(updates)
    reload_settings()

    applied_live = [key for key in updates if spec_by_key[key]["apply"] == "live"]
    needs_recreate = [key for key in updates if spec_by_key[key]["apply"] == "restart"]
    return {"appliedLive": applied_live, "needsRecreate": needs_recreate}
