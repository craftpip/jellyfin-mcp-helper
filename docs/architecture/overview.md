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
- Optionally starts the web UI server thread in the lifespan when
  `WEB_UI_ENABLED=true`.

### Services layer — `app/services/`

The processing engine, split by responsibility:

- `scanner.py` — walks download roots, emits candidate files.
- `classifier.py` — guessit + regex based media classification.
- `resolver.py` — maps candidates to target paths in the library roots.
- `scan_manager.py` — scan → report → confirm workflow and file moves.
- `organizer.py` — legacy immediate organize/normalize run flow.
- `run_manager.py` — legacy run lifecycle.
- `normalizer.py` — library-side rename/normalization (safe/full modes).
- `jellyfin.py` — Jellyfin API client (libraries, scans, ongoing series).
- `download_client.py` — qBittorrent MCP client (in-progress, seed stop).
- `release_tracker.py` — locally stored next-release dates.
- `ollama.py` / `openrouter.py` — LLM clients used as external classifier.

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
| `18328` | Host-mapped port for the backend (compose maps `18328:18327`). |
| `18329` | Web UI server (React + `/api`). |
| `5173` | React dev server (Vite), proxies `/api` and `/mcp` → `http://localhost:18329`. |

## Client interfaces

1. **MCP / JSON-RPC** — the primary interface for agents (claude, opencode, etc.).
   POST `{jsonrpc,id,method:tools/list | tools/call}` to `/mcp`.
2. **REST** — scan endpoints under `/scans` (backend, port 18328) and `/runs`
   (legacy), plus the Web UI's native `/api` routes on port 18329.
3. **Web UI** — React SPA talking to the `/api` routes on the UI server
   (optionally behind `UI_PANEL_PASSWORD` auth).

## Runtime state on disk

- `config/ongoing_releases.json` — Release Tracker store (the only runtime file
  the service writes in `config/`; scan plans are kept in memory only).
- `reports/` — run summaries (`run-{id}.json`) and scan reports.
- `logs/` — service logs and run JSONL traces (`run-{id}.jsonl`).
