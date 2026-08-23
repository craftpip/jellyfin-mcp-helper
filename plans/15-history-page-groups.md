# 15 — History Page: Groups Exactly Like Scan Report (No Shortcuts)

> **Status: Plan — awaiting `go` to implement. No code will be changed until you approve.**

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

- **Exactly like Scan report, per history card:** Each `history_groups` row is one card with header `group_title` (`sourceFolder` name, e.g. `[bonkai77] Millennium Actress…` or `Movie.mkv`), `N files`, `confirmed_at`, `history_id` badge. Expand `▼` shows table `Source → Target` (same columns as Scan report: `Source`, `Target Path` with `PathPills`/`Suspect`/`Corrected`/`Cross-drive`, `Source → Target Path` input with `Browse…`, `Size`, `Delete` if applicable), `Trail` (`path_history_json` joined `→`), `Status`.
- **Filters + search + collapse:** Same `filter-chips` (`All`/`New`/`Replace`/`Extras` with `✓` on active, `groupItems` + `matchesFilter` + `itemSearchText` from `report.js:74`), `Search by title, path…` (rounded `999px`, `maxWidth 260` like `ReportPanel.jsx:102`), `Collapse/Expand` single toggle (`allExpanded ? Collapse : Expand`).
- **Actions per card:** `Undo` (moves files back via `POST /history/{id}/undo`) and `Save & Move Again` (edits `New Target` per `confirmId` → `POST /history/{id}/retarget` with `{confirmId, newTarget}`), plus per-group `Move again` that re-queues the same `source_path`s via `POST /api/scans/{scan_id}/confirm` or `history_store` retarget path — **not a placeholder table**.
- **Scans history also visible, but not replacing confirms:** Below (or above) the confirm cards, a collapsible `Scans history (20)` section shows past scans as groups exactly like Scan report (fetch `GET /api/scans/history?limit=20` → for each `scan_id` `GET /api/scans/history/{id}` → `mapReportItems` + `groupItems` → same `group-header`/`group-body`), with `Move again` per scan group (calls `POST /api/scans/{scan_id}/confirm` with `itemIds` of that scan’s items). This satisfies “migrate old scans so I can see them” without hiding confirms.

### 2.2 Data & API (No New Shortcuts)

- **Source of truth for History:** `app.db` `history_groups`/`history_items` (already `MAX_HISTORY` not applicable — keep all, prune only if >200 and user explicitly asks). `reports/history/*.json` + `app.db` `scans` remain for scan history, merged via `scan_history.list_history` (`7afa601`).
- **Migration:** On `init_db`, `_migrate_if_needed` already moves `reports/history/*.json` → `scans` table if missing; for History, ensure any file-based `history_groups.json` (if existed pre-DB) is migrated to `history_groups` — currently `history_store` is DB-only, so no file migration needed, but verify `history_groups` count before/after and do not delete.
- **API:** Keep `GET /api/history?limit=50` (groups) and `GET /api/scans/history?limit=20` (scans) separate; do not merge into one table. Frontend `HistoryPage` will call both in parallel (`Promise.all`) and render two sections.
- **No stub:** Do not return a flat `Scan ID | Date | Movies...` table for scans — must be full groups.

### 2.3 Grouping & Counts

- **Grouping:** `history_groups.group_key` = `sourceFolder` (same as Scan report `containerPath`/`sourceFolder`), `group_title` = folder name only. `history_items` keep `source_folder`/`target_path`/`path_history_json`. When rendering a scan’s history, use `report.js:groupItems` on that scan’s `items` so the grouping matches Scan report exactly (including `GENERIC_FOLDERS` fallback).
- **Counts:** Per-card `N files` and `totalSize` from `history_items`; filter chips `All`/`New`/`Replace`/`Extras` counts from that scan’s `items` (same `counts` logic as `ReportPanel.jsx:51`).

### 2.4 Edge Cases

- **No confirms yet:** Show `Scans history (20)` as groups (so you see old scans immediately) and hint `No confirms yet — your past scans are below, confirm a group to see it here as well.`
- **No scans either:** Show `No confirms yet — scan and confirm a group to see it here.`
- **Many scans (20 → 200):** Fetch only first 5 full reports eagerly, lazy-load the rest on expand (`onToggle` for that `scan_id` fetches `GET /api/scans/history/{id}` if not in `scanReports` cache) to keep `History` fast.
- **Trail:** `path_history_json` may be `null` for old rows — fallback to `source_path → target_path`.

---

## 3. Implementation Steps (Full, No Shortcuts)

1. **HistoryPage state** (`HistoryPage.jsx:8`): Add `scans`, `scanReports` (`scan_id → report`), `scanExpanded` (`scan_id → bool`), `scanGroupsExpanded` (`scan_id → Set/group ids` or reuse `expanded`), `scanEditing` if needed. Keep existing `groups`/`expanded`/`editing` for confirms.
2. **Load** (`load()`): `Promise.all([apiGet('/history?limit=50'), apiGet('/scans/history?limit=20')])` → `setGroups` + `setScans`; then for `scans.slice(0,5)` `apiGet('/scans/history/{id}')` → `setScanReports`. Do not replace confirms with scans.
3. **Render** (`return`): Keep existing `▼/▶` confirm cards exactly as `fe43516` (no flat table). Add above (or below, per your preference — default **above** confirms) a `Scans history (N)` section that for each `scan` renders a scan card header (`scan_id` `saved_at`, `Movies`/`Series`/`Skipped`/`To move`) that expands to **Scan-report-style groups** (`groupItems(mapReportItems(report))` → `group-header`/`group-body` with `Source → Target` table, `PathPills`, `Suspect`/`Corrected`, `Browse…`, filters, `Move again` per group via `POST /api/scans/{scan_id}/confirm` with `itemIds` of that group’s items).
4. **Filters/search:** Reuse `report.js:matchesFilter`/`itemSearchText` and `filter-chips` + `search-bar` (same `summary-strip` placement, rounded `999px`, `maxWidth 260`) inside each scan’s group view, not a separate flat filter.
5. **Actions:** For scans, `Confirm` per group and `Undo` not applicable (scans are not yet confirmed); for confirms, keep `Undo`/`Save & Move Again` as before. Do not stub `Move again` as a toast — it must call the real confirm/retarget endpoint and poll progress.
6. **Tests:** Add `HistoryPage.test.jsx` (render with mocked `GET /history` + `GET /scans/history` + `GET /scans/history/{id}`, assert `▼` cards, expand, `Source → Target` table, `Move again` calls `POST /api/scans/{id}/confirm` with correct `itemIds`).

---

## 4. Verification

- `python3 -m pytest tests/` → 407+ (existing `test_scan_errors.py` `test_singleton...` etc. still green)
- `npm test` in `app/ui/react` → 104 (existing `report.test.js` `groupItems` newest-first, `App.test.jsx` selection, `HistoryPage.test.jsx` new)
- `npm run build` in `app/ui/react` → `react-dist` + `docker restart jellysort` → `GET /history` shows your 1 confirm (if any) as card + `GET /api/scans/history` shows 20 scans as cards, each expandable to Scan-report groups with `Move again` (verify via `curl /api/scans/history/{id}` and UI click).

## 5. Testing Flow — Iterate Until Zero Errors (Self-Criticism) — No Shortcuts

**Do not stop at first green.** After every code change, run the full matrix **again and again** until **zero failures**:

1. `docker exec jellysort python3 -m pytest tests/ -q` → must be `407 passed` (or current count) with **no** `FAILED`, no `warnings` that hide failures. If any `FAILED`, read the full traceback, fix the root cause (not a stub), and re-run from step 1.
2. `npm test` in `app/ui/react` → must be `12 passed` / `104 passed` with **no** `failed`. If any `failed`, open the `expect` diff, fix the component/reducer (not the test to hide the bug), and re-run from step 1.
3. `npm run build` in `app/ui/react` → must be `✓ built` with no `ERROR: Expected ")"` etc. If any `error`, fix the JSX/TS and re-run from step 1.
4. `docker restart jellysort` → `curl -s http://127.0.0.1:18327/health` → `{"status":"ok"}`, then `curl /api/history` + `curl /api/scans/history` + UI screenshot `http://10.69.1.164:18328/history` → History shows cards exactly like Scan report (header `▼/▶`, `Source → Target` table, `PathPills`/`Suspect`/`Corrected`, `Browse…`, filters with `✓`, `Move again`/`Undo`). If any mismatch, fix and re-run from step 1.

**Self-criticism — learn to criticize yourself:**

- After each green run, ask: *What did I assume? What did I not test? What edge case did I skip to save time?* (e.g., “Did I test `filter=extra` when `valid` list rejected it?” — that was the `Extras 37` bug). Write the answer in the commit message or `plans/` notes.
- If you catch yourself thinking “this is good enough” or “the test is too strict,” treat it as a **red flag** — the test is right, you are shortcutting. Revert the shortcut and do the full `groupItems`/`matchesFilter` path.
- Every fix must be verified by **re-running the full matrix**, not just the one test you touched. Keep a checklist in this plan and tick it only after the full matrix is green.

**Status:** Plan updated with testing flow — still plan only, no code changed. Awaiting your `go` to implement exactly, no shortcuts.
