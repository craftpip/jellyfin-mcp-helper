# JellySort

An API service and MCP server for organizing downloaded media into a Jellyfin library. It scans download folders, classifies items, plans target paths, lets you review or edit the plan, then confirms the move and optionally refreshes Jellyfin.

## Documentation Sync

The docs in this repo (`README.md`, `docs/`, `AGENTS.md`) describe the code
at a specific commit, kept in sync by the recursive plan
`plans/07-code-doc-sync.md` (never deleted, run repeatedly).

- **Last synced commit:** `93634ef` (2026-08-28)

To sync: review `git log --oneline 93634ef..HEAD`, update the docs for every
commit in that range, then set this line to the new HEAD.

## Features

- **Scan -> review -> confirm workflow**: build a move plan before writing anything.
- **Background progress + final report**: check scan progress first, then fetch an LLM-friendly report.
- **Plan editing before confirm**: redirect specific items with `downloads_scan_update`.
- **Multi-root curation**: movie and series roots can include descriptions to help root selection.
- **Jellyfin tools**: list libraries, browse items, inspect ongoing series, and trigger targeted scans.
- **Release Tracker**: store and query locally tracked next-release dates for ongoing series.
- **Incomplete-download detection**: skips downloads that are still in progress (detected via incomplete-file markers on disk).
- **Guessit + regex classification**: local, pattern-based (no external model required).

## Requirements

1. Python 3.11+ or Docker.
2. Optional Jellyfin server + API key for library refresh and Jellyfin MCP tools.

## Quick Start

### 1. Configure `.env`

Copy `.env.example` to `.env` and update it for your setup.

```bash
cp .env.example .env
```

Common settings:

```env
# Skip downloads still in progress (incomplete-file markers on disk)
ENABLE_INCOMPLETE_DOWNLOAD_DETECTION=true

# Optional Jellyfin integration
ENABLE_JELLYFIN_INTEGRATION=true
JELLYFIN_BASE_URL=http://localhost:8096
JELLYFIN_API_KEY=your-jellyfin-key
JELLYFIN_MOVIE_LIBRARY_NAME=Movies
JELLYFIN_SERIES_LIBRARY_NAME=Shows

# Download + library roots
DOWNLOAD_ROOTS=/media/downloads
MOVIE_ROOTS=/media/movies::Standard movies,/media/movies_4k::4K movies
SERIES_ROOTS=/media/series::Primary shows folder
```

Notes:

1. `MOVIE_ROOTS` and `SERIES_ROOTS` accept comma-separated paths.
2. Each library root can optionally include a description after `::`.
3. Those descriptions are included in the scan report so an LLM can choose the right destination root.
4. The paths in `.env` are container-side paths, not your host machine paths.
5. That means every path in `DOWNLOAD_ROOTS`, `MOVIE_ROOTS`, and `SERIES_ROOTS` must exist inside the container via Docker volume mounts.

### 2. Mount your media paths in Docker

Update `docker-compose.yml` so the container can see the same download and library paths referenced in `.env`.

Important:

1. `/media1`, `/media2`, `/media3`, `/media/movies`, and `/media/series` are just examples.
2. They are not a special built-in format. You can use any container paths you want.
3. The only rule is that your `.env` values must match the paths as seen from inside the container.
4. If Jellyfin stores movies under one mounted folder and series under another, mount both and list both in `.env`.

Current compose example:

```yaml
services:
  jellysort:
    ports:
      - "18328:18327"
    volumes:
      - /path/to/downloads1:/media1
      - /path/to/downloads2:/media2
      - /path/to/downloads3:/media3
      - .:/app
```

Example host-to-container mapping:

```yaml
volumes:
  - /srv/downloads:/data/downloads
  - /srv/jellyfin/movies:/data/movies
  - /srv/jellyfin/series:/data/series
```

Then your `.env` should use those container-side paths:

```env
DOWNLOAD_ROOTS=/data/downloads
MOVIE_ROOTS=/data/movies::Main movies library
SERIES_ROOTS=/data/series::Main series library
```

If you have multiple download or library locations, list every mounted container path as a comma-separated entry in `.env`.

The app listens on port `18327` inside the container and is exposed on `18328` by default.

### 3. Start the service

```bash
docker compose up -d --build
```

## Health Check

```bash
curl http://localhost:18328/health
```

Expected response:

```json
{"status":"ok"}
```

## REST API

The scan workflow is asynchronous.

1. Create a scan.
2. Poll progress until status is completed.
3. Fetch the final report.
4. Confirm the scan.

Examples:

```bash
# Start a new scan
curl -X POST http://localhost:18328/scans \
  -H 'Content-Type: application/json' \
  -d '{"replaceExisting":true}'

# Check current scan progress
curl http://localhost:18328/scans/current/progress

# Get the final current scan report
curl http://localhost:18328/scans/current/report

# Inspect the raw scan state
curl http://localhost:18328/scans/current

# Confirm a completed scan
curl -X POST http://localhost:18328/scans/{scan_id}/confirm

# Delete the current scan
curl -X DELETE http://localhost:18328/scans/current
```

Current REST endpoints:

- `GET /health`
- `POST /scans`
- `GET /scans/current/progress`
- `GET /scans/{scan_id}/progress`
- `GET /scans/current/report`
- `GET /scans/{scan_id}/report`
- `GET /scans/current`
- `GET /scans/{scan_id}`
- `POST /scans/{scan_id}/confirm`
- `DELETE /scans/current`

Legacy compatibility endpoints still exist under `/runs`, but new integrations should use `/scans`.

## Web UI

A React single-page app for the scan -> review -> confirm workflow, enabled via
`WEB_UI_ENABLED=true`. The UI is mounted at `/` on the MCP app, so it is served
on the **same port as MCP (`18328`)** — `http://host:18328/`, `/settings`,
and the MCP endpoint `http://host:18328/mcp` all share one port (`/apikeys` is a
backward-compat route that serves the same SPA).
The UI talks to the backend through native `/api` REST routes (no MCP round-trip):

- `GET /api/status` — service info + `auth.required`.
- `GET /api/libraries` — Jellyfin library list.
- `POST /api/libraries/scan` — trigger a library scan (`{libraryName, ...}` in the body).
- `POST /api/scans` — create a scan.
- `GET /api/scans/{scan_id}/progress` and `/report` (`current` variants exist) — poll + report.
- `PATCH /api/scans/current/items` — edit target paths.
- `POST /api/scans/current/confirm` — start the move.
- `GET /api/scans/{scan_id}/confirm-progress` — poll the move.
- `DELETE /api/scans/current/items` — delete source files.

Set `UI_PANEL_PASSWORD` to protect the panel. When set, `/api` routes (except
`/api/status`, `/api/login`, and static assets) require a Bearer token from
`POST /api/login`; the UI shows a login screen and stores the token in
`localStorage`. Leave it empty to keep the panel open.

Build/update the UI bundle from `app/ui/react` with `npm run build`, then
`docker restart jellysort`.

## MCP

List tools:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Organizer Tools

Core organizer flow:

1. `downloads_scan_start`
2. `downloads_scan_progress`
3. `downloads_scan_report`
4. Optional: `downloads_scan_update`
5. `downloads_scan_confirm`
6. Optional: `downloads_confirm_progress`

Example scan:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"downloads_scan_start","arguments":{"replaceExisting":true}}}'
```

Example report fetch:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"downloads_scan_report","arguments":{"scanId":"abc123"}}}'
```

Example target update:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"downloads_scan_update","arguments":{"scanId":"abc123","items":[{"confirmId":"m1","targetPath":"/media/movies_4k/Movie Title (2024)/Movie Title (2024).mkv"}]}}}'
```

Example confirm:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"downloads_scan_confirm","arguments":{"scanId":"abc123"}}}'
```

### Jellyfin Tools

- `jellyfin_library_scan`
- `jellyfin_libraries`
- `jellyfin_library_items`
- `jellyfin_ongoing_latest_episodes`

`jellyfin_library_scan` supports:

1. Whole-library scans.
2. Targeted scans by `itemNames` or `itemIds`.
3. `metadataRefreshMode` and `imageRefreshMode` values:
   - `Default`
   - `FullRefresh`
   - `ValidationOnly`
4. Optional `replaceAllMetadata` and `replaceAllImages` when using full refresh modes.

### Release Tracker Tools

- `release_tracker_update`
- `release_tracker_lookup` with seriesName
- `release_tracker_lookup` with dueOnly=true
- `release_tracker_lookup` without seriesName
- `release_tracker_update` with action=delete

Use Release Tracker for locally stored next-release markers for ongoing shows. If a user asks what date is already tracked for a series, the intended workflow is to query Release Tracker first before using live Jellyfin or the web.

## Scan Report Flow

The intended organizer workflow is:

1. Start `downloads_scan_start`.
2. Poll `downloads_scan_progress` until the scan completes.
3. Read `downloads_scan_report`.
4. If any target path or root is wrong, fix it with `downloads_scan_update`.
5. Fetch the report again and verify the updated targets.
6. Run `downloads_scan_confirm`.
7. If needed, poll `downloads_confirm_progress` until complete.

The final report includes:

1. Summary counts.
2. Available movie and series roots with descriptions.
3. Markdown tables for movie and series move targets.
4. Skipped-item summaries.
5. LLM instructions for path validation and root curation.

## Environment Variables

Important variables from `.env.example`:

| Variable | Required | Description |
|----------|----------|-------------|
| `MODEL_CLASSIFY_CONFIDENCE_THRESHOLD` | No | Min confidence for a classification result (0.65) |
| `MODEL_PATH_CONFIDENCE_THRESHOLD` | No | Min confidence for a path-resolution match (0.6) |
| `ENABLE_INCOMPLETE_DOWNLOAD_DETECTION` | No | Skip downloads still in progress (incomplete-file markers on disk, default true) |
| `ENABLE_JELLYFIN_INTEGRATION` | No | Enable Jellyfin refresh integration |
| `JELLYFIN_BASE_URL` | If Jellyfin enabled | Jellyfin server URL |
| `JELLYFIN_API_KEY` | If Jellyfin enabled | Jellyfin API key |
| `JELLYFIN_MOVIE_LIBRARY_NAME` | No | Jellyfin movie library name |
| `JELLYFIN_SERIES_LIBRARY_NAME` | No | Jellyfin series library name |
| `DOWNLOAD_ROOTS` | Yes | Comma-separated download roots |
| `MOVIE_ROOTS` | Yes | Comma-separated movie roots, optional `::description` |
| `SERIES_ROOTS` | Yes | Comma-separated series roots, optional `::description` |
| `SERIES_TITLE_ALIASES` | No | `alias::canonical` entries mapping release titles to library folder names |
| `WEB_UI_ENABLED` | No | Enable the web UI (served on the same port as MCP, 18328) |
| `WEB_UI_PORT` | No | Deprecated — unused. The web UI shares the MCP port |
| `UI_PANEL_PASSWORD` | No | Panel password; when set, the web UI requires login |
| `JELLYSORT_MCP_TOKEN` | No | MCP token — when set, every `/mcp` request must present it; when empty, MCP is open. Deprecated aliases: `MCP_DEFAULT_TOKEN`, `ADMIN_UI_TOKEN` |

Full variable reference and the live-vs-restart apply model:
[docs/getting-started/configuration.md](docs/getting-started/configuration.md).

## Development

Run tests:

```bash
python3 -m pytest tests/
```

Rebuild after source changes:

```bash
docker compose build && docker compose restart
```
