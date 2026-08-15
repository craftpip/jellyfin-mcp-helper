# JellySort Documentation

JellySort is a self-hosted **API service + MCP server** that watches download
folders, classifies the media inside, plans a tidy target layout for your
Jellyfin library, and moves/replaces files into place — then triggers a
Jellyfin library scan so the new content shows up.

This folder is the complete project documentation, written from the code.

## Quick links

- **[Getting started](getting-started/README.md)** — install, configure, and run
  - [Quickstart](getting-started/quickstart.md)
  - [Configuration reference](getting-started/configuration.md)
- **[Architecture](architecture/README.md)** — how the pieces fit together
  - [System overview](architecture/overview.md)
  - [Media processing flow](architecture/media-flow.md)
- **[Backend](backend/README.md)** — the FastAPI/MCP application
  - [Application entrypoint](backend/main.md)
  - [MCP JSON-RPC protocol](backend/mcp.md)
  - [MCP tools reference](backend/mcp-tools.md)
  - [REST API](backend/api.md)
  - [Data models](backend/models.md)
  - [Settings and config models](backend/config.md)
- **[Services](services/README.md)** — the processing engine
  - [Scanner](services/scanner.md)
  - [Classifier](services/classifier.md)
  - [Resolver](services/resolver.md)
  - [Scan manager](services/scan-manager.md)
  - [Organizer](services/organizer.md)
  - [Normalizer](services/normalizer.md)
  - [Jellyfin client](services/jellyfin.md)
  - [qBittorrent client](services/download-client.md)
  - [Release tracker](services/release-tracker.md)
  - [LLM clients (Ollama / OpenRouter)](services/llm-clients.md)
- **[Web UI](web-ui/README.md)** — the React frontend
  - [Overview](web-ui/overview.md)
  - [State store](web-ui/store.md)
  - [Utilities and report mapping](web-ui/utils.md)
  - [Components](web-ui/components.md)
- **[Deployment](deployment/README.md)** — Docker and release workflow
  - [Docker](deployment/docker.md)
- **[Testing](testing/README.md)** — backend and frontend test suites
  - [Backend tests](testing/backend.md)
  - [Corpus fixtures](testing/corpus.md)

## Repository layout (source of truth)

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI entry point, MCP JSON-RPC endpoint, tool registry |
| `app/core/` | Settings, logging, version |
| `app/models/` | Pydantic schemas |
| `app/services/` | Scanner, classifier, resolver, scan/organize/normalize managers, Jellyfin + qBittorrent + LLM clients, release tracker |
| `app/ui/` | FastAPI UI server (`server.py`) and the React app (`react/`) with its built bundle (`react-dist/`) |
| `config/` | Runtime state (`ongoing_releases.json`) |
| `reports/` | Generated run/scan reports |
| `logs/` | Runtime logs |
| `tests/` | pytest suite + obfuscated download-path corpus |
| `plans/` | Project plans and roadmaps |
| `docker-compose.yml` / `Dockerfile` | Container deployment |
| `.env` | Active configuration |

## At a glance

- **Language / runtime:** Python 3.12 (FastAPI + uvicorn), React 18 (Vite) for the UI.
- **Ports:** single port — MCP (`/mcp`) and Web UI (`/`, `/settings`, `/api/*`) both on `18327` (internal) / `18328` (host-mapped).
- **Media classification:** [guessit](https://guessit.readthedocs.io/) plus regex
  fallbacks for SxxEyy patterns, bare episodes, extras, samples, and foreign
  language episodes; optional external LLM (Ollama or OpenRouter) as an
  external classifier / name resolver.
- **Integrations:** Jellyfin (library scans, media updates, ongoing-series
  tracking) and qBittorrent (in-progress detection, seed stopping).
- **Clients:** MCP clients (claude, opencode) talk to the service over
  JSON-RPC; the web UI talks to the same endpoint.
