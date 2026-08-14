# Media Processing Flow

The core workflow is **scan → classify → resolve → plan → review → confirm**.
The modern path uses `ScanManager`; a legacy path uses `OrganizerService`.

## 1. Scan

`scanner.py` walks every root in `PathsConfig.download_roots` with `os.walk`,
skipping known junk directories (markers like `.trickplay`) and collecting video
files (`VIDEO_EXTENSIONS = {.mkv, .mp4, .avi, .mov, .m4v, .wmv, .flv}`).

Each file becomes a `CandidateItem` with its `name`, the `container_path`
(parent folder), `relative_path`, and `file_size`.

Sample-sized files (**under** 150 MB, `SAMPLE_SIZE_THRESHOLD`) are flagged so
the classifier can mark them as `sample` extras. Filesystem errors during walking
are collected per-path (`ScanPathError`) instead of aborting the whole scan.

## 2. Classify

`classifier.py` classifies each candidate with guessit plus regex fallbacks:

1. Parse the filename (guessit).
2. Extract a clean title; skip the parsed title when the container folder is a
   better/fuller title (e.g. folder `Nimbus 7_9 (2020)` vs clean title `Nimbus`).
3. Extract season/episode via several regexes:
   - `SxxEyy` patterns (with optional `v\d+` revisions).
   - Season-only markers (`Season 02`, `S02`).
   - Dash/word-dash episodes (`Show - 4`, `Show Episode 4`).
   - Bare episode numbers, dot-separated episodes, and **contained** bare
     episodes (a leading number inside a show folder).
   - Foreign episode tokens (`episodio`, `episode`, `capitulo`, …).
   - Decimal episodes only when prefixed by `SxxE` (so codec decimals like
     `Opus 2.0` never look like episode numbers).
4. Infer the kind: explicit episode → `series`, movie/season markers → `movie`,
   a folder that looks like a movie title (`3 Idiots (2009)`) → `movie`.
5. Override with extra/sample detection: numbered anime extras (`NCOP1`,
   `NCED2`, `OP1`, `ED3`, `SP01`), markers (`ova`, `ona`, `special`, `bonus`,
   `recap`, `trailer`, …) and samples are classified `skip`.

The result is a `ClassificationResult` with `kind`, `title`, `episode_title`,
`year`, `season`, `episode`, `confidence`, and `reason`. When `use_local_ai`
is enabled, an external LLM (`ollama`/`openrouter`) can classify instead, and
its output is kept when confidence clears the threshold.

## 3. Resolve

`resolver.py` decides the target path for each candidate:

- **Movies** → `{movie_root}/{Title (Year)}/{Title (Year)}.{ext}`.
- **Series** → `{series_root}/{Show}/{Season NN}/{episode_title} - S{ss}E{ee}{ext}`.

Resolution details:

- `sanitize_name` strips characters invalid on common filesystems.
- Text is normalized (case-fold, punctuation — including apostrophes — removed)
  so `Fox's Den` matches `Foxs Den`.
- A target root is picked per item (`_pick_drive_root`, same-drive preference).
  Existing series folders are matched by normalized title via `series_aliases`
  (a bounded rglob scan of video files in the folder, max ~12 samples) and
  `series_lookup_key`; when no existing folder matches, a per-scan path memory
  reuses the show folder chosen for the first season of the same show.
- Existing season folders are reused; existing files for an episode (including
  `v2`/`v3` revisions) are detected so the plan can say `replace` instead of
  `move`.

The resolver keeps a bounded cache (`series_aliases`, `series_video_count`,
path memories) that is cleared (`clear_resolver_cache`) between scan runs.

## 4. Plan

`scan_manager.py` turns resolutions into a `ScanPlan` containing `ScannedItem`s.
Each item records:

- classification (`name`, `item_type`, `confidence`, `reason`)
- `target_path`, `action` (`move` / `replace` / `skip`), `error`
- existence flags (`show_folder_exists`, `season_folder_exists`, `file_exists`)
- `file_size`, `cross_drive` (source and target are on different media roots)

Rules applied while building the plan:

- In-progress downloads (qBittorrent, when enabled) are skipped.
- Zero-byte files are skipped.
- Revision files (`v2`, `REPACK2`) overwrite existing targets.
- Items whose target already exists and `replace_existing` is false are skipped.

The plan is returned to the caller as a **report** (JSON with summary counts,
roots with descriptions, and per-item move tables) for review.

## 5. Review / update

Before confirming, callers can:

- Re-fetch the report.
- Update individual item targets (`update move new downloads scan` /
  `PATCH`-style REST), validated to stay inside the configured roots and use
  known video extensions.

## 6. Confirm

`confirm_scan` runs in the background and walks the items in phases:

1. `preparing` — reset counters, resolve prerequisites.
2. `stopping_seeding` — if qBittorrent integration is on and the item matches an
   active download path, stop seeding before moving.
3. `moving` — perform the file operation:
   - **Same drive** → `os.replace` (atomic).
   - **Cross drive** → chunked copy to a `.{name}.partial` temp file, `fsync`,
     then `os.replace`; progress (copied bytes, speed, percent) is tracked live.
4. `deleting_source` — remove the source and clean up empty parent folders.
5. `triggering_jellyfin` — for new/updated paths, notify Jellyfin and trigger
   library scans for the affected libraries.
6. `completed` / `failed`.

Per-confirm progress is scoped to the current batch (`confirm_processed`,
baseline snapshots of cumulative counts), while the final report still reflects
the cumulative scan totals.

## Legacy flow (organizer)

`organizer.py` runs the same scan/classify/resolve steps but **applies moves
immediately** per item inside a `RunState`, supporting `dry_run` and optional
normalization. `run_manager.py` wraps this in a "one active run" lifecycle with
streaming logs. New integrations should use the scan workflow instead.
