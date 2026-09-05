# 09 — Drive-style collapsed transfer toast

> **Status: PROPOSED — awaiting `go` before implementation.**

## Goal

When many files are queued for transfer, the bottom-right toast stack fills
the screen (header + up to 12 per-file rows + "+N more"). Collapse it
Google-Drive-style: **one compact card showing only the file currently moving
plus queue counts**, with an opt-in expander for the full list.

## Current behavior (evidence)

- `app/ui/react/src/components/Toasts.jsx:4` — `MAX_VISIBLE_QUEUE = 12`; `:56-89`
  renders a `.transfer-queue` with one `.transfer-toast` row **per file**
  (done tick / spinner / fail / queued dot), plus `:88` `+N more in queue`.
- Header (`:40-55`) already shows `Moving {processed} of {total}`, overall bar,
  `Moved/Replaced/Failed` counts, and `· N batch(es) queued`.
- `app/ui/react/src/utils/transfer.js` — `buildTransferQueue` (one entry per
  confirm item, `state: queued|copying|done|failed`) and
  `deriveTransferQueue` (marks active via `result.current_file`, progress
  `percent/speed/eta/copied/size`). No change needed here.
- `app/ui/react/src/styles/theme.css:285-335` — fixed 380px column, unbounded
  vertical growth (12 rows × ~50px + header ≈ 700px+).
- `Toasts.test.jsx:64-83` asserts all three rows render simultaneously
  (`alpha/beta/gamma`) — these assertions change with this plan.

## Proposed behavior

Single compact card, fixed footprint regardless of queue size:

1. **Header (unchanged):** `Moving {processed} of {total}`, overall progress
   bar, `Moved/Replaced/Failed` counts, `· N batch(es) queued` suffix.
2. **Body — active file only:** the one row with `state === 'copying'`
   (spinner + name + per-file bar + `copied/size · speed · ETA`). If no row is
   copying yet (batch just started / between batches), show the first `queued`
   row as "Up next: {name}". Never more than 1 file row by default.
3. **Footer — queue summary + expander:**
   - `{K} file(s) in queue` where `K = total - processed - (active ? 1 : 0)`
     (0 → footer hidden while running; always hidden when done/failed).
   - Existing queued-*batch* suffix stays in the header (`· 2 batches queued`);
     the footer counts *files*, making the two numbers complementary, not
     duplicated.
   - Text button `Show all {total}` toggles the full per-file list
     (today's rows, scrollable `max-height: 40vh; overflow-y: auto`); toggles
     back to `Show less`. Local `useState` in `TransferToasts`, default
     collapsed.
4. **Terminal states:** `Move completed` / `Confirm failed` keep the header +
   counts; body collapses to nothing (no active file); the expander remains
   until auto-dismiss (`TRANSFER_DONE_REMOVE_MS`) so failures stay inspectable.
   Optionally auto-expand on `failed` (see open question).
5. **Status toasts untouched:** transient `toast-good/err` messages stay stacked
   above the card as today; only the transfer queue collapses.
6. **A11y:** keep `role="status" aria-live="polite"` on the container; expander
   is a real `<button>` with `aria-expanded`.

## Files to change

1. `app/ui/react/src/components/Toasts.jsx`
   - `TransferToasts`: derive `active = queue.find(copying) ?? first queued`,
     `waiting = total - processed - (active && active.state === 'copying' ? 1 : 0)`;
     render header + single active row + footer (`{waiting} in queue` + toggle);
     full list only when expanded.
   - Remove `MAX_VISIBLE_QUEUE` slicing in collapsed mode (keep capped +
     scrollable list in expanded mode, e.g. render all with CSS scroll rather
     than a magic 12 + "+N more" — or keep the cap inside the expanded list).
2. `app/ui/react/src/styles/theme.css`
   - `.transfer-details-toggle` (text button), `.transfer-queue.scrollable`
     (`max-height: 40vh; overflow-y: auto`), `.transfer-waiting` footer line.
3. Tests (`npm test` in `app/ui/react`, never root `npx vitest`):
   - `Toasts.test.jsx`: collapsed by default (only `beta.mkv` + `2 files in
     queue`-style text visible, `alpha/gamma` hidden); click expander →
     all rows appear; `Show less` collapses again; completed header shows no
     active row; queued-batch suffix still renders.
   - `transfer.test.js`: no changes expected (helpers untouched) — keep green.
4. Docs (per plan 07 sync, after implementation):
   - `docs/web-ui/components.md` — Toasts paragraph: collapsed card behavior.
   - `AGENTS.md` — only if a durable pattern emerges; prefer the existing
     section.

No backend / MCP / `.env` change. After React change: `npm run build` in
`app/ui/react` + `docker restart jellysort`.

## Verification

1. `cd app/ui/react && npm test` — all suites green (updated + new cases).
2. `docker exec jellysort python3 -m pytest tests/ -q` — backend untouched,
   stays green.
3. Manual: confirm 20+ files → card stays one compact panel showing the live
   file + `N files in queue`; expand → scrollable full list; collapse again;
   complete → `Move completed` + counts, then auto-dismiss.

## Open questions (confirm before `go`)

1. Default collapsed always, or auto-expand when the batch is small (e.g. ≤3 files — everything already fits)?
2. Auto-expand on failure so failed files are immediately visible, or stay collapsed with the `Failed: N` count?
3. Footer wording: `{K} files in queue` (proposed) vs Drive-like `Uploading 1 item · K pending`?
