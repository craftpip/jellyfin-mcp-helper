# MCP Protocol

The service speaks MCP over JSON-RPC 2.0 on `POST /mcp`. The app listens on port
`18327` inside the container, host-mapped to `18328`. The web UI is mounted at
`/` on the same app, so MCP (`/mcp`) and the UI (`/`, `/settings`, `/api/*`) all
share the single port `18328`. Compatible with MCP clients such as Claude and
opencode.

## Authentication

MCP requests are gated by `require_mcp_auth` (`app/core/auth.py`):

- `JELLYSORT_MCP_TOKEN` empty (default) → every request passes and is
  logged as user `anonymous`.
- `JELLYSORT_MCP_TOKEN` set → the request must present the same token
  via `Authorization: Bearer <token>` **or** `X-API-Key: <token>`:
  - Valid token → request attributed to user `admin` (logged as
    `as <user>`).
  - Deprecated aliases `MCP_DEFAULT_TOKEN` and `ADMIN_UI_TOKEN` are
    accepted as fallbacks.
  - Missing/invalid token → HTTP `401` with a JSON-RPC error body
    `{"code": -32001, "message": "unauthorized"}` keeping the request `id`.

See [auth.md](auth.md) for the full auth details.

## Request/response shape

All requests and responses are `application/json`.

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "...", "arguments": {...}}}
```

Successful tool calls return the standard MCP `result` envelope with `content`
(a `text` item containing JSON) and `isError`:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [{"type": "text", "text": "{...json..."}],
    "isError": false
  }
}
```

A tool that fails (bad arguments, scan not found, Jellyfin not configured, …)
returns a normal result with `isError: true`, so the model sees the message:

```json
{"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "{\"error\": \"libraryName is required\"}"}], "isError": true}}
```

Protocol-level failures (unknown method or tool) use the JSON-RPC `error` envelope:

```json
{"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Tool not found"}}
```

The conversion happens in one place: `mcp()` wraps `_mcp_dispatch()` and turns
any `tools/call` JSON-RPC error except `-32601` into an `isError` result. The
activity log treats `isError` results as failures (`❌ … reason`).

## Supported methods

| Method | Behavior |
| --- | --- |
| `initialize` | Handshake. Negotiates `protocolVersion`: echoes the client's version when supported (`2025-06-18`, `2025-03-26`, `2024-11-05`), else `2024-11-05`. Returns `capabilities.tools`, `serverInfo: {name: JellySort, version}`. |
| `notifications/initialized` | Acknowledged with HTTP 204. |
| `ping` | Health. Returns `result: {}`. |
| `tools/list` | Returns `tools` (17 tool definitions, snake_case names with `title` + `annotations`) plus `llm_instructions` (`RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS`). |
| `tools/call` | Dispatches the named tool with `arguments`. |

## Error codes

| Code | Meaning |
| --- | --- |
| `-32601` | Method not found / Tool not found (JSON-RPC error). |
| `-32000`, `-32602` | Used internally by tool handlers; returned to clients as `isError: true` results, not JSON-RPC errors. |

## Logging

Every `/mcp` request is logged by the middleware as a compact activity line:

- Success: `✅ tools/call downloads_scan_start — 12ms, HTTP 200, from IP`
- Error: `❌ ... — reason, 12ms, HTTP 200, from IP`
- Unknown tool: `⚠️ TOOL xxx <name> (not found)` warnings are emitted by the
  dispatch handler (`app/main.py:1909`).

## Tool call conventions

- Tools that start background work (`downloads_scan_start`,
  `downloads_scan_confirm`) **return immediately** and include
  `what_happens_now`, `available_now`, `llm_instructions`, and `next` guidance
  in the JSON payload.
- Progress tools explicitly instruct clients to **wait at least 10 seconds**
  between polls.
- Read-only tools never move files; `downloads_scan_confirm` and
  `downloads_scan_delete_items` are the only write tools.

See [mcp-tools.md](mcp-tools.md) for the complete tool reference.
