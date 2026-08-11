# React Migration — Web UI

Migrate the vanilla.js single-file panel (`app/ui/index.html`, 1711 lines) to a React.js app. **The legacy panel must stay alive and fully functional at `/` for the entire migration.** Nothing ships to `/` until the React app reaches full parity. It is crucial that **everything** in the vanilla app is migrated — no feature, helper, or interaction is dropped.

## Decisions (owner, Aug 2026)

- **Language:** JavaScript (not TypeScript). Port mirrors the vanilla code closely.
- **Styling:** Port the existing GitHub-dark stylesheet verbatim. Visual parity is a hard requirement; no UI framework, no Tailwind.
- **Route strategy (final):** The React app is the **main UI at `/`**. The legacy panel moved to `/legacy` (308 from `/legacy`). Old `/react` bookmarks redirect to `/` (308); `/assets` and `/react/assets` both serve the built bundle. Both proxy through the same existing `/mcp` endpoint.
- **State management:** React Context + `useReducer` (no new dependencies). One app store mirrors the vanilla module-level globals.

## Status (Aug 2026)

- **Phase 11 complete — route swap done:** `/` serves the React app (verified live: connect, 9 library scan buttons, fresh scan → auto-report). Legacy panel serves at `/legacy/` with a "React UI →" link back to `/`; React top-bar has "← Legacy UI" to `/legacy/`.
- 24 Vitest + RTL tests green (`npm test` in `app/ui/react`, 4 files); 117 backend pytest tests green.
- Live parity walk completed against the legacy panel (progress/toasts, log, toolbar, filters, selection, path edit, confirm modal, skip groups, row limit). One deliberate legacy-bug fix applied to the React port: single-item groups can now edit their target path (legacy reverts every edit — see "Path editing for solo groups" below).
- Verified in a real browser: connect (18 tools), 9 library scan buttons, full scan → report auto-load, summary pills, filter chips, search, default selection, target path edit persistence, confirm modal preflight (summary pills + rows + Start Move), skip-group toolbar (All/None/Delete Selected), row-limit all.

## Current state of the app

- `app/ui/index.html` — entire UI in one file: HTML + CSS + vanilla JS.
- `app/ui/server.py` — FastAPI app serving `index.html` at `/` and proxying JSON-RPC to the MCP port at `/mcp` (GET/POST/OPTIONS, 300s timeout, 502 JSON on connect failure).
- The UI is a thin JSON-RPC 2.0 client. Every action is one MCP tool call (`tools/call`) or `tools/list`. No backend behavior needs to change for the migration.

## Target architecture

```
app/ui/
  index.html          # legacy vanilla panel (stays live, later moves to /legacy)
  server.py           # + static mount for React build, /react route, later / swap
  react/              # NEW: React source (Vite)
    src/
      main.jsx
      App.jsx
      store/AppStore.jsx        # Context + useReducer mirroring vanilla globals
      mcp/mcpClient.js          # JSON-RPC wrapper (mcpCall, mcpListTools)
      utils/format.js           # formatBytes, formatConfirmPhase, fileName, escHtml
      utils/path.js             # smart path sync (syncPathChanges)
      hooks/usePolling.js       # scan + confirm auto-poll (2s)
      components/
        TopBar.jsx              # title, subtitle, connection status pill
        Toast.jsx / LogPanel.jsx
        ActionsPanel.jsx        # Start Scan, Get Report, Confirm Selected, Library Scans
        ScanProgressPanel.jsx
        ReportPanel.jsx         # summary pills, search, filters, toolbar, table
        ReportGroups.jsx        # grouped collapsible table
        ConfirmModal.jsx        # blocking preflight + progress modal
        Badges.jsx / PathPills.jsx / FilterChips.jsx
      styles/theme.css          # ported verbatim from index.html <style>
    vite.config.js              # dev proxy: /mcp -> http://localhost:18329
    package.json, index.html
  react-dist/         # Vite build output (committed? see deploy section)
```

### Development vs deployment

- **Dev:** `npm run dev` in `app/ui/react` — Vite serves the React app on its own port and proxies `/mcp` to `http://localhost:18329` (the running container's UI port). React hots-reloads; the legacy panel keeps working on 18329.
- **Deploy preview:** `npm run build` → `react-dist/`; open `http://<host>:18329/react/`. Legacy still at `/`.
- **Final:** after parity sign-off, `server.py` serves React at `/`, legacy at `/legacy`.

### Backend changes (`app/ui/server.py`)

Only static serving changes; `/mcp` proxy is untouched.

1. Serve `react-dist/` as static files under `/react/assets`.
2. Route `GET /react` (and `/react/`) → `react-dist/index.html` (SPA fallback).
3. **Final phase:** `GET /` → React `index.html`; `GET /legacy` → legacy `index.html`.

## Migration phases

Each phase ends with the legacy panel still live at `/` and the React app at `/react` behaving identically. Verify each phase against the parity checklist.

### Phase 0 — Scaffold
- [x] `app/ui/react/` via Vite (react template, JavaScript).
- [x] Add `react`/`vite`/`@vitejs/plugin-react` to a new `app/ui/react/package.json` (independent from the Python deps).
- [x] Copy `index.html` `<style>` block into `styles/theme.css` verbatim.
- [x] Vite dev proxy `/mcp` → `http://localhost:18329`.
- [x] Add `server.py` static mount + `/react` route (deploy preview works).

### Phase 1 — Shell & plumbing
- [x] `mcp/mcpClient.js`: `mcpCall(name, args)`, `mcpListTools()` — port verbatim (JSON-RPC 2.0, id = Date.now(), parse `result.content[0].text`, throw on `json.error`).
- [x] `store/AppStore.jsx`: `scanId, confirmActive, scanRunning, pollTimer, currentItems (with _liveTarget), currentSkippedItems, jellyfinLibraries, currentFilter, rowLimit, reportAll, reportGroups`.
- [x] Toast system (info/good/err, auto-dismiss 3.5s) and Log panel (collapsible `<details>` at bottom, colored lines, auto-scroll).
- [x] TopBar with connection status pill (connecting / connected (N tools) / error).
- [x] `utils/format.js`: `formatBytes`, `formatConfirmPhase`, `fileName`, `escHtml`, `copyText`.

### Phase 2 — Connection & libraries
- [x] On mount: `tools/list` → status pill + log. Then `get available jellyfin libraries list` → `jellyfinLibraries`.
- [x] Library scan buttons in the Actions panel; per-button disable while a scan runs; log + toast messages (`trigger jellyfin library scan`).
- [x] Auto-load report on connect if one exists.

### Phase 3 — Scan start & progress
- [x] Start Scan → `move new downloads scan`; button → "Scanning...", disabled; progress panel appears; auto-poll.
- [x] ScanProgressPanel: fill %, info rows (ID, status, processed/total, current file, elapsed, ETA), `progress-running` glow while running, scroll-into-view when it appears.
- [x] Poll every 2s via `usePolling` (`get move new downloads scan progress`); toast only on state transitions (started/completed/failed) — no per-tick toast spam.
- [x] On completed: toast, hide progress, auto-fetch report after 500ms.

### Phase 4 — Report: summary, search, filters, toolbar
- [x] ReportPanel appears on report load; hint + legend (✓ exists / ✗ created / cross-drive).
- [x] Summary pills: Movies, Series, Skipped, Actions Needed; clickable scan_id (copy); Collapse all / Expand all buttons.
- [x] Search input (row-text match), row-limit select (50/100/500/all) with "showing X of Y" hint.
- [x] Filter chips with live counts: All, New, Replace, Existing path, New path.
- [x] Toolbar: selection summary + Select All / Select None / Select existing / Select all new / Select all existing (disabled until items exist).
- [x] Item mapping from report JSON (derive title/season/episode from targetPath, confirmId, action, pathExists, fileExists, fileSize, crossDrive).

### Phase 5 — Report: grouped table
- [x] Group by title; collapsible headers (title, item count, total size).
- [x] Group toolbar: group checkbox, title, DuckDuckGo search link, All/None; action groups get Update Paths + Confirm; skip-only groups get Delete Selected.
- [x] Actionable rows: default-checked checkbox, Action badge (New/Existing), cross-drive badge, path-exists pills (series Show/Season/File, movie Folder/File) with ✓/✗ marks + tooltips, Episode column (series), Source→Target cell (mono source name + editable target input), Size, Actions column (Delete).
- [x] Skipped rows: unchecked skip-check, Skipped badge, skip-reason box, source path, Size, Delete.
- [x] Empty state placeholder ("No items to review.").

### Phase 6 — Selection logic
- [x] `setCheckedItems` modes: all / none / existing / move / replace.
- [x] Group header checkbox syncs to all rows; row changes update group header.
- [x] Selection summary recomputes against visible (post-filter) rows; Confirm Selected enabled state.
- [x] Skipped rows excluded from selection/confirm logic.

### Phase 7 — Path editing & updates
- [x] Editable target inputs; per-group Update Paths → `update move new downloads scan` with only changed `{confirmId, targetPath}`; toast + refresh `originalTarget`.
- [x] Smart path sync (`syncPathChanges`): compute prefix/chunk diff; propagate to sibling rows **in the same group only**; revert the edited row if nothing synced.
- [x] Paste handling (debounce sync to final value); Enter in input focuses an Update Paths button.

### Phase 8 — Confirm modal (blocking)
- [x] Preflight: title ("Confirm Move — …"), pills (Items, Move, Replace, Total size), cross-drive warning box, first 8 rows (+N more) with badge/title/size/cross-drive badge.
- [x] Start Move → `confirm move new downloads scan` (scanId + itemIds).
- [x] Progress view: phase, overall %, counts (moved/replaced/failed), elapsed, overall ETA, last update; Current File section (source, target, size, copied, speed, file ETA, file %); cross-drive note.
- [x] Non-dismissable while running; Done button on completion/failure.
- [x] Poll every 2s (`get move new downloads scan confirm progress`); on completed toast with counts + auto-fetch report after 800ms.
- [x] Guard: no new confirm while `confirmActive`.

### Phase 9 — Delete source
- [x] Per-row Delete (actionable + skipped) with native confirm → `delete move new downloads scan items` → re-fetch report.
- [x] Group "Delete Selected" for skip groups.

### Phase 10 — Parity verification (full)
- [ ] Walk the parity checklist below feature by feature, legacy vs React.
- [x] `python3 -m pytest tests/` still green (no backend regressions).
- [x] Add Vitest + React Testing Library component tests for the core behaviors (store reducer, filter logic, smart path sync, selection, confirm modal states, mcp client error paths).

### Phase 11 — Route swap
- [ ] `server.py`: `/` → React, `/legacy` → `index.html`.
- [ ] Remove old `/react` route (or keep as alias).
- [ ] Update README / INSTALL / AGENTS.md UI references.
- [ ] Final `docker compose build && docker compose up -d` + smoke test the whole flow on `/`.

## Feature parity checklist (EVERYTHING in index.html)

Map each vanilla item to its React equivalent. Nothing below may be dropped.

**Global / shell**
- [ ] Header: title "JellySort", subtitle "Scan, review, and move download files into your media library".
- [ ] Connection status pill: `connecting...` / `connected (N tools)` / `error: …` with `.connected` / `.error` classes.
- [ ] Toasts (info/good/err), auto-remove 3.5s, top-right.
- [ ] Log panel: collapsible `<details>`, monospace, colored `.info/.good/.err/.warn` lines, auto-scroll to bottom.
- [ ] All button styles: default, `.primary`, `.warn`, `.danger`, `.small`; disabled state.
- [ ] Badges: `.badge.move/replace/skip`, `.badge.action-move/action-replace/action-skip`, `.crossdrive-badge`.
- [ ] Status pills (`✓/✗` + folder/season/file icons, tooltips).
- [ ] Spinner, progress-bar fill, `progressGlow` animation.
- [ ] Filter chips, summary pills, group header/body, warn-box, modal styles, hint/legend/flow.
- [ ] `max-width: 1600px` layout, dark `#0d1117` theme, focus-visible styles.

**State & lifecycle**
- [ ] `scanId, confirmActive, scanRunning, pollTimer, currentItems, currentSkippedItems, jellyfinLibraries, currentFilter, rowLimit, POLL_INTERVAL_MS=2000`.
- [ ] Per-item `_liveTarget` tracking for smart sync + originalTarget comparison.

**Connection flow**
- [ ] `checkConnection` on load: tools/list → status; load libraries; render "Scan {name}" buttons; auto-load report.
- [ ] `triggerLibraryScan(name)`: disable all buttons during call, log + toast start/success/error, re-enable.

**Scan**
- [ ] Start Scan: guard on running/confirm; disable + "Scanning..."; log start; hide progress; show 0% panel; call `move new downloads scan`; store scanId; log + toast; poll.
- [ ] Progress panel: % fill, info rows (ID/status/processed/total/current file/elapsed/ETA), running glow, scroll-into-view.
- [ ] `pollScanProgress`: on no-scan hint → hide progress, reset scanId/scanRunning; on completed → toast, hide, auto `fetchReport` after 500ms; on running → re-poll 2s; toasts only on transitions.

**Report**
- [ ] `fetchReport`: no-report hint → hide panel, reset state; still-running → warn + return; else render + log "N actions pending".
- [ ] `renderReport`: summary pills (Movies, Series, Skipped, Actions Needed with color), clickable copyable scan_id, Collapse all / Expand all.
- [ ] `renderItemsFromReport`: map actionable + skipped to row shape (title/season/episode from target path); reset filter + search.
- [ ] `renderItemsFromSlice`: row limit, `_reportAll`, per-item `_liveTarget` init, empty state, "Showing X of Y" hint.
- [ ] Filter chips with counts; `setFilter`; `applyRowLimit`.
- [ ] `renderGroupedTable`: groups keyed by title, collapsible, per-group total size; flat index map for lookups.
- [ ] `groupItems`, `toggleGroup`, `toggleAllGroups`, `applyFilter` (query + action + fileExists; hide empty groups), `updateSelectionSummary`.
- [ ] Group header checkbox sync (`syncGroupHeaderChecks`); `setCheckedItems(all/none/existing/move/replace)`.
- [ ] Path-pill rendering per item type; STATUS_ICONS; `escHtml` everywhere user data is rendered.

**Path editing**
- [ ] `.target-input` per actionable row, mono font, prefilled with targetPath.
- [ ] `syncPathChanges`: group-scoped prefix/chunk diff propagation; revert-on-no-match.
- [ ] Paste debounce; Enter→focus Update Paths.
- [ ] `applyGroupTargetEdits`: only changed items → `update move new downloads scan`; toast + originalTarget update.

**Confirm modal**
- [ ] `openConfirmModal(itemIds, label)`: guard confirmActive; build pills (Items/Move/Replace/Total size); cross-drive warn box with text; list first 8 + "+N more".
- [ ] `runConfirm`: set running state; hide cancel/start; call `confirm move new downloads scan`; poll.
- [ ] `renderConfirmModalProgress`: phase labels (`idle/preparing/stopping_seeding/moving/deleting_source/triggering_jellyfin/completed/failed`), overall % + meta, current-file section, note (cross-drive fallback), Done button on done/failed, non-dismissable while running.
- [ ] `pollConfirmProgress`: complete → counts toast + `fetchReport` after 800ms; failed → stop; running → re-poll 2s; errors handled with toast + state reset.
- [ ] `confirmSelected` from toolbar + `confirmGroup` per group; "Confirm Selected" label updates while moving.

**Delete**
- [ ] `deleteSourceItem` (per-row) and `deleteSelectedSkipped` (skip groups) with confirm dialogs → `delete move new downloads scan items` → re-fetch report. Blocked while confirm running.

**Cleanups (do NOT replicate legacy bugs)**
- [ ] Single `renderPathExistsPill` (legacy defines it twice — bug).
- [ ] Remove dead `toggleAll`, unused `parseReportMd`, dead tab bar (only one tab exists).
- [ ] Per-tick poll toasts removed (toast only on transitions).
- [ ] Favicon: inline SVG (fixes 404).

## Testing strategy

- **Unit/component (new):** Vitest + React Testing Library in `app/ui/react`. Cover: store reducer transitions, report item mapping, group/filter logic, `syncPathChanges`, selection modes, confirm modal states, mcp client success/error, `formatBytes`/`formatConfirmPhase`.
- **Backend (existing):** `python3 -m pytest tests/` must stay green throughout (no backend behavior changes).
- **Parity (manual per phase):** run the legacy panel and React side-by-side against the same backend; exercise each checklist row in both and compare. Re-run the full checklist before Phase 11.
- **Browser verification:** use the dev-server URL for the React app and `http://<host>:18329/` for legacy.

## Deployment & commands

- **Run tests:** `python3 -m pytest tests/`
- **React install/dev:** `cd app/ui/react && npm install && npm run dev`
- **React build:** `cd app/ui/react && npm run build` → `react-dist/`
- **Apply to container:** the compose file bind-mounts `.` to `/app`, so a fresh `react-dist/` is visible after restart; follow the documented flow `docker compose build && docker compose up -d` and verify at `/react`.

## Risks & gotchas

- **Do not touch `/mcp` semantics.** The React client must produce byte-compatible JSON-RPC requests.
- **Polling timing:** keep 2s scan/confirm polling; a shorter or missing poll breaks progress UX.
- **Smart path sync is subtle:** the legacy diff/sync logic (`_syncingPaths` reentrancy guard, paste debounce, group-scoping by `item.title`) must be ported exactly — it is the most likely place to regress.
- **Selection accounting** ties to *visible* (filtered) rows; port `updateSelectionSummary` carefully.
- **Escaping:** all user-controlled strings (titles, paths, reasons) must go through the same escaping React provides; never use `dangerouslySetInnerHTML` where a component can render directly.
- **Docker:** image is built from `.` context and bind-mounted; frontend changes need `npm run build` + container restart (not just a source save).
- **Legacy stays canonical until sign-off.** Only flip the `/` route after the Phase 10 checklist passes.

## Related

- `plan/01-ui-ux-overhaul.md`, `plan/02-ui-ux-review-aug-2026.md` — the legacy UI already implements most of these; during the React port, carry the implemented behavior forward (confirm modal, filter chips, cross-drive clarity, state-aware buttons, auto-load report). Do not backslide on items already done.
- AGENTS.md "Known Patterns" — path-sync group scoping, auto-load report on scan complete / page load, Jellyfin library scan semantics.
