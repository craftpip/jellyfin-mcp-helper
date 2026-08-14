# Jellyfin Client — `app/services/jellyfin.py`

HTTP client for the Jellyfin API. Authenticates with an API key via the
`X-Emby-Token` header.

## Construction

`JellyfinClient(base_url, api_key, movie_library, series_library)`

`JellyfinClient.from_env()` returns `None` unless `ENABLE_JELLYFIN_INTEGRATION`
is truthy and `JELLYFIN_API_KEY` is set. Default base URL is
`http://host.docker.internal:8096`.

## Methods

| Method | Endpoint(s) used | Purpose |
| --- | --- | --- |
| `library_name_for_kind(kind)` | — | `Movies` for `movie`, `Shows` for `series`. |
| `list_libraries()` | `GET /Library/VirtualFolders` | `[{name, id}]` of all libraries. |
| `scan_library(library_name, item_ids, item_names, recursive, metadata_refresh_mode, image_refresh_mode, replace_all_metadata, replace_all_images)` | `GET /Items` (name→id resolution), `POST /Items/{id}/Refresh` | Trigger a refresh for the whole library or specific items. |
| `notify_media_updated(paths)` | `POST /Library/Media/Updated` | Tell Jellyfin specific paths changed (used after moves/replaces). |
| `list_library_items(library_name, search, ongoing_only, limit)` | `GET /Items` (+ `/Seasons`, `/Episodes` per series) | Compact browse/search with fuzzy client-side matching. |
| `recently_added_items(library_name, hours, limit)` | `GET /Items` (DateCreated) | Files added within a window, newest first. |
| `list_ongoing_series_latest_episodes(library_name, search, limit)` | `GET /Items` + per-series seasons/episodes | Latest available episode per ongoing series. |

### `scan_library` details

1. Resolve the library name to its `ItemId` via `list_libraries`.
2. Optional `itemNames`: resolved to item IDs through `GET /Items`
   (`SearchTerm`, `IncludeItemTypes=Series,Movie`); unmatched names are
   returned in `not_found`.
3. POST `/Items/{id}/Refresh` for each resolved id (concurrently) or the whole
   library with:
   - `Recursive`, `MetadataRefreshMode`, `ImageRefreshMode`
     (`Default` / `FullRefresh` / `ValidationOnly`),
   - `ReplaceAllMetadata`, `ReplaceAllImages`.
4. Returns `{name, id, scanned_items?, not_found?}`.

### `list_library_items` details

- Movies and series are fetched and merged, newest first.
- `ongoing_only` keeps only series whose status is ongoing.
- Fuzzy search (`_fuzzy_score`) is applied client-side with token overlap and
  similarity scoring to handle typos and partial names.
- Series include total season count, total episode count, and per-season counts
  (`_get_series_seasons`).

### Ongoing series

`_is_ongoing_series` checks the item's status/`Status` field against the
ongoing set. `ONGOING_STATUSES` covers values such as `continuing`,
`returning series`, and `in production`.
