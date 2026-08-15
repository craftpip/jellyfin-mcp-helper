# 06 — Failed-Classification Detection + Smart Correction + Target-Folder Dropdown

> **Status: PLANNED** — not yet implemented. **Blocked:** Dugil will not execute until
> the open questions at the bottom are pinned down and the owner approves.

Owner request (three-part):

1. **Detect failed scans / failed classifications** in the report. Two concrete
   failures were found in a real scan:
   - A long-running franchise series, Season 21: the report shows every S21
     episode "matched" a franchise folder, yet the show folder does not exist,
     the season folder does not exist, and there are no prior seasons (20, 19,
     …) in it. That is a phantom match, i.e. a failed resolution.
   - A franchise **movie** ("… Movie 05 …") was classified as a **series**
     episode (S01E05) with no preceding episodes and no show folder.
   - General rule the owner wants encoded: *an episode being scanned must have a
     previous episode* (on disk or in the same scan plan) — users do not
     deliberately download episodes from the middle of a season. Detect every
     item that violates this.
2. **Make smart moves to fix it.** If a series was "matched" to a non-existent
   or wrong folder, there is almost certainly a *real* folder for the same
   series elsewhere on the library. Find it and re-target there instead of the
   phantom/wrong folder.
3. **Report every candidate target destination** that was considered during
   resolution, so the UI can present them as a dropdown and the user can pick
   the target folder by hand when auto-detection is unsure.

Names in this plan are obfuscated per the corpus rule. The real franchise is
referenced as **Nimbus** (long-running, 21+ seasons, accented library folder).

---

## Research / current state (verified)

### Live scan facts (in-memory scan in container `jellysort`, ~Aug 15)

- 137 candidates → 15 movies, 109 series, 18 skipped, 124 actionable.
- **108 of 109 series items resolve with `showFolderExists=False`** — the
  resolver is broadly failing to match existing library folders, not just this
  one franchise. Only 1 series item matched an existing folder (a release whose
  source container folder name happened to equal the target folder name).

### Case 1 — franchise series S21 (phantom show folder)

- 103 items target the phantom path
  `/mediaX/series/Nimbus/Season 21/{Episode Title} - S21E01..E13.mp4` with
  show/season/file all `✗`.
- The **real** library folder exists:
  `/mediaX/series/Nimbus Pocket Monsters (1996)/` containing
  `s01 - <subtitle>` … `s21 - Midnight Ultra Journeys` (all 21 seasons).
- Matching fails for three independent reasons:
  1. **Diacritics break tokenization.** `tokenize("Nimbus")` gives `{nimbus}`,
     but the real folder's first word contains an accented char, so
     `tokenize("Nimbús …")` → `{"nimb", "us"}` — zero overlap with the title.
     Both `_pick_exact_path_match` (resolver.py:361) and
     `_shortlist_target_paths` (resolver.py:394) *skip the folder before any
     scoring* when the token intersection is empty. The real folder never
     enters the shortlist.
  2. **Long folder names.** Exact normalized-name equality fails ("Nimbus
     Pocket Monsters (1996)" ≠ "Nimbus"); the token-subset path that would
     rescue it is gated behind the token-overlap check above.
  3. **Alternate season-dir naming.** The library uses `s21 - Midnight Ultra
     Journeys`. `season_dir_candidates` / `_pick_existing_season_dir`
     (resolver.py:73, 512) only accept *exact* normalized names (`season 21`,
     `s21`, …). Even a correctly matched show folder would spawn a brand-new
     `Season 21` subfolder instead of joining the real one.
- The phantom then **propagates through in-scan memory**: the first S21
  candidate creates `/mediaX/series/Nimbus/Season 21` in
  `_series_path_memory` (resolver.py:216-218) and the other 102 items "match"
  it via `_lookup_series_path` (resolver.py:211-214) although nothing exists on
  disk.

### Case 2 — franchise movie classified as series S01E05

- `[Grp] Nimbus Movie 05 Nimbus Heroes [1280x688_Blu_Ray_Dual_Audio][…].mkv`
  inside `/torrents/Nimbus Movie 05/` is classified as **series**,
  `title="Nimbus Movie"`, `episode=5`, reason `Matched episode pattern`
  (classifier.py:444-445), phantom target
  `/mediaX/series/Nimbus Movie/Season 01/Nimbus Heroes - S01E05.mkv`.
- `guessit` on the label yields `type=episode, title="Nimbus Movie",
  episode=5, episode_title="Nimbus Heroes"`. Same shape for
  `… the Movie 11 - <subtitle> …` → S01E11.
- Compare: `Nimbus Movie 3` (no zero-pad, no subtitle token) is **correctly**
  classified as a movie. The zero-padded `05`/`11` digits are the trigger.
- Same family also lands as series: `S21M01` / `S22M01` special/movie releases
  (guessit: `type=movie`, title contains `S21M01`).

### Existing building blocks that make the fix cheap

- `_shortlist_target_paths` (resolver.py:372) already scores **all** series
  folders and returns the top 20; only the single winner surfaces via
  `_best_path_match` (resolver.py:436). The candidate list already exists — it
  is just never returned.
- `update_scan` (scan_manager.py:437) + `PATCH /api/scans/{scan_id}/items`
  (server.py:339) already let a client change an item's target path and
  recompute exists/action flags.
- Report items already carry `showFolderExists/seasonFolderExists/fileExists`
  (presenters.py:79-110); the LLM instructions already tell the LLM to redirect
  wrong paths via the update tool (presenters.py:132-146).
- React rows already render the target path via `PathPills` (ReportPanel.jsx);
  `computePathSync` (report.js) syncs target edits across a title group.

---

## Design decisions

### Detection

- **D1 — Per-series-item continuity signals.** For every series item compute a
  verdict from three signals and set `suspect=True` when any fires:
  - `phantom_show_folder` — resolved show dir does not exist on disk
    (`show_folder_exists=False`) **and** `existing_match is None` (the
    "match" came from in-scan memory or a brand-new path). A brand-new S01E01
    of an unknown show is **not** suspect by itself; see D3.
  - `season_gap` — show dir exists but has **no** season folder `season-1`
    (target S21 with no s20, or no seasons at all) **and** `season-1` is not
    planned earlier in the same scan (see D2). Direct continuation (season-1
    present, or planned in this scan) is fine. This keeps a new two-season
    download (S21+S22, neither on disk yet) from flagging S22.
  - `episode_gap` — `episode > 1` and episode `episode-1` exists **neither**
    on disk in the target season dir **nor** is planned earlier in the same
    scan (see D2). Episode 1 of any season is never a gap.
- **D2 — Coverage includes the in-scan plan.** `scan_manager` maintains
  `planned_episodes: dict[(series_key, season), set[int]]` **and**
  `planned_seasons: dict[series_key, set[int]]`, fed as items are planned, plus
  on-disk coverage from the target show/season dirs. So a batch download
  (S21E01..E13 in one scan) does **not** flag E05 or S22 — earlier episodes and
  the previous season are planned. **In-progress (skipped) downloads are always
  skipped and do NOT count as planned coverage** — they are skipped before
  classification (`scan_manager.py:206-223`) and excluded; no attribution work
  is done for them (resolved per user directive).
- **D3 — Suppress false positives for genuinely new shows.** Only flag when the
  item looks like a continuation: `phantom_show_folder` alone is not enough —
  require `season > 1` **or** `episode > 1`. A fresh S01E01 with no folder
  anywhere stays clean.
- **D4 — Group-level detection.** Because the phantom propagates via in-scan
  memory, flag and correct at the **series_key group** level (all items sharing
  normalized title + year), not just per item. Detection output per group:
  `has_phantom`, `max_target_season`, `has_prior_season_in_any_candidate`.

### Correction (smart moves)

- **C1 — Diacritic folding (root cause fix).** Add a diacritic fold to
  `normalize_text` / `tokenize` (resolver.py:30-40) so `Nimbús` ≡ `Nimbus`.
  Precedent: the apostrophe strip already normalizes punctuation globally. This
  single change lets the real folder pass the token-overlap gate and enter the
  shortlist, fixing the case-1 group.
- **C2 — Alternate season-dir naming.** `_pick_existing_season_dir` accepts a
  dir when its normalized name **starts with** a valid season token
  (`s21`, `season 21`) optionally followed by `- <subtitle>` text, e.g.
  `s21 - Midnight Ultra Journeys` → Season 21. Exact matches still win.
- **C3 — Name-independent matching signals (the "name is so different it never
  shows up" problem).** Matching cannot depend on the show name sharing tokens
  with the folder name. Four signals that don't require a name match at all:
  - **Season-arc subtitle (strongest for long-running franchises).** The
    release's season text (`Nimbus S21 Sun & Moon Ultra Adventures`) and a
    library season dir's name (`s21 - Sun and Moon Ultra Adventures`) both
    contain the arc `sun moon ultra adventures`. Normalize both (fold
    diacritics, `&`→`and`, drop filler words) and compare with
    `SequenceMatcher`; a match ≈ confirms the same show/season even with zero
    show-name overlap.
  - **Episode-title via library file aliases.** A library folder that already
    holds a file for the exact episode being downloaded is the show:
    `[AnimeRG] Pokémon - 0985 - A Dream Encounter!` shares
    `a dream encounter` with `Pokemon S21E01 A Dream Encounter`. Extend
    `series_aliases` to also extract post-number episode titles, and match
    against the classification's `episode_title` (and sibling items in the
    scan group).
  - **Year match.** Folder contains the release year (`(1996)`).
  - **Manual aliases.** `SERIES_TITLE_ALIASES` (already applied at
    classification time) stays as the explicit backstop.
- **C3b — Deep re-search with continuity evidence.** When a series item is a
  continuation (`season > 1` or mid-season `episode > 1`) and the normal
  resolution produced a phantom, run `find_continuation_show(title, year,
  season, episode_title, roots)` across **all** series roots:
  - **Candidate set (recall tier):** folders matching by **any** of: normalized
    name equality, token subset, startswith/contains (after C1), **season-arc
    subtitle**, **episode-title alias**, or year. **No token-overlap gate** on
    this tier — a folder shares nothing with the show name but matches the arc
    or an episode title and must still appear.
  - **Auto-pick (precision tier):** a candidate must have at least one strong
    signal (arc match, episode-title match, or name subset) **plus** continuity
    evidence (season set contains `target_season - 1`, or the closest season
    below target). Empty/new folders are penalized.
  - **Ordering for both tiers:** arc/subtitle match → episode-title match →
    name-subset → year → bare fuzzy, so a franchise folder wins over a
    lookalike.
  - **Cost control:** cheap signals first (name tokens, year, season-number
    presence in the folder's season dirs); the `series_aliases` episode-title
    walk only runs on folders that already pass a cheap pre-filter (shared
    token, shared year, or a season dir for the target season), and stays
    capped (`rglob` by extension + break at ~12 samples) — never
    `sorted(rglob("*"))` (AGENTS.md resolver-hang lesson). **Assumption to
    note:** the season-arc signal depends on the *release* text containing the
    arc (e.g. `S21 Sun & Moon Ultra Adventures`); many anime releases only
    carry `S21E01 - <Title>` and the arc lives solely in the library season-dir
    name — in that case the arc signal is silent and episode-title alias + year
    carry the match. Keep arc matching recall-tier (never precision-tier alone).
  - If found: re-target the **whole group** to that show dir (join the real
    season dir via C2), set `existing_match`, `corrected=True`, note.
  - If not found: keep the new path but keep the item flagged with an explicit
    reason so the LLM/user can redirect.
- **C4 — Movie-marker reclassification.** When a release would be `series` via
  a bare/guessed episode number but the title or container folder carries a
  movie marker (`Movie <N>`, `the Movie <N>`) and there is **no explicit
  SxxEyy**, classify as **movie** instead: `kind=movie`, `season=None`,
  `episode=None`, title from the cleaned container folder name (or guessit
  title + number). Explicit `SxxEyy` always wins (keeps real TV safe).
- **C5 — Scan-scoped two-layer memory (no repeated disk scans).** The user
  directive: search memory, not disk, again and again. `_run_scan_sync` builds
  **once per scan** a disk index of existing target folders (movie + series
  roots via `list_target_paths`, currently re-listed for *every* candidate in
  `_resolve_series`/`_resolve_movie`) and hands it to the resolver. The
  resolver keeps `_series_path_memory` as a **planned-target memory**: it
  records the show dir we *decided to write to* (whether it exists on disk yet
  or not), so every episode of the same show group lands in the same target
  folder — exactly the current behavior, but now without re-listing disk per
  candidate. Lookup consults memory first, disk index second. The phantom
  flag does **not** depend on purging memory — it comes from comparing the
  remembered dir against the disk index: remembered but **not in the disk
  index** → `existing_match=None` → phantom signal fires (and the C3b deep
  search then finds the real folder, which *is* in the index). Genuinely new
  shows keep their deterministic path and are suppressed by D3. This makes the
  phantom self-healing instead of a memory bug.
- **C6 — Manual override clears flags.** Any change via `update_scan` (UI edit
  or LLM update tool) resets `suspect`/`flags`/`corrected` on that item — the
  human/LLM has taken over.

### Report + UI (owner's dropdown idea)

- **D5 — Report carries every candidate target.** `ResolvedTarget` gains
  `candidate_targets` (top-N scored destinations, including the default "new
  folder" one and, for movie-marker suspects, an "as movie" destination). It
  flows to `ScannedItem` → `format_report_items` (new `candidateTargets`
  field) **and** into `format_report_md` (compact per-row list) and the LLM
  report instructions. Each candidate: full target file path + label + evidence
  (e.g. `existing folder — has s01–s20`, `new folder`, `reclassify as movie`).
  Below-threshold candidates are included so the user can deliberately override
  (they may know better than the score).
- **D6 — UI dropdown for the target folder.** `ReportRow` renders a
  `<select>` when `candidateTargets.length >= 2` (hidden when only one option,
  keeping the report clean). Picking an option PATCHes
  `targetPath` via the existing items API, then refreshes the report; the
  flag is cleared per C6. For suspect rows the selector is expanded with a
  warning badge and the evidence labels. Selecting the same base folder on one
  row offers to sync the rest of its title group (reuse `computePathSync`).
- **D7 — Directory browser as the manual escape hatch.** When candidates are
  empty, thin, or the user simply disagrees with all of them, a "Browse…"
  control opens a modal that lets the user navigate the configured movie/series
  roots and pick any folder. The browser is **root-constrained**: only
  directories under a configured movie or series root are listable/selectable —
  mirrors the `update_scan` allowed-roots validation. No absolute escape, no
  `..`, no symlinks out of root; hidden dirs and `.trickplay` are skipped.
  Selecting a folder re-targets the item **server-side** (filename + season
  handling recomputed by the backend, never hand-assembled by the client) and
  optionally applies to the whole series group.

---

## Parts

### Part A — Diacritic folding + name-independent signal extraction (`app/services/resolver.py`)

1. `fold_diacritics(value)` (NFD + strip combining marks, or an explicit map)
   applied inside `normalize_text` (and therefore `tokenize`,
   `normalize_series_text`). Update the apostrophe test to also cover
   `"Nimbús" == "Nimbus"`.
2. Signal extractors (pure, unit-testable):
   - `season_arc_text(container_path, label)` → the release's season-arc text
     after the `S21`/`Season 21` marker (e.g. `sun moon ultra adventures`),
     with diacritic fold + `&`→`and` + filler-word drop.
   - `season_dir_arc(season_dir_name)` → the library side of the same
     (`s21 - Sun and Moon Ultra Adventures` → `sun moon ultra adventures`).
   - extend `series_aliases` to also yield post-number episode titles
     (`[AnimeRG] Pokémon - 0985 - A Dream Encounter!` →
     `a dream encounter`).
3. Re-verify the token-overlap gates now admit accented folders; the existing
   subset/startswith/contains scoring then does the rest. The candidate tier in
   Part F deliberately drops that gate.

### Part B — Alternate season-dir naming (`app/services/resolver.py`)

`_pick_existing_season_dir`: after the exact-name pass, accept a child dir when
`normalize_text(child.name)` starts with one of `season_dir_candidates(season)`
as a word boundary (e.g. `s21 - midnight ultra journeys` starts with `s21`).
Return the exact match first if present.

### Part C — Continuity detection (`app/models/schemas.py`, `resolver.py`, `scan_manager.py`)

1. `ScannedItem` gains: `suspect: bool = False`, `flags: list[str] = []`
   (values `phantom_show_folder | season_gap | episode_gap`),
   `corrected: bool = False`, `correction_note: str | None = None`.
2. `ResolvedTarget` gains: `phantom_show_folder: bool`, `has_previous_season:
   bool`, `max_existing_season: int | None`, `candidate_targets: list[...]`.
3. `_resolve_series` computes the disk-based signals and returns them.
4. `scan_manager._run_scan_sync` tracks `planned_episodes` per
   `(series_key, season)` and `planned_seasons` per `series_key` (derive
   series_key from the resolved title) and computes the final `episode_gap`
   (on-disk ∪ planned) and `season_gap` (on-disk ∪ planned). `update_scan`
   resets flags for edited items (C6).
5. **Build the disk index once per scan** (C5): `_run_scan_sync` lists
   existing movie/series root folders a single time and passes it to the
   resolver (`resolver.prepare_scan(paths)`), removing the per-candidate
   `list_target_paths` re-lists in `_resolve_series`/`_resolve_movie`
   (resolver.py:179-181, 121-123).

### Part D — Deep re-search + group re-target (`resolver.py`, `scan_manager.py`)

1. `PathResolver.find_continuation_show(...)` per C3b (cheap signals first,
   bounded alias walk, continuity tie-break, returns show dir or None).
2. Group pass at the end of `_run_scan_sync` (before
   `reset_runtime_state`): group series items by series_key; for each group
   with a phantom/wrong base, run the deep search; on success re-target all
   group items (target path, show/season exists, `existing_match`,
   `corrected`, `correction_note`) and update `planned_targets` keys.
   **Recompute `file_exists`/`action` during re-target** using the existing
   `s{ss}e{ee}`-tag match (`resolver.py:233-240`). Per user: Jellyfin reads
   all naming styles, so no need to map the folder's absolute `- 0985 -`
   numbering — a pre-existing absolute-numbered episode is treated as "not the
   same target" → "move" (open Q8).
3. Scan-scoped disk index + planned-target memory per C5 (built once per scan
   in `_run_scan_sync`; `_lookup_series_path` consults memory, then the index).

### Part E — Movie-marker reclassification (`app/services/classifier.py`)

1. Add markers:
   - `MOVIE_MARKER_RE = r"\bmovie[\s_.-]*\d{1,3}\b"` (and `the movie <N>`) —
     covers `Nimbus Movie 05 …`.
   - `FRANCHISE_MOVIE_MARKER_RE = r"\bs\d{1,2}m\d{1,2}\b"` — covers the
     `S21M01`/`S22M01` special/movie releases the research section names but
     the original marker missed (they currently stay series).
2. In `classify_candidate`, before `_infer_kind`: if there is **no explicit
   SxxEyy/season-episode token** (`has_explicit_episode` is False — note the
   `Nimbus Movie 05` case gets episode=5 from *guessit*, not from a bare-number
   regex, so the gate must be `has_explicit_episode is False`, not "came from a
   bare/guessed number") and the title or container folder carries either
   marker → force `kind="movie"`, `season=None`, `episode=None`, title from the
   cleaned container folder name (guard: only when the container is not the
   download root itself — `Path(container_path).name` on a root is
   `downloads`, which would corrupt the title; fallback: guessit title +
   number).
3. Keep explicit `SxxEyy` and movie-`<N>`-without-marker behavior unchanged.

### Part F — CandidateTargets plumbing (`resolver.py`, `schemas.py`, `presenters.py`)

1. `_resolve_series` / `_resolve_movie` build `candidate_targets` from the
   shortlist scores (cap ~5): existing folders (with continuity/arc/episode
   evidence labels) + default new-folder path; movie-marker suspects
   additionally get an "as movie" destination. **"As movie" is not a bare path
   change:** selecting it must also flip the item's `item_type` to `movie` and
   clear `season`/`episode` (report grouping, counts, and confirm all branch on
   `item_type`), so the retarget/reclassify payload carries a
   `reclassifyAsMovie` flag, not just a `targetPath`.
2. **The candidate tier uses the recall set from C3b — no token-overlap gate.**
   A folder that shares zero tokens with the show name but matches the
   season-arc subtitle, an episode title, or the year is still listed, so it
   can appear in the dropdown even when the show names diverge completely.
   Only the auto-pick keeps the precision gate. **Scope guard:** the
   gate-free recall tier applies **only to suspect continuation groups** (the
   C3b path), never to every series item — dropping the gate globally would
   re-introduce the `series_aliases` full-directory walk for every candidate
   (the AGENTS.md resolver-hang lesson). Non-suspect items keep the normal
   token-gated shortlist.
3. `format_report_items` emits `candidateTargets: [{path, label, evidence,
   source}]`; `format_report_md` adds a compact candidates list per series row;
   `report_llm_instructions` mentions suspect/corrected items and the candidate
   list.

### Part G — Manual target selection UI: browse + search + select (`app/ui/react/src/`, `app/ui/server.py`)

The primary manual surface is a **plain folder browser** over the configured
target roots (movie + series roots): navigate, **search** for a folder, click
to **select** it. The candidate dropdown (Part F) stays as a quick-pick above
it; "Browse…" is the full escape hatch when candidates are wrong, thin, or
absent.

Backend (`app/ui/server.py`, all behind `require_panel_auth`):
1. `GET /api/browse/roots` → configured movie/series roots with descriptions
   (kind-filtered to the item's type by default).
2. `GET /api/browse?path=<dir>` → shallow listing of a root-constrained dir:
   `{path, parent, entries: [{name, path, isDir, videoCount, seasonNumber}]}`.
   `videoCount` for a leaf/season dir = direct video children (capped ~500, no
   deep walk); for a **show-level dir** (children are subdirs, not files) count
   direct video children **recursively but capped** (or report season-dir
   count) — a "direct children only" rule shows `0 videos` on every show
   folder, which is misleading; `seasonNumber` detected from the dir name via
   the C2 token/arc rules; sort season-numeric then alpha; skip hidden dirs,
   `.trickplay`, and symlinks that resolve outside the root (resolve +
   `relative_to` check per `update_scan`).
3. `GET /api/browse/search?q=<text>` → folder-name search **across all
   roots** (normalized + diacritic-folded substring/token match), capped
   results (~50), each with full path + root + seasonNumber when it looks like
   a season dir. This is how the user finds `Pocket Monsters (1996)` even when
   the auto candidates never surfaced it.
4. `POST /api/scans/{scan_id}/items/retarget` `{confirmId, directory,
   applyToGroup?}` → server recomputes the full target: same filename base as
   the item's current target; if the chosen dir is show-level, join the
   matching season subdir (C2) or `Season {ss}`; validates the dir is under a
   configured root; reuses the `update_scan` recompute path (action/exists +
   flag reset per C6). Filename logic stays server-side — the client never
   assembles a target path. **Multi-season guard:** when `applyToGroup` is set
   and the group spans more than one season, the pick must be show-level (the
   server then joins each item's own season subdir); a season-level pick with a
   multi-season group is rejected (`400`) because it would force every item
   into one season dir.

Frontend:
1. `BrowseModal.jsx`: search box at top (fires `/browse/search`), a root
   selector chip row, breadcrumb path, parent `..` entry, folder rows with
   video count + season badge, and "Select this folder" / "Cancel".
2. `ReportRow`: a small "Browse…" button next to the target path (and a
   "Browse" entry at the bottom of the candidate dropdown). On select → POST
   retarget (with a "apply to N group rows" checkbox) → `fetchReport`.
3. Store: `retargetItem(confirmId, directory, applyToGroup)` action.

---

## Tests

Backend (`python3 -m pytest tests/`, via container):
- `test_resolver.py`: diacritic fold (`Nimbús Pocket Monsters (1996)` matches
  title `Nimbus`); `s21 - Midnight Ultra Journeys` accepted as Season 21;
  `_lookup_series_path` reuses a remembered planned dir within the same scan
  (update `test_resolve_series_reuses_first_planned_show_path_within_same_scan`);
  the scan-scoped disk index is built once and reused (no per-candidate
  re-list); `find_continuation_show` continuity tie-break (folder with s20
  beats folder with only s05); new S01E01 not flagged.
- `test_scan_errors.py` / new `test_scan_continuity.py`: episode-gap fires for
  lone S01E05, does **not** fire when E01-E04 are planned in the same scan or
  present on disk; season-gap does **not** fire for S22 when S21 is planned in
  the same scan; in-progress (skipped) items are excluded from planned coverage
  (a mid-batch scan where E01-E04 are in-progress still flags E05); group
  re-target moves all items to the found show dir and keeps `planned_targets`
  consistent; `update_scan` clears flags.
- `test_classifier.py`: `Nimbus Movie 05 Nimbus Heroes` → movie; `Nimbus Movie
  3` stays movie; explicit `SxxEyy` stays series.
- Corpus: refresh from a real scan, re-obfuscate (AGENTS.md rule), add the two
  new patterns (accented long folder name + `Movie 05` marker).
- `test_ui_api.py`: report items expose `candidateTargets`.
- New `test_browse.py`: browse listing is root-constrained (rejects
  `../`, absolute escape, out-of-root symlink); returns sorted entries with
  `seasonNumber` and capped `videoCount`; search finds `Nimbus Pocket Monsters
  (1996)` via normalized + diacritic-folded query even though the auto
  candidates didn't; retarget joins the matching season subdir for a show-level
  pick and keeps the filename base; retarget with `applyToGroup` updates every
  group row and clears flags.

Frontend (`cd app/ui/react && npm test`):
- `report.test.js`: `targetOptions` builds the option list; suspect model.
- `ReportPanel`/`App.test.jsx`: dropdown renders when `>= 2` candidates,
  selection PATCHes the new target and clears the flag.
- `BrowseModal.test.jsx`: renders roots + entries from a mocked
  `/browse` listing, search box fires `/browse/search`, "Select this folder"
  POSTs retarget and refreshes the report.

## Files touched

- `app/services/resolver.py` — diacritics, season-dir matching, continuity
  signals, deep search, memory trust, `candidate_targets`.
- `app/services/scan_manager.py` — `planned_episodes`, flags, group re-target,
  `update_scan` flag reset.
- `app/services/classifier.py` — movie-marker reclassification.
- `app/models/schemas.py` — `ScannedItem`/`ResolvedTarget` new fields.
- `app/services/presenters.py` — report fields + md + LLM instructions.
- `app/ui/server.py` — `/api/browse/roots`, `/api/browse`,
  `/api/browse/search`, `/api/scans/{scan_id}/items/retarget`.
- `app/ui/react/src/components/ReportPanel.jsx` — dropdown + suspect badge +
  "Browse…" button.
- `app/ui/react/src/components/BrowseModal.jsx` — new: browse/search/select
  modal.
- `app/ui/react/src/utils/report.js` — option/suspect helpers.
- `app/ui/react/src/store/AppStore.jsx` — `retargetItem` action.
- `tests/…`, `tests/corpus/download_paths.json`, frontend tests.

## Implementation order

1. Parts A + B (root-cause matching fixes) → verify on the live scan: the
   Nimbus S21 group must resolve into the real folder with all 13 episodes.
2. Part C (detection signals + report fields) → verify the report flags.
3. Part D (deep search + group re-target) → verify auto-correction.
4. Part E (classifier movie-marker) → verify the two movie cases.
5. Part F (candidateTargets) → verify report lists candidates.
6. Part G (UI dropdown + browse) → verify dropdown select → PATCH → refresh;
   verify BrowseModal: search jumps to a folder, selecting re-targets with
   season join and group apply.
7. `python3 -m pytest tests/` + `cd app/ui/react && npm test`; corpus refresh
   + obfuscation; per AGENTS.md: `docker compose build && docker compose
   restart`, re-verify edited files after restart (filesystem rollback hazard).

## Rollout / verification

1. Rebuild + restart, run a scan: the Nimbus S21 items land in
   `/mediaX/series/Nimbus Pocket Monsters (1996)/s21 - Midnight Ultra Journeys`
   (join, not a new folder); `showFolderExists`/`seasonFolderExists` show ✓.
2. `Nimbus Movie 05 …` and `… the Movie 11 …` are movies (or flagged + offered
   the "as movie" candidate); no phantom `/mediaX/series/Nimbus Movie/Season
   01/` group.
3. Report md/items include `candidateTargets`; the LLM report names suspect/
   corrected items; the UI shows the dropdown on items with alternatives and a
   warning badge on suspect rows.
4. Pick a different folder in the dropdown → PATCH applies, flags clear, row
   refreshes; group sync reuses `computePathSync`.
5. Confirm + move a mixed batch; Jellyfin library scan still fires
   (scan_manager.py:931); report counts stay correct.

## Open questions — must be pinned down before execution

1. **File-naming style inside the real folder.** **RESOLVED (user):** keep the
   resolver's `{Episode Title} - SxxEyy` style. **Jellyfin is the target and
   reads all naming styles** — getting the file into the correct folder matters,
   matching the folder's existing `- 0985 -` style does not. Folder correctness
   is the goal; naming-style adoption is out of scope.
2. **Movie reclassification title.** For `Nimbus Movie 05 Nimbus Heroes`,
   use the cleaned container folder name (`Nimbus Movie 05`) or guessit
   title + number (`Nimbus Movie 5`)? Recommend folder name. Also: auto-
   reclassify when the marker is present, or only flag + offer the "as movie"
   candidate in the dropdown?
3. **Gap strictness.** Season gap = "no `season-1` exists" (recommend). Episode
   gap = "`episode-1` missing on disk and in plan" (recommend). Should a
   *partial* earlier set (e.g. only E03 exists for E05) still flag? Recommend
   yes (flag), since E01/E02 are missing.
4. **Candidate cardinality & threshold.** Cap candidateTargets at 5 (recommend)
   and always include below-threshold candidates (recommend) so the user can
   override.
5. **In-progress downloads as coverage.** **RESOLVED (user):** always skipped,
   never counted as planned coverage.
6. **Diacritic folding scope.** Global in `normalize_text` (recommend, matches
   the apostrophe precedent) vs only in candidate matching. Global changes
   every matcher; corpus must be re-verified.
7. **Auto-correction scope.** Apply the deep-search re-target automatically
   (recommend, still flagged for review since confirm is manual) vs only
   propose it as the top candidate for the dropdown.
8. **Absolute-number → (season, episode) mapping.** **RESOLVED (user):**
   naming style is irrelevant — Jellyfin reads all styles; the target is
   Jellyfin. So replace/move detection just uses the existing `s{ss}e{ee}` tag
   match (option b): a pre-existing absolute-numbered file is treated as "not
   the same target" → "move". If that ever yields duplicate episodes in
   Jellyfin, revisit with per-season off-by-N mapping as a follow-up — not
   blocking.
9. **Report size with candidateTargets.** Each series row gains up to 5
   candidate paths + evidence; a 100+ row scan report could balloon (LLM
   context + md). Recommend capping md to the top 2 candidates per row, full
   list only in `items[]`/dropdown. Confirm.
10. **Browse multi-season group pick.** **DECIDED:** season-level pick with
    `applyToGroup` on a multi-season group is rejected (400) — the pick must be
    show-level so each item joins its own season.
