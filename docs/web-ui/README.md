# Web UI

The React frontend. The built bundle lives in `app/ui/react-dist/` and is served
at `/` by `app/ui/server.py`; the React client talks to the backend through the
native `/api` REST routes exposed by the UI server (`app/ui/server.py`), which
share the backend `ScanManager`/`ReleaseTracker` — no MCP round-trip.

- [Overview](overview.md) — architecture, serving, dev workflow.
- [State store](store.md) — `AppStore.jsx` (Context + useReducer).
- [Utilities and report mapping](utils.md) — `report.js`, `format.js`, `apiClient.js`.
- [Components](components.md) — the top-level component tree.

## Quick facts

- Stack: React 18 + Vite 6 (JavaScript), Vitest + React Testing Library (jsdom).
- Production build outputs to `app/ui/react-dist/` (absolute asset base).
- The UI is mounted at `/` on the MCP app, so it shares port `18328` with MCP.
  Dev server on port `5173`, proxying `/api` → `http://localhost:18328`.
- The panel is password-protected when `UI_PANEL_PASSWORD` is set (see
  `app/ui/server.py` auth; the React app shows a login screen and stores the
  session token in `localStorage`).
- After UI source changes: `npm run build`, then `docker restart jellysort`.
- Tests: `npm test` from `app/ui/react`.
