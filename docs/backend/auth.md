# Auth and Admin — MCP keys, env management, admin API

Two auth layers exist, one per surface:

- **MCP auth** (`app/core/auth.py`) — gates `POST /mcp` with API keys.
- **Panel auth** (`app/ui/auth.py`) — gates the Web UI `/api/*` routes with a
  panel password / session token (see [web-ui/overview](../web-ui/overview.md)).

This page covers the MCP side plus the admin API endpoints that manage keys and
environment variables.

## MCP auth (`app/core/auth.py`)

`require_mcp_auth(request)` is a FastAPI dependency on `/mcp`:

- `MCP_ALLOW_UNAUTHENTICATED=true` (default) → pass;
  `request.state.mcp_user = "anonymous"`.
- Otherwise, a valid `Authorization: Bearer <key>` or `X-API-Key: <key>` sets
  `request.state.mcp_user` to the key's `user`; `ADMIN_UI_TOKEN` is accepted as
  user `"admin"`; missing/invalid keys raise `MCPUnauthorizedError` → HTTP 401
  with the JSON-RPC body `{"code": -32001, "message": "unauthorized"}` (request
  `id` preserved). The MCP activity log line appends `as <user>`.

## API key store (`app/services/api_key_manager.py`)

State lives in `MCP_KEYS_FILE` (`config/mcp_keys.json`, gitignored, bind
mounted, read per request — key changes never need a container restart). Keys
are `jsort_` + 32 hex chars; only the SHA-256 hash is stored on disk.

| Operation | Behavior |
| --- | --- |
| `create_key(name, user, scopes)` | Generates the key, stores the hash, returns the **full key exactly once**. `name` is required. |
| `list_keys()` | Never includes hashes or full keys. |
| `set_enabled(key_id, enabled)` / `delete_key(key_id)` | Toggle/remove. |
| `authenticate(raw_key)` | Constant-time compare (`hmac.compare_digest`); updates `last_used_at`. |

Writes are guarded by a `threading.Lock` and use atomic file replacement.

## Env management (`app/services/env_manager.py`)

The Settings page backend. `ENV_SPEC` is the manifest of every setting
`{key, section, type, secret, apply, description}` mirroring `.env.example`
sections; secret keys (`*API_KEY*`, `QBT_WEBUI_PASS`, `ADMIN_UI_TOKEN`) are
masked. `apply` is `"live"` or `"restart"` (see
[getting-started/configuration](../getting-started/configuration.md)).

- `list_env()` → `{saved, effective, spec}` with secrets masked and
  `saved != effective` flagged (pending restart).
- `reload_settings()` — re-parses `.env`, patches `os.environ`, resets the
  cached `Settings`, clears `get_config()`; makes `live` vars take effect
  without a restart.
- `update_env(changes)` — validates by constructing `Settings(**os.environ,
  **changes)` (rejects bad values with a readable message), rewrites `.env`
  line-wise **preserving comments** (atomic `write` + `os.replace`), reloads
  changed `live` vars, and returns `{appliedLive: [...], needsRecreate: [...]}`.

## Admin API (`app/ui/server.py`, all behind `require_panel_auth`)

Routes live under `/api/admin/*` (the React apiClient prepends `/api`). They
use the UI panel login, not a separate token.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/admin/env` | `ENV_SPEC` + saved + effective + pending-restart diff. |
| `POST` | `/api/admin/env` | `{updates: {KEY: value}}` → `{appliedLive, needsRecreate}`; blank secret fields mean "keep unchanged". |
| `GET` | `/api/admin/api-keys` | Key list (no secrets). |
| `POST` | `/api/admin/api-keys` | `{name, user?, scopes?}` → the full key, once. |
| `PATCH` | `/api/admin/api-keys/{id}` | Toggle `enabled`. |
| `DELETE` | `/api/admin/api-keys/{id}` | Delete a key. |

Tests: `test_api_key_manager.py`, `test_mcp_auth.py`, `test_env_manager.py`,
plus the admin endpoint tests in `test_ui_api.py`.