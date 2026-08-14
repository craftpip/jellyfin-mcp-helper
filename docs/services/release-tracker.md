# Release Tracker — `app/services/release_tracker.py`

A tiny local key-value store for **next-release markers** of ongoing series.
Powers the five Release Tracker MCP tools. This is the "local memory" layer:
the intended workflow reads it **before** consulting Jellyfin or the web when a
user asks about a tracked series.

## Storage

- Default file: `BASE_DIR/config/ongoing_releases.json` (bind-mounted, survives
  container rebuilds).
- All writes happen under a process-wide `Lock` and use an atomic temp-file
  replace, so concurrent access is safe.

## Record shape

```json
{
  "libraryName": "Shows",
  "seriesName": "Some Show",
  "seriesId": "abc…",
  "nextReleaseDate": "2026-06-28T18:00:00+09:00",
  "nextSeason": 2,
  "nextEpisode": 7,
  "timezone": "Asia/Tokyo",
  "source": "llm",
  "notes": "...",
  "updatedAt": "2026-06-27T…"
}
```

## Keys

- Records are keyed by `seriesId` when present, else by
  `_name_key(libraryName, seriesName)` (normalized lowercase names).
- `_find_existing_key` also matches by `seriesId` first, then by normalized
  name — so an upsert with a `seriesId` can replace a name-keyed record and
  vice versa.

## Methods

| Method | Behavior |
| --- | --- |
| `upsert_release(payload)` | Validates `libraryName`/`seriesName`/`nextReleaseDate`, parses the date (respecting `timezone`), and inserts/updates the record. Returns the stored record. |
| `list_releases(library_name, limit)` | All tracked markers, sorted by `nextReleaseDate` ascending. Returns `{tracked_count, items}`. |
| `get_release(payload)` | Single record by `seriesId` or name; `None` if missing. |
| `get_due_releases(library_name, before, limit)` | Markers due at or before `before` (`"now"` or ISO datetime), sorted ascending. |
| `delete_release(payload)` | Remove one marker; returns the removed record or `None`. |

## Date parsing

- `nextReleaseDate` accepts an ISO datetime (with or without offset) or a plain
  date, which is treated as due at the **start** of that date.
- `timezone` (IANA, e.g. `Asia/Tokyo`) is applied to plain dates / naive
  datetimes.
- `_parse_stored_datetime` re-parses stored ISO values for sorting/due checks.
