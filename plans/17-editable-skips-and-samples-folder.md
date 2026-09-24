# 17 — Editable skips + Jellyfin-native `samples/` routing (only in-progress/missing/error stay locked)

> **Status: IMPLEMENTED 2026-09-23 — backend 470 passed, frontend 165 passed.**

## Goal

Today every `action == "skip"` report row is non-editable: no target editor, no
Browse, no Update Paths / Confirm — only **Delete**. Any classifier mistake
(size-heuristic sample, low-confidence guess, dup collision, exists+no-replace)
leaves the file stuck; the user can only delete it.

Change it so **only truly unmovable rows stay locked** (in-progress, source-missing,
error/zero-byte). Every other skip becomes **editable like an extra**: it gets a
proposed target, can be re-pointed via Update Paths / Browse, and confirmed once
it resolves to `move`/`replace`. Sample-marker files additionally get a
Jellyfin-native **`samples/`** target (flat, filename only) instead of an empty
target.

User-confirmed decisions:
1. Sample folder = whatever Jellyfin respects (researched below → `samples/`).
2. Locked = in-progress + source-missing + error (zero-byte counts as error).

## Jellyfin research (what Jellyfin respects for samples)

Sources: `jellyfin.org/docs/general/server/media/movies`,
`.../media/shows`, `ExtraTests.cs` / `FindExtrasTests.cs` (naming lib).

- **Folder rule (directory wins over filename):** a subfolder named `samples`
  inside the movie folder / series folder (tests also cover season level)
  resolves every file in it as `ExtraType.Sample`, regardless of filename
  (`TestDirectoriesVideoExtras`: `InlineData(ExtraType.Sample, "samples")`).
- **Filename rule:** bare `sample.mp4` next to the feature resolves as Sample.
- **Suffix rule:** `-sample` / `.sample` / `_sample` / ` sample`
  (`TestSample`: `300-sample.mp4`, `300.sample.mp4`, …).
- Supported sibling folders (same mechanism): `behind the scenes`,
  `deleted scenes`, `interviews`, `scenes`, `shorts`, `featurettes`, `clips`,
  `trailers`, `extras`/`other` (generic catch-all), `theme-music`, `backdrops`.
- Series extras live at **show level** (`/series/Dexter/trailer.mkv`,
  `/series/Dexter/trailers/trailer2.mkv` in `FindExtrasTests`) — same level our
  current `extras/` uses. Season-00 specials are a separate (metadata-provider)
  concept, not file-extra detection — out of scope.

**Consequence:** route sample-marker files flat into
`<Movie>/samples/<file>` / `<Show>/samples/<file>` (filename only, same flat
rule as plan 16's `extras/` flattening). Do NOT reuse `extras/` for them —
Jellyfin types them `Unknown` there instead of `Sample`.

## Current behavior (evidence)

- `app/classification/kinds.py:80` — `_looks_like_sample` = `sample` marker in
  label/title/other **OR** `file_size < SAMPLE_SIZE_THRESHOLD` (150MB,
  `app/core/constants.py:32`). `classifier.py:160` forces `kind = "skip"` for
  movies only, reason `"Detected sample file"`.
- `app/services/scan_orchestrator.py:519-545` — `kind == "skip"` or low
  confidence → `ScannedItem(item_type=kind, target_path="", action="skip")`.
  Same empty-target shape for in-progress (`:452-473`), zero-byte (`:475-500`),
  revision-dedup (`:554-609`), exists+no-replace (`:688-693`), source-missing
  (`:738-749`), exception (`:710-725`).
- `app/services/retarget.py:199-200,243-244` — `update_scan` + `retarget_item`
  **400 on any skip** (`item.action == "skip" or item.item_type == "skip"`).
- `app/services/presenters.py:223-237` — skip payload drops `targetPath`,
  `candidateTargets`, `flags`, `suspect`, `corrected` (frontend can't render
  editors even if it wanted to).
- `app/ui/react/src/components/ReportPanel.jsx:320-364` — skip row = badge +
  reason + **Delete only**. `ReportGroup:225,268` — all-skip groups get only
  "Delete Selected". `utils/report.js:138-157` maps skips without target;
  `:356` default-selects only `action !== 'skip'`. `AppStore.jsx:744-750`
  confirm/update selections skip-filter the same way.
- `app/ui/react/src/api/types.ts:7` — `ItemKind` lacks `"extra"` (already
  drifted from backend `ItemKind` in `schemas.py:9`).

## Proposed behavior

### 1. Split sample detection: marker-based vs size-only

`kinds.py` / `classifier.py` (backend, placeholder names only):

- **Marker-based** (`sample` word in label/title/other, same `SAMPLE_MARKERS`):
  stays non-movie, but becomes routable instead of bare `skip` — new
  `extra_type = "sample"` on an `extra`-kind result
  (`_extra_type` gains a `sample` branch first, before `trailer`, since it is
  the most specific signal). Reason e.g. `"Detected sample extra"`.
- **Size-only** (no marker, just `< 150MB`): do NOT force `skip` anymore.
  Keep `kind = movie` (or whatever inference said) and flag `suspect = True`,
  `flags = ["small-file-sample-suspect"]`, reason notes the heuristic. A real
  145MB movie stays a confirmable movie; a real sample the user recognizes can
  still be browsed to `samples/`.
- Resolver `_resolve_extra` routes `extra_type == "sample"` to
  `<show|movie>/samples/<filename>` flat (mirrors the `extras/` branch, different
  dirname). All other extra types keep `extras/`.

### 2. Locked vs editable skips — explicit flag, not reason-sniffing

Add `ScannedItem.locked: bool = False` (alias `locked`, default False so old
payloads parse). Set `locked=True` at creation **only** for:

| producer | reason today | locked |
| --- | --- | --- |
| in-progress marker | `"In-progress download"` | ✅ |
| zero-byte | `"Zero-byte file…"` | ✅ (error class) |
| source missing (incremental) | `"Source missing on disk"` | ✅ |
| exception | `"Error: …"` | ✅ |
| sample-marker extra, low-confidence, dup-collision, exists+no-replace | various | ❌ editable |

Low-confidence skips and dup-collision skips **get a resolved target** at scan
time (run them through the resolver like any actionable item; low-confidence
keeps `suspect=True`). Exists+no-replace keeps its computed target. So every
unlocked skip carries a usable `target_path` + `candidate_targets`.

`update_scan` / `retarget_item` guard changes from
`action == "skip"` to `locked`: locked → same 400 as today; unlocked skip →
allowed. After any target change, `refresh_item_after_target_change` already
recomputes `move`/`replace` from existence — so saving an edit (or Browse
retarget) naturally promotes the row to actionable; no separate "unskip" call.
Confirm path (`scan_manager`/`move_executor`) accepts items whose live action
is `move`/`replace` regardless of origin.

Extra→movie/series reclassification: `apply_retarget`'s else-branch currently
assumes series. Extend `effective_type` so an explicit user pick (Browse to a
movie dir = `reclassify_as_movie`, Browse to a show dir = series) wins over
`item_type == "extra"`, letting a misrouted sample be corrected to a real
movie/episode and vice versa.

### 3. Frontend — editable skip rows

- `utils/report.js`: pass through `targetPath`, `candidateTargets`, `flags`,
  `suspect`, `corrected`, `locked`, `extraType` for skips (same fields as
  actionable). Add `isLockedItem(item)` helper (`action === 'skip' && locked`).
- `ReportPanel.jsx`: skip row branches — locked keeps today's Delete-only row;
  unlocked renders the full actionable row chrome (shared `TargetPathEditor`,
  Browse button, badges, per AGENTS.md row-sync rule). `ReportGroup`: a group
  containing any unlocked item gets Update Paths / Confirm (not Delete
  Selected); fully-locked groups keep Delete Selected.
- `AppStore.jsx`: selection/confirm/update-paths include unlocked skips
  (`action !== 'skip' || !locked`). Default-checked set includes unlocked skips
  (they are actionable proposals now).
- `api/types.ts`: `ItemKind` gains `"extra"` (matches backend); add `locked?`.
- Counts: unlocked skips still count as `skipped` until the user saves an edit
  that flips them to `move`/`replace` (single source of truth stays backend
  `scan.counts`; no frontend recount).

### 4. What does NOT change

- In-progress detection (filesystem markers, `scanner.py`) untouched.
- Locked rows: no editor, no Browse, no confirm — Delete only, exactly as today.
- Already-persisted scans: old skip rows have no target/`locked` flag and stay
  as-is; a **fullRescan** re-resolves them into the new shape (incremental
  preserves verbatim, same rule as every re-classification change).
- `samples/` creation happens at move time (`move_executor` mkdir parents),
  never during browse/resolve (read-only browse rule stands).

## Files to change

| File | Change |
| --- | --- |
| `app/classification/kinds.py` | marker vs size split helper; `_extra_type` gains `sample` branch |
| `app/classification/classifier.py` | marker-sample → `kind=extra/extra_type=sample`; size-only → keep kind + suspect flag |
| `app/models/schemas.py` | `ScannedItem.locked: bool = False` |
| `app/services/scan_orchestrator.py` | set `locked` per table; resolve targets for unlocked skips (low-conf, dup, exists) |
| `app/services/resolver.py` | `extra_type == "sample"` → `<show\|movie>/samples/<file>` flat |
| `app/services/retarget.py` | skip-guard → locked-guard; `effective_type` covers extra→movie/series correction |
| `app/services/presenters.py` | skip payload passes target/candidates/flags/locked through |
| `app/ui/react/src/utils/report.js` | passthrough + `isLockedItem` |
| `app/ui/react/src/components/ReportPanel.jsx` | locked Delete-only vs unlocked full row; group toolbar rule |
| `app/ui/react/src/store/AppStore.jsx` | selections/confirms include unlocked skips |
| `app/ui/react/src/api/types.ts` | `ItemKind` + `locked` |
| `tests/test_classifier.py`, `test_resolver.py`, `test_scan_errors.py`, `test_ui_api.py` | marker→samples target; size-only→movie+suspect; locked-guard; retarget promotes skip→move |
| `app/ui/react/.../ReportPanel.test.jsx?`, `report.test.js` | locked vs editable row cases |

## Verification

1. `docker exec jellysort python3 -m pytest tests/` — backend green (new: sample-marker
   file lands `<Show>/samples/<file>` flat; 100MB unmarked movie stays
   movie+suspect; locked rows 400 on retarget, unlocked promote to move).
2. `cd app/ui/react && npm test` — frontend green (locked row = Delete only,
   unlocked row = editor+Browse).
3. Manual (fullRescan): seed a `sample`-named file + a sub-150MB real movie +
   an in-progress (`*.mkv.!qB`) file. Sample proposes `samples/` (editable,
   confirm moves it); small movie proposes its movie target with suspect flag;
   in-progress row stays locked, Delete-only. Browse an unlocked skip to another
   library → target/action update, Confirm moves it.
4. After green: `npm run build` + `docker restart jellysort`, re-grep that no
   real media names leaked into code/tests (AGENTS.md obfuscation rule).
