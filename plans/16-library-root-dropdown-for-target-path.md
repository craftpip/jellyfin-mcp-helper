# 16 — Library-root dropdown + remainder input for target paths

> **Status: IMPLEMENTED 2026-09-23 — frontend 149 passed, backend 453 passed, rebuilt + restarted.**
>
> Follow-up (same day): single-input look — the group carries the input
> chrome, select + input share the same monospace 0.78rem type, no ellipsis
> truncation (group scrolls horizontally), only a subtle `▾` affordance on
> the prefix. Dropdown width is dynamic (`calc(<chars>ch + 10px)` on the
> monospace type). Rebuilt + restarted.
>
> Follow-up: live path-status — `GET /api/browse/exists?target=&kind=`
> (`server.py`, read-only, reuses `refresh_item_after_target_change` +
> `format_path_exists` so pills preview exactly what Update Paths would
> record). `TargetPathEditor` takes `onCommit(fullPath)`, fired on text blur
> and right after a dropdown change. `AppStore.refreshPathStatus` (report,
> with seq race guard + `_statusCheckedFor` dedup) and HistoryPage-local
> `refreshHistoryPathStatus` update the `path-status` pills in place.
> Frontend 152 passed, backend 455 passed, rebuilt + restarted.

## Goal

In the report, each row shows `Source path` and an editable `Target path`
(free-text input today). The user wants the **prefix** of the target — the
library root (e.g. `/mnt/media1t/downloads/movies`, `/mnt/media2t/downloads/series`,
…-r variants) — to be a **dropdown**, while the rest of the path stays a
free-text input. Both controls render as **one joined group** per row.
The dropdown lists **all configured library paths** (movie + series roots).

Full customizability is preserved: dropdown swaps the prefix, the text input
edits everything after it.

## Current behavior (evidence)

- `app/ui/react/src/components/ReportPanel.jsx:409-423` — single
  `<input class="target-input" value={liveTarget}>` bound to the full target
  path; `onTargetInputChange(item._idx, e.target.value)` writes the whole string.
- `app/ui/react/src/components/HistoryPage.jsx:283-290` — same single-input
  shape for history rows (`value={edited}`, `handleEditChange(...)`).
  Per `AGENTS.md` ("Report UI and History UI must stay in sync") both rows
  must change together via shared code.
- `app/ui/react/src/store/AppStore.jsx:755-786` — `onTargetInputChange`
  writes `_liveTarget`, recomputes `crossDrive` via `isCrossDriveItem`, runs
  group `computePathSync`, regroups. Anything that builds a new target string
  can reuse this path unchanged.
- `app/ui/server.py:976-979` — `GET /api/browse/roots` already returns all
  library paths (`_browse_root_configs`: `{key, path, kind, description}` from
  `movie_roots` + `series_roots`). No new backend data source needed.
  Current `.env` has 6 movie + 6 series roots (incl. `::ns+12 releases`
  descriptions).
- `app/services/retarget.py:187-206` — `PATCH /scans/.../items`
  (`update_scan`) validates every new target with `validate_target_path`
  against allowed roots, so a dropdown-swapped prefix that stays under a
  configured root always passes; a remainder edit that escapes roots still
  400s as today.

## Proposed behavior

### 1. New shared component — `TargetPathEditor.jsx`

Shared by `ReportPanel` and `HistoryPage` (sync rule). One joined group:

```
[ library-root <select> ][ remainder text input........ ]
```

- Props: `value` (full target path), `roots` (`[{key,path,kind,description}]`),
  `onChange(fullPath)`, plus passthrough (`onKeyDown`, `id` hooks for tests).
-   `splitTarget(fullPath, roots)` helper (in `report.js`, unit-tested):
  longest-prefix match of `fullPath` against `roots[].path` (trailing-slash
  insensitive). Returns `{ root, remainder }` where `root` always ends with
  `/` and `remainder` is everything after it. Example: full
  `/mnt/media2t/downloads/series/Toshi Densetsu Series/Season 01/Toshi .mp4`
  with root `/mnt/media2t/downloads/series` → root
  `/mnt/media2t/downloads/series/`, remainder
  `Toshi Densetsu Series/Season 01/Toshi .mp4`. The dropdown value/option
  list uses the slash-terminated root form.
- No-match case (target outside all roots — legacy/manual path): dropdown
  shows a disabled `Custom…` option displaying the current prefix, remainder
  input shows the full path so nothing is lost; picking a real root then
  joins `newRoot + '/' + remainder-basename-tail` (see below).
- Dropdown change: `onChange(newRoot + remainder)` where `newRoot` ends with
  `/` (e.g. switching to `/mnt/media1t/downloads/series/` keeps
  `Toshi Densetsu Series/Season 01/Toshi .mp4`). Remainder edit:
  `onChange(currentRoot ? currentRoot + newRemainder : newRemainder)` with
  leading `/` stripped from the typed remainder.
  Both flow through the existing `onTargetInputChange` / `handleEditChange`
  so group sync, link-toggle, cross-drive badge, and Update Paths behave
  exactly as today.
- Display label per option: `{description} — {path}` grouped with `<optgroup
  label="Movies">` / `<optgroup label="Series">` by `kind`. Full path stays
  in `title` attr.
- Styling: `theme.css` — `.target-path-group { display:flex }`, select
  (ellipsis, max-width ~220px, muted) + input sharing one border/radius
  (joined group, minimal/modern/elegant per workspace rules); mobile wraps
  (`theme.css:920` media query area). Reuses `.target-input` classes so the
  existing responsive rules still apply.

### 2. Roots data — fetch once, cache in store

- `AppStore` gains `libraryRoots` state + `loadLibraryRoots()` calling
  `GET /api/browse/roots` (same endpoint `BrowseModal` uses). Called from
  `checkConnection` / `loadLibraries` alongside the Jellyfin load, and lazily
  on first report render if empty. `HistoryPage` reads the same store value —
  no per-row fetching.
- Failure/empty (backend unreachable, no roots): fall back to today's plain
  single input so rows never break.

### 3. Wiring

- `ReportPanel.jsx` `ReportRow`: replace the lone `<input>` with
  `<TargetPathEditor value={liveTarget} roots={state.libraryRoots}
  onChange={(v) => actions.onTargetInputChange(item._idx, v)} ... />`.
  Link-toggle, Browse button, Enter→Update-Paths focus all untouched.
- `HistoryPage.jsx` row: same component with `value={edited}`,
  `onChange={(v) => handleEditChange(historyId, confirmId, v)}`.
- Series-vs-movie filtering: **no filtering** — dropdown always lists all
  roots (user asked for all library paths). The current root stays selected
  even when kinds differ, so a series→movie library move is one click.
- Browse/retarget flow untouched: it sets a full `targetPath` via server-side
  rebuild; the editor just re-splits it on next render.

### 4. Edge cases

| Case | Behavior |
| --- | --- |
| Target exactly equals a root (no remainder) | remainder empty, input placeholder shows `relative/path…` |
| Remainder edit to absolute-looking `/x/y` | stripped of leading `/`, joined directly under current slash-terminated root (never escapes via UI typing; paste of full path with another root prefix re-splits on next render since split runs on `value`) |
| Paste full path from another root | goes through `onTargetInputChange` whole-string path; next render `splitTarget` detects the new prefix and the dropdown selection follows |
| Group sync (`computePathSync`) | unchanged — it sees full strings before/after, so a root swap on one linked row propagates the same prefix swap to linked siblings sharing the old prefix |
| Cross-drive badge | unchanged — `isCrossDriveItem` already re-evaluates on `_liveTarget` change, so a `/media1t`→`/media2t` dropdown swap flips the badge live |
| Path validation on save | unchanged — `PATCH items` still 400s if the joined path is outside roots |

### 5. Files to change

| File | Change |
| --- | --- |
| `app/ui/react/src/utils/report.js` | `splitTarget` + `joinTarget` pure helpers |
| `app/ui/react/src/components/TargetPathEditor.jsx` (new) | joined select+input group |
| `app/ui/react/src/store/AppStore.jsx` | `libraryRoots` state, `loadLibraryRoots()`, hook into `checkConnection`/`loadLibraries` |
| `app/ui/react/src/components/ReportPanel.jsx` | use `TargetPathEditor` in `ReportRow` |
| `app/ui/react/src/components/HistoryPage.jsx` | use `TargetPathEditor` in history row |
| `app/ui/react/src/styles/theme.css` | `.target-path-group` joined styles + responsive |
| `app/ui/react/src/components/TargetPathEditor.test.jsx` (new) + `report.test.js` | split/join unit tests, dropdown-change join test, custom-path fallback |
| `app/ui/react/src/components/ReportPanel.test.jsx` / `HistoryPage.test.jsx` | row renders dropdown with roots; select change calls `onTargetInputChange`/`handleEditChange` with joined path |

No backend / `.env` / MCP change. `GET /api/browse/roots` is reused as-is.

## Open questions (confirm before `go`)

1. Dropdown lists **all** roots unfiltered (movies + series together) — correct,
   or should series rows default-filter to series roots (still switchable)?
2. Option label: `description — path` with Movies/Series optgroups — ok, or
   path-only?
3. Out-of-root `Custom…` fallback as described — ok?

## Verification

1. `cd app/ui/react && npm test` — new + existing suites green.
2. `python3 -m pytest tests/` — backend untouched, still green.
3. `npm run build` in `app/ui/react`, then `docker restart jellysort`
   (bind-mount picks up `react-dist/`).
4. Manual: scan producing a movie + a series row. Each target cell shows
   `[root dropdown][remainder input]` as one group. Change the dropdown →
   remainder keeps `Show/Season 01/file.mkv`, cross-drive badge updates,
   sibling linked rows sync, Update Paths persists (report reload shows the
   new prefix). Type in the remainder → prefix stays. Reload → selection
   persists per row.
