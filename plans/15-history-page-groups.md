# 15 — History Page: Groups Exactly Like Scan Report (No Shortcuts)

> **Status: Implemented 2026-08-24 (§3 steps 1–6).** Matrix green: backend `415 passed`
> (+8 new in `tests/test_history_store.py`), frontend `112 passed` (+8 new
> `HistoryPage.test.jsx`), `npm run build` ✓, container restarted, live `/api/history` +
> `/history` verified, `config/app.db` migration confirmed (`suspect`, `corrected`,
> `correction_note`, `cross_drive` columns present). FK note: `scans` row is written by the
> orchestrator when the scan completes, before any confirm, so `append_history_group` never hits
> the foreign key. Remaining manual check: perform one real Confirm and verify exactly one card
> with only the moved files appears (History page shows `No confirms yet` until then).

> **Goal:** History (`/history` → `HistoryPage.jsx`) must show **confirmed groups exactly like the Scan report** — per-sourceFolder `▼/▶` cards, `Source → Target` table with `PathPills`/`Suspect`/`Corrected`, `Browse…`, filters (`All`/`New`/`Replace`/`Extras` with `✓`), search, and `Move again`/`Undo` — not a flat table. One Confirm = one history card; two separate Confirms on same sourceFolder = two history cards.

---

## 1. Current State (Verified)

- **Scan report** (`ReportPanel.jsx:34`): `reportAll` → `groupItems` by `sourceFolder`/`containerPath` (plan 12), `▼/▶` header `g-title`/`g-count`/`g-size`, `group-body` table `Source → Target Path` (`PathPills`, `Suspect`/`Corrected`, `Cross-drive`), `Browse…` + `target-input` with `computePathSync`, filter chips `All`/`New`/`Replace`/`Extras`, search, `Collapse/Expand` toggle, `Confirm` per group.
- **History page** (`HistoryPage.jsx:5`): Fetches `GET /api/history?limit=50` → `history_groups` + `history_items` (`app.db` `history_groups`/`history_items`, written by `ScanManager.confirm_scan` → `history_store.save_group`). Renders `▼/▶` cards per `history_id` (`group_title`, `N files`, `confirmed_at`, `history_id` badge) → table `Source | Current Target | New Target (edit) | Trail | Status` (`path_history_json`), `Undo` (`POST /history/{id}/undo`) / `Save & Move Again` (`POST /history/{id}/retarget`). **No scan history shown** — `GET /api/scans/history` (20 `reports/history/*.json` + `app.db` `scans`, `MAX_HISTORY 200` after `07b9943`) is visible only on Dashboard `Recent:` and `GET /api/scans/history`, not in `/history`.
- **Bug from last plan (`b4baba8`):** Replaced the card UI with a flat `Scans history` table to surface `reports/history` scans, which hid the card UI you use to move again — reverted in `0617a54` to the card layout, but now `History` shows `No confirms yet` (0 `history_groups` rows) and no scans.
- **User expectation:** History is **confirm history**, not Dashboard. Old scans (20 on disk) should also be reachable as groups like Scan report so you can `Move again`, with `MCP_ALLOW_UNAUTHENTICATED` etc. unchanged. One group at a time → one history row; two actions on same group → two rows (`history_store` keyed by `history_id` per Confirm, not per sourceFolder).

---

## 2. Desired Behavior (No Shortcuts)

### 2.1 What History Must Show

- **Exactly like Scan report, per history card — but only the moved files, and stripped to just the group:** Each `history_groups` row is **one Confirm = one card**, and that card shows **only the `history_items` for that `history_id`** — the `N files` you actually moved in that Confirm (e.g., 3 files from `Show.S01`), **not the whole scan report** (which had `123` files). Your “Why are you showing the whole report in each and every history item? You should only show the part with the files which I moved, right?” (2026-08-24) is correct — showing the whole `123`-file scan per history item was the `b4baba8` shortcut and is removed. Expand `▼` shows table `Source → Target` (same columns as Scan report: `Source`, `Target Path` with `PathPills`/`Suspect`/`Corrected`/`Cross-drive`, `Source → Target Path` input with `Browse…`, `Size`, `Delete` if applicable), `Trail` (`path_history_json` joined `→`), `Status`. **Do not show the Scan report’s summary pills (`3 Movies 83 Series 7 Skipped 123 to move`), search bar, or filter chips (`All 123`/`New 122`/`Replace 1`/`Extras 37`) in History — per your “You don’t need to show all these buttons. Just show the fucking group” (2026-08-24).**
- **Scans history is not History:** `GET /api/scans/history` (`reports/history` + `app.db` `scans`, 20 → 200) stays on **Dashboard** `Recent:` and `GET /api/scans/history` API, **not** in `/history`. History page shows **only confirmed groups** (what you moved), not every scan’s full report. If you have `0` confirms, History correctly shows `No confirms yet` — your 20 scans are still on disk and in `GET /api/scans/history`, but they are **not** History until you Confirm.

### 2.2 Data & API (No New Shortcuts)

- **Source of truth for History:** `app.db` `history_groups`/`history_items` (already `MAX_HISTORY` not applicable — keep all, prune only if >200 and user explicitly asks). `reports/history/*.json` + `app.db` `scans` remain for scan history, merged via `scan_history.list_history` (`7afa601`).
- **Migration:** On `init_db`, `_migrate_if_needed` already moves `reports/history/*.json` → `scans` table if missing; for History, ensure any file-based `history_groups.json` (if existed pre-DB) is migrated to `history_groups` — currently `history_store` is DB-only, so no file migration needed, but verify `history_groups` count before/after and do not delete.
- **API:** Keep `GET /api/history?limit=50` (groups) and `GET /api/scans/history?limit=20` (scans) separate; do not merge into one table. Frontend `HistoryPage` will call both in parallel (`Promise.all`) and render two sections.
- **No stub:** Do not return a flat `Scan ID | Date | Movies...` table for scans — must be full groups.

### 2.3 Grouping & Counts

- **Grouping:** `history_groups.group_key` = `sourceFolder` (same as Scan report `containerPath`/`sourceFolder`), `group_title` = folder name only. `history_items` keep `source_folder`/`target_path`/`path_history_json`. When rendering a scan’s history, use `report.js:groupItems` on that scan’s `items` so the grouping matches Scan report exactly (including `GENERIC_FOLDERS` fallback).
- **Counts:** Per-card `N files` and `totalSize` from `history_items`; filter chips `All`/`New`/`Replace`/`Extras` counts from that scan’s `items` (same `counts` logic as `ReportPanel.jsx:51`).

### 2.4 Edge Cases

- **No confirms yet:** Show `No confirms yet — scan and confirm a group to see it here.` (scans are **not** listed here per §2.1; they stay on Dashboard `Recent:`).
- **No scans either:** Show `No confirms yet — scan and confirm a group to see it here.`
- **Many scans (20 → 200):** Fetch only first 5 full reports eagerly, lazy-load the rest on expand (`onToggle` for that `scan_id` fetches `GET /api/scans/history/{id}` if not in `scanReports` cache) to keep `History` fast.
- **Trail:** `path_history_json` may be `null` for old rows — fallback to `source_path → target_path`.

---

## 3. Implementation Steps (Full, No Shortcuts)

> **Resolution of the earlier scans-section idea:** Steps 1–4 below used to describe adding a
> `Scans history (N)` section (old scans expandable into full report groups with `Move again`)
> **inside `/history`**. That design produced `caa293c`, which you rejected (“why the whole report
> in each history item?”) and was reverted in `7d9ece3`. It is superseded by §2.1: scans stay on
> Dashboard `Recent:` + `GET /api/scans/history`; `/history` renders confirm cards only. The steps
> below are the corrected, final implementation list.

1. **Backend data for row parity:** `history_items` gains `suspect`, `corrected`, `correction_note`,
   `cross_drive` columns (PRAGMA-based `ALTER TABLE` migration in `init_db`; table currently empty).
   `move_executor._run_confirm_task` persists them at confirm time (`_is_cross_drive(source, target)`).
2. **Live existence in API:** `history_store.list_history_groups`/`get_history_group` compute per item
   `source_exists`, `target_exists`, and `pathExists` (`Show ✓ Season ✓ File ✓` / `Folder ✓ File ✓`)
   so the frontend can reuse `PathPills` unchanged.
3. **Delete if applicable:** new endpoint `POST /api/history/{history_id}/delete-source`
   (`confirmId`) deletes the leftover source file only when `source_path` still exists on disk as a
   file; UI shows the Delete button only when `source_exists` is true (window.confirm before).
4. **HistoryPage expanded table = Scan-report row parity:** columns `Action` (action badge +
   `Cross-drive`/`Suspect`/`Corrected` badges + `PathPills`), `Source → Target Path` (source line,
   editable target input, `Browse…`), `Size` (`formatBytes(file_size)`), `Trail`, `Status`,
   Delete-if-applicable. Browse reuses the scan-report modal: refactor `BrowseModal.jsx` to export a
   presentational `FolderPicker` (props: `onPick(path)`, `onClose()`, `title`) plus the existing
   store-connected default export for the scan flow (unchanged behavior). No summary pills, no
   search bar, no filter chips anywhere in `/history`.
5. **Keep actions:** `Undo` (`POST /history/{id}/undo`) and `Save & Move Again`
   (`POST /history/{id}/retarget`) unchanged.
6. **Tests:** Add `HistoryPage.test.jsx` (mocked fetch): card header + expand, Action badges
   (`Suspect`/`Corrected`/`Cross-drive` render only when flagged), `PathPills`, size formatting,
   trail join, edit input + `Browse…` pick fills the input, `Save & Move Again` POSTs correct
   `updates`, `Undo` POSTs undo, Delete button hidden when `source_exists` false and calls
   delete-source when true; assert **no** `.summary-strip`/`.filter-chips`/`.search-bar` in
   History. Backend: extend tests for new columns persistence, `pathExists` computation, and
   delete-source guardrails (missing item → 404; nonexistent source → `deleted: false`).

---

## 4. Verification

- `python3 -m pytest tests/` → 407+ (existing `test_scan_errors.py` `test_singleton...` etc. still green)
- `npm test` in `app/ui/react` → 104 (existing `report.test.js` `groupItems` newest-first, `App.test.jsx` selection, `HistoryPage.test.jsx` new)
- `npm run build` in `app/ui/react` → `react-dist` + `docker restart jellysort` → `GET /history` shows your 1 confirm (if any) as card + `GET /api/scans/history` shows 20 scans as cards, each expandable to Scan-report groups with `Move again` (verify via `curl /api/scans/history/{id}` and UI click).

## 5. Testing Flow — Iterate Until Zero Errors (Self-Criticism) — No Shortcuts

**Do not deliver as soon as possible.** Take your time. Many things are still missing (e.g., History cannot “Move on all” groups, flat table was a shortcut). Test again and again, check what is missing, and question yourself before delivering:

- **Do not stop at first green.** After every code change, run the full matrix **again and again** until **zero failures**:

  1. `docker exec jellysort python3 -m pytest tests/ -q` → must be `407 passed` (or current count) with **no** `FAILED`, no `warnings` that hide failures. If any `FAILED`, read the full traceback, fix the root cause (not a stub), and re-run from step 1.
  2. `npm test` in `app/ui/react` → must be `12 passed` / `104 passed` with **no** `failed`. If any `failed`, open the `expect` diff, fix the component/reducer (not the test to hide the bug), and re-run from step 1.
  3. `npm run build` in `app/ui/react` → must be `✓ built` with no `ERROR: Expected ")"` etc. If any `error`, fix the JSX/TS and re-run from step 1.
  4. `docker restart jellysort` → `curl -s http://127.0.0.1:18327/health` → `{"status":"ok"}`, then `curl /api/history` + `curl /api/scans/history` + UI screenshot `http://10.69.1.164:18328/history` → History shows cards exactly like Scan report (header `▼/▶`, `Source → Target` table, `PathPills`/`Suspect`/`Corrected`, `Browse…`, filters with `✓`, `Move again` per group **and** `Move on all` for the whole scan, `Undo`). If any mismatch, fix and re-run from step 1.

- **Check what is missing before delivering:** After each green run, manually open `http://10.69.1.164:18328/history` and `http://10.69.1.164:18328/` side-by-side and compare: Does History have the same `Source → Target` table, `PathPills`, `Suspect`/`Corrected` badges, `Browse…`, `Move again` per group, **and** a top-level `Move on all` for the scan? Does `Move on all` actually call `POST /api/scans/{id}/confirm` with all `itemIds` and show queued progress? If any of those are missing or stubbed, it is still not deliverable.

**Self-criticism — learn to criticize yourself (per your instruction — never apply shortcuts):**

- After each green run, ask: *What did I assume? What did I not test? What edge case did I skip to save time to deliver quickly?* (e.g., “Did I test `filter=extra` when `valid` list rejected it?” — that was the `Extras 37` bug; “Can I Move on all groups at once?” — currently missing). Write the answer in the commit message or `plans/` notes.
- **Never deliver as soon as possible** — deliver only when the full matrix is green **and** manual History vs Scan report comparison is pixel-identical in functionality. If you catch yourself thinking “this is good enough” or “the test is too strict,” treat it as a **red flag** — the test is right, you are shortcutting. Revert the shortcut and do the full `groupItems`/`matchesFilter`/`Move on all` path.
- Every fix must be verified by **re-running the full matrix**, not just the one test you touched. Keep a checklist in this plan and tick it only after the full matrix is green.

**Status:** Plan updated per your “do not deliver as soon as possible, take time, test again and again, question yourself, many things missing, can’t Move on all” — still plan only, no code changed. Awaiting your `go` to implement exactly, no shortcuts.
