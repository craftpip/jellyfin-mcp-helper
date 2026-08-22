# Getting Started

How to install, configure, and run JellySort.

- [Quickstart](quickstart.md) — configure `.env`, mount media, start Docker, health check.
- [Configuration reference](configuration.md) — every environment variable and how settings are loaded.

## Requirements

- Python 3.11+ or Docker.
- Optional: a qBittorrent MCP server for download-state checks and pre-move handling.
- Optional: a Jellyfin server + API key for library refresh and Jellyfin MCP tools.

## Quick summary

```bash
cp .env.example .env
# edit .env, mount your media in docker-compose.yml
docker compose up -d --build
curl http://localhost:18328/health   # {"status":"ok"}
```
