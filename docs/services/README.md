# Services

The processing engine and integrations in `app/services/`.

| Module | Role |
| --- | --- |
| [scanner](scanner.md) | Filesystem walking → candidates |
| [classifier](classifier.md) | guessit + regex classification |
| [resolver](resolver.md) | Target path resolution |
| [scan-manager](scan-manager.md) | Scan → plan → confirm workflow + file moves |
| [organizer](organizer.md) | Legacy immediate organize flow |
| [normalizer](normalizer.md) | Library-side rename/normalize (safe/full) |
| [jellyfin](jellyfin.md) | Jellyfin API client |
| [download-client](download-client.md) | qBittorrent MCP client |
| [release-tracker](release-tracker.md) | Local next-release store |
| [llm-clients](llm-clients.md) | Ollama / OpenRouter LLM clients |
| `run_manager.py` | Legacy run lifecycle wrapper |

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
scan_manager / organizer ──► ScannedItem plan / immediate move
```
