# MCP Auth + Configuration & API-Key Pages

Owner request: add multiple pages to the Web UI — one to manage all environment
variables and one to manage API keys that are used to access this MCP server.
Add a flag `MCP_ALLOW_UNAUTHENTICATED` that lets all unauthenticated MCP
requests through; when disabled, requests must present a valid API key.

## Current state (verified)

- `POST /mcp` (`app/main.py:1093`) has **no authentication** and the Web UI
  proxies `/mcp` to `http://localhost:18327/mcp` with **only** the
  `Content-Type` header (`app/ui/server.py:35-37`).
- Settings are read from `.env` via pydantic-settings (`app/core/config.py`),
  cached by a module-global `_settings` and `@lru_cache get_config()`.
  Changes only apply after a process start.
- `.env` is bind-mounted into the container (`.:/app` volume + `env_file`).
  `env_file` is applied at **container creation**, so `.env` edits need a
  `docker compose` recreate, not just `docker restart`.
- Web UI is a single-file SPA (`app/ui/index.html`, 1711 lines). The `.tabs` /
  `.tab-content` CSS scaffolding exists but the tab bar was removed (plan 02).
- `config/` is bind-mounted and already holds `ongoing_releases.json`.
- No secrets/paths policy change: repo must never contain real keys.

## Design decisions

- **D1 — Page model (DECIDED):** keep the single SPA and add a top-level nav
  with three page sections: **Scan & Move**, **Settings**, **API Keys**. The
  page content lives in `index.html` and JS switches sections.
- **D1.1 — Env apply model (DECIDED):** saving a setting writes `.env`
  **immediately** (the bind mount makes the file change visible on the host
  instantly). Whether the running container picks it up depends on how the
  value is consumed:
  - **Applied live** — an in-process `reload_settings()` re-reads `.env`,
    patches `os.environ`, resets the `_settings` cache and clears
    `get_config`. Verified per-request consumers pick these up on the next
    call with **no restart** (see Part E.1).
  - **Recreate required** — values baked into long-lived state at startup
    (`ScanManager` holds `self._config` from `app/core/config.py`, `WEB_UI_*`
    spawn the UI thread in the lifespan). These show a **"Recreate required"**
    banner listing the changed vars and the exact command.
- **D2 — `MCP_ALLOW_UNAUTHENTICATED` default:** recommend `true` on first
  rollout (preserves current behavior) and flip to `false` after keys exist.
  Secure-by-default (`false`) is the end state. Ask the owner.
- **D3 — API key storage:** `config/mcp_keys.json` (bind-mounted, survives
  rebuilds, read per-request — **no container restart needed** when keys
  change). Keys stored **hashed** (SHA-256), full key shown once at creation.
- **D4 — Console access gate (DECIDED):** a single `SERVER_PASSWORD` env var
  controls console access:
  - **`SERVER_PASSWORD` set** → the console binds `0.0.0.0` (reachable from
    any IP on the LAN) and a **login screen** requires the password before the
    UI (including the Settings + API Keys admin pages) loads.
  - **`SERVER_PASSWORD` empty** → no login prompt, but the console only binds
    `127.0.0.1` / localhost — not reachable from the LAN.
  - The bind address lives in a derived `UI_BIND_HOST` env var that
    `env_manager` auto-syncs from `SERVER_PASSWORD` on save (one knob drives
    both). Bind changes need a container recreate (existing banner mechanic).
- **D4.1 — Docker bind mechanics:** `env_file` passes `UI_BIND_HOST` to the
  container, but `docker-compose.yml` sets `environment: UI_BIND_HOST: "0.0.0.0"`
  (compose `environment` overrides `env_file`), so the app always listens on
  all interfaces **inside** the container. The actual LAN/localhost boundary is
  enforced by the **host-side port binding** in compose:
  `"${UI_BIND_HOST:-127.0.0.1}:18329:18329"`. This is required because
  docker-proxy forwards published ports to the container's bridge IP — a
  loopback-only bind inside the container would break even host-localhost
  browsing. Non-Docker (`uvicorn` on the host) uses `UI_BIND_HOST` directly.
- **D5 — Auth failure transport:** HTTP `401` with a JSON-RPC error body
  (`code: -32001, message: "unauthorized"`). Standard MCP clients treat 401 as
  an auth failure; keep `id` from the request.
- **D6 — Per-key tool scopes:** optional. Phase 2 allows a key to be restricted
  to a subset of tool names (`scopes: ["get jellyfin library items", ...]`).
  Not required for v1.

## Part A — Config additions (`app/core/config.py`)

```python
mcp_allow_unauthenticated: bool = Field(default=True, alias="MCP_ALLOW_UNAUTHENTICATED")
mcp_keys_file: str = Field(default="config/mcp_keys.json", alias="MCP_KEYS_FILE")
admin_ui_token: str | None = Field(default=None, alias="ADMIN_UI_TOKEN")
```

Add all three to `.env.example` under a new `── MCP Access Control ──` section.

## Part B — API key store (`app/services/api_key_manager.py`)

New module, no restart required on write:

```json
{
  "keys": [
    {
      "id": "k_2f7c...",
      "name": "opencode on laptop",
      "user": "owner",
      "key_prefix": "jsort_a1b2",
      "key_hash": "sha256:<hex>",
      "scopes": ["*"],
      "enabled": true,
      "created_at": "2026-08-11T...",
      "last_used_at": null
    }
  ]
}
```

API:

- `create_key(name, user, scopes) -> dict` — generate `jsort_` + 32 hex chars,
  store hash only, return full key **once**.
- `list_keys() -> list[dict]` — never includes the hash or full key.
- `set_enabled(key_id, enabled)`, `delete_key(key_id)`.
- `authenticate(raw_key) -> dict | None` — constant-time compare
  (`hmac.compare_digest`) against stored hashes; updates `last_used_at`.
- Read file fresh per call (small file) or cache keyed on mtime.

Thread-safety: guard writes with a `threading.Lock`.

## Part C — MCP auth enforcement (`app/core/auth.py`, `app/main.py`)

- New dependency `require_mcp_auth(request: Request)` applied to `/mcp`:
  - `MCP_ALLOW_UNAUTHENTICATED=true` → pass, set `request.state.mcp_user = "anonymous"`.
  - Otherwise read `Authorization: Bearer <key>` **or** `X-API-Key: <key>`.
  - Valid key → `request.state.mcp_user = key.user`; invalid/missing → HTTP 401
    + JSON-RPC error body (D5).
- `ADMIN_UI_TOKEN`, when set, is accepted as a valid key for user `"admin"`
  (so the UI proxy can authenticate when unauth is off).
- Log the auth result in the existing activity line
  (`_format_mcp_activity_line` in `app/main.py:99`) — append
  `as <user>`.
- `initialize` / `ping` may stay open or use the same gate — use the same gate
  for simplicity and consistency.

## Part D — UI proxy header passthrough (`app/ui/server.py`)

`proxy_mcp` currently drops all headers except `Content-Type`. Change to:

1. Forward the incoming `Authorization` / `X-API-Key` header if present.
2. Else, attach `Authorization: Bearer <ADMIN_UI_TOKEN>` when configured.
3. Else, no header (works while `MCP_ALLOW_UNAUTHENTICATED=true`).

## Part E — Environment variable management

### `app/services/env_manager.py`

- `ENV_SPEC`: manifest of every setting with `{key, section, type, secret,
  apply, description}` — mirrors the `.env.example` sections (AI/Classification,
  Download Client, Web UI, Jellyfin, Storage Paths, MCP Access Control).
  Secret keys: `*API_KEY*`, `QBT_WEBUI_PASS`, `ADMIN_UI_TOKEN`.
- `apply: "live" | "restart"` per variable:

  | Variable | apply | Why |
  |---|---|---|
  | `ENABLE_JELLYFIN_INTEGRATION`, `JELLYFIN_BASE_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_MOVIE_LIBRARY_NAME`, `JELLYFIN_SERIES_LIBRARY_NAME` | live | `JellyfinClient.from_env()` reads `os.environ` per call |
  | `ENABLE_DOWNLOAD_CLIENT_CHECK`, `DOWNLOAD_CLIENT`, `QBT_MCP_URL`, `QBT_MCP_API_KEY`, `QBT_WEBUI_USER`, `QBT_WEBUI_PASS` | live | `QbittorrentClient.from_env()` reads `os.environ` per operation |
  | `OPENROUTER_API_KEY`, `MODEL_PROVIDER`, `MODEL_MODE`, `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_TEMPERATURE`, `MODEL_REQUEST_TIMEOUT_SECONDS`, `MODEL_RETRY_ATTEMPTS` | live | model clients built per classification call from env |
  | `MCP_ALLOW_UNAUTHENTICATED`, `MCP_KEYS_FILE`, `ADMIN_UI_TOKEN` | live | auth dependency reads settings per request |
  | `DOWNLOAD_ROOTS`, `MOVIE_ROOTS`, `SERIES_ROOTS`, `SERIES_TITLE_ALIASES`, `MODEL_CLASSIFY_CONFIDENCE_THRESHOLD`, `MODEL_PATH_CONFIDENCE_THRESHOLD`, `WEB_UI_ENABLED`, `WEB_UI_PORT` | restart | captured in the `ScanManager(self._config)` snapshot or in the startup lifespan (web UI thread) |

  This table must be verified during implementation against actual call
  sites; any var found to be read from the `ScanManager` snapshot moves to
  `restart`.

- `list_env() -> {saved, effective, spec}`:
  - `saved`: parsed from `BASE_DIR / ".env"` (`BASE_DIR` already exists in
    `app/core/config.py`).
  - `effective`: from `get_settings()` (the running process).
  - Secrets are **masked** in both unless explicitly revealed.
  - Flag entries where `saved != effective` (pending a restart).
- `reload_settings()`:
  - Re-parse `.env`; for each changed key set `os.environ[key]` (or delete).
  - Reset the module-global `_settings` to `None` and call
    `get_config.cache_clear()`.
  - This is what makes `apply: "live"` vars take effect without a restart.
- `update_env(changes)`:
  - Validate first by constructing `Settings(**os.environ, **changes)` —
    reject on Pydantic error with a readable message.
  - Rewrite `.env` **preserving comments** (line-wise edit; only touch known
    keys) and write atomically (`write` + `os.replace`).
  - For each changed var, call `reload_settings()` for `live` vars.
  - Return the list of changed vars that are `apply: "restart"` so the UI can
    show the recreate banner.
- The UI shows a **"Recreate required"** banner with
  `docker compose up -d --force-recreate` when any saved change is
  `apply: "restart"`. (The container cannot restart itself without a docker
  socket — do not mount one.)

### Endpoints (on the UI app, `app/ui/server.py`)

- `GET /admin/env` → spec + saved + effective + pending-restart diff.
- `POST /admin/env` → `{updates: {KEY: value}}`, masks out any secret field
  that the client left blank (blank = "keep unchanged"); responds with
  `{appliedLive: [...], needsRecreate: [...]}`.

## Part F — API-key management endpoints (UI app)

- `GET /admin/api-keys` → list (no secrets).
- `POST /admin/api-keys` → `{name, user?, scopes?}` → full key in response
  once. **`name` is required** — 422/400 with `"name is required"` if missing
  or blank. `user` and `scopes` are optional (default `user: "default"`,
  `scopes: ["*"]`).
- `PATCH /admin/api-keys/{id}` → toggle `enabled`.
- `DELETE /admin/api-keys/{id}`.

All admin endpoints (Part E + F) require `ADMIN_UI_TOKEN` (D4) — 401 otherwise.

## Part G — Web UI pages (`app/ui/index.html`)

1. **Nav bar** at the top (reuse `.tabs` CSS): `Scan & Move` | `Settings` |
   `API Keys`. `showPage(id)` toggles `.tab-content.active`.
2. **Scan & Move** — the existing page moved into a section.
3. **Settings page**:
   - Render `ENV_SPEC` grouped by section.
   - Text/number/bool inputs per type; secret fields masked with reveal toggle.
   - Per-var badge: **live** (applies on save) vs **recreate** (needs
     recreate) — plus an "Effective vs saved" indicator.
   - On save, if any changed var is `apply: "restart"`, show a **"Recreate
     required"** banner listing the vars and the `docker compose up -d
     --force-recreate` command.
   - "Save" → `POST /admin/env`.
4. **API Keys page**:
   - Table: name, user, prefix, enabled, created, last used, scopes, actions.
   - "Create Key" form with a **required Name** input (blocked until filled),
     optional user + scopes → show the full key once in a copyable modal with
     a "store it now, it will not be shown again" warning.
   - Enable/disable + delete actions.
5. **Admin gate**: if the first admin call returns 401, show a password overlay
   that stores the token in `sessionStorage` and retries.
6. **Client setup hint** on the API Keys page: show the header snippet for
   MCP clients (`Authorization: Bearer <key>`) and the opencode remote MCP
   config shape (`"headers": {"Authorization": "Bearer ..."}`).

## Tests (`tests/`)

- `test_api_key_manager.py`: create→authenticate round-trip; **create without
  `name` rejected**; full key not retrievable after creation; wrong key /
  disabled key / unknown key rejected; enable/disable; delete; list never
  leaks hash; file round-trip.
- `test_mcp_auth.py`: `MCP_ALLOW_UNAUTHENTICATED=true` passes without headers;
  `=false` rejects missing/invalid key with 401 + JSON-RPC body; valid Bearer
  and `X-API-Key` both pass; `ADMIN_UI_TOKEN` accepted.
- `test_env_manager.py`: `list_env` masks secrets and detects
  saved≠effective; `update_env` validates (bad bool/int rejected), preserves
  comments, writes atomically (tmpdir); `reload_settings` updates
  `os.environ` and clears caches; live vs restart classification correct.
- Keep existing `python3 -m pytest tests/` green.

## Files touched

- `app/core/config.py` — new settings fields.
- `app/core/auth.py` (new) — MCP + admin auth dependencies.
- `app/services/api_key_manager.py` (new) — key store.
- `app/services/env_manager.py` (new) — ENV_SPEC, read/write `.env`.
- `app/main.py` — `/mcp` gate + auth in activity log.
- `app/ui/server.py` — admin endpoints, proxy header passthrough.
- `app/ui/index.html` — nav + Settings page + API Keys page + admin gate.
- `.env.example`, `.env` — `MCP_ALLOW_UNAUTHENTICATED`, `MCP_KEYS_FILE`,
  `ADMIN_UI_TOKEN`.
- `tests/*`, `CHANGELOG.md`, `AGENTS.md` (patterns section), `version.py`
  bump per release workflow.

## Implementation order

1. Part A config + Part B key store + Part C auth + tests (backend core).
2. Part D proxy passthrough; `MCP_ALLOW_UNAUTHENTICATED=true` stays default so
   nothing breaks.
3. Part E env manager + endpoints + tests.
4. Part F key endpoints.
5. Part G UI pages + admin gate.
6. Run `python3 -m pytest tests/`, then
   `docker compose build && docker compose up -d`, verify per AGENTS.md.

## Rollout / verification

1. With `MCP_ALLOW_UNAUTHENTICATED=true`: existing clients keep working.
2. Create a key in the UI, copy the header snippet into an MCP client.
3. Set `MCP_ALLOW_UNAUTHENTICATED=false` in `.env`, recreate the container.
4. Confirm: keyed client works, unauthenticated curl gets 401, UI still works
   (proxy uses `ADMIN_UI_TOKEN`).
5. Edit an env var in Settings, confirm `.env` updated and the pending-diff
   banner clears after `docker compose up -d --force-recreate`.
6. Confirm no real keys/paths leak into the repo; API keys are hashed on disk.
