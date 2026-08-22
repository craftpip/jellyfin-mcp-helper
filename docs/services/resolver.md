# Resolver — `app/services/resolver.py`

Decides where each classified candidate should live in the library roots, and
detects existing files/folders so the plan can say `move` vs `replace`.

## Module-level helpers

| Function | Purpose |
| --- | --- |
| `sanitize_name(value)` | Clean a name for use as a filesystem path component. |
| `fold_diacritics(value)` | NFD + strip combining marks, so `Nimbús` ≡ `Nimbus`. Applied inside `normalize_text`/`tokenize` (global — every matcher benefits). |
| `normalize_text(value)` | Lowercase, fold diacritics, strip punctuation (including apostrophes), keep word tokens. Global normalization used by matching. |
| `normalize_series_text(value)` | `normalize_text` wrapper for series titles. |
| `tokenize(value)` | Set of normalized word tokens. |
| `series_lookup_key(title, year)` | Canonical key for a series (title + optional year). |
| `series_aliases(path)` | Bounded set of normalized titles seen in a series folder (rglob per extension, stops after ~12 video samples); also yields post-number episode titles so an episode-title match (`A Dream Encounter`) can identify a show whose name diverges completely. |
| `season_dir_candidates(season_number)` | Possible season folder names (e.g. `Season 01`, `S01`, …). |
| `season_arc_text(value)` | Release-side season-arc text after the `S21`/`Season 21` marker (`S21 Sun & Moon Ultra Adventures` → `sun moon ultra adventures`). |
| `season_dir_arc(dir_name)` | Library-side equivalent (`s21 - Sun and Moon Ultra Adventures` → `sun moon ultra adventures`). |
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
- Reuses an existing season folder (`_pick_existing_season_dir`) — exact
  normalized names win, but a dir whose name **starts with** a valid season
  token also counts (`s21 - Midnight Ultra Journeys` → Season 21), so
  subtitle-style season dirs are joined instead of recreated.
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

### Continuity detection and deep re-search (smart correction)

For continuation items (`season > 1` or mid-season `episode > 1`) the resolver
computes suspect signals and, on a phantom match, re-searches across all series
roots instead of trusting the remembered path:

- **Signals** (surfaced as `suspect`/`flags` on the item): `phantom_show_folder`
  (resolved show dir exists nowhere on disk — it came from in-scan memory),
  `season_gap` (show exists but has no `season-1` and none is planned in the
  scan), `episode_gap` (`episode-1` missing on disk and in the scan plan).
  A fresh S01E01 of an unknown show is never suspect.
- **Deep search** — `find_continuation_show(title, year, season, episode_title,
  roots)`: a **recall tier** with no token-overlap gate (folders matching by
  season-arc subtitle, episode-title alias, year, or name subset all compete),
  and an **auto-pick tier** requiring a strong signal + continuity evidence
  (has `season-1`, or the closest season below target). Cost control: cheap
  signals first; the bounded alias walk only runs on folders that pass a cheap
  pre-filter — never `sorted(rglob("*"))`.
- On success the whole title group is re-targeted to the found show dir
  (`corrected=True`, `correction_note` set) joining the real season dir via the
  subtitle rule above; `file_exists`/`action` are recomputed per item.

### Candidate targets

Every resolution builds `candidate_targets` (top-N, capped) from the shortlist
scores plus the default new-folder path — for suspect continuation groups the
recall set above is used (no token gate) so a lookalike/franchise folder still
appears; movie-marker suspects additionally get an "as movie" destination
(`reclassify_as_movie`, flips `item_type` when picked). Candidates flow into
report items (`candidateTargets`) and the report markdown; the UI surfaces them
via Browse/retarget (see [web-ui/overview](../web-ui/overview.md)).

### Scan-scoped disk index and planned-target memory

`prepare_scan(paths)` builds the existing movie/series folder index **once per
scan** — `_resolve_series`/`_resolve_movie` never re-list the roots per
candidate. `_series_path_memory` is the *planned-target* memory: it records the
show dir the scan decided to write to (on disk or not) so every episode of one
show lands in the same target folder. `_lookup_series_path` consults memory
first, then the disk index — a remembered dir that is **not** in the index is
a phantom (the suspect signal), so the phantom flag is self-healing instead of
a memory bug.

### Runtime state

- `reset_runtime_state()` — clears caches and path memories at the start of a
  scan.
- `bind_run_state(run_state)` — binds a legacy `RunState` for logging.

## Notes

- `_is_valid_series_path` sanity-checks a target before it is accepted.
- `_movie_folder_name` produces the `Title (Year)` folder name.
- Path matching treats punctuation and diacritics as irrelevant: `Fox's Den`
  matches `Foxs Den`; `Nimbús Pocket Monsters (1996)` matches title `Nimbus`
  and a `S01E05` release of a franchise movie with zero name overlap can still
  find the show via season-arc or episode-title evidence.
