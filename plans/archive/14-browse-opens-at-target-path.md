# 14 — Browse modal opens at the item's intended target folder

> **Status: PROPOSED — awaiting `go`.**

## Goal

Today, clicking **Browse…** on a report row opens the folder browser on the
combined "All libraries" root list (`/api/browse/roots`), so the user always
starts at the top and must drill down. Change it so the browser opens at the
folder that is actually going to be used for that file — i.e. the directory of
the item's `targetPath` (`…/Show Name/Season 01` for series, `…/Movie (2024)`
for movies). If that folder does not exist on disk yet, open at the nearest
existing folder in its parent chain, so the user sees the show/movie/root
folder that does exist instead of an empty "All libraries" screen.

## Decisions (user-confirmed 2026-09-21)

1. The intended folder is **whatever path is detected for the file** — the
   target folder = `dirname(targetPath)`. If that folder does not exist, show
   the nearest existing path **in its parents chain or itself** (i.e. the path
   itself wins when it exists; otherwise walk up to the closest existing
   ancestor).
2. **Do not auto-create the folder while browsing.** The browse flow is
   read-only: no `mkdir` anywhere in resolve/browse. Folder creation stays
   exclusively at move time (`move_executor`). The browser only ever *loads*
   directories that already exist.

## Current behavior (evidence)

- `app/ui/react/src/store/AppStore.jsx:1133` — `openBrowse(confirmId)` sets
  `browseModal`, and `BrowseModal.jsx` opens with no initial path.
- `app/ui/react/src/components/BrowseModal.jsx:68-88` — on mount it always
  calls `/api/browse/roots` and renders the root folders as the top-level
  listing (`didInit` guard, never drills into the item's target).
- `app/ui/react/src/components/BrowseModal.jsx:165-232` — the "All libraries"
  breadcrumb already exists, so returning to the roots from a drilled path is
  free; we only need to change where it *starts*.
- `app/ui/server.py:959-971` — `GET /api/browse` **400s on a non-existent
  directory** (`if not dir_path.is_dir(): raise HTTPException 400`), so the
  frontend cannot simply `load(dirname(targetPath))` when the target folder is
  missing — the resolve-to-existing-ancestor step must run first.
- `app/ui/react/src/components/BrowseModal.test.jsx:108-138` — first test
  asserts the modal opens on all libraries; this assertion changes with the
  feature.

## Proposed behavior

### 1. Backend — new resolve endpoint (`app/ui/server.py`)

Add `GET /api/browse/resolve?target=<path>` (panel-auth protected, next to the
other browse routes at `:954`). **Read-only — existence checks only, never
creates any directory.**

- Input: the item's full `targetPath` (a file path, per report items).
- Walk: start at `Path(target).parent` (the intended folder the file lands in).
  If it exists, that IS the answer — showing the path itself. Otherwise move up
  the chain while `candidate` is not a directory, stopping at the first path
  that exists. No `mkdir` is ever called.
- Root check: use `_browse_root_for(target, config)`. If the target is not
  under any configured movie/series root → return `{"path": null}` (the browse
  UI cannot navigate there anyway; caller falls back to current behavior). If
  the resolved existing ancestor is above the root, return the root itself when
  it exists, else `null`.
- Response: `{"path": "<nearest existing ancestor dir>" | null, "target": "<target>"}`.

Behavior contract (these become tests):

| target dir               | disk state                          | resolved path          |
| ------------------------ | ----------------------------------- | ---------------------- |
| `…/Show/Season 01`       | season exists (even if empty)       | `…/Show/Season 01`     |
| `…/Show/Season 01`       | season missing, show exists         | `…/Show`               |
| `…/Show/Season 01`       | show missing, `…/series` exists     | `…/series` (root)      |
| `…/Show/Season 01`       | nothing exists incl. root           | `null` → all libraries |
| target under no root     | anything                            | `null` → all libraries |

### 2. Frontend — start the picker on the resolved path (`BrowseModal.jsx`)

- `BrowseView` (line 13) computes the intended folder from the item:
  `initialPath = item?.targetPath ? item.targetPath.split('/').slice(0, -1).join('/') : null`.
- `FolderPicker` gains an optional `initialPath` prop. On mount (`didInit`):
  - `initialPath` set → `GET /api/browse/resolve?target=<initialPath>`; if the
    response has a non-null `path`, `load(path)` to open there. If `path` is
    `null` or the call errors → fall back to the current roots-loading branch.
  - `initialPath` unset (History page line 388, Settings page browser) → current
    behavior unchanged (starts on "All libraries").
- No other UI changes: the breadcrumb already shows "All libraries" as the first
  crumb (`:219`) for any drilled-in `cwd`, so the user can climb back to the
  roots exactly as before. `goUp`/`load` paths are untouched. The picker never
  creates a folder — the "Select this folder" action only ever commits an
  *existing* directory (the resolved open-path), and any new target structure
  (e.g. a missing Season folder) is created later by the move executor, not by
  browsing.

### 3. Tests

- Backend — `tests/test_ui_api.py::TestBrowseAndRetarget` (uses `_make_client`
  tmp_path roots):
  1. resolve returns the existing season dir for a target whose folder exists;
  2. resolve walks up to the nearest existing ancestor (season missing → show
     dir; show missing → series root);
  3. resolve returns `null` when the root itself does not exist, and for a
     target outside configured roots; absolute-path validation 400.
- Frontend — `app/ui/react/src/components/BrowseModal.test.jsx`:
  - update the first test's mock + assertions: `/api/browse/resolve` returns the
    item's season dir → modal renders that folder's contents first (not the
    roots list); root crumb still shown so climbing back to "All libraries"
    works;
  - new case: resolve returns `null` → modal still opens on the roots list
    (regression for history/settings-style callers).
  - Run `npm test` in `app/ui/react` (never root `npx vitest`).

### 4. Files to change

| File | Change |
| --- | --- |
| `app/ui/server.py` | `_browse_resolve_target` helper + `GET /api/browse/resolve` route |
| `app/ui/react/src/components/BrowseModal.jsx` | `FolderPicker` `initialPath` prop; `BrowseView` passes `item.targetPath` dirname; resolve-then-load init |
| `app/ui/react/src/components/BrowseModal.test.jsx` | resolve mock + updated/additional cases |
| `tests/test_ui_api.py` | `TestBrowseAndRetarget` resolve tests |

No `.env`/MCP change. After implementation: `python3 -m pytest tests/` +
`cd app/ui/react && npm test && npm run build` + `docker restart jellysort`.

## Verification

1. `cd app/ui/react && npm test` — all suites green (incl. resolved-open-path
   and null-fallback cases).
2. `python3 -m pytest tests/` — backend green (incl. new resolve cases).
3. Manual: scan a new series + a new movie. Browse a series row whose Season
   folder does not exist yet → the modal opens at the existing Show folder
   (parent chain), with the "All libraries" crumb present. Browse a movie row
   whose folder exists → opens inside it. Browsing must never create
   directories (`ls` the library before/after opening the modal → unchanged); a
   folder is only created at move time.