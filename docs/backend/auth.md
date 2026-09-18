# Auth and Admin — MCP keys, env management, admin API

Two auth layers exist, one per surface:

- **MCP auth** (`app/core/auth.py`) — gates `POST /mcp` with API keys.
- **Panel auth** (`app/ui/auth.py`) — gates the Web UI `/api/*` routes with a
  panel password / session token (see [web-ui/overview](../web-ui/overview.md)).

This page covers the MCP side plus the admin API endpoints that manage keys and
environment variables.

## MCP auth (`app/core/auth.py`)

`require_mcp_auth(request)` is a FastAPI dependency on `/mcp`:

- `JELLYSORT_MCP_TOKEN` empty (default) → pass;
  `request.state.mcp_user = "anonymous"`.
- Otherwise, a valid `Authorization: Bearer <token>` or `X-API-Key: <token>`
  matching the token sets `request.state.mcp_user` to `"admin"`;
  missing/invalid tokens raise `MCPUnauthorizedError` → HTTP 401 with the
  JSON-RPC body `{"code": -32001, "message": "unauthorized"}` (request `id`
  preserved). Deprecated aliases `MCP_DEFAULT_TOKEN` and `ADMIN_UI_TOKEN` are
  accepted as fallbacks. The MCP activity log line appends `as <user>`.

## API key store (deprecated)

The old multi-key system (`app/services/api_key_manager.py`, `MCP_KEYS_FILE`)
has been removed. MCP auth is now a single token (`JELLYSORT_MCP_TOKEN`).
The `api_key_manager.py` file still exists but is no longer imported.

## Env management (`app/services/env_manager.py`)

The Settings page backend. `ENV_SPEC` is the manifest of every setting
`{key, section, type, secret, apply, description}` mirroring `.env.example`
sections; secret keys (`*API_KEY*`, `JELLYSORT_MCP_TOKEN`) are
masked. `apply` is `"live"` or `"restart"` (see
[getting-started/configuration](../getting-started/configuration.md)).

- `list_env()` → `{saved, effective, spec}` with secrets masked and
  `saved != effective` flagged (pending restart).
- `reload_settings()` — re-parses `.env` via `_read_dotenv()` and resets the
  cached `Settings` (so `get_settings()` re-reads the file on next call);
  `.env` is the authoritative source fed as init kwargs to `Settings`, no
  `os.environ` patching is involved. `live` vars therefore take effect on the
  next per-request read without a restart.
- `update_env(changes, old_passwords)` — validates by constructing
  `Settings(**merged)` where `merged = {**_read_dotenv(), **updates}` (rejects
  bad values with a readable message), rewrites `.env` line-wise **preserving
  comments** (atomic `write` + `os.replace`), calls `reload_settings()`, and
  returns `{appliedLive: [...], needsRecreate: [...]}` (blank secret fields
  mean "keep unchanged"; changing `UI_PANEL_PASSWORD` requires the old
  password).

## Admin API (`app/ui/server.py`, all behind `require_panel_auth`)

Routes live under `/api/admin/*` (the React apiClient prepends `/api`). They
use the UI panel login, not a separate token.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/admin/env` | List all settings (saved + effective + spec). |
| `POST` | `/api/admin/env` | Update settings (validates, persists to `.env`, returns `appliedLive`/`needsRecreate`). |

Tests: `test_mcp_auth.py`, `test_env_manager.py`, plus the admin endpoint tests in `test_ui_api.py`.