# Settings and Config Models

See [getting-started/configuration](../getting-started/configuration.md) for the
full environment-variable reference, load order, and the live-vs-restart apply
model.

Summary of the derived objects in `app/core/config.py`:

- `BASE_DIR` — repository root (`parents[2]` of `config.py`).
- `LOG_DIR` / `REPORT_DIR` — `BASE_DIR/logs` and `BASE_DIR/reports`.
- `Settings` — raw `.env` values (pydantic-settings).
- `PathsConfig` — parsed download/movie/series roots plus `library_layout`.
- `ModelConfig` — classification/path confidence thresholds only (the legacy
  LLM provider/tuning config was removed with the LLM clients).
- `AppConfig` — everything combined (`paths`, `model`,
  `series_title_aliases`, `log_dir`, `report_dir`).
- `get_settings()` / `get_config()` — cached accessors.

## Runtime env management (`app/services/env_manager.py`)

`ENV_SPEC` is the manifest of every setting with `{key, section, type, secret,
apply, description}`; per-var `apply` classification:

| apply | Variables |
| --- | --- |
| `live` | Jellyfin (`ENABLE_JELLYFIN_INTEGRATION`, `JELLYFIN_*`), incomplete-download detection (`ENABLE_INCOMPLETE_DOWNLOAD_DETECTION`), `UI_PANEL_PASSWORD`, `JELLYSORT_MCP_TOKEN` — all read from `os.environ` per call/request. |
| `restart` | `DOWNLOAD_ROOTS`, `MOVIE_ROOTS`, `SERIES_ROOTS`, `SERIES_TITLE_ALIASES`, `MODEL_CLASSIFY_CONFIDENCE_THRESHOLD`, `MODEL_PATH_CONFIDENCE_THRESHOLD`, `WEB_UI_ENABLED`, `WEB_UI_PORT` — baked into the `ScanManager` snapshot or the startup lifespan. |

`reload_settings()` re-parses `.env`, patches `os.environ`, resets the
`Settings` cache and clears `get_config()` — this makes `live` vars take effect
without a restart. `update_env()` validates via `Settings(**merged)`, rewrites
`.env` preserving comments (atomic `write` + `os.replace`), and returns
`{appliedLive, needsRecreate}`. The admin API surface is documented in
[auth.md](auth.md).

## MCP auth

`app/core/auth.py` gates `/mcp` — when `JELLYSORT_MCP_TOKEN` (or deprecated `MCP_DEFAULT_TOKEN`/`ADMIN_UI_TOKEN`) is set, every request must present it as `Authorization: Bearer <token>` or `X-API-Key`; when empty, MCP is open. See [auth.md](auth.md).
