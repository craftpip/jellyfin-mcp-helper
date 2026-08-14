# Backend Tests

Run with:

```bash
python3 -m pytest tests/
```

## Test files

| File | Covers |
| --- | --- |
| `test_classifier.py` | `classify_candidate`: SxxEyy patterns, revisions, anime extras, bare/contained episodes, movie-title folders, the full corpus sweep, and the "no release junk in titles" regression assertion. |
| `test_mcp_errors.py` | MCP JSON-RPC error shapes, `tools/list` contents, Jellyfin client formatting (`list_library_items`, fuzzy search, `_fuzzy_score`), ongoing-series status handling, `notify_media_updated`, library-scan trigger, Release Tracker upsert/get/due/list/delete. |
| `test_recent_files.py` | `recent_video_files` (mtime window, extension filter, nested dirs, skip markers, hours guard) and recent-file item shaping. |
| `test_resolver.py` | `sanitize_name`, `normalize_*`, season-dir candidates, movie/series resolution with existing show/season folders, cross-root exact matches, episode-file existence (replace vs move). |
| `test_scan_errors.py` | Scan flow edge cases: filesystem errors collected as skip items, scan progress/report formatting, per-confirm progress scoping, update-target validation. |

## Highlights

- **Corpus regression** (`test_classifier.py`): every path in
  `tests/corpus/download_paths.json` is classified and the test fails if any
  title/episode_title contains release junk (codecs, resolutions, group names)
  or brackets.
- **Per-confirm progress** (`test_scan_errors.py`): asserts `processed`/`total`
  and per-confirm `counts` so cumulative-vs-per-batch counting cannot regress.
- **MCP error contract** (`test_mcp_errors.py`): invalid params and unknown
  tools return HTTP 200 with a JSON-RPC `error` envelope (not HTTP errors).
