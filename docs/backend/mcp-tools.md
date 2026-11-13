# MCP Tools Reference

16 tools are registered in `app/main.py` (`_mcp_tools()`). Tools fall into four
groups: **Organizer** (scan workflow), **Filesystem/Library browsing**,
**Jellyfin**, and **Release Tracker**.

## Conventions

- **Names** follow the MCP spec (`^[a-zA-Z0-9_-]{1,64}$`, snake_case). The old
  spaced names (`move new downloads scan`, `get jellyfin library items`, …) are
  **not advertised** but stay callable as aliases (`MCP_TOOL_ALIASES` +
  `_resolve_tool_name` in `app/main.py`), so older clients keep working.
- **Annotations:** every tool carries `title` and `annotations`
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint=false`).
  Read-only: progress/report/browse/lookup tools. Destructive:
  `downloads_scan_confirm` (moves/replaces files), `downloads_scan_delete_items`,
  `release_tracker_update` (its `action=delete`).
- **Errors:** a failing tool returns a normal `result` with `isError: true` and
  `content[0].text = {"error": "..."}` so the model can read it and retry. Only
  an unknown tool name is a JSON-RPC protocol error (`-32601`).
- **Token budget:** list tools stay compact; detail is a separate call
  (`jellyfin_library_items` → `jellyfin_item_details`).

## Organizer workflow

Core flow:

1. `downloads_scan_start`
2. `downloads_scan_progress` (poll, ≥10s apart)
3. `downloads_scan_report`
4. Optional: `downloads_scan_update` (redirect items)
5. `downloads_scan_confirm`
6. Optional: `downloads_confirm_progress`

### `downloads_scan_start`

- **Purpose:** start a background scan of configured download folders.
- **Read-only:** classifies candidates and prepares a move plan; does **not**
  move files.
- **Arguments:** `replaceExisting` (boolean, default `true`) — when false, items
  with an existing target are planned as `skip` instead of `replace`.
- **Returns:** compact progress payload with `scan_id`, `status`,
  `what_happens_now`, `available_now`, `llm_instructions`, `next`.

### `downloads_scan_progress`

- **Arguments:** `scanId` (optional; defaults to the current active scan).
- **Returns:** status, current file, processed/total counts, elapsed time, ETA.

### `downloads_confirm_progress`

- **Arguments:** `scanId` (optional).
- **Returns:** confirm status (phase), current file, processed/total, elapsed,
  ETA.

### `downloads_scan_report`

- **Arguments:** `scanId` (optional).
- **Returns:** final report — summary counts, available movie/series roots with
  descriptions, per-item move/replace/skip tables, LLM path-validation guidance.
  If the scan is still running, returns compact progress guidance instead.

### `downloads_scan_update`

- **Purpose:** redirect planned items to a different root **before** confirming.
- **Read-only** (does not move files).
- **Arguments:** `scanId` (required), `items` (required): array of
  `{confirmId, targetPath}` where `targetPath` must be under a configured movie
  or series root.
- **Note:** fetch the report again after updating to verify, then confirm.

### `downloads_scan_delete_items`

- **Purpose:** permanently delete the source download file for one or more
  planned items and remove them from the plan.
- **Destructive** — cannot be undone.
- **Arguments:** `scanId`, `itemIds` (both required).

### `downloads_scan_confirm`

- **Purpose:** apply a completed scan plan (moves files, may stop active
  downloads first).
- **Arguments:** `scanId` (required); optional selectors: `itemIds` (compact
  confirmId values), `sourcePaths` (exact source paths), `sourcePrefixes`
  (source path prefixes, e.g. one release folder). Omit all to confirm the whole
  plan.
- **Returns immediately**; process runs in the background.

## Filesystem / library browsing

### `downloads_recent_files`

- **Purpose:** list video files in download folders added/modified in the last
  N hours. Reads the filesystem, not Jellyfin.
- **Arguments:** `hours` (number, default `24`, clamped to 0.5 – 720).
- **Returns:** items shaped like `jellyfin_library_items` (name, type,
  path; movies add year + empty audio/subtitle arrays, series add
  season/episode counts), plus `count`, `rootsChecked` and any filesystem
  `errors`. Read-only.

### `jellyfin_recently_added`

- **Purpose:** list the individual files most recently added to a Jellyfin
  library, sorted by `DateCreated` descending. Reads Jellyfin's index, not the
  filesystem. Episodes and movies appear as separate items.
- **Arguments:** `libraryName` (required), `hours` (number, default `72`),
  `limit` (integer, default `10`).
- **Returns:** each item includes the absolute file path on disk; movies also
  include year and audio/subtitle languages.

## Jellyfin

### `jellyfin_library_scan`

- **Purpose:** trigger a Jellyfin metadata refresh / library scan for a named
  library.
- **Arguments:** `libraryName` (required), optional `itemNames`/`itemIds` to scan
  specific items, `recursive` (default `true`),
  `metadataRefreshMode`/`imageRefreshMode` (`Default`, `FullRefresh`,
  `ValidationOnly`), `replaceAllMetadata`/`replaceAllImages` (apply with
  FullRefresh).
- **Implementation note:** resolves the library via `GET /Library/VirtualFolders`
  then calls `/Items/{ItemId}/Refresh` with the refresh-mode query params.

### `jellyfin_libraries`

- **Purpose:** list all Jellyfin libraries available to the configured user.
- **Arguments:** none.
- **Note:** its description is augmented with the cached library list hint when
  available.

### `jellyfin_library_items`

- **Purpose:** compact browse/search of movies and series, most recently added
  first (`DateCreated` descending).
- **Arguments:** `libraryName` (required), `search` (optional fuzzy search with
  client-side token overlap + similarity scoring), `ongoingOnly` (default
  `false`), `limit` (default `10`).
- **Returns (kept small on purpose):** movies `name/type/year/path`; series
  `name/type/ongoing/path/season_count/episode_count`. No languages, no
  per-season data. Series totals come from **one** library-wide Season query
  (`_library_season_totals`), not one request per series.

### `jellyfin_item_details`

- **Purpose:** detail for ONE movie or series (best fuzzy match).
- **Arguments:** `libraryName`, `name` (required; legacy `seriesName` accepted),
  `season` (optional, series only).
- **Series returns** per season: `episode_numbers` (ranges like `1-12, 14`),
  `missing_episodes` (gaps up to the highest on-disk episode),
  `aired_not_downloaded` / `upcoming` (only when Jellyfin has virtual
  missing-episode metadata), `audio_languages`, `subtitle_languages`,
  `language_groups` (only when episodes differ). With `season`: only that
  season plus `episode_list` (number, title, languages). Season 0 = specials.
- **Movie returns:** `year`, `runtime_minutes`, `versions[]` with `path`,
  `size_gb`, `container`, `resolution`, `video_codec`, `audio_tracks`,
  `audio_languages`, `subtitle_languages`.
- One `/Shows/{id}/Episodes` call (series) or one `/Items?Ids=` call (movie).

### `jellyfin_ongoing_latest_episodes`

- **Purpose:** list only ongoing series with their latest available episode.
- **Arguments:** `libraryName` (required), `search` (optional; `all`/omitted =
  everything), `limit` (default `10`).

## Release Tracker

Local next-release markers stored in `config/ongoing_releases.json`. The
intended workflow is **local-first**: read the tracker before Jellyfin or the
web when the user asks about a tracked series.

Two tools (the five old ones are aliases):

| Tool | Mode | Args |
| --- | --- | --- |
| `release_tracker_lookup` | `seriesName` given → the one stored marker (local-memory lookup, use first). | `libraryName`, `seriesName`, optional `seriesId` |
| `release_tracker_lookup` | `dueOnly=true` → markers due now/overdue. | optional `libraryName`, `before` (default `now`), `limit` (default `50`) |
| `release_tracker_lookup` | neither → list all stored markers. | optional `libraryName`, `limit` (default `100`) |
| `release_tracker_update` | `action=store` (default) → create/update one marker. | `libraryName`, `seriesName`, `nextReleaseDate` |
| `release_tracker_update` | `action=delete` → remove one marker. | `libraryName`, `seriesName` |

Details:

- `nextReleaseDate` accepts an ISO datetime (`2026-06-28T18:00:00+09:00`) or a
  plain date (`2026-06-28`, treated as due at the start of that date).
- `seriesId` is the preferred key (names can change) and is returned by
  `jellyfin_ongoing_latest_episodes`.
- Optional fields on store: `nextSeason`, `nextEpisode`, `timezone` (IANA),
  `source` (e.g. `llm`, `manual`, website name), `notes`.
