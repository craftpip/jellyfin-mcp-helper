# Classifier — `app/services/classifier.py`

Classifies a `CandidateItem` into `movie`, `series`, or `skip` using
[guessit](https://guessit.readthedocs.io/) plus a set of carefully tuned regex
fallbacks. This is the most pattern-sensitive part of the codebase — the
regression corpus in `tests/corpus/download_paths.json` exists to keep fixes
permanent.

## Entry point

`classify_candidate(candidate, series_title_aliases=None) -> ClassificationResult`

Flow:

1. Choose the label to parse (`relative_path` if present, else the filename).
2. `guessit(label, {"single_value": True})`.
3. Extract the title:
   - `_extract_title` prefers the parsed series/title, but keeps the container
     folder name when it is a "fuller" title (e.g. folder `Nimbus 7_9 (2020)`
     vs clean parsed title `Nimbus`) or when the parsed title has no
     alphabetic characters (bare-episode files whose guessit title is just a
     number).
   - For contained bare episodes, the container folder itself is used as the
     series name (unless the container is the movie's own title folder).
4. Split foreign-language episode titles (`_split_foreign_episode_title`) for
   patterns like `Show Episodio 04 Title`.
5. Extract the episode title (`_extract_episode_title`): guessit
   `episode_title`, or CRC-bracket/`SxxEyy`-derived fallbacks.
6. Apply title aliases (`_apply_title_alias`) from `SERIES_TITLE_ALIASES`.
7. Extract year/season/episode, filling gaps with regex fallbacks.
8. Infer kind, then apply extra/sample overrides (→ `skip`).

## Regexes

| Regex | Matches |
| --- | --- |
| `EXTRA_MARKERS` | `ncop\d*`, `nced\d*`, `op\d*`, `ed\d*`, `sp\d*`, `ova`, `ona`, `special`, `extras?`, `bonus`, `recap`, `trailer` |
| `SAMPLE_MARKERS` | `sample` |
| `SEASON_EPISODE_RE` | `SxxEyy` (validation helper) |
| `SPECIAL_TAG_RE` | boundary-bounded `sp` tag |
| `DECIMAL_EPISODE_RE` | `SxxEyy.zz` decimals — **must** be prefixed by `SxxE` so codec decimals (`Opus 2.0`, `DDP2.0`) never match |
| `SEASON_ONLY_RE` | `season 2`, `S02` |
| `SEASON_EPISODE_TOKEN_RE` | `SxxEyy` with optional `v\d+` revision |
| `SEASON_DASH_EPISODE_RE` | `Sxx - yy` |
| `SEASON_WORD_DASH_EPISODE_RE` | `season 2 - 4` |
| `SEASON_FOLDER_RE` | `Season 02` / `S02` folder names |
| `BARE_EPISODE_RE` | bare episode numbers in a filename stem |
| `CONTAINED_BARE_EPISODE_RE` | leading number + separator + title; the separator `.` must NOT be followed by a digit, so floats never match |
| `FOREIGN_EPISODE_RE` | `episodio`, `episode`, `capitulo`, `capitolo`, `capítulo`, `chapitre`, `épisode`, `kapitel` + number |

## Season/episode extraction order

1. `_extract_season_episode(label)` — `SxxEyy`, then `Sxx - yy`, then
   `season x - y`.
2. `_extract_season_from_folder` — the parent folder matches `Season 02`/`S02`.
3. `_extract_bare_episode_from_name` — only when the season came from a folder.
4. `_extract_contained_bare_episode` — leading number in a file inside a
   folder, **guarded by `_container_is_movie_folder`** so `3 Idiots (2009).mkv`
   in a `3 Idiots (2009)` folder is a movie, not series episode 3.
5. `foreign_episode` fallback.

## Kind inference (`_infer_kind`)

| Condition | Kind | Confidence |
| --- | --- | --- |
| Explicit episode matched | `series` | 0.9 |
| guessit says episode + episode number | `series` | 0.9 |
| Season matched | `series` | 0.8 |
| guessit says movie | `movie` | 0.9 |
| Year present, no `SxxEyy` | `movie` | 0.75 |
| Default (standalone file) | `movie` | 0.65 |

## Extra / sample overrides

- If the kind would be `series`/`movie` but the label or episode_title contains
  an extra marker (or `SPECIAL_TAG_RE` / `DECIMAL_EPISODE_RE` match), the kind
  becomes `skip` ("Detected extras/specials marker").
- If the kind is `movie` and the label/title/`other` contains `sample`, **or**
  the file is smaller than 150 MB, the kind becomes `skip` ("Detected sample
  file").

## Known-good examples (kept in the corpus)

- `[RlsGrp] Show - S01E02.mkv` → series, S01E02.
- `NCED1`, `NCOP2`, `OP1`, `ED3`, `SP01`, `SP02` → skip (numbered extras).
- `S01E01` with `Opus 2.0` / `DDP2.0` → series (codec decimals must not skip).
- `spider.mkv`, `space.mkv` → not skipped by `sp`.
- `2.5.Crumpled.Staircase.2021.S01E01...` → series, title `2.5 Crumpled
  Staircase (2021)` (leading decimal is a title prefix, not an episode).
- `[RlsGrp] Nimbus 7_9 (2020) (Season 02) ...` → series, title `Nimbus`,
  season 2 (numeric junk `7_9` must not win over the clean title).
- `4.The.Conclusion.mkv` in a show folder → series, episode 4.
- `3 Idiots (2009).mkv` in a `3 Idiots (2009)` folder → movie (movie-title
  folder guard).

## Notes

- `_extract_series_from_source` cleans the container folder name: strips
  leading `[Group]` brackets, trailing group tags (`- RlsGrp`), tech tags
  (`1080p`, `x265`, `Dual Audio`, …) and season markers.
- `_is_fuller_title` requires the parsed title words to be a subset of the
  container words and the container to be longer, and rejects containers whose
  extra words are non-year numbers (that's the junk the folder won with).
- Keep pattern fixes here in the existing sections; see `AGENTS.md` for the
  documented pattern-fix history.
