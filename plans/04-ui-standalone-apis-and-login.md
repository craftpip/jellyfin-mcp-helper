# UI Standalone APIs + Panel Login

> **Status: COMPLETE** (implemented on the `dev` branch, released as v0.0.3).
> The React UI is fully independent of the MCP server — it calls native `/api`
> routes on the UI server that share the backend `ScanManager`/`ReleaseTracker`.
> Panel auth via `UI_PANEL_PASSWORD` works (empty = direct login). The `/mcp`
> proxy route was removed from `server.py` per D2. Notes on deviations:
> - Auth lives in `app/ui/auth.py` (login, logout, `require_panel_auth`),
>   exactly as planned; tokens are in-memory 32-hex strings.
> - `POST /api/libraries/scan` takes `{libraryName, ...}` in the body (no path
>   segment), matching the plan's route table.
> - Presenter extraction (Part A) kept behavior byte-identical; MCP tool
>   responses are unchanged (verified by the full pytest suite).
> - Verification: 127 backend tests + 33 frontend tests green; live panel loads
>   via `/api` with no console errors; `/api/status` reports
>   `auth.required: false` while `UI_PANEL_PASSWORD` is empty.

Owner request: make the Web UI panel independent of the MCP server. MCP is just
one feature JellySort offers; the panel should be its own thing. Replace every
MCP tool call the React UI currently makes with native HTTP APIs on the UI app,
and add an optional panel login password controlled by an environment variable.
When no password is set, the panel logs in directly with no prompt.

## Current state (verified)

- The React app (port 18329) does **not** talk to the backend directly. It
  POSTs JSON-RPC `tools/call` to `/mcp`, which `app/ui/server.py:59` proxies to
  `http://localhost:18327/mcp` (the MCP app in the same container/process).
  If the MCP endpoint is gone, the whole UI is dead — that is the coupling this
  plan removes.
- The UI uses exactly these MCP calls (all in `app/ui/react/src/store/AppStore.jsx`):

  | MCP call | Used for | AppStore line |
  |---|---|---|
  | `tools/list` (`mcpListTools`) | connection check | 162 |
  | `get available jellyfin libraries list` | library dropdown | 167 |
  | `trigger jellyfin library scan` | scan a library | 187 |
  | `move new downloads scan` | start scan | 213 |
  | `get move new downloads scan progress` | scan progress poll | 233 |
  | `get move new downloads scan report` | report load | 137 |
  | `update move new downloads scan` | apply target edits | 376 |
  | `confirm move new downloads scan` | run confirm | 460 |
  | `get move new downloads confirm progress` | confirm progress poll | 483 |
  | `delete move new downloads scan items` | delete source files | 539, 567 |

  The other MCP tools (recently added files, library items, ongoing series,
  release tracker, ...) are **not** used by the UI.
- The UI app is created by `create_ui_app(mcp_target_url)` in
  `app/ui/server.py:20` and spawned as a daemon thread from the MCP app's
  lifespan (`app/main.py:580`, `_start_ui_server`). It currently has no access
  to the `ScanManager` / `ReleaseTracker` instances — that is why it proxies
  instead of calling them directly.
- All the response formatting the UI relies on (`_format_scan_progress`,
  `_format_scan_report`, `_format_confirm_progress`, `_format_report_items`,
  `_is_cross_drive_transfer`, `EPISODE_TAG_RE`, ...) lives in `app/main.py`.
  Reusing them from `app/ui/server.py` would create a circular import
  (`main.py` imports `create_ui_app`).
- Web UI is enabled via `WEB_UI_ENABLED=true`; port 18329 is published in
  `docker-compose.yml` (`"18329:18329"`). No auth exists anywhere on the panel.
- `.env` is bind-mounted; `docker-compose.yml` `env_file: .env` is applied at
  container create, so a new env var needs `docker compose up -d --force-recreate`
  to take effect in the running container.

## Design decisions

- **D1 — UI is self-sufficient (DECIDED).** `create_ui_app(scan_manager=None,
  release_tracker=None)`. When instances are passed (normal single-container
  run from `main.py`), both FastAPI apps share the same process state — the
  same `ScanManager`, the same `ReleaseTracker`. When none are passed (running
  the UI fully standalone with its own uvicorn entrypoint), the UI app builds
  them in its own lifespan. Either way the UI's backend never touches MCP.
- **D2 — MCP stays a feature, not a dependency (DECIDED).** `app/main.py`
  keeps serving the MCP server on 18327/18328 for MCP clients. The UI proxy
  route (`/mcp`) is **removed** from `server.py`; the React app talks only to
  native `/api/*` endpoints. MCP tool responses keep their current shapes for
  external clients; the UI gets equivalent native endpoints.
- **D3 — One native endpoint per UI action, same response body (DECIDED).**
  Each native endpoint returns exactly the JSON the equivalent MCP `tools/call`
  returned, so `AppStore.jsx` changes are mechanical (swap `mcpCall` for an
  `apiCall` with the URL). No response-shape translation layer in the client.
- **D4 — Panel password from env (DECIDED).** New env var
  `UI_PANEL_PASSWORD` (`app/core/config.py` field `ui_panel_password`,
  default `""`):
  - **Set (non-empty)** → the panel shows a login screen; every `/api/*` call
    (except `/api/login` and `/api/status`) requires a session token.
  - **Empty (default)** → direct login, no prompt, all endpoints open.
  - Value is read via `get_settings()` at request time, so a password change
    needs a container recreate (env_file is applied at create) — same
    limitation as all env vars; documented in the rollout section.
- **D5 — Session token, in-memory (DECIDED).** `POST /api/login` compares the
  submitted password with `UI_PANEL_PASSWORD` using `hmac.compare_digest` and,
  on success, issues a random 32-hex token kept in a module-level set. Clients
  send `Authorization: Bearer <token>`; the auth dependency checks the set.
  Tokens die on process restart (client re-logs-in on 401). No persistence, no
  cookie handling, LAN-scope only — matching the existing security posture of
  the project (no real secrets committed, plan 03).
- **D6 — `/api/status` is public (DECIDED).** Returns `{service, version,
  auth: {required: bool}}` so the React app can decide whether to render the
  login screen before making any authed call.
- **D7 — Static assets stay public (DECIDED).** `/`, `/assets`, `/react`
  redirects remain unauthenticated so the login screen itself can load. The API
  is the gate; there is no sensitive data in the bundle.
- **D8 — Two event loops share the ScanManager (DECIDED, with a guard note).**
  Today only the MCP app's event loop ever calls `ScanManager`; the UI thread
  merely proxies HTTP. After this change the UI app runs its own uvicorn loop
  (separate thread) and calls the same `ScanManager` / `ReleaseTracker`
  instances directly. Verified: `create_scan`, `confirm_scan`, `to_thread` and
  `create_task` are loop-agnostic (`self._loop` at `scan_manager.py:105` is
  written but never read; tasks run on whichever loop called them), so a scan
  started from the UI runs on the UI loop and vice versa. A `threading.Lock`
  already guards release-tracker writes; keep `ScanManager` reads/writes as-is
  (GIL-atomic) but **verify during implementation** that a scan started via MCP
  while the UI polls does not corrupt state (see rollout step 3).
- **D9 — Request logging on the UI app (DECIDED).** Add a lightweight HTTP
  middleware in `server.py` mirroring `main.py`'s `log_requests` (timestamp,
  method, path, duration, HTTP status, `X-Request-ID`) but only for `/api/*`
  — today native UI calls are invisible in the logs.

## Part A — Shared presenters (`app/services/presenters.py`, new)

Move the formatters out of `app/main.py` into a new module imported by both
`app/main.py` and `app/ui/server.py` (avoids the circular import):

- `EPISODE_TAG_RE`, `_format_path_exists`, `_format_report_md`,
  `_format_report_items`, `_report_llm_instructions`, `_report_next_step`,
  `_format_scan_report`, `_format_scan_progress`, `_format_confirm_progress`,
  `_format_duration`, `_format_transfer_speed`, `_is_cross_drive_transfer`.

(Leave `_build_recent_file_items` in `main.py` — it is only used by the
"recently added download files" MCP tool, which the UI does not use.)

Rename them without the leading underscore where sensible (`format_scan_report`,
etc.) and update imports in `main.py`. Keep behavior byte-identical — the MCP
tool responses must not change.

## Part B — Config + env (`app/core/config.py`, `.env.example`)

```python
ui_panel_password: str = Field(default="", alias="UI_PANEL_PASSWORD")
```

`.env.example`, new section:

```ini
# ── Web UI Panel Auth ────────────────────────
# Login password for the Web UI panel (port 18329).
# Empty (default) = direct login, no password prompt.
# Set a value to require a password before the panel APIs respond.
UI_PANEL_PASSWORD=
```

## Part C — Native API endpoints (`app/ui/server.py`)

`create_ui_app(scan_manager=None, release_tracker=None)` builds a FastAPI app
that, when `scan_manager` is None, creates `ScanManager(get_config())` and
`ReleaseTracker()` in its own lifespan (standalone mode). The `/mcp` proxy
route is deleted. New routes (all responses mirror the MCP tool bodies):

| Method + path | Mirrors MCP tool | Request body / query |
|---|---|---|
| `GET /api/status` | `tools/list` + `initialize` | — → `{service, version, auth: {required}}` |
| `GET /api/libraries` | `get available jellyfin libraries list` | — → `{libraries: [...]}` |
| `POST /api/libraries/scan` | `trigger jellyfin library scan` | `{libraryName, itemIds?, itemNames?, recursive?, metadataRefreshMode?, imageRefreshMode?, replaceAllMetadata?, replaceAllImages?}` |
| `POST /api/scans` | `move new downloads scan` | `{replaceExisting?}` → scan-start response (`scan_id`, `message`, progress, ...) |
| `GET /api/scans/current/progress` | `get move new downloads scan progress` | → `_format_scan_progress` body |
| `GET /api/scans/{scan_id}/progress` | same, with scanId | → `_format_scan_progress` body |
| `GET /api/scans/current/report` | `get move new downloads scan report` | → `_format_scan_report` body |
| `GET /api/scans/{scan_id}/report` | same, with scanId | → `_format_scan_report` body |
| `PATCH /api/scans/current/items` | `update move new downloads scan` | `{items: [{confirmId, targetPath}]}` → updated report |
| `PATCH /api/scans/{scan_id}/items` | same, with scanId | → updated report |
| `POST /api/scans/current/confirm` | `confirm move new downloads scan` | `{itemIds?, sourcePaths?, sourcePrefixes?}` → confirm-start response |
| `POST /api/scans/{scan_id}/confirm` | same, with scanId | → confirm-start response |
| `GET /api/scans/current/confirm-progress` | `get move new downloads confirm progress` | → `_format_confirm_progress` body |
| `GET /api/scans/{scan_id}/confirm-progress` | same, with scanId | → `_format_confirm_progress` body |
| `DELETE /api/scans/current/items` | `delete move new downloads scan items` | body `{itemIds: [...]}` → updated report |
| `DELETE /api/scans/{scan_id}/items` | same, with scanId | → updated report |

**No-scan semantics (must mirror the MCP exactly — the UI depends on it):**

- `GET /api/scans/current/progress`, `.../report`,
  `.../confirm-progress` with **no current scan** → HTTP **200** with
  `{hint: "No scan found. ..."}` (same body the MCP tool returns). The React
  app checks `result.hint` in `fetchReport` (`AppStore.jsx:138`) and
  `pollScanProgress` (`:237`) to gracefully clear state — a 404 there would
  surface as a hard error.
- `GET /api/scans/{scan_id}/...` with an **unknown** `scan_id` →
  `manager.get_scan` raises HTTPException 404 (matches the MCP tool's error
  path); map to 404 with the same `detail`.

**Error mapping:** bad input (missing `libraryName`, `itemIds`, `items`) → 400
with a `detail` message mirroring the MCP `-32602` message; service errors →
400/500 with the MCP `-32000` message.

Implement routes as thin handlers that call the shared `ScanManager` /
`ReleaseTracker` methods (same calls `main.py` makes) and wrap with the
presenter functions. `JellyfinClient.from_env()` is built per call, exactly as
`main.py` does. Add the `log_requests` middleware (D9).

**Standalone entry point:** at the bottom of `server.py` add
`if __name__ == "__main__": uvicorn.run(create_ui_app(), host="0.0.0.0",
port=18329)` so the UI can be launched fully on its own
(`python -m app.ui.server`) without the MCP app.

## Part D — Panel auth (`app/ui/auth.py` new, wired in `server.py`)

- `POST /api/login` — body `{password}`; if `ui_panel_password` is empty,
  return 200 with `{token: "", directLogin: true}`. Else
  `hmac.compare_digest(password, ui_panel_password)`; success → 200
  `{token: <32-hex>}`; failure → 401 `{detail: "invalid password"}`.
- `POST /api/logout` — removes the token from the session set.
- Dependency `require_panel_auth` applied to every `/api/*` route except
  `/api/login`, `/api/logout`, `/api/status`:
  - `ui_panel_password` empty → allow.
  - Else `Authorization: Bearer <token>` (or `X-Panel-Token`) present and in
    the in-memory session set → allow; otherwise 401.
- `GET /api/status` returns `auth.required` from `ui_panel_password` so the
  client knows whether to render the login screen.

## Part E — Frontend API client (`app/ui/react/src/api/apiClient.js`, new)

Replace `src/mcp/mcpClient.js` (delete it). Keep a small call surface so
`AppStore.jsx` diffs stay mechanical:

```js
const BASE = '/api'
let token = localStorage.getItem('jsort_panel_token') || ''

export function setAuthToken(t) { token = t; localStorage.setItem('jsort_panel_token', t) }
export async function apiCall(method, path, body) { ... fetch, Authorization header, throw on !ok with detail ... }
export const apiGet   = (path) => apiCall('GET', path)
export const apiPost  = (path, body) => apiCall('POST', path, body)
export const apiPatch = (path, body) => apiCall('PATCH', path, body)
export const apiDelete = (path, body) => apiCall('DELETE', path, body)
```

- All helpers throw on non-2xx with the `detail` message; a 401 is surfaced
  distinctly so the store can flip to the login screen.
- `AppStore.jsx` replacements:
  - `mcpListTools()` in `checkConnection` → `apiGet('/api/status')`; the
    "connected (N tools)" message becomes "connected".
  - `mcpCall('get available jellyfin libraries list')` → `apiGet('/api/libraries')`.
  - `mcpCall('trigger jellyfin library scan', {libraryName: name})` → `apiPost('/api/libraries/scan', {libraryName: name})`.
  - `mcpCall('move new downloads scan')` → `apiPost('/api/scans')`.
  - `mcpCall('get move new downloads scan progress', {scanId})` → `apiGet('/api/scans/current/progress')` or `apiGet('/api/scans/'+scanId+'/progress')`.
  - `mcpCall('get move new downloads scan report', {scanId})` → `apiGet('/api/scans/current/report')` or `apiGet('/api/scans/'+scanId+'/report')`.
  - `mcpCall('update move new downloads scan', {scanId, items})` → `apiPatch('/api/scans/current/items', {items})`.
  - `mcpCall('confirm move new downloads scan', {scanId, itemIds})` → `apiPost('/api/scans/current/confirm', {itemIds})`.
  - `mcpCall('get move new downloads confirm progress', {scanId})` → `apiGet('/api/scans/current/confirm-progress')` or `/api/scans/'+scanId+'/confirm-progress'`.
  - `mcpCall('delete move new downloads scan items', {scanId, itemIds})` → `apiDelete('/api/scans/current/items', {itemIds})`.
- New auth state in the store: `authRequired`, `authed`. `checkConnection`
  reads `/api/status`; when `auth.required && !authed`, the app renders the
  login screen instead of the main UI. On any 401 from an API call, clear the
  token and show the login screen.
- New `src/components/LoginScreen.jsx`: password input, submit → `POST
  /api/login` → store token via `setAuthToken`, re-run `checkConnection`.
- `src/App.jsx`: render `LoginScreen` when `authRequired && !authed`.
- `vite.config.js` dev proxy: change `/mcp` → `/api` (target stays
  `http://localhost:18329`).

## Part F — main.py wiring

- `_start_ui_server` becomes a plain function receiving the shared instances:
  `create_ui_app(app.state.scan_manager, app.state.release_tracker)`.
- Remove the `mcp_port` / `MCP_TARGET_URL` plumbing (UI no longer proxies).
- Update the import of the moved presenters.
- MCP app, `/health`, legacy `/scans`, `/runs` endpoints unchanged.

## Tests (`tests/`, `app/ui/react`)

- `tests/test_ui_api.py` (new):
  - Direct-login mode (no `UI_PANEL_PASSWORD`): `/api/status` returns
    `auth.required=false`; every endpoint responds without a token; response
    bodies match the MCP tool shapes (compare key sets against the MCP handler
    bodies where practical).
  - **No-scan semantics:** `GET /api/scans/current/report`,
    `.../progress`, `.../confirm-progress` with no scan → HTTP 200 + `hint`
    key (not 404); `GET /api/scans/{unknown}/report` → 404.
  - Password mode (monkeypatch env): `/api/login` wrong password → 401, right
    password → token; authed endpoints 401 without token / 200 with token;
    `/api/status` returns `auth.required=true`; `/api/logout` invalidates.
  - Scan lifecycle against a temp-dir `ScanManager` (reuse the fixtures/pattern
    from `tests/test_scan_errors.py`): POST `/api/scans` → poll progress →
    GET report → PATCH items → POST confirm → confirm-progress → DELETE items.
  - Confirm / report with missing or unknown scanId → 404.
- Frontend: `cd app/ui/react && npm test` — update `App.test.jsx` for the
  `/api` client (the fetch mock switches from JSON-RPC bodies to
  method+path routing, and `connected (1 tools)` becomes `connected`); add
  `apiClient` tests (token header, 401 surfaced), keep existing
  report/path-sync tests green.
- Keep `python3 -m pytest tests/` fully green (MCP tool responses unchanged).

## Files touched

- `app/services/presenters.py` (new) — shared formatters moved from `main.py`.
- `app/ui/auth.py` (new) — login, token store, `require_panel_auth`.
- `app/ui/server.py` — `create_ui_app(scan_manager, release_tracker)`, native
  `/api/*` routes, removed `/mcp` proxy, standalone lifespan.
- `app/main.py` — pass shared instances to `create_ui_app`, import presenters.
- `app/core/config.py` — `ui_panel_password` field.
- `.env.example`, `.env` — `UI_PANEL_PASSWORD`.
- `app/ui/react/src/api/apiClient.js` (new), `src/mcp/mcpClient.js` (deleted).
- `app/ui/react/src/store/AppStore.jsx` — swap MCP calls for API calls, auth state.
- `app/ui/react/src/components/LoginScreen.jsx` (new).
- `app/ui/react/src/App.jsx` — login gate.
- `app/ui/react/vite.config.js` — dev proxy `/api`.
- `tests/test_ui_api.py` (new); `app/ui/react/src/App.test.jsx` updates.
- `AGENTS.md` (web UI / project structure sections), `README.md`,
  `docs/web-ui/README.md`, `docs/web-ui/overview.md`, `docs/web-ui/store.md`,
  `docs/web-ui/utils.md` (`src/mcp/` → `src/api/`), `docs/architecture/overview.md`
  (proxy no longer exists) — reflect the standalone API surface. `docs/backend/*`
  (MCP feature docs) stay, since the MCP server itself is unchanged.
- Version bump in `app/core/version.py` per the release workflow.

## Implementation order

1. Part A: extract presenters; update `main.py` imports; run pytest (green).
2. Part B: config field + `.env.example`.
3. Part C + D: native routes + auth on `server.py`; Part F wiring in `main.py`;
   backend tests.
4. Part E: frontend `apiClient.js`, `AppStore.jsx`, `LoginScreen`, `App.jsx`,
   vite proxy; frontend tests.
5. `cd app/ui/react && npm run build`, then per AGENTS.md:
   `docker compose build && docker compose up -d --force-recreate` (new env
   var needs a recreate, not just restart), then re-verify.

## Rollout / verification

1. No `UI_PANEL_PASSWORD` in `.env`: open the panel — loads straight in, no
   login prompt; run a scan, review the report, edit a path, confirm a move,
   delete an item — all through `/api/*`, no `/mcp` requests in the browser
   network tab.
2. Set `UI_PANEL_PASSWORD=changeme`, recreate the container: the panel shows
   the login screen; wrong password → 401/error; correct password → token
   stored, UI loads. Confirm MCP clients on 18328 still work unchanged.
3. Restart the container while logged in → session token invalidated → UI
   shows login again (expected).
4. **Two-loop concurrency (D8):** with a scan running in the UI, start another
   scan via an MCP client on 18328; confirm both progress pollers keep working
   and the newer scan wins (previous cancelled) without a crash or torn state.
5. Verify the file-move flow end to end after the container restart (AGENTS.md
   "Filesystem rollback hazard" — re-check the edited files after restart).
6. Run `python3 -m pytest tests/` and `cd app/ui/react && npm test` — both
   green.
