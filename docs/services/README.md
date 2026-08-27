# Services

The processing engine and integrations in `app/services/`.

| Module | Role |
| --- | --- |
| [scanner](scanner.md) | Filesystem walking → candidates |
| [classifier](classifier.md) | guessit + regex classification |
| [resolver](resolver.md) | Target path resolution |
| [scan-manager](scan-manager.md) | Scan → plan → confirm workflow + file moves |
| [jellyfin](jellyfin.md) | Jellyfin API client |
| [download-client](download-client.md) | In-progress (incomplete-file marker) detection |
| [release-tracker](release-tracker.md) | Local next-release store |
| `presenters.py` | Shared report/progress formatters (MCP + UI) |
| `history_store.py` | Confirm history (`history_groups`/`history_items` in `app.db`, `path_history_json`, `suspect`/`corrected`/`cross_drive`, live `pathExists`) |
| `scan_history.py` | Scan snapshots (`scans` table + `reports/history/*.json`, `MAX_HISTORY=200`, `ON CONFLICT DO UPDATE` upsert, singleton `reports/current.json`) |
| `api_key_manager.py` | Hashed MCP API-key store — see [backend/auth](../backend/auth.md) |
| `env_manager.py` | `ENV_SPEC` + live/restart env reload — see [backend/auth](../backend/auth.md) |

## Data flow

```
scanner.scan_candidates ──► CandidateItem
        │
        ▼
classifier.classify_candidate ──► ClassificationResult (kind/title/season/episode)
        │
        ▼
resolver.PathResolver.resolve ──► ResolvedTarget (root_key/target_path)
        │
        ▼
scan_manager ──► ScannedItem plan (move / replace / skip)
```
