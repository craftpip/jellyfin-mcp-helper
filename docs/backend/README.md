# Backend

The FastAPI application that powers JellySort. It exposes the MCP JSON-RPC
endpoint, legacy REST endpoints, and hosts the service singletons.

- [Application entrypoint](main.md) — app lifecycle, middleware, wiring.
- [MCP protocol](mcp.md) — JSON-RPC 2.0 over HTTP, request/response shape.
- [MCP tools reference](mcp-tools.md) — all 18 tools with inputs and outputs.
- [REST API](api.md) — health, scans, runs endpoints.
- [Data models](models.md) — the Pydantic schemas.
- [Settings and config models](config.md) — see [getting-started/configuration](../getting-started/configuration.md).

## Source files

| File | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app, MCP endpoint, tool registry, service singletons |
| `app/core/config.py` | Settings + derived config models |
| `app/core/logging.py` | Logging setup |
| `app/core/version.py` | `VERSION` |
| `app/models/schemas.py` | Pydantic schemas |
