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

When `UI_PANEL_PASSWORD` is non-empty, the `/api` routes (except `/api/status`,
`/api/login`, and the static assets) require a Bearer token:

- `GET /api/status` reports `auth.required`.
- `POST /api/login` with `{"password": "..."}` returns a signed
  `{"token": ..., "directLogin": true}` on success (401 on wrong password).
- `POST /api/logout` drops the token.
- The token is verified via `itsdangerous`; an expired/invalid token returns 401
  and the React app falls back to the login screen.
- With an empty password the panel stays open (`auth.required: false`).

## REST routes

All are mounted under `/api` on port 18328. Requests use JSON bodies and respond
with JSON (204 for body-less success).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/status` | Service info + `auth.required`. |
| `GET` | `/libraries` | Jellyfin library list (from the shared ReleaseTracker). |
| `POST` | `/libraries/{name}/scan` | Trigger a Jellyfin library scan. |
| `POST` | `/scans` | Create a new scan (`{"replaceExisting": true}`). |
| `GET` | `/scans/{scan_id}/progress`, `/scans/current/progress` | Scan progress. |
| `GET` | `/scans/{scan_id}/report`, `/scans/current/report` | Final scan report. |
| `PATCH` | `/scans/current/items` | Update item target paths. |
| `POST` | `/scans/current/confirm` | Start the confirm/move for itemIds. |
| `GET` | `/scans/{scan_id}/confirm-progress`, `/scans/current/confirm-progress` | Confirm progress. |
| `DELETE` | `/scans/current/items` | Delete source files + remove items from the plan. |

## React app

- `src/main.jsx` mounts `<App/>`.
- `src/App.jsx` composes the top-level layout; when the API reports
  `auth.required` it renders the login screen instead.
- `src/store/AppStore.jsx` provides `AppStoreProvider` + `useAppStore()`
  (Context + useReducer).
- `src/api/apiClient.js` is the REST client (`apiGet`, `apiPost`, `apiPatch`,
  `apiDelete`, `setAuthToken`, `ApiError`).
- `src/components/LoginScreen.jsx` is the password gate.
- `src/utils/` holds pure helpers (`report.js`, `format.js`).
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
