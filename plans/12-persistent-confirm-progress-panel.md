# 12 — Persistent, minimizable, group-aware confirm progress panel

> **Status: IMPLEMENTED 2026-09-21 (uncommitted).**
>
> Implementation note (deviation from the draft): restore-on-load is gated
> behind a `jsort_transfer_active` localStorage flag set by `runConfirm` (both
> immediate and queued starts) and cleared on dismiss/error/idle-restore — so
> unrelated page loads never GET confirm progress (keeps the SSE test's
> `confirmProgressGets === 0` invariant and avoids a request per load). Only a
> browser that started a transfer restores its panel. `queue_groups` items also
> carry `failed: bool(item.error)` (failed items keep `confirmed=False`) so
> restored rows show failed, not queued.
>
> User direction (2026-09-21): the confirmation progress panel should be
> **persistent** (still visible after a page refresh), **minimizable**
> (collapsed/expanded), **open by default**, and rendered as **one box** —
> current file + files queued behind it inside a single panel, Google-Drive-style
> — not as separate toasts. Queue entries must be **grouped by their show/movie
> group** and labeled with the group name, so confirming one series then another
> shows the currently-moving group and the just-queued group under their names.
>
> Decision on the three open questions: **persist completed until dismissed**
> (no auto-dismiss); **show every queued file** (scrollable list, no cap);
> **container restart** persistence is out of scope (in-memory `ScanPlan`
> resets to `idle` — existing behavior).

## Goal

Replace today's bottom-right confirm-progress stack (header card + one separate
toast card per file, all gone on page refresh) with a **single persistent
transfer panel** that:

1. Survives a page refresh while a move is running / recently completed.
2. Can be minimized to a compact strip and is **open by default** when a
   transfer is active (minimized state remembered across reloads).
3. Shows files **grouped by their show/movie group**, each group named — the
   currently-moving batch (its active file + the rest of its queue) plus every
   confirm batch queued behind it — all inside one box.

## Current behavior (evidence)

- `app/ui/react/src/components/Toasts.jsx:44-80` — `TransferToasts` renders a
  `.transfer-header` card (title, overall bar, `Moved/Replaced/Failed` counts,
  `· N batch(es) queued`) **plus** `.transfer-queue` of per-file rows; each row
  (`:83-93`) is itself a `.transfer-toast` bordered card (bg + border + radius
  from `theme.css:325`) — visually "different toasts", not one box.
- The queue is a **flat file list with no group context** — row names come from
  `buildTransferQueue(itemIds, items)` (`utils/transfer.js:7`) which keeps only
  `sourcePath`/`name`/`targetPath`, dropping the report's `title` group.
- State is **ephemeral React state only**: `transferQueue`/`transferSummary`
  (`AppStore.jsx:89-90`), `confirmActiveRef = useRef(false)` (`:156`). On
  refresh nothing re-subscribes and the panel never renders — the backend keeps
  running but the UI forgets.
- Restore hook already exists: `checkConnection` (`AppStore.jsx:360-399`) runs
  on startup after auth. `GET /api/scans/current/confirm-progress`
  (`app/ui/server.py:899`) + SSE `/api/scans/confirm/events` (`:642`) return the
  live `ScanPlan` confirm state — which survives a **page** refresh (it is only
  lost when the container restarts, since `ScanManager` is in-memory).
- `format_confirm_progress` (`app/services/presenters.py:283-351`): returns
  `current_file`, `processed/total`, `counts`, `queue_length/queue_items` — but
  **not the ordered list of files** in the running/queued batches, so a fresh
  page has nothing to rebuild the queue from.
- Group titles already exist backend-side per item, derivable from the target
  path exactly as the frontend does in `mapReportItems`
  (`app/ui/react/src/utils/report.js:91-107`): series → show folder
  (`parts[-3]` of the target), movie → parent folder (`parts[-2]`).
  `ScannedItem.name` is the source *filename*, not the title — do not use it for
  grouping.
- Auto-dismiss: `TRANSFER_DONE_REMOVE_MS = 4500` (`transfer.js:3`);
  `scheduleTransferRemovals` in `AppStore.jsx` clears done rows — hostile to
  "keep showing me what finished".
- Plan 09 already collapsed the list to a single active row + expander, but kept
  per-file toast cards and no persistence/minimize/groups.

## Proposed behavior

### 1. One persistent, group-aware panel (Drive-style box)

One fixed-position panel (bottom-right, reused footprint) containing:

- **Header row:** `Moving {processed} of {total}` (or `Move completed` /
  `Confirm failed`), overall progress bar, `Moved · Replaced · Failed` counts,
  `· N batch(es) queued` when queued, a **minimize** button, and a **dismiss**
  (×) button shown only in terminal state.
- **Body — one group section per show/movie (NOT per-file toast cards):**
  - **Moving group** (the batch currently running): shows the file currently
    copying (spinner + name + per-file bar + `copied/size · speed · ETA`);
    before the first copy starts, the first queued file as `Up next`; the rest
    of that batch listed as compact rows beneath.
  - **Queued groups** (confirm batches behind the running move): each its own
    section — group name header (e.g. the series title) + its file rows, with a
    `Queued` badge so the user sees which batch is waiting.
  - Every group is labeled with its **group name** (show/series/movie title).
    Files belonging to the same show appear under one header even when a single
    confirm batch spans several groups.
  - Whole body scrollable (`max-height`); all queued files shown, no cap.
- **Status toasts unchanged:** ephemeral `toast-good/err/info` messages stay a
  separate transient stack; only the transfer queue becomes the persistent box.

### 2. Minimizable, open by default

- Header minimize toggle collapses the panel to a compact strip (e.g. one line:
  spinner + `Moving 3 of 12` + expand chevron). **Open (expanded) by default.**
- Minimized state persisted in `localStorage`
  (key e.g. `jellysort.transferMinimized`) → remembered across refresh.
- On refresh with an active transfer it renders open (unless previously
  minimized).

### 3. Persistent across refresh

On startup, after `checkConnection` auth succeeds:

1. `GET /api/scans/current/confirm-progress`.
2. If `status === 'running' | 'completed' | 'failed'` or `queue_length > 0`:
   - Rebuild the queue from a **backend-provided grouped file list** (new
     `queue_groups`, see below) instead of in-page item ids.
   - Set `confirmActiveRef.current = true`, dispatch `SET_CONFIRM_ACTIVE`,
     `SET_TRANSFER_QUEUE`, `SET_TRANSFER_SUMMARY` (primed with
     `processed/total/counts/queueLength`).
   - Re-subscribe to SSE (`subscribeConfirmProgress`, existing fallback to
     polling via `pollConfirmProgress`) so the restored panel keeps live updates.
   - Restore minimized state from `localStorage`.
3. Terminal state persists too: `Move completed` stays visible until dismissed
   (`×`) or a new transfer starts — no 4.5s auto-dismiss.

Scope note: persistence is across **page refresh**, not container restart —
`ScanPlan`/`ScanManager` are in-memory, so a restart still resets to `idle`
(existing behavior, documented in AGENTS.md). Persisting live confirm state to
SQLite is out of scope.

### Backend: grouped remaining-batch payload

- `ScanPlan` (`app/models/schemas.py`) gains the running batch's selection so
  the presenter can recompute remaining files without the call arguments:
  `confirm_item_ids`, `confirm_source_paths`, `confirm_source_prefixes`
  (snapshot stored in `_start_confirm`, `app/services/scan_manager.py:303`).
- `format_confirm_progress` (`presenters.py`) gains **`queue_groups`**:
  ```
  [
    { group: "Show Name", kind: "series", batch: "running" | "queued",
      current_file: "…" (running batch only),
      items: [{ confirm_id, source_path, source_name, target_path, kind }] },
    …
  ]
  ```
  - Derived from `scan.items` filtered by unconfirmed + the running-batch
    selection, then the queued batches resolved from `manager._confirm_queue`
    (each entry's `item_ids`/`source_paths` → scan.items). Queued-batch sections
    keep their scan order.
  - **Grouping rule = the frontend's `mapReportItems` title rule** (target-path
    parts: series → `parts[-3]` show folder, movie → `parts[-2]` folder). Items
    are batched by that derived title; each group gets an explicit `group`
    label. `current_file` stays the single live current item (matched by
    `source_path`) and the current `processed`/`counts` remain per-confirm, so
    the existing `deriveTransferQueue` alignment still works.

## Files to change

1. `app/models/schemas.py` — `ScanPlan` `confirm_item_ids` /
   `confirm_source_paths` / `confirm_source_prefixes` fields.
2. `app/services/scan_manager.py` — `_start_confirm` stores the selection;
   expose `_confirm_queue` to the presenter for queued-batch resolution.
3. `app/services/presenters.py` — `format_confirm_progress` adds `queue_groups`
   (grouped by target-path-derived title; existing keys unchanged).
4. `app/ui/react/src/utils/transfer.js` — new
   `buildTransferGroupsFromBackend(queueGroups)` (preserves group name + kind +
   batch status; derives `source_name` from `source_path` when absent) and a
   `buildTransferGroups(itemIds, items)` for the local (post-confirm) path that
   groups by the mapped item's `title` (from `mapReportItems` group). Drop the
   flat `TRANSFER_DONE_REMOVE_MS` auto-dismiss path.
5. `app/ui/react/src/store/AppStore.jsx` — startup restore in `checkConnection`;
   `scheduleTransferRemovals` gated to explicit dismiss; minimize/dismiss
   actions; `applyConfirmProgress` terminal path keeps summary instead of
   clearing; queue now keyed by group.
6. `app/ui/react/src/components/Toasts.jsx` — restructure `TransferToasts` into
   the single box: header (minimize + dismiss) + grouped body (moving group with
   active row, queued groups with name header + `Queued` badge + file rows);
   no per-row `.transfer-toast` cards.
7. `app/ui/react/src/styles/theme.css` — panel/list-row/group-header styles;
   remove/neutralize the per-row card look; add minimized strip style.
8. Tests (`cd app/ui/react && npm test`, never root `npx vitest`):
   - `Toasts.test.jsx`: one box (queued rows inside the panel, no separate toast
     cards), both groups render with their names when a second batch is queued,
     moving-group active row, minimize → strip, expand back, open-by-default.
   - `App.test.jsx`: refresh-restore (progress GET returns running +
     `queue_groups` → panel renders grouped, SSE subscribed), completed persists
     until dismissed.
   - `transfer.test.js`: `buildTransferGroupsFromBackend` grouping/naming/order.
9. Docs (per plan 07 sync, after implementation): `docs/web-ui/components.md`
   Toasts/transfer panel paragraph; `AGENTS.md` only if a durable pattern
   emerges. Backend `python3 -m pytest tests/` must stay green (presenter/schema
   additions are additive).

After React change: `npm run build` in `app/ui/react` + `docker restart jellysort`.

## Verification

1. `cd app/ui/react && npm test` — all suites green (updated + new cases).
2. `docker exec jellysort python3 -m pytest tests/ -q` — backend stays green.
3. Manual:
   - Confirm a series batch of 6+ episodes → ONE box shows one group (series
     name) with the copying file + the rest queued below (list rows, not
     separate toasts); minimize → strip; refresh mid-move → panel is back,
     previous minimized state respected, live updates resume (SSE logged).
   - Confirm a second series while the first is moving → a second group section
     appears under its show name with a `Queued` badge + its files.
   - Confirm a movie → its own group (movie title), single file.
   - Refresh after completion → `Move completed` + counts remain until `×`.
   - Confirm while a move is already running → queued group visible in the same
     box; refresh keeps both visible.