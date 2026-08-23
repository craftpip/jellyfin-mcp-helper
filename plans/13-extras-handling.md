# 13 — Handle Show Specials & Movie/Show Extras (instead of skipping)

> **Current:** `app/services/classifier.py:12` `EXTRA_MARKERS` (`special|sp|ova|ona|extras|bonus|recap|trailer…`) + `S00` causes `kind=skip`. JellySort ignores them — user must move specials/extras by hand.

> **Goal:** Detect specials/extras, classify them as `extra` (not `skip`), and move them to the correct Jellyfin location: `Show/Season 00` or `Show/Specials` for series specials, and `Movie (YEAR)/{extras-type}/` or `Movie -trailer` for movie extras.

---

## 1. Angles

### 1.1 What counts as an “extra”

* **Series specials:** File or folder name contains `S00E01`, `SP01`, `special`, `ova`, `ona`, `episode 0`, or folder `Season 00` / `Specials`. Already matched by `SPECIAL_TAG_RE` / `DECIMAL_EPISODE_RE` etc. — we just change the outcome from `skip` to `extra`.
* **Movie/Show extras with suffix:** Jellyfin docs list suffixes that are handled in-place: `-trailer`, `-behindthescenes`, `-deletedscene`, `-featurette`, `-interview`, `-short`, `-other`, `-extra`, `-scene`, `-clip`, `-behindthescenes`, plus single-file names `trailer.mp4` / `sample.mp4` in the same folder.
* **Movie extras folders:** Torrent is a folder named like `Movie (2021) [Extras]` or contains subfolders `trailers/`, `behindthescenes/`, `deleted scenes/` — the folder name itself carries the extra type.

### 1.2 Where they go (per your answers: single `extras` folder, Jellyfin spec for season)

* **All extras & specials — single folder:** Per your answer “only one folder `extras`”, every file we detect as `extra` or `special` (and anything we can’t classify) goes to **`Show Name/extras/`** for series and **`Movie (YEAR)/extras/`** for movies — we do **not** flatten into typed subfolders (`trailers/`, `behindthescenes/` etc.) and we do **not** create `Season 00` for them. This keeps it simple as you asked: one `extras` folder per show/movie holds everything.
* **Season-specific extras (answer 2: “Do as Jellyfin says”):** Jellyfin says a *single* `trailer.mp4` can live as `Show/Season 01/trailer.mp4`, but since you want a single `extras` folder, we will still send it to `Show/extras/` — Jellyfin will pick it up as a show extra, not a season extra. If you later want per-season, we can split.
* **No flattening (answer 3):** The torrent’s internal structure is preserved under `extras/` — e.g. `Movie (2021) [Extras]/Featurettes/making.mkv` → `Movie (2021)/extras/Featurettes/making.mkv` (or just `Movie (2021)/extras/making.mkv` if you prefer flat — we’ll keep the relative path under `extras/`).

### 1.3 Classification change

* Add new `ItemKind = "extra"` (or reuse `skip` with a flag — but a distinct kind is cleaner for the UI and history).
* `_looks_like_extra` stays as the detector, but instead of `kind = skip` it sets `kind = extra` with `confidence 0.85` and `reason = "Detected extras/specials marker"`. Keep the `skip` for true junk (`sample` files < threshold, etc.) separate.
* New helper `_extra_type(label)` → `trailer | behindthescenes | deletedscene | featurette | interview | short | other | special` based on which marker matched. This drives the target.

### 1.4 Target resolution

* **Series extra →** `show_dir / Season 00 / f"{show} - S00E{NN:02d}{ext}"` — episode number comes from `S00E` in the name, or if none, assign the next available `S00E` by scanning `Season 00` for existing `S00Exx` files and using `max+1`. If the torrent is a season pack of specials, keep them together in `Season 00` with sequential numbers.
* **Movie extra with folder type →** `movie_dir / {extra_folder} / filename` where `extra_folder` is the detected type (`trailers`, `behindthescenes`, etc.). Create the subfolder.
* **Movie extra with suffix →** Keep the suffix in the filename and leave it in `movie_dir` (no subfolder needed). The resolver should not strip `-trailer` etc.
* **Fallback:** If we can’t determine the extra type, treat it as `other` → `movie_dir/extras/` or `show_dir/Season 00/` with a descriptive name.

### 1.5 UI

* **ReportPanel:** New `extra` badge (e.g. purple) alongside `move`/`replace`/`skip`. Extras show in the actionable list, not in “Skipped”. The target path will clearly be `.../Season 00/...` or `.../trailers/...`.
* **History:** `extra` is a separate `item_type`, so the `pathHistory` and undo still work.
* **Logs:** `reason` will say which marker triggered it.

### 1.6 Edge cases

* **Mixed torrent with main + extras in one folder:** The scanner will produce two items for the same source folder — one `series`/`movie` and one `extra`. They will be two groups (by source folder they’d be together today, but with the new `extra` kind they may need to stay together or be split — we will keep them in the same source-folder group, but the UI will show the `extra` badge so the user can see).
* **Sample files:** Keep `sample` as `skip` (not `extra`) — they are not real extras to keep, and the `SAMPLE_SIZE_THRESHOLD` guard stays.
* **Existing “skip” for specials in corpus:** Update `tests/corpus/download_paths.json` obfuscated entries and the underscore-junk test to expect `extra` instead of `skip` for those markers.

---

## 2. Implementation Steps

1. **Schemas** `app/models/schemas.py` — add `ItemKind = "extra"` and `extra_type: str | None` to `ClassificationResult` and `ScannedItem` (alias `extraType`).
2. **Classifier** `app/services/classifier.py` — change `_looks_like_extra` branch from `kind=skip` to `kind=extra` + set `extra_type`; add `_extra_type()` helper. Keep `_looks_like_sample` as `skip`.
3. **Resolver** `app/services/resolver.py` — add `_resolve_extra` that builds `show_dir/extras/filename` or `movie_dir/extras/filename` (preserving the torrent’s internal `relative_path` under `extras/`). No per-type subfolders, no `Season 00` numbering for extras — just `extras/` as you asked.
4. **Presenters** `app/services/presenters.py:format_report_items` — include `extraType` in the returned dict and handle `extra` alongside `move`/`replace` for the report.
5. **UI** `ReportPanel.jsx` — add a third badge style for `extra`, include it in the actionable counts and filter chips, and show the target as `.../extras/...` so it’s obvious.
6. **History** — no schema change needed; `extra` is just another `item_type` that gets a `pathHistory`.
7. **Tests** — update `tests/test_classifier.py` (expect `extra` for `SP01`, `NCOP1`, etc.), add a new test for a movie `-trailer` file, and add a resolver test for an extra target.

---

**Status:** Ready — answers 1-5 incorporated (all extras → single `extras/` folder, no flatten, Jellyfin spec for season, update tests). Awaiting your `go`.
