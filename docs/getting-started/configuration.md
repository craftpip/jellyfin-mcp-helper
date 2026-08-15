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
  - `ModelConfig.from_env(settings)` — copies model tuning values.
  - `series_title_aliases` — parsed from `SERIES_TITLE_ALIASES`.
  - `log_dir` / `report_dir` — always `BASE_DIR/logs` and `BASE_DIR/reports`.
- `BASE_DIR` is the repository root (`Path(__file__).resolve().parents[2]`).

Settings are read at process start; changes to `.env` require a container
restart (and `docker compose` recreate for values applied via `env_file` at
container creation).

## Variables

### AI / Classification

| Variable | Default | Description |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | API key, required only when `MODEL_PROVIDER=openrouter`. |
| `MODEL_PROVIDER` | `ollama` | Model provider: `ollama` or `openrouter`. |
| `MODEL_MODE` | `external-classifier` | Keep as `external-classifier`. |
| `MODEL_BASE_URL` | — | Model API base URL (Ollama default `http://localhost:11434`). |
| `MODEL_NAME` | `llama3.2:1b` | Model name to use. |
| `MODEL_TEMPERATURE` | `0` | Temperature (0 = deterministic). |
| `MODEL_CLASSIFY_CONFIDENCE_THRESHOLD` | `0.65` | Min confidence for LLM classification. |
| `MODEL_PATH_CONFIDENCE_THRESHOLD` | `0.6` | Min confidence for LLM path resolution. |
| `MODEL_REQUEST_TIMEOUT_SECONDS` | `120` | Timeout for model API calls. |
| `MODEL_RETRY_ATTEMPTS` | `2` | Retry attempts for model API calls. |

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

`PromptPolicy` controls the LLM prompt contract:

- `classifyAs: ["movie", "series", "skip"]`
- `extractFields: ["title", "year", "season", "episode", "confidence", "reason"]`
