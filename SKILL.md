---
name: jellyfin-download-organizer
description: Manage the Jellyfin Download Organizer API service via HTTP when you need to plan or execute download reorganizations, monitor the active scan, or trigger status/summary checks (health, current scan, MCP tools).
---

# Jellyfin Download Organizer API Skill

## Running the service
- The service runs as a Docker container
- **Always check if the container is running first** using `docker ps --filter name=jellyfin-download-organizer`
- If not running, start it with: `docker compose up -d` (from the project root)
- Port: `18328` (from docker-compose.yml)

## base configuration
- local base URL: `http://127.0.0.1:18328`
- LAN base URL: `http://10.69.1.164:18328`
- only one scan can be active at a time
- service loads config from `config/`, logs to `logs/`, and writes reports to `reports/`
- required env in `.env`: `OPENROUTER_API_KEY`, `QBT_MCP_URL`, `QBT_WEBUI_USER`, `QBT_WEBUI_PASS`, `JELLYFIN_BASE_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_MOVIE_LIBRARY_NAME`, `JELLYFIN_SERIES_LIBRARY_NAME`

## endpoints

### health
- `GET /health`
- quick check the API is up before any scan or polling
- example: `curl http://10.69.1.164:18327/health`

### create scan (`POST /scans`)
- body: `{"replaceExisting": true/false}` (default: true)
- creates a scan plan (does NOT move files)
- returns scan_id and list of items with planned actions
- example: `curl -X POST http://10.69.1.164:18327/scans -H 'content-type: application/json' -d '{"replaceExisting":true}'`

### current scan (`GET /scans/current`)
- poll progress or get latest scan details
- response fields: `scan_id`, `status`, `operation`, `items[]`, `counts.{total,movies,series,skipped,moved,replaced,failed}`, `created_at`, `confirmed_at`, `error`
- example: `curl http://10.69.1.164:18327/scans/current`

### specific scan (`GET /scans/{scan_id}`)
- fetch a specific scan by ID
- example: `curl http://10.69.1.164:18327/scans/648e797cf283494487dc2aaf28854af1`

### confirm scan (`POST /scans/{scan_id}/confirm`)
- apply the scan plan: move files, stop seeding torrents
- triggers Jellyfin library scan after files are moved
- example: `curl -X POST http://10.69.1.164:18327/scans/648e797cf283494487dc2aaf28854af1/confirm`

### delete current scan (`DELETE /scans/current`)
- cancel and delete the current scan
- example: `curl -X DELETE http://10.69.1.164:18327/scans/current`

### MCP wrapper (`POST /mcp`)
- implements JSON-RPC 2.0 protocol for MCP clients

#### supported methods
- `initialize` – handshake, returns protocol version and capabilities
- `ping` – health check
- `notifications/initialized` – acknowledgment (returns 204)
- `tools/list` – returns available tools
- `tools/call` – execute a tool by name

#### available tools
- `scan media library` – scans torrent folders and creates an organization plan
  - arguments: `{"replaceExisting": boolean}` (default: true)
- `confirm scan` – apply a previously created scan plan
  - arguments: `{"scanId": string}` (required)
- `get scan report` – review the current scan plan
  - arguments: `{"scanId": string}` (optional, returns current scan if omitted)

#### MCP tool call examples
```bash
# List available tools
curl -X POST http://10.69.1.164:18328/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Scan media library
curl -X POST http://10.69.1.164:18328/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"scan media library","arguments":{"replaceExisting":true}}}'

# Get scan report
curl -X POST http://10.69.1.164:18328/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get scan report"}}'

# Confirm scan
curl -X POST http://10.69.1.164:18328/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"confirm scan","arguments":{"scanId":"abc123"}}}'
```

## workflow guidance
1. call `scan media library` or `POST /scans` to create a scan plan (does NOT move files)
2. review the scan report - each item shows: name, destination, reason
3. if satisfied, call `confirm scan` or `POST /scans/{scan_id}/confirm` to apply the plan
4. if not satisfied, call `scan media library` again to re-scan
5. warn before confirming; explain what will happen

## scan report format
The scan returns a structured report with:
- **summary**: scan_id, status, counts (total/movies/series/skipped/moved/replaced/failed/skipped_in_progress)
- **files_to_move**: list of files to move, each with:
  - `name`: original file name
  - `destination`: target path where file will be moved
  - `reason`: why it was matched (e.g., "Matched movie pattern")
- **skipped**: files that were skipped with reason (e.g., "In-progress download")
- **skipped_in_progress**: count of incomplete torrents found in qBittorrent (progress < 99.9%) - their files are automatically skipped during scan if they match media being organized
- **next**: instructions for next steps

## quick links
- health: `http://10.69.1.164:18328/health`
- current scan: `http://10.69.1.164:18328/scans/current`
- create scan: `POST http://10.69.1.164:18328/scans`