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

Errors use the JSON-RPC `error` envelope:

```json
{"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Tool not found"}}
```

## Supported methods

| Method | Behavior |
| --- | --- |
| `initialize` | Handshake. Returns `protocolVersion 2024-11-05`, `capabilities.tools`, `serverInfo: {name: JellySort, version}`. |
| `notifications/initialized` | Acknowledged with HTTP 204. |
| `ping` | Health. Returns `result: {}`. |
| `tools/list` | Returns `tools` (18 tool definitions) plus `llm_instructions` (`RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS`). |
| `tools/call` | Dispatches the named tool with `arguments`. |

## Error codes

| Code | Meaning |
| --- | --- |
| `-32000` | Server error (e.g. an `HTTPException` raised by a tool). |
| `-32601` | Method not found / Tool not found. |
| `-32602` | Invalid params (e.g. missing `scanId`). |

## Logging

Every `/mcp` request is logged by the middleware as a compact activity line:

- Success: `✅ tools/call move new downloads scan — 12ms, HTTP 200, from IP`
- Error: `❌ ... — reason, 12ms, HTTP 200, from IP`
- Unknown tool: `⚠️ TOOL xxx <name> (not found)` warnings are emitted by the
  dispatch handler (`app/main.py:1909`).

## Tool call conventions

- Tools that start background work (`move new downloads scan`,
  `confirm move new downloads scan`) **return immediately** and include
  `what_happens_now`, `available_now`, `llm_instructions`, and `next` guidance
  in the JSON payload.
- Progress tools explicitly instruct clients to **wait at least 10 seconds**
  between polls.
- Read-only tools never move files; `confirm move new downloads scan` and
  `delete move new downloads scan items` are the only write tools.

See [mcp-tools.md](mcp-tools.md) for the complete tool reference.
