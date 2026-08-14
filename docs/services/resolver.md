# Resolver — `app/services/resolver.py`

Decides where each classified candidate should live in the library roots, and
detects existing files/folders so the plan can say `move` vs `replace`.

## Module-level helpers

| Function | Purpose |
| --- | --- |
| `sanitize_name(value)` | Clean a name for use as a filesystem path component. |
| `normalize_text(value)` | Lowercase, strip punctuation (including apostrophes), keep word tokens. Global normalization used by matching. |
| `normalize_series_text(value)` | `normalize_text` wrapper for series titles. |
| `tokenize(value)` | Set of normalized word tokens. |
| `series_lookup_key(title, year)` | Canonical key for a series (title + optional year). |
| `series_aliases(path)` | Bounded set of normalized titles seen in a series folder (rglob per extension, stops after ~12 video samples). |
| `season_dir_candidates(season_number)` | Possible season folder names (e.g. `Season 01`, `S01`, …). |
| `series_video_count(path)` | Video file count in a folder (bounded at ~20). |
| `clear_resolver_cache()` | Clear all cached lookups (called between scan runs). |

## `PathResolver`

`PathResolver(config: AppConfig)` — the main resolver.

### Target layouts

- **Movie:** `{movie_root}/{Movie Title (Year)}/{Movie Title (Year)}.{ext}`
- **Series:** `{series_root}/{Show}/{Season NN}/{episode_title} - S{ss}E{ee}{ext}`

The season folder is formatted like `Season 01` (see
`PathsConfig.library_layout`).

### `async resolve(candidate, classification) -> ResolvedTarget`

Dispatches on `classification.kind` to `_resolve_movie` or `_resolve_series`.

### `_resolve_movie`

- Picks a movie root with `_pick_drive_root`, which prefers a root on the same
  drive as the source (falling back to the source-root-indexed default).
- Builds the folder name as `Title (Year)` when a year exists.
- Reuses an existing matching folder (`_pick_existing_path`) when safe.

### `_resolve_series`

- Picks a series root with `_pick_drive_root` (same-drive preference), then
  matches an **existing** show folder by normalized title using `series_aliases`
  and `series_lookup_key` (fast token-overlap pre-checks avoid walking unrelated
  trees — see the resolver-scan-hang fix in `AGENTS.md`).
- When no existing folder matches, a per-scan path memory
  (`_remember_series_path` / `_lookup_series_path`) reuses the show folder chosen
  for the first season of the same show, so a freshly-added multi-season series
  is not split across drives during one scan.
- Reuses an existing season folder (`_pick_existing_season_dir`).
- Detects an existing file for the same episode (`SxxEyy` with optional `v\d+`)
  so `[RlsGrp] Show - S01E04v2.mkv` is found even when the constructed target
  name differs → the item is planned as `replace`.
- Also records an "alias season" memory so episodes that belong to a series
  alias resolve consistently.

### Existing-path matching

- `_pick_existing_path` / `_pick_exact_path_match` / `_shortlist_target_paths` /
  `_best_path_match`: progressively cheaper matching — exact title match, token
  overlap, then a scored shortlist. `_is_safe_existing_match` prevents matching
  a folder whose content contradicts the desired name (e.g. would clobber
  another show).
- These walk the tree lazily (targeted extension globs, not `sorted(rglob)`),
  and each match is bounded to a small sample, so scans over large libraries
  stay fast.

### Runtime state

- `reset_runtime_state()` — clears caches and path memories at the start of a
  scan.
- `bind_run_state(run_state)` — binds a legacy `RunState` for logging.

## Notes

- `_is_valid_series_path` sanity-checks a target before it is accepted.
- `_movie_folder_name` produces the `Title (Year)` folder name.
- Path matching treats punctuation as irrelevant: `Fox's Den` matches `Foxs Den`.
