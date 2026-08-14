# Architecture

How the JellySort pieces fit together.

- [System overview](overview.md) — components, ports, and runtime.
- [Media processing flow](media-flow.md) — scan → classify → resolve → plan → confirm.

## Top-level layout

```
app/
  main.py          FastAPI entry point, MCP JSON-RPC endpoint, tool registry
  core/            settings, logging, version
  models/          Pydantic schemas (requests, items, plans, state)
  services/        the processing engine and integrations
  ui/              server.py (UI host) + react/ (source) + react-dist/ (bundle)
config/            runtime state (ongoing releases; scan plans live in memory)
reports/           generated reports
logs/              runtime logs
tests/             pytest suite
plans/             project plans
```
