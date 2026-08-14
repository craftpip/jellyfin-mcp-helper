# MCP Tools Reference

18 tools are registered in `app/main.py` (`_mcp_tools()`). Tools fall into four
groups: **Organizer** (scan workflow), **Filesystem/Library browsing**,
**Jellyfin**, and **Release Tracker**.

## Organizer workflow

Core flow:

1. `move new downloads scan`
2. `get move new downloads scan progress` (poll, ≥10s apart)
3. `get move new downloads scan report`
4. Optional: `update move new downloads scan` (redirect items)
5. `confirm move new downloads scan`
6. Optional: `get move new downloads confirm progress`

### `move new downloads scan`

- **Purpose:** start a background scan of configured download folders.
- **Read-only:** classifies candidates and prepares a move plan; does **not**
  move files.
- **Arguments:** `replaceExisting` (boolean, default `true`) — when false, items
  with an existing target are planned as `skip` instead of `replace`.
- **Returns:** compact progress payload with `scan_id`, `status`,
  `what_happens_now`, `available_now`, `llm_instructions`, `next`.

### `get move new downloads scan progress`

- **Arguments:** `scanId` (optional; defaults to the current active scan).
- **Returns:** status, current file, processed/total counts, elapsed time, ETA.

### `get move new downloads confirm progress`

- **Arguments:** `scanId` (optional).
- **Returns:** confirm status (phase), current file, processed/total, elapsed,
  ETA.

### `get move new downloads scan report`

- **Arguments:** `scanId` (optional).
- **Returns:** final report — summary counts, available movie/series roots with
  descriptions, per-item move/replace/skip tables, LLM path-validation guidance.
  If the scan is still running, returns compact progress guidance instead.

### `update move new downloads scan`

- **Purpose:** redirect planned items to a different root **before** confirming.
- **Read-only** (does not move files).
- **Arguments:** `scanId` (required), `items` (required): array of
  `{confirmId, targetPath}` where `targetPath` must be under a configured movie
  or series root.
- **Note:** fetch the report again after updating to verify, then confirm.

### `delete move new downloads scan items`

- **Purpose:** permanently delete the source download file for one or more
  planned items and remove them from the plan.
- **Destructive** — cannot be undone.
- **Arguments:** `scanId`, `itemIds` (both required).

### `confirm move new downloads scan`

- **Purpose:** apply a completed scan plan (moves files, may stop active
  downloads first).
- **Arguments:** `scanId` (required); optional selectors: `itemIds` (compact
  confirmId values), `sourcePaths` (exact source paths), `sourcePrefixes`
  (source path prefixes, e.g. one release folder). Omit all to confirm the whole
  plan.
- **Returns immediately**; process runs in the background.

## Filesystem / library browsing

### `get recently added download files`

- **Purpose:** list video files in download folders added/modified in the last
  N hours. Reads the filesystem, not Jellyfin.
- **Arguments:** `hours` (number, default `24`, clamped to 0.5 – 720).
- **Returns:** items shaped like `get jellyfin library items` (name, type,
  path; movies add year + empty audio/subtitle arrays, series add
  season/episode counts), plus `count`, `rootsChecked` and any filesystem
  `errors`. Read-only.

### `get recently added in library`

- **Purpose:** list the individual files most recently added to a Jellyfin
  library, sorted by `DateCreated` descending. Reads Jellyfin's index, not the
  filesystem. Episodes and movies appear as separate items.
- **Arguments:** `libraryName` (required), `hours` (number, default `72`),
  `limit` (integer, default `10`).
- **Returns:** each item includes the absolute file path on disk; movies also
  include year and audio/subtitle languages.

## Jellyfin

### `trigger jellyfin library scan`

- **Purpose:** trigger a Jellyfin metadata refresh / library scan for a named
  library.
- **Arguments:** `libraryName` (required), optional `itemNames`/`itemIds` to scan
  specific items, `recursive` (default `true`),
  `metadataRefreshMode`/`imageRefreshMode` (`Default`, `FullRefresh`,
  `ValidationOnly`), `replaceAllMetadata`/`replaceAllImages` (apply with
  FullRefresh).
- **Implementation note:** resolves the library via `GET /Library/VirtualFolders`
  then calls `/Items/{ItemId}/Refresh` with the refresh-mode query params.

### `get available jellyfin libraries list`

- **Purpose:** list all Jellyfin libraries available to the configured user.
- **Arguments:** none.
- **Note:** its description is augmented with the cached library list hint when
  available.

### `get jellyfin library items`

- **Purpose:** compact browse/search of movies and series, newest first.
- **Arguments:** `libraryName` (required), `search` (optional fuzzy search with
  client-side token overlap + similarity scoring), `ongoingOnly` (default
  `false`), `limit` (default `10`).
- **Returns:** absolute directory path per item; movies include
  `audio_languages`/`subtitle_languages`; series include season/episode counts.

### `get ongoing jellyfin series latest episodes`

- **Purpose:** list only ongoing series with their latest available episode.
- **Arguments:** `libraryName` (required), `search` (optional; `all`/omitted =
  everything), `limit` (default `10`).

## Release Tracker

Local next-release markers stored in `config/ongoing_releases.json`. The
intended workflow is **local-first**: read the tracker before Jellyfin or the
web when the user asks about a tracked series.

| Tool | Purpose | Required args |
| --- | --- | --- |
| `store ongoing series next release` | Store/update one marker. | `libraryName`, `seriesName`, `nextReleaseDate` |
| `get ongoing series next release` | Single-marker lookup (local-memory lookup tool). | `libraryName`, `seriesName` |
| `get due ongoing series releases` | Markers due now/overdue. | optional `libraryName`, `before` (default `now`), `limit` (default `50`) |
| `get ongoing series next releases` | List all tracked upcoming markers. | optional `libraryName`, `limit` (default `100`) |
| `delete ongoing series next release` | Delete one marker. | `libraryName`, `seriesName` |

Details:

- `nextReleaseDate` accepts an ISO datetime (`2026-06-28T18:00:00+09:00`) or a
  plain date (`2026-06-28`, treated as due at the start of that date).
- `seriesId` is the preferred key (names can change) and is returned by
  `get ongoing jellyfin series latest episodes`.
- Optional fields on store: `nextSeason`, `nextEpisode`, `timezone` (IANA),
  `source` (e.g. `llm`, `manual`, website name), `notes`.
