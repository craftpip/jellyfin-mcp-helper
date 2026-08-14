# REST API

Legacy REST endpoints, kept for backward compatibility and scripting. The
primary interface is the MCP endpoint (see [mcp.md](mcp.md)). The scan workflow
is asynchronous: create → poll progress → fetch report → confirm.

## Endpoints

### `GET /health`

```json
{"status": "ok"}
```

### `POST /scans`

Create a new background scan (202). Body is a `ScanRequest` (see
[models.md](models.md)). Returns the `ScanPlan`.

```bash
curl -X POST http://localhost:18328/scans \
  -H 'Content-Type: application/json' -d '{"replaceExisting": true}'
```

### Scan progress / report

| Endpoint | Returns |
| --- | --- |
| `GET /scans/current/progress` | `_format_scan_progress` of the current scan (404 if none). |
| `GET /scans/{scan_id}/progress` | `_format_scan_progress` of a specific scan. |
| `GET /scans/current/report` | `_format_scan_report` of the current scan (404 if none). |
| `GET /scans/{scan_id}/report` | `_format_scan_report` of a specific scan. |
| `GET /scans/current` | Raw current `ScanPlan` (404 if none). |
| `GET /scans/{scan_id}` | Raw `ScanPlan` for a specific scan. |

### `POST /scans/{scan_id}/confirm`

Confirm (apply) a completed scan in the background. Returns the `ScanPlan`.

```bash
curl -X POST http://localhost:18328/scans/{scan_id}/confirm
```

### `DELETE /scans/current`

Delete the current scan.

```bash
curl -X DELETE http://localhost:18328/scans/current
```

## Legacy run endpoints

Kept for compatibility; new integrations should use `/scans`.

| Endpoint | Behavior |
| --- | --- |
| `GET /runs/current` | Returns the current scan (404 with "No runs have been started yet" if none). |
| `POST /runs` | Body `{dryRun: true}` (default) → `create_scan`; `{dryRun: false}` → `create_scan` then `confirm_scan` immediately. |

## Example flow

```bash
# Start a new scan
curl -X POST http://localhost:18328/scans -H 'Content-Type: application/json' -d '{"replaceExisting":true}'

# Check progress
curl http://localhost:18328/scans/current/progress

# Get the final report
curl http://localhost:18328/scans/current/report

# Inspect the raw scan state
curl http://localhost:18328/scans/current

# Confirm a completed scan
curl -X POST http://localhost:18328/scans/{scan_id}/confirm

# Delete the current scan
curl -X DELETE http://localhost:18328/scans/current
```
