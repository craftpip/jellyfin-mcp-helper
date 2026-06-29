# jellyfin-mcp-helper

An API service and MCP server for organizing downloaded media into a Jellyfin library. It scans download folders, classifies items, plans target paths, lets you review or edit the plan, then confirms the move and optionally refreshes Jellyfin.

## Features

- **Scan -> review -> confirm workflow**: build a move plan before writing anything.
- **Background progress + final report**: check scan progress first, then fetch an LLM-friendly report.
- **Plan editing before confirm**: redirect specific items with `update move new downloads scan`.
- **Multi-root curation**: movie and series roots can include descriptions to help root selection.
- **Jellyfin tools**: list libraries, browse items, inspect ongoing series, and trigger targeted scans.
- **Release Tracker**: store and query locally tracked next-release dates for ongoing series.
- **qBittorrent integration**: can stop active downloads before moving files.
- **Model-backed classification**: supports `ollama` or `openrouter`.

## Requirements

1. Python 3.11+ or Docker.
2. A model provider for classification:
   - `ollama` (default), or
   - `openrouter` with `OPENROUTER_API_KEY`.
3. Optional qBittorrent MCP server for download-state checks and pre-move handling.
4. Optional Jellyfin server + API key for library refresh and Jellyfin MCP tools.

## Quick Start

### 1. Configure `.env`

Copy `.env.example` to `.env` and update it for your setup.

```bash
cp .env.example .env
```

Common settings:

```env
# Model provider
MODEL_PROVIDER=ollama
MODEL_BASE_URL=http://localhost:11434
MODEL_NAME=llama3.2:1b

# Or use OpenRouter instead
# MODEL_PROVIDER=openrouter
# OPENROUTER_API_KEY=your-key

# Optional qBittorrent integration
ENABLE_DOWNLOAD_CLIENT_CHECK=true
DOWNLOAD_CLIENT=qbittorrent
QBT_MCP_URL=http://localhost:8093/mcp
QBT_MCP_API_KEY=your-mcp-key

# Optional Jellyfin integration
ENABLE_JELLYFIN_INTEGRATION=true
JELLYFIN_BASE_URL=http://localhost:8096
JELLYFIN_API_KEY=your-jellyfin-key
JELLYFIN_MOVIE_LIBRARY_NAME=Movies
JELLYFIN_SERIES_LIBRARY_NAME=Shows

# Download + library roots
DOWNLOAD_ROOTS=/media/torrents
MOVIE_ROOTS=/media/movies::Standard movies,/media/movies_4k::4K movies
SERIES_ROOTS=/media/series::Primary shows folder
```

Notes:

1. `MOVIE_ROOTS` and `SERIES_ROOTS` accept comma-separated paths.
2. Each library root can optionally include a description after `::`.
3. Those descriptions are included in the scan report so an LLM can choose the right destination root.

### 2. Mount your media paths in Docker

Update `docker-compose.yml` so the container can see the same download and library paths referenced in `.env`.

Current compose example:

```yaml
services:
  organizer:
    ports:
      - "18328:18327"
    volumes:
      - /mnt/media1t/downloads:/media1
      - /mnt/media2t/downloads:/media2
      - /mnt/media3t/downloads:/media3
      - ./app:/app/app
      - ./config:/app/config
      - ./logs:/app/logs
      - ./reports:/app/reports
```

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

## MCP

List tools:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Organizer Tools

Core organizer flow:

1. `move new downloads scan`
2. `get move new downloads scan progress`
3. `get move new downloads scan report`
4. Optional: `update move new downloads scan`
5. `confirm move new downloads scan`
6. Optional: `get move new downloads confirm progress`

Example scan:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"move new downloads scan","arguments":{"replaceExisting":true}}}'
```

Example report fetch:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get move new downloads scan report","arguments":{"scanId":"abc123"}}}'
```

Example target update:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"update move new downloads scan","arguments":{"scanId":"abc123","items":[{"confirmId":"m1","targetPath":"/media/movies_4k/Movie Title (2024)/Movie Title (2024).mkv"}]}}}'
```

Example confirm:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"confirm move new downloads scan","arguments":{"scanId":"abc123"}}}'
```

### Jellyfin Tools

- `trigger jellyfin library scan`
- `get available jellyfin libraries list`
- `get jellyfin library items`
- `get ongoing jellyfin series latest episodes`

`trigger jellyfin library scan` supports:

1. Whole-library scans.
2. Targeted scans by `itemNames` or `itemIds`.
3. `metadataRefreshMode` and `imageRefreshMode` values:
   - `Default`
   - `FullRefresh`
   - `ValidationOnly`
4. Optional `replaceAllMetadata` and `replaceAllImages` when using full refresh modes.

### Release Tracker Tools

- `store ongoing series next release`
- `get ongoing series next release`
- `get due ongoing series releases`
- `get ongoing series next releases`
- `delete ongoing series next release`

Use Release Tracker for locally stored next-release markers for ongoing shows. If a user asks what date is already tracked for a series, the intended workflow is to query Release Tracker first before using live Jellyfin or the web.

## Scan Report Flow

The intended organizer workflow is:

1. Start `move new downloads scan`.
2. Poll `get move new downloads scan progress` until the scan completes.
3. Read `get move new downloads scan report`.
4. If any target path or root is wrong, fix it with `update move new downloads scan`.
5. Fetch the report again and verify the updated targets.
6. Run `confirm move new downloads scan`.
7. If needed, poll `get move new downloads confirm progress` until complete.

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
| `MODEL_PROVIDER` | No | `ollama` or `openrouter` |
| `OPENROUTER_API_KEY` | If using OpenRouter | OpenRouter API key |
| `MODEL_BASE_URL` | Usually yes | Model endpoint URL |
| `MODEL_NAME` | No | Model name, default `llama3.2:1b` |
| `ENABLE_DOWNLOAD_CLIENT_CHECK` | No | Enable qBittorrent download-state checks |
| `DOWNLOAD_CLIENT` | No | Download client type, currently `qbittorrent` |
| `QBT_MCP_URL` | If qBittorrent enabled | qBittorrent MCP endpoint |
| `QBT_MCP_API_KEY` | If qBittorrent enabled | qBittorrent MCP API key |
| `ENABLE_JELLYFIN_INTEGRATION` | No | Enable Jellyfin refresh integration |
| `JELLYFIN_BASE_URL` | If Jellyfin enabled | Jellyfin server URL |
| `JELLYFIN_API_KEY` | If Jellyfin enabled | Jellyfin API key |
| `JELLYFIN_MOVIE_LIBRARY_NAME` | No | Jellyfin movie library name |
| `JELLYFIN_SERIES_LIBRARY_NAME` | No | Jellyfin series library name |
| `DOWNLOAD_ROOTS` | Yes | Comma-separated download roots |
| `MOVIE_ROOTS` | Yes | Comma-separated movie roots, optional `::description` |
| `SERIES_ROOTS` | Yes | Comma-separated series roots, optional `::description` |

## Development

Run tests:

```bash
python3 -m pytest tests/
```

Rebuild after source changes:

```bash
docker compose build && docker compose restart
```
