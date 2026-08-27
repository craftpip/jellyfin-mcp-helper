# System Overview

JellySort is a self-hosted service that scans download folders, classifies the
media, plans a target layout, and moves files into a Jellyfin library. It
exposes both a JSON-RPC (MCP) API and a REST API, plus an optional web UI.

## Components

### Backend application — `app/main.py`

- FastAPI app that runs the MCP JSON-RPC endpoint (primary interface) and legacy
  REST endpoints.
- Holds the MCP tool registry (`_mcp_tools()`) and dispatch/handlers.
- Owns the long-lived `ScanManager` and `ReleaseTracker` instances.
- Mounts the web UI app at `/` in the lifespan when `WEB_UI_ENABLED=true`, so UI
  and MCP share the single port `18328`.

### Services layer — `app/services/`

The processing engine, split by responsibility:

- `scanner.py` — walks download roots, emits candidate files, and flags
  in-progress downloads via incomplete-file markers.
- `classifier.py` — guessit + regex based media classification.
- `resolver.py` — maps candidates to target paths in the library roots.
- `scan_manager.py` — scan → report → confirm workflow and file moves.
- `presenters.py` — shared report/progress formatting (MCP + UI).
- `jellyfin.py` — Jellyfin API client (libraries, scans, ongoing series).
- `release_tracker.py` — locally stored next-release dates.
- `api_key_manager.py` / `env_manager.py` — MCP key store + env management
  (see [backend/auth](../backend/auth.md)).

### Web UI — `app/ui/`

- `server.py` — small FastAPI server hosting the built React bundle plus native
  `/api` REST routes (scan lifecycle, libraries, panel auth). Shares the backend
  `ScanManager`/`ReleaseTracker`; fully independent of the MCP server (the old
  `/mcp` proxy is gone).
- `react/` — Vite React source; builds to `react-dist/`.
- `react-dist/` — built bundle served at `/`.

## Ports and runtime

| Port | Purpose |
| --- | --- |
| `18327` | Backend (uvicorn `app.main:app`) — internal. |
| `18328` | Single host-mapped port (compose maps `18328:18327`). Serves MCP (`/mcp`), the Web UI at `/`, `/settings`, and the UI's `/api/*` routes. |
| `5173` | React dev server (Vite), proxies `/api` → `http://localhost:18328`. |

## Client interfaces

1. **MCP / JSON-RPC** — the primary interface for agents (claude, opencode, etc.).
   POST `{jsonrpc,id,method:tools/list | tools/call}` to `/mcp` on port 18328.
2. **REST** — scan endpoints under `/scans` (backend) and `/runs` (legacy),
   plus the Web UI's native `/api` routes — all on port 18328.
3. **Web UI** — React SPA talking to the `/api` routes on the same server
   (optionally behind `UI_PANEL_PASSWORD` auth).

## Runtime state on disk

- `config/ongoing_releases.json` — Release Tracker store (the only runtime file
  the service writes in `config/`; scan plans are kept in memory only).
- `reports/` — run summaries (`run-{id}.json`) and scan reports.
- `logs/` — service logs and run JSONL traces (`run-{id}.jsonl`).
