# Docker

## Dockerfile

- Base: `python:3.12-slim`.
- Installs the pinned runtime deps via pip (no cache): `uvicorn[standard]`,
  `fastapi`, `httpx`, `pydantic`, `pydantic-settings`, `guessit` (see
  `requirements.txt` for the exact pins; the Dockerfile pins are kept in sync).
- `WORKDIR /app`; exposes `18327` (the single backend port that serves both MCP
  and the mounted web UI).
- `CMD uvicorn app.main:app --host 0.0.0.0 --port 18327`.

Note: the source is **not** copied into the image — the compose file bind-mounts
the whole repo into `/app`, so edits and `react-dist/` builds are live.

## docker-compose.yml

```yaml
name: jellysort
services:
  jellysort:
    build: .
    image: jellysort:dev
    container_name: jellysort
    restart: unless-stopped
    ports:
      - "18328:18327"   # single port: MCP (/mcp) + Web UI (/, /settings, /api/*)
    env_file:
      - .env
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - .:/app
      - <host-download-path>:/media1
      - <host-download-path>:/media2
      - <host-download-path>:/media3
```

## Key facts

- **Ports:** the app listens on `18327` inside the container and is exposed on
  `18328`. That single port serves both MCP (`/mcp`) and the Web UI (`/`,
  `/settings`, `/api/*`).
- **`.env`:** passed via `env_file`, so changes require a `docker compose`
  recreate (`docker compose up -d`) rather than a plain `docker restart`.
- **Media mounts:** each host download/library path is bind-mounted at a
  container path (`/media1`, `/media2`, …). The `.env` values for
  `DOWNLOAD_ROOTS` / `MOVIE_ROOTS` / `SERIES_ROOTS` **must match the container
  paths**, not the host paths.
- **Repo mount:** `.` is mounted at `/app`, so `app/` source changes and rebuilt
  `react-dist/` are picked up after a `docker restart jellysort`. The bind mount
  can enter a stale state after a transient filesystem error (`Errno 5`); a full
  `docker compose down && docker compose up -d` re-establishes it.
- **`host.docker.internal`:** `host-gateway` mapping lets the container reach
  services on the host (Jellyfin's default base URL is
  `http://host.docker.internal:8096`).

## Rebuild after source changes

```bash
docker compose build && docker compose restart
```

## Common operations

```bash
# Start
docker compose up -d --build

# Health check
curl http://localhost:18328/health   # {"status":"ok"}

# Restart (picks up bind-mounted source + built UI)
docker restart jellysort

# Full recreate (re-applies env_file, re-establishes mounts)
docker compose up -d
```
