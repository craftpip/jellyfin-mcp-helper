# Web UI Overview

## Serving

`app/ui/server.py` (`create_ui_app(scan_manager=None)`) is a small FastAPI app
mounted at `/` on the MCP app in `app/main.py` when `WEB_UI_ENABLED=true`, so the
UI and MCP share the single port `18328`. It shares the backend
`ScanManager`/`ReleaseTracker` instances:

- `GET /` → serves the built React `index.html` from `app/ui/react-dist/`
  (404 with a "React UI not built yet. Run `npm run build` in app/ui/react/."
  hint when the bundle is missing).
- `/assets` and `/react/assets` → static mounts of `react-dist/assets`
  (the `/react/assets` mount is backward-compat for old bookmarks).
- `GET /react` and `GET /react/` → 308 redirect to `/`.
- `/api/*` → native REST routes that operate directly on the shared
  `ScanManager`/`ReleaseTracker` (no MCP round-trip). See "REST routes" below.
- The old `/mcp` JSON-RPC proxy has been removed — the panel is fully
  independent of the MCP server.

## Panel auth

Auth lives in `app/ui/auth.py`:

- When `UI_PANEL_PASSWORD` is non-empty, the `/api` routes (except
  `/api/status`, `/api/login`, `/api/logout`, and the static assets) require a
  Bearer token:
  - `GET /api/status` reports `auth.required`.
  - `POST /api/login` with `{"password": "..."}` returns
    `{"token": <32-hex>}` on success (401 on wrong password); with an empty
    password it returns `{"token": "", "directLogin": true}`.
  - Tokens are **in-memory** (`secrets.token_hex(16)` held in a session set) —
    they die on process restart and the client re-logs-in on any 401.
  - `POST /api/logout` drops the token from the session set.
- With an empty password the panel stays open (`auth.required: false`).

## REST routes

All are mounted under `/api` on port 18328. Requests use JSON bodies and respond
with JSON (204 for body-less success). All routes except `/api/status`,
`/api/login`, `/api/logout` sit behind `require_panel_auth` (panel password or
the admin gate for the `/api/admin/*` routes).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/status` | Service info + `auth.required`. |
| `GET` | `/libraries` | Jellyfin library list (via `JellyfinClient.from_env()`). |
| `POST` | `/libraries/scan` | Trigger a Jellyfin library scan (`{libraryName, ...}` in the body). |
| `POST` | `/scans` | Create a new scan (`{"replaceExisting": true}`). |
| `GET` | `/scans/{scan_id}/progress`, `/scans/current/progress` | Scan progress. |
| `GET` | `/scans/{scan_id}/report`, `/scans/current/report` | Final scan report. |
| `PATCH` | `/scans/current/items` | Update item target paths. |
| `POST` | `/scans/current/confirm` | Start the confirm/move for itemIds (queued when a move is already running). |
| `GET` | `/scans/{scan_id}/confirm-progress`, `/scans/current/confirm-progress` | Confirm progress (incl. `queue_length`/`queue_items`). |
| `DELETE` | `/scans/current/items` | Delete source files + remove items from the plan. |
| `GET` | `/browse/roots` | Configured movie/series roots for the folder browser. |
| `GET` | `/browse?path=<dir>` | Shallow, root-constrained folder listing (`entries` with `videoCount`/`seasonNumber`). |
| `GET` | `/browse/search?q=<text>` | Folder-name search across all roots (normalized + diacritic-folded), depth-limited, capped. |
| `POST` | `/scans/{scan_id}/items/retarget` | Re-target an item (or its whole group) to a browsed folder; server-side filename/season logic, optional `reclassifyAsMovie`. |
| `GET` | `/admin/env` | Env spec + saved + effective + pending-restart diff (Settings page). |
| `POST` | `/admin/env` | Save env changes → `{appliedLive, needsRecreate}`. |
| `GET` | `/admin/api-keys` | MCP API-key list (no secrets). |
| `POST` | `/admin/api-keys` | Create a key → full key once (requires `name`). |
| `PATCH` | `/admin/api-keys/{id}` | Enable/disable a key. |
| `DELETE` | `/admin/api-keys/{id}` | Delete a key. |
| `GET` | `/history?limit=50` | Confirm history groups (`history_groups` + `history_items`, live `source_exists`/`target_exists`/`pathExists`). |
| `GET` | `/history/{history_id}` | Single confirm group with items. |
| `POST` | `/history/{history_id}/undo` | Undo a confirm group (restore moved files). |
| `POST` | `/history/{history_id}/retarget` | Save & Move Again for a history group (`{updates: [{confirmId, directory}]}`). |
| `POST` | `/history/{history_id}/delete-source` | Delete leftover source file (`{confirmId}`, 404/400 guards, window.confirm in UI). |
| `GET` | `/scans/history?limit=20` | Scan snapshots (`app.db scans` + `reports/history/*.json`, merged, `MAX_HISTORY=200`). |
| `GET` | `/scans/history/{scan_id}` | Single scan report snapshot. |

**No-scan semantics:** `GET /api/scans/current/...` with no current scan →
HTTP 200 with `{hint: "No scan found. ..."}` (the React app checks `result.hint`
to clear state); an **unknown** `scan_id` → 404 (matches the MCP tool error
path).

**Browse must be cheap — never walk the whole tree.** Show folders (children
are subdirs, no season number) report the count of season subfolders instead of
a recursive video count; search is a depth-limited (max 3) `os.scandir` walk
with per-dir child caps and junk-name pruning (trickplay/extras/sample/…).
Browse/search read roots from the shared `ScanManager`'s config snapshot, not
the global settings (which read the real `.env` media roots).

## React app

- `src/main.jsx` mounts `<App/>`.
- `src/App.jsx` composes the top-level layout; when the API reports
  `auth.required` it renders the login screen instead. Page switching
  (`/`, `/settings`, `/apikeys`) is path-based SPA routing: the store reads
  `window.location.pathname` and navigates with `history.pushState` +
  `popstate`; the server serves the same `index.html` for `/scan`,
  `/settings`, `/apikeys` so deep links refresh.
- `src/store/AppStore.jsx` provides `AppStoreProvider` + `useAppStore()`
  (Context + useReducer).
- `src/api/apiClient.js` is the REST client (`apiGet`, `apiPost`, `apiPatch`,
  `apiDelete`, `setAuthToken`, `ApiError`).
- `src/components/` — `LoginScreen` (password gate), `SettingsPage` /
  `ApiKeysPage` (admin pages, nav in `TopBar`), `BrowseModal` (smart-correction
  folder browser), plus the scan/report/confirm components.
- `src/utils/` holds pure helpers (`report.js`, `format.js`, `transfer.js`).
- `src/styles/theme.css` is the stylesheet; `src/test/setup.js` is the test
  setup.

## Vite config

`vite.config.js`:

- `base: '/'` for builds (absolute asset URLs, so the bundle works at `/`,
  `/settings`, `/apikeys`), `'/'` in dev.
- `build.outDir: '../react-dist'`, `emptyOutDir: true`.
- Dev server port `5173` with `/api` proxied to
  `http://localhost:18328`.
- Vitest: jsdom environment, `globals: true`, setup file `./src/test/setup.js`,
  tests co-located as `src/**/*.{test,spec}.{js,jsx}`.

## Dev workflow

```bash
cd app/ui/react
npm install
npm run dev      # Vite dev server on :5173, /api proxied to :18328
npm test         # Vitest (jsdom)
npm run build    # outputs to ../react-dist
```

After a build or any `app/ui/` source change, restart the container:

```bash
docker restart jellysort
```

(The compose file bind-mounts the repo into `/app`, so the built bundle and
edited `server.py` are picked up on restart — no image rebuild needed.)
