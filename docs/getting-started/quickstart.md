# Quickstart

## 1. Configure `.env`

Copy `.env.example` to `.env` and update it for your setup:

```bash
cp .env.example .env
```

Common settings:

```env
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
4. The paths in `.env` are **container-side** paths, not host paths.
5. Every path in `DOWNLOAD_ROOTS`, `MOVIE_ROOTS`, and `SERIES_ROOTS` must exist inside the container via Docker volume mounts.

## 2. Mount your media paths in Docker

Update `docker-compose.yml` so the container sees the same download and library paths referenced in `.env`.

Important:

1. `/media1`, `/media2`, `/media3`, `/media/movies`, and `/media/series` are just examples — not a special built-in format. Any container paths work.
2. The only rule is that your `.env` values must match the paths as seen from **inside** the container.
3. If Jellyfin stores movies under one mounted folder and series under another, mount both and list both in `.env`.

Current compose example (see [deployment/docker.md](../deployment/docker.md)):

```yaml
services:
  jellysort:
    ports:
      - "18328:18327"   # single port: MCP (/mcp) + Web UI (/, /settings, /api/*)
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

## 3. Start the service

```bash
docker compose up -d --build
```

## 4. Health check

```bash
curl http://localhost:18328/health
```

Expected response:

```json
{"status":"ok"}
```

## 5. Run a scan (REST)

The scan workflow is asynchronous:

1. Create a scan.
2. Poll progress until status is `completed`.
3. Fetch the final report.
4. Confirm the scan.

```bash
# Start a new scan
curl -X POST http://localhost:18328/scans \
  -H 'Content-Type: application/json' \
  -d '{"replaceExisting":true}'

# Check current scan progress
curl http://localhost:18328/scans/current/progress

# Get the final current scan report
curl http://localhost:18328/scans/current/report

# Confirm a completed scan
curl -X POST http://localhost:18328/scans/{scan_id}/confirm
```

## 6. MCP

List tools:

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Call a tool (example scan):

```bash
curl -X POST http://localhost:18328/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"move new downloads scan","arguments":{"replaceExisting":true}}}'
```

See [backend/mcp.md](../backend/mcp.md) and [backend/mcp-tools.md](../backend/mcp-tools.md) for the full protocol and tool reference.
