# 10 — Responsive panel (mobile / small screenshots)

## Problem

At 390px viewport the panel overflows horizontally and several elements collapse:

- Scan report page is **481px wide on a 390px viewport** (`data-page-width=481`, content col `335px` but report `table` is `460px` wide → ~125px overflow, page scrolls sideways).
- Skip-reason badge in report table collapses to **14px wide**, one word per line (`Lower / revision / v0 / skipped; / ...` stacked vertically over 681px height).
- Report table header `thead tr` is **319px tall** (headers wrapped vertically) — `Action / Type / Source → Target / Size` unreadable.
- `env-row` (Settings + SetupWizard Jellyfin step) is a side-by-side flex row (`gap:16px`, input `flex:0 1 320px`) — squeezes label + input on narrow screens.
- History table uses `table-layout:fixed` + 6 fixed-width columns (`150+110+90+140+110`) — same overflow class as report.
- No `@media` rules exist in `theme.css` except `prefers-reduced-motion` — everything is desktop-first.
- TopBar wraps to two rows (110px tall) — acceptable, but `top-actions` buttons crowd; scan-menu popup `max-width:min(300px,90vw)` is the only responsive-aware rule.

Viewport meta is fine (`width=device-width, initial-scale=1.0` in `app/ui/react/index.html`).

## Breakpoints

- `≤640px` — phones (390×844 target). Stack everything, tables → cards.
- `641–900px` — tablets / small laptop screenshots. Two-column where safe, tables scroll internally.
- `>900px` — current desktop layout unchanged.

All changes go in `app/ui/react/src/styles/theme.css` (single stylesheet) + minimal JSX class hooks where a table must become cards (ReportPanel, HistoryPage). No color/brand changes.

## Global

- `body { padding: 20px }` → `12px` at ≤640px; `.panel { padding: 20px }` → `12px`.
- `h1 1.4rem` stays; `.subtitle` → hide or clamp to 1 line at ≤640px (it currently forces brand block to 64px + wraps TopBar).
- Add `img { max-width: 100% }`, `table { display:block; overflow-x:auto }` fallback so no table can widen the page even before card conversion.
- Modal: `.modal { width: 90% }` → at ≤640px `width: calc(100vw - 24px)`, `max-height: 88vh`, `.modal-actions` buttons full-width stacked (`flex-direction: column-reverse`, buttons `width:100%`).

## Per page

### 1. TopBar (`TopBar.jsx`, `.top-bar`)
Current at 390px: brand (logo 44px + title + 2-line subtitle) full row, actions wrap below — works but tall.
- ≤640px: `.top-bar { gap:8px }`, `.brand-logo { 32px }`, `h1 { font-size:1.15rem }`, `.subtitle { display:none }` (title suffices; frees one row).
- `.top-actions { margin-left:0; width:100%; flex-wrap:wrap }`, buttons `flex:1 1 auto; min-height:36px` (touch targets; current 28px is small).
- Scan split-button + `LibraryScanDropdown` keep on one row (`flex:1`), History/Settings/Logout wrap to second row.
- Scan-menu popup already `max-width:min(300px,90vw)` — keep, add `left:0` fallback when `right:0` would clip.
Validate: logo+title one line, all buttons ≥36px tall, no horizontal scroll, dropdown fully visible.

### 2. Scan landing (`Dashboard.jsx`, `ActionsPanel.jsx`)
- `.summary-strip` already wraps — keep, pills `font-size:0.75rem` at ≤640px.
- Dashboard "Last scan" panel: `marginLeft:auto` pills (libraries count, Undo, View in History) currently inline — at ≤640px force `margin-left:0; width:100%` so buttons don't squeeze beside pills; buttons full-width.
- `.start-scan { min-height:calc(100vh - 170px) }` → `min-height:50vh` at ≤640px; `.btn-start { padding:14px 36px; font-size:1.05rem }` → `width:100%; max-width:320px`.
- "Your libraries" line (`join(' · ')`) → `word-break:break-word`.
Validate: no empty giant vertical gap, Start Scan reachable without scroll, pills wrap to ≤2 rows.

### 3. Scan progress (`ScanProgressPanel.jsx`, `.progress-center`)
- Already centered column; `.progress-file { max-width:min(720px,90vw) }` is responsive-safe.
- ≤640px: `.progress-center { padding:0 12px; min-height:40vh }`, `.progress-percent { font-size:1.5rem }`.
Validate: bar `max-width:640px` shrinks, filename wraps, status readable.

### 4. Report (`ReportPanel.jsx` — worst offender)
Elements: `#reportPanel` header, `.summary-strip` (4 pills + search), `.report-toolbar` (selectionSummary + filter chips + Collapse all), `.group-header`, `.group-toolbar`, `#reportItems table`.
- Summary strip: pills wrap OK today; search `.search-bar { flex:0 1 240px; min-width:180px }` → at ≤640px `flex:1 1 100%; max-width:none` (own row, full width).
- Toolbar: `#selectionSummary` + `#filterChips` + `.report-actions` → stack vertically (`flex-direction:column; align-items:stretch`); filter chips scroll horizontally (`flex-wrap:nowrap; overflow-x:auto`) OR wrap to 2 rows — prefer wrap (5 chips fit: All/New/Replace/Extras + Suspect second row, seen in snapshot at y=368/396).
- **Group header** (`.group-header`): title + count + size + arrow. At ≤640px allow title wrap (`white-space:normal`), keep `g-size` right-aligned; increase tap height to 44px.
- **Group toolbar** (`.group-toolbar`): checkbox label (flex:1, ellipsis) + Search link + Confirm/Update/Delete. At ≤640px: `flex-wrap:wrap`; `chk-text` max-width shrinks; action button `margin-left:auto`.
- **Table → cards** (the fix for the 460px overflow + 14px badge + 319px thead):
  - ≤640px: hide `thead`; each `tbody tr` becomes a card (`display:block; border:1px solid; border-radius:8px; margin:8px; padding:10px`); each `td` becomes a full-width row (`display:block; width:100%`).
  - Order in card: Action badges → Type → Source→Target (input full width, min-height 36px) → Size + Delete row (Delete right-aligned, ≥36px).
  - `.path-cell .target-input { font-size:0.92rem }` → `font-size:16px` on mobile (prevents iOS zoom-on-focus) — same for `#filterInput`, `.browse-search input`.
  - `.skip-reason` then flows naturally (no 14px column to squeeze into).
  - Keep `table-layout:fixed` desktop table for >640px untouched.
- Link toggle (28×29px) → 36×36px at ≤640px.
Validate at 390px: `data-page-width ≤ 390` (no sideways scroll), thead hidden, every row a readable card, target input fully visible without horizontal scroll, Delete tappable, badges on own lines.

### 5. History (`HistoryPage.jsx`)
Same table-overflow class as report + extra Trail/Status columns; header row is inline-style flex (title + badges + date + id).
- ≤640px: header stacks (`flex-wrap:wrap`; date + id drop to second line, `font-size:0.7rem`).
- Table → same card pattern as report: hide thead; Action/Type/Path/Size/Trail/Status stack; Trail button + Status badge + Delete full-width rows.
- `overflowX:auto` wrapper stays as safety for 641–900px.
- Trail popup (fixed, `width:92%; max-width:920px`) → at ≤640px `padding:12px; width:calc(100vw - 24px)`; trail table Path column `word-break:break-all` (already) + hide `#` column.
Validate: group header fits without ellipsis overflow, cards readable, popup doesn't clip.

### 6. Settings (`SettingsPage.jsx`, `.admin-page`, `.env-row`)
- `.admin-page { max-width:1080px }` fine.
- `.env-row { flex row; gap:16px; input flex:0 1 320px }` → at ≤640px `flex-direction:column; align-items:stretch; gap:8px`; `.env-input { flex:none; width:100% }`; secret-field buttons stay inline (Reveal/Clear small).
- Path/alias rows already force column via inline style — keep.
- `StoragePathField` pills + Edit button row wraps OK; `StoragePathEditor` table (`Path | Description | Remove`) → at ≤640px Description column stacks below Path (or allow `overflow-x:auto` — editor is a modal, prefer stacked inputs).
- `admin-footer` Save button → full-width at ≤640px (`width:100%; min-height:44px`).
- `McpClientSetup` code block already `overflow-x:auto` — keep.
Validate: no label/input side-squeeze, every input ≥36px tall, Save reachable, editor modal fits 390px.

### 7. SetupWizard (`SetupWizard.jsx`, `.wiz-*`)
- `.wiz-steps` (5 steps horizontal) → at ≤640px allow wrap or horizontal scroll (`overflow-x:auto; gap:8px; font-size:0.75rem`); current `gap:14px` overflows with 5 labels.
- `.wiz-crumbs code` (cwd path) already ellipsis — keep; Up button stays.
- `.wiz-dirs li` (folder + Select) → keep row, Select button ≥36px.
- Jellyfin step reuses `.env-row` → inherits Settings stacked fix.
- `.wiz-nav` footer (Skip + spacer + Back/Next/Finish) → at ≤640px wrap; Finish `flex:1 1 100%` primary.
Validate: all 5 steps visible (scroll or wrap), each wizard body fits without page-level horizontal scroll.

### 8. Modals
- **Confirm** (`ConfirmModal.jsx`): `.summary-strip` wraps; `.confirm-list` rows (badge + title ellipsis + size + cross-drive) → at ≤640px title wraps to 2 lines max (`white-space:normal`), FROM/TO paths keep ellipsis (title attr preserves full path); modal-actions stacked full-width.
- **Browse/FolderPicker** (`BrowseModal.jsx`): `.browse-search` (input + Search btn) → input `font-size:16px`, button ≥36px; `.browse-crumbs` wraps (already flex-wrap); `.browse-list` rows: `browse-row-main` + `browse-row-sub` (monospace path) → sub `word-break:break-all`; `.browse-footer` (`Target: ...` + Cancel/Select) → stack (`flex-direction:column; align-items:stretch`), Select primary full-width.
- **StoragePathBrowser** (nested modal in Settings): same as Browse + `wiz-dirs` rows.
Validate: every modal opens fully inside 390px viewport, no clipped buttons, Select/Start Move tappable.

### 9. Overlays (`Toasts.jsx`, transfer toasts, `LogPanel.jsx`, `CommandPalette.jsx`, `LoginScreen.jsx`)
- `.transfer-toasts { width:380px; max-width:calc(100vw - 40px) }` already responsive — keep; verify header/counts wrap (they do: `overflow-wrap:anywhere`).
- `.toast { max-width:400px }` → add `max-width:calc(100vw - 40px); right:12px; top:12px` at ≤640px.
- `.log` fine (pre-wrap).
- Command palette: check width — cap at `calc(100vw - 24px)`.
- Login card `max-width:380px` + `padding:24px` page — already fits 390px; verify inputs 16px font (no iOS zoom).
Validate: toasts don't cover action buttons; login usable at 390px.

## Validation (per element, per page)

1. `npm test` in `app/ui/react` (frontend suite) + `python3 -m pytest tests/` (backend untouched, sanity).
2. `npm run build` in `app/ui/react` + `docker restart jellysort`.
3. SVG geometry at 390px (`browser_web_page_svg`, viewport 390×844) for `/`, `/settings`, `/history`:
   - `data-page-width ≤ 390` (no horizontal overflow) — currently 481 on `/`.
   - No element with `data-x + data-width > 390` except intentional full-bleed.
   - Report thead hidden / rows are cards; skip-reason width ≈ card width (not 14px).
4. Screenshots at 390×844 for `/`, `/settings`, `/history`, plus Confirm + Browse modals open and SetupWizard step 1: eyeball every element above.
5. Repeat SVG + screenshots at 768×1024 (tablet: tables may scroll internally, no page overflow) and 1280×800 (desktop unchanged).
6. Touch: buttons/inputs ≥36px at ≤640px; inputs 16px font (no iOS zoom).

## Out of scope

No color/typography rebrand, no new pages, no backend changes. Desktop layout pixel-identical (all changes inside `@media` + card conversion at ≤640px).
