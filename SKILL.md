---
name: jellyfin-mcp-helper
description: Manage the jellyfin-mcp-helper API service via HTTP when you need to create scan plans, review scan reports, validate destination mappings, and confirm file organization actions.
---

# jellyfin-mcp-helper API Skill

## installation variables (replace all before use)
- `{{CLONE_PATH}}` - absolute path where this repository is cloned
- `{{LAN_IP}}` - LAN IP where the service is reachable
- `{{PORT}}` - service port (default is usually `18328`)
- `{{QBT_WEBUI_URL}}` - qBittorrent Web UI base URL
- `{{JELLYFIN_BASE_URL}}` - Jellyfin server base URL

## configured values (after replacement)
- repo path: `{{CLONE_PATH}}`
- local base URL: `http://127.0.0.1:{{PORT}}`
- LAN base URL: `http://{{LAN_IP}}:{{PORT}}`
- qBittorrent Web UI: `{{QBT_WEBUI_URL}}`
- Jellyfin base URL: `{{JELLYFIN_BASE_URL}}`

## Running the service
- The service runs as a Docker container
- **Always check if the container is running first** using `docker ps --filter name=jellyfin-mcp-helper`
- If not running, start it with: `docker compose up -d` (from the project root)
- Port: `{{PORT}}` (from docker-compose.yml)

## base configuration
- local base URL: `http://127.0.0.1:{{PORT}}`
- LAN base URL: `http://{{LAN_IP}}:{{PORT}}`
- only one scan can be active at a time
- service loads config from `{{CLONE_PATH}}/config/`, logs to `{{CLONE_PATH}}/logs/`, and writes reports to `{{CLONE_PATH}}/reports/`
- qBittorrent integration requires valid Web UI auth (`QBT_WEBUI_USER` and `QBT_WEBUI_PASS`)
- Jellyfin integration requires `JELLYFIN_API_KEY`
- required env in `.env`: `OPENROUTER_API_KEY`, `QBT_MCP_URL`, `QBT_WEBUI_USER`, `QBT_WEBUI_PASS`, `JELLYFIN_BASE_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_MOVIE_LIBRARY_NAME`, `JELLYFIN_SERIES_LIBRARY_NAME`

## endpoints

### health
- `GET /health`
- quick check the API is up before any scan or polling
- example: `curl http://{{LAN_IP}}:{{PORT}}/health`

### create scan (`POST /scans`)
- body: `{"replaceExisting": true/false}` (default: true)
- creates a scan plan (does NOT move files)
- returns scan_id and report data with planned actions
- example: `curl -X POST http://{{LAN_IP}}:{{PORT}}/scans -H 'content-type: application/json' -d '{"replaceExisting":true}'`

### get scan report (`GET /scans/{scan_id}`)
- fetch the report for a specific scan by ID
- example: `curl http://{{LAN_IP}}:{{PORT}}/scans/648e797cf283494487dc2aaf28854af1`

### confirm scan (`POST /scans/{scan_id}/confirm`)
- apply the scan plan: move files, stop seeding torrents
- triggers Jellyfin library scan after files are moved
- example: `curl -X POST http://{{LAN_IP}}:{{PORT}}/scans/648e797cf283494487dc2aaf28854af1/confirm`

## workflow guidance
1. call `POST /scans` to create a scan plan (does NOT move files)
2. use the response from create scan as the initial scan report (it returns immediately)
3. logically validate the report before confirm: check for `error`, missing destinations, and suspicious destination path mapping
4. if needed, call `GET /scans/{scan_id}` to fetch the latest report again
5. if satisfied, call `POST /scans/{scan_id}/confirm` to apply the plan
6. warn before confirming and explain that files will be moved and seeding entries may be stopped

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
- health: `http://{{LAN_IP}}:{{PORT}}/health`
- create scan: `POST http://{{LAN_IP}}:{{PORT}}/scans`
- get scan report: `GET http://{{LAN_IP}}:{{PORT}}/scans/{scan_id}`
