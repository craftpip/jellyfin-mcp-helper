# Confirm Queue + Background Moving + Per-Item Working Indicator

> **Status: PLANNED** — not yet implemented.

Owner request: queue up multiple confirmations and let them keep progressing in
the background while the report is reviewed. When a confirm is requested while a
move (or scan) is already running, don't reject it — add it to a UI-maintained
queue that processes batches one at a time in the background. Show in the report
which items are currently being worked on, and hide the group Confirm button
while a target path edit is pending so the user applies the edit first.

## Current state (verified)

- Confirmation is per-group. `ReportPanel.jsx:231` renders a group "Confirm"
  button; there is **no** global "Confirm Selected" button anymore —
  `confirmButtonLabel` (`AppStore.jsx:31`) is set but never rendered.
- `confirmSelected` (`AppStore.jsx:502`) and `confirmGroup` (`:518`) both guard
  on `confirmActive` and reject a second confirm with
  `toast('A move is already running — wait for it to finish', 'info')`.
- `runConfirm` (`AppStore.jsx:545`) POSTs `/api/scans/current/confirm` using the
  **current** `scanId`. Backend `confirm_scan` (`app/services/scan_manager.py:527`)
  rejects with 400 `"Scan is still running..."` when `scan.status == "running"`
  and 409 `"Confirm already running..."` when `confirm_status == "running"`.
- Progress is polled by `pollConfirmProgress` (`AppStore.jsx:579`); it stops
  entirely once `confirmActive` goes false. Completion branch (`:600`) resets
  state, toasts, and calls `fetchReport` after 800 ms. The poll has no notion of
  a next batch.
- The bottom-right transfer toasts (`Toasts.jsx` `TransferToasts`) already
  render per-file state for the **active** batch via `deriveTransferQueue`
  (`app/ui/react/src/utils/transfer.js`) — `queued/copying/done/failed`. This is
  the natural model to reuse for the queue and the row indicators.
- Report rows (`ReportPanel.jsx` `ReportRow`, `:259`) have no per-item move
  state; the Actions cell shows badge + cross-drive + `PathPills` only.
- Group toolbar (`ReportPanel.jsx:224-235`): when `hasPathEdits` is true the
  "Update Paths" button appears **and** the "Confirm" button stays visible, so
  the user can confirm without applying path edits.
- While a scan runs, `App.jsx` hides the report panel (`{!state.scanRunning &&
  !state.reportLoading && <ReportPanel />}`), so queueing from the UI during a
  scan is defensive only; the important case is "confirm while a confirm runs".

## Design decisions

- **D1 — Queue lives in the UI (DECIDED).** New `confirmQueue` state in
  `AppStore.jsx`. Each entry snapshots everything the confirm needs at enqueue
  time so batches survive report reloads and still target the right scan:
  `{id, scanId, itemIds, label, items: [{confirmId, title, sourceName,
  sourcePath, targetPath, fileSize}], status: 'queued'|'active'|'done'|'failed',
  error, addedAt}`. The backend keeps its single-confirm-per-scan model — the UI
  serializes batches.
- **D2 — One batch at a time, strictly sequential (DECIDED).** The active batch
  drives the existing confirm-progress poll + transfer toasts exactly as today.
  Queued batches wait. A new batch is dispatched only when the current one is
  `completed`/`idle`/`failed` **and** no scan is running.
- **D3 — Enqueue instead of reject (DECIDED).** Remove the
  "already running" toasts in `confirmSelected`/`confirmGroup`. They now always
  open the preflight modal. `runConfirm` decides:
  - `confirmActive || scanRunning` → append the batch snapshot to `confirmQueue`
    as `queued`, close the modal, toast `"Added N item(s) to the move queue"`.
  - otherwise → start immediately (current behavior).
- **D4 — Confirm by snapshot scanId (DECIDED).** Queued batches POST to
  `/api/scans/{scanId}/confirm`, not `/scans/current/confirm`, so a batch queued
  against report A is never applied to a later scan B's item ids.
- **D5 — Auto-advance the queue (DECIDED).** In `pollConfirmProgress`'s
  completion/failed branches, after the active batch is finalized, mark it
  `done`/`failed` and call `dequeueNext()`: if a `queued` batch exists and no
  scan is running, mark it `active` and start its confirm. The poll keeps
  running while `confirmActive || confirmQueue has queued/active entries`, so it
  bridges between batches. `pollScanProgress`'s completion branch also flushes
  the queue once the report is loaded (defensive, D1 scan case).
- **D6 — Per-item working indicator (DECIDED).** Maintain a
  `moveStates` map in state, `{confirmId: 'queued'|'copying'|'done'|'failed'}`,
  derived from: queued batches' items (`queued`), the active batch's
  `deriveTransferQueue` output (`copying`/`done`/`failed`), and completion
  counts. `ReportRow` renders: spinner + "Moving" chip when `copying`, ✓ when
  `done`, ✕ when `failed`, a "Queued" dot when `queued`. This is what "show when
  I confirm an item that it is being worked on" means — visible in the rows the
  user is reviewing.
- **D7 — Queue visible in the UI (DECIDED).** Extend the transfer toast area
  (`Toasts.jsx`) with a "Queued" section listing each pending batch
  (`title — N item(s)`), and add `+N batches queued` to the active header. The
  report toolbar may later show a compact chip; the toasts are the primary
  surface (owner: "The Q will be maintained in the UI").
- **D8 — Hide Confirm while path edits pending (DECIDED).** In the group
  toolbar, render the Confirm button only when `!hasPathEdits` (`{!hasPathEdits
  && <button ...>Confirm</button>}`). "Update Paths" remains; after the edit is
  applied (`applyGroupTargetEdits`) `hasPathEdits` clears and Confirm returns.

## Part A — Store: confirm queue (`AppStore.jsx`)

1. State: `confirmQueue: []`, `moveStates: {}`, plus a `SET_CONFIRM_QUEUE` /
   `SET_MOVE_STATES` reducer case each.
2. `buildConfirmBatch(itemIds, label)` — snapshots items + `scanId`, returns a
   batch object (unique `id` via a counter like `toastSeq`).
3. `runConfirm(itemIds)`:
   - Build the batch.
   - If `confirmActive || scanRunning`: push to `confirmQueue` (`queued`),
     update `moveStates` for its items to `queued`, close modal, toast. Return.
   - Else: set `confirmActive=true`, mark batch `active`, POST
     `/api/scans/{scanId}/confirm`, start `pollConfirmProgress` (current path,
     with the snapshot scanId).
4. `dequeueNext()` — shift the first `queued` batch; if none or `scanRunning`,
   stop. Else mark it `active`, run its confirm via `/api/scans/{scanId}/confirm`,
   and ensure the poll is scheduled.
5. `pollConfirmProgress`:
   - Continue polling while `confirmActive || queueHasPending` (replace the
     `if (!confirmActive) return` guard at `:580`).
   - Poll `/api/scans/{scanId}/confirm-progress` (snapshot scanId).
   - Completion/failed branch (`:600-614`): finalize the active batch
     (`done`/`failed`), set `confirmActive=false`, update `moveStates`, then
     `dequeueNext()` instead of returning. Keep the existing toast +
     `setTimeout(fetchReport, 800)`.
   - `SET_CONFIRM_BUTTON_LABEL` still reflects the active batch.
6. `confirmSelected`/`confirmGroup` (`:502`/`:518`): drop the `confirmActive`
   reject-toast; always open the preflight modal.
7. On a new scan (`startScan`), clear stale `moveStates` and any queue whose
   `scanId` no longer matches the current scan (or simply clear the queue —
   see rollout note).

## Part B — Per-item working indicator (`ReportPanel.jsx` + theme.css)

1. `ReportRow` reads `state.moveStates[item.confirmId]`; when set, render a
   state chip in the Actions cell (spinner + `Moving`, `✓ Moved`, `✕ Failed`,
   `● Queued`), using the existing `.transfer-spinner` / tick / fail styles or
   small new classes (`.row-state`).
2. Rows for `done`/`failed` get a muted class so completed items read visually.
3. The store keeps `moveStates` in sync via `deriveTransferQueue` (active batch)
   and the queue contents (queued), plus completion counts.

## Part C — Hide Confirm while path edits pending (`ReportPanel.jsx`)

In the group toolbar (`:224-235`) change the Confirm render to:
```jsx
{!hasPathEdits && (
  <button className="warn small" onClick={() => actions.confirmGroup(gi)}>
    Confirm
  </button>
)}
```

## Part D — Queue surface in the toasts (`Toasts.jsx`)

1. `TransferToasts` header gains a queued count when `confirmQueue` has pending
   batches: `Move completed` / `Moving x of y` + `· N more queued`.
2. Below the active queue, render a "Queued" group listing each pending batch
   (`{label || 'batch'} — N item(s)`, status dot), capped like
   `MAX_VISIBLE_QUEUE`.

## Tests

Frontend (`cd app/ui/react && npm test`, vitest + jsdom):
- `transfer.test.js` or new `queue.test.js` for the pure batch/derivation
  helpers (build a batch, dequeue ordering, per-item moveState derivation).
- `Toasts.test.jsx`: header shows `+N more queued`; queued section lists pending
  batches.
- `ReportPanel`/`App.test.jsx`: with a mock confirm-progress payload, a queued
  batch auto-starts after the active one completes; a `copying` item renders the
  "Moving" indicator; a group with `hasPathEdits` renders "Update Paths" but not
  "Confirm".
- `AppStore` unit coverage via `App.test.jsx` fetch mock: second Confirm during
  an active confirm enqueues instead of toasting "already running"; queue
  flushes sequentially (two mock confirm-progress sequences).

Backend (`python3 -m pytest tests/`): no backend behavior changes expected —
confirm serialization stays in the UI. Run the full suite to confirm.

## Files touched

- `app/ui/react/src/store/AppStore.jsx` — `confirmQueue`, `moveStates`,
  `runConfirm`, `dequeueNext`, `pollConfirmProgress`, `confirmSelected`,
  `confirmGroup`, new reducer cases.
- `app/ui/react/src/utils/transfer.js` — optional pure helpers for batch
  snapshot / moveState derivation (keep testable).
- `app/ui/react/src/components/ReportPanel.jsx` — Confirm hidden on `hasPathEdits`;
  per-item working indicator in `ReportRow`.
- `app/ui/react/src/components/Toasts.jsx` — queued-batch section + header count.
- `app/ui/react/src/styles/theme.css` — row state chip styles.
- Tests listed above.

## Implementation order

1. Part A (store): queue state + enqueue + auto-advance; keep existing single
   batch behavior as the no-queue case. Backend untouched.
2. Part D (toasts queue surface), then Part B (row indicators), then Part C
   (hide Confirm) — all UI-only.
3. `cd app/ui/react && npm test`, then `npm run build`.
4. Per AGENTS.md: `docker restart jellysort` (bind-mount picks up the new
   `react-dist/`), then verify live. No docker compose build needed unless
   backend files change (they shouldn't).

## Rollout / verification

1. Scan → report → confirm group A. While it runs, confirm group B and C: both
   enqueue (no "already running" toast); the transfer toasts show A active with
   `+2 more queued` and the queued batches listed.
2. As A finishes, B auto-starts, then C — no clicks needed; the poll bridges
   batches; final toasts show each completion; `fetchReport` refreshes the
   report between batches (verify moved items drop out / change state).
3. While an item is being copied, its report row shows the "Moving" indicator;
   done rows show ✓ and failed rows show ✕, all updating live as the toasts do.
4. Edit a target path in a group: "Update Paths" appears and Confirm disappears;
   apply the edit (Confirm returns) or discard the edit (Confirm returns).
5. Edge: queue an item, then start a new scan before it runs — the queued batch
   targets its snapshot `scanId` via `/api/scans/{scanId}/confirm`; confirm
   with a stale/unknown scanId errors cleanly (backend 404) and the batch is
   marked `failed` without blocking the rest of the queue.
6. Re-check edited files after `docker restart jellysort` (AGENTS.md filesystem
   rollback hazard) and keep `python3 -m pytest tests/` +
   `cd app/ui/react && npm test` green.
