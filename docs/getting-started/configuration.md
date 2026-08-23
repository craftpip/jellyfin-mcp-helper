# Configuration Reference

All configuration is environment-variable driven via a `.env` file, loaded by
pydantic-settings (`app/core/config.py`). Copy `.env.example` to `.env` and edit.

## How settings are loaded

- `Settings` (pydantic-settings `BaseSettings`) reads every documented variable
  from the environment and `.env`, mapping snake_case field names to the
  uppercase `ALIAS` names.
- `get_settings()` caches a module-level `Settings` instance.
- `get_config()` (an `@lru_cache`) builds the derived `AppConfig`:
  - `PathsConfig.from_env(settings)` — parses `DOWNLOAD_ROOTS` / `MOVIE_ROOTS` /
    `SERIES_ROOTS` into structured roots.
  - `ModelConfig.from_env(settings)` — copies the classification/path
    confidence thresholds.
  - `series_title_aliases` — parsed from `SERIES_TITLE_ALIASES`.
  - `log_dir` / `report_dir` — always `BASE_DIR/logs` and `BASE_DIR/reports`.
- `BASE_DIR` is the repository root (`Path(__file__).resolve().parents[2]`).

### Apply model: live vs restart

Every variable is classified by `ENV_SPEC` (see
[app/services/env_manager.py](../../app/services/env_manager.py) and
[backend/config.md](../backend/config.md)) as either **live** or **restart**:

- **Live** — read per request/operation from `os.environ` (Jellyfin and
  qBittorrent client settings, `UI_PANEL_PASSWORD`, `MCP_ALLOW_UNAUTHENTICATED` /
  `MCP_KEYS_FILE` / `MCP_DEFAULT_TOKEN`). Saving them via the Settings page takes
  effect immediately (no restart).
- **Restart** — captured in the `ScanManager` snapshot or the startup lifespan
  (media roots, thresholds, `WEB_UI_*`). They need
  `docker compose up -d --force-recreate` (the compose `env_file` applies at
  container creation) — the Settings page shows a "Recreate required" banner
  listing exactly these vars.

`reload_settings()` (env_manager) re-parses `.env`, patches `os.environ` for
changed keys, resets the `Settings` cache and clears `get_config()` — this is
what makes `live` vars take effect without a restart. `.env` is bind-mounted
into the container, so disk edits are visible instantly.

## Variables

### Classification thresholds

| Variable | Default | Description |
| --- | --- | --- |
| `MODEL_CLASSIFY_CONFIDENCE_THRESHOLD` | `0.65` | Min confidence for a classification result to be kept. |
| `MODEL_PATH_CONFIDENCE_THRESHOLD` | `0.6` | Min confidence for a path-resolution match to be used. |

(The legacy LLM model vars — `MODEL_PROVIDER`, `MODEL_MODE`, `MODEL_BASE_URL`,
`MODEL_NAME`, `MODEL_TEMPERATURE`, `OPENROUTER_API_KEY`,
`MODEL_REQUEST_TIMEOUT_SECONDS`, `MODEL_RETRY_ATTEMPTS` — were removed with the
LLM clients and are no longer read by the code.)

### Download client (qBittorrent via MCP)

| Variable | Default | Description |
| --- | --- | --- |
| `ENABLE_DOWNLOAD_CLIENT_CHECK` | `true` | Enable qBittorrent download-state checks. |
| `DOWNLOAD_CLIENT` | *(unset)* | Client type. Must be set to `qbittorrent` to enable the client (only `qbittorrent` is implemented). |
| `QBT_MCP_URL` | — | qBittorrent MCP endpoint. |
| `QBT_MCP_API_KEY` | — | API key for the qBittorrent MCP server. |
| `QBT_WEBUI_USER` / `QBT_WEBUI_PASS` | — | Optional qBittorrent WebUI credentials. |

### Jellyfin integration (optional)

| Variable | Default | Description |
| --- | --- | --- |
| `ENABLE_JELLYFIN_INTEGRATION` | `true` | Auto-scan Jellyfin libraries after moving files. |
| `JELLYFIN_BASE_URL` | — | Jellyfin server URL. |
| `JELLYFIN_API_KEY` | — | Jellyfin API key (Dashboard > API Keys). |
| `JELLYFIN_MOVIE_LIBRARY_NAME` | `Movies` | Jellyfin movie library name. |
| `JELLYFIN_SERIES_LIBRARY_NAME` | `Shows` | Jellyfin series library name. |

### Storage paths

| Variable | Required | Description |
| --- | --- | --- |
| `DOWNLOAD_ROOTS` | Yes | Comma-separated paths where downloads reside. |
| `MOVIE_ROOTS` | Yes | Comma-separated movie roots; optional `::description` per entry. |
| `SERIES_ROOTS` | Yes | Comma-separated series roots; optional `::description` per entry. |
| `SERIES_TITLE_ALIASES` | No | `alias::canonical` entries (comma-separated) mapping release titles (often Japanese) to the library folder name. Example: `Yani Neko::Chainsmoker Cat Yani Neko`. |

### Web UI

| Variable | Default | Description |
| --- | --- | --- |
| `WEB_UI_ENABLED` | `false` | Enable the React web UI. It is mounted at `/` on the MCP app, so it shares the single port `18328`. |
| `WEB_UI_PORT` | `18329` | Deprecated — unused. The web UI shares the MCP port. |
| `UI_PANEL_PASSWORD` | *(empty)* | Panel login password. Empty = direct login (no prompt); non-empty = the `/api` routes (except `/api/status`, `/api/login`, static assets) require a Bearer token from `POST /api/login`. Tokens are in-memory 32-hex strings (see [web-ui/overview](../web-ui/overview.md)); changing the value needs a container recreate. |

### MCP Access Control

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_ALLOW_UNAUTHENTICATED` | `true` | Allow unauthenticated MCP requests. When `false`, every `/mcp` request needs a valid API key (`Authorization: Bearer` or `X-API-Key`) or `MCP_DEFAULT_TOKEN`. |
| `MCP_KEYS_FILE` | `config/mcp_keys.json` | Path to the hashed API-key store (see [backend/auth.md](../backend/auth.md)). |
| `MCP_DEFAULT_TOKEN` | *(empty)* | Master key accepted by MCP auth for the user `"admin"`. |

## Derived config structures

`PathsConfig` (`app/core/config.py`) turns the flat strings into:

- `download_roots: list[str]`
- `movie_roots: dict[str, str]` / `movie_root_descriptions: dict[str, str]`
  — keys are `movie_0`, `movie_1`, …
- `series_roots: dict[str, str]` / `series_root_descriptions: dict[str, str]`
  — keys are `series_0`, `series_1`, …
- `library_layout` — target layout style defaults:
  - `movieFolderStyle: "Movie Title (Year)"`
  - `seasonFolderStyle: "Season 01"`
  - `episodeFileStyle: "Show Name - S01E01"`

It also exposes helpers used across the app:

- `get_media_prefixes()` — strips a trailing `torrents`/`downloads` segment from
  each download root to derive the media prefix (used to infer cross-drive moves).
- `find_download_root_for_folder(name)` — locates which download root contains a
  folder (used to detect in-progress downloads).
