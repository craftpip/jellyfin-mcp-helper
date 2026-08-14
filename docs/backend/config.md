# Settings and Config Models

See [getting-started/configuration](../getting-started/configuration.md) for the
full environment-variable reference and load order.

Summary of the derived objects in `app/core/config.py`:

- `BASE_DIR` — repository root (`parents[2]` of `config.py`).
- `LOG_DIR` / `REPORT_DIR` — `BASE_DIR/logs` and `BASE_DIR/reports`.
- `Settings` — raw `.env` values (pydantic-settings).
- `PathsConfig` — parsed download/movie/series roots plus `library_layout`.
- `PromptPolicy` — LLM prompt contract (`classifyAs`, `extractFields`).
- `ModelConfig` — LLM provider/tuning.
- `AppConfig` — everything combined (`paths`, `model`,
  `series_title_aliases`, `log_dir`, `report_dir`).
- `get_settings()` / `get_config()` — cached accessors.
