# Normalizer — `app/services/normalizer.py`

Library-side cleanup/normalization of the already-organized roots. It fixes
folder naming, season layout, and removes junk artifacts. Two modes:
`safe` (structure only) and `full` (also renames titles via the LLM).

## `NormalizerService.execute(run_state)`

1. For every **series root** → `_normalize_series_root`.
2. In `full` mode, for every **movie root** → `_normalize_movie_root`.

### `_normalize_series_root` (per series folder)

1. `_cleanup_transcoding_artifacts` — remove leftover transcoding files.
2. `_cleanup_orphan_trickplay` — remove `.trickplay` dirs with no media.
3. `_normalize_season_folders` — rename season folders to a canonical form
   (e.g. `Season 01` via `_normalize_season_name`), merging when the target
   exists (`_merge_or_rename`).
4. `_move_root_episodes` — move episode files sitting in the series root into
   `Season 01` (creating it if needed), moving associated `.trickplay` dirs too.
5. In `full` mode, `_resolve_series_name` (regex first, then optional LLM) and
   `_rename_path` when confident — otherwise just logs a suggestion.

### `_normalize_movie_root` (full mode)

- Cleans transcoding artifacts.
- For each loose movie file, `_normalize_movie_file`.
- For each folder, normalizes the contained video file and renames the folder to
  the resolved movie name when confident.

## File operations

- `_rename_path` — rename a path (logging `normalize.rename`).
- `_merge_or_rename` — rename, merging when the target already exists.
- `_move_item` — move a file/dir (with dry-run awareness).
- `_delete_path` — delete junk artifacts.

## Name resolution

- `_resolve_title(raw_name, prefer_kind)` — regex-based title cleanup
  (`_prefer_cleaned_title`, `_strip_year_suffix`, `_title_tokens`, prefix
  truncation checks).
- `_resolve_series_name` / `_resolve_movie_name` — regex first; when
  `use_local_ai`, falls back to `_resolve_with_ai` (via `_get_ollama_client`).
- `_build_ai_prompt(raw_name, prefer_kind)` — prompt for the Ollama title
  resolver.
- `_is_confident(score, allow_medium)` — passes when the score clears the
  threshold (or `allow_medium` relaxes it).

## Notes

- Runs entirely under `RunState` (legacy), so it is dry-run capable and logs to
  the run log.
- `_normalize_season_name` canonicalizes season folder names; `_clean_name` /
  `_clean_spacing` fix spacing and stray characters.
