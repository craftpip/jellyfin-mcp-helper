# Application Entrypoint — `app/main.py`

The service is a single FastAPI application (`app = FastAPI(title="JellySort",
version=VERSION, lifespan=lifespan)`).

## Lifespan

The `lifespan` async context manager wires up singletons at startup:

- `ScanManager` — the scan/confirm engine (from `app/services/scan_manager.py`),
  stored on `app.state.scan_manager`.
- `ReleaseTracker` — the local next-release store, stored on
  `app.state.release_tracker`.
- Optional web UI thread — started when `WEB_UI_ENABLED=true`, serving
  `app/ui/server.py`'s app on `WEB_UI_PORT`.
- Jellyfin library list — fetched once and cached to augment the
  `get available jellyfin libraries list` tool description.

The Jellyfin and qBittorrent clients are **not** app-level singletons — they are
built on demand from env settings (`JellyfinClient.from_env()`,
`QbittorrentClient.from_env()`) inside the tool handlers.

On shutdown only a log line is emitted; **no scan state is persisted**. Scan
plans live in memory on the `ScanManager` (`config/current_scan.json` is not
written by the service — the only runtime file in `config/` is
`ongoing_releases.json`, written by the Release Tracker).

## HTTP middleware

`log_requests` wraps every request:

- Assigns a short request id (`X-Request-ID` header).
- Skips logging for `/health`.
- For `/mcp` requests it captures the JSON-RPC request/response bodies and logs a
  compact MCP activity line (via `_format_mcp_activity_line`) including the tool
  name and success/error status.
- Other requests get a `✅ METHOD path completed — Nms, HTTP S, from IP` line.
- Exceptions are logged with a `❌` marker and re-raised.

## MCP endpoint

`POST /mcp` (see [mcp.md](mcp.md)) is the primary interface. It is implemented
as a streaming HTTP JSON-RPC endpoint supporting `tools/list` and `tools/call`
with a handshake (`initialize`, `notifications/initialized`) compatible with MCP
clients.

## REST endpoints

See [api.md](api.md) for the full list (`/health`, `/scans/*`, `/runs/*`).

## Service wiring

| Singleton | Module | Notes |
| --- | --- | --- |
| `scan_manager` | `app/services/scan_manager.py` | Create/update/confirm/delete scans |
| `release_tracker` | `app/services/release_tracker.py` | Local next-release store |

Jellyfin and qBittorrent clients are constructed per use (see above), not wired
as app singletons.
