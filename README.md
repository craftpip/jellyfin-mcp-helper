# Jellyfin Download Organizer

An API service that automatically organizes downloaded media into your Jellyfin library. Scans download folders, classifies media (movie/series), resolves target paths, moves files, and triggers Jellyfin library scans.

## Features

- **Scan & Confirm** - Scan first to see what will happen, then confirm to apply
- **AI Classification** - Uses Ollama to classify media as movie, series, or skip
- **Smart Path Resolution** - Matches against existing library folders
- **Download Client Integration** - Stops active downloads before moving files (e.g., qBittorrent)
- **Jellyfin Integration** - Triggers library scans after moving files
- **MCP Support** - Can be called via MCP from any LLM

## Requirements

1. **Ollama** - For AI classification (e.g., `llama3.2:1b`)
2. **Download Client** - e.g., qBittorrent with MCP server for stopping active downloads
3. **Jellyfin** - Optional, for triggering library scans

## Quick Start

### 1. Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
# Required - get from https://openrouter.ai/
OPENROUTER_API_KEY=your-key

# Download client config (e.g., qBittorrent via gluetun)
DOWNLOAD_CLIENT=qbittorrent
QBT_MCP_URL=http://host.docker.internal:8093/mcp
QBT_MCP_API_KEY=your-mcp-key

# Optional - Jellyfin for library scans
JELLYFIN_BASE_URL=http://host.docker.internal:8096
JELLYFIN_API_KEY=your-jellyfin-key

# Paths - comma-separated, must match docker volumes
DOWNLOAD_ROOTS=/downloads
MOVIE_ROOTS=/downloads/movies
SERIES_ROOTS=/downloads/series
```

### 2. Update docker-compose.yml

Uncomment and update the volume mounts to match your paths:

```yaml
volumes:
  - /path/to/your/downloads:/downloads
  - /path/to/your/movies:/downloads/movies
  - /path/to/your/series:/downloads/series
```

### 3. Run

```bash
docker compose up -d
```

## Usage

### REST API

```bash
# Create a scan (preview what would happen)
curl -X POST http://localhost:18327/scans

# Get current scan
curl http://localhost:18327/scans/current

# Confirm and apply the scan
curl -X POST http://localhost:18327/scans/{scan_id}/confirm

# Discard current scan
curl -X DELETE http://localhost:18327/scans/current
```

### MCP

```bash
# List available tools
curl -X POST http://localhost:18327/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Scan library (returns scan_id + plan)
curl -X POST http://localhost:18327/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"scan library","arguments":{}}}'

# Confirm scan (apply the plan)
curl -X POST http://localhost:18327/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"confirm scan","arguments":{"scanId":"abc123"}}}'
```

## Flow

```
1. LLM calls "scan library"
   → Returns scan_id + list of files with targets
   → Does NOT move any files

2. User reviews the plan
   → Can check target paths, confidence scores

3. LLM calls "confirm scan scan_id"
   → Actually moves files
   → Stops active downloads in qBittorrent
   → Triggers Jellyfin library scans
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | API key for Ollama/OpenRouter |
| `DOWNLOAD_CLIENT` | No | Download client type (default: `qbittorrent`) |
| `QBT_MCP_URL` | Yes | qBittorrent MCP endpoint |
| `QBT_MCP_API_KEY` | Yes | MCP API key |
| `JELLYFIN_BASE_URL` | No | Jellyfin URL |
| `JELLYFIN_API_KEY` | No | Jellyfin API key |
| `MODEL_BASE_URL` | No | Ollama URL (default: http://localhost:11434) |
| `MODEL_NAME` | No | Model name (default: llama3.2:1b) |

## Health Check

```bash
curl http://localhost:18327/health
# Returns: {"status":"ok"}
```

## Example Response

**Scan library response:**
```json
{
  "scan_id": "abc123",
  "status": "pending",
  "items": [
    {
      "source_path": "/downloads/Movie (2024)/",
      "name": "Movie (2024)",
      "item_type": "movie",
      "confidence": 0.92,
      "target_path": "/downloads/movies/Movie (2024)/",
      "action": "move"
    }
  ],
  "counts": {"total": 5, "movies": 3, "series": 2, "skipped": 0}
}
```
