# 10 — Responsive panel (mobile / small screens)

## Status (2026-09-19 refresh — old plan was pre-retheme)

The UI was rethemed after this plan was written (dark glass, `theme.css` ~780 lines,
new `report-bar`/`dash-bar`/`group-header`/`group-toolbar` sticky stack, `browse-modal`,
transfer toasts, login glow). The old plan's selectors/values (body 20px, h1 1.4rem,
modal 90%, `start-scan` hero, old summary-strip) no longer match.

Partially done: `theme.css:767-776` has one `@media (max-width:720px)` block that
converts `#reportItems` table → cards and hides `thead`. Everything below is still
desktop-first and breaks at 390px.

Viewport meta is fine (`width=device-width, initial-scale=1.0` in `app/ui/react/index.html`).

## Problem (current theme)

- Report table uses `table-layout:fixed` + `colgroup` (34/150/flex/76/76). Without the
  720px card fallback the page scrolls sideways; skip-reason badge squeezes into its
  column; `thead th` sticky at `top:133px` assumes desktop bar heights.
- Sticky stack assumes desktop heights: `.top-bar top:8px`, `.group-header top:64px`,
  `.group-toolbar top:103px`, `#reportItems thead top:133px`. When TopBar wraps to two
  rows on mobile these offsets are wrong (headers overlap / gap).
- `HistoryPage.jsx` has its own 5-col fixed table (`150/flex/76/140/110`) with inline
  styles, `overflowX:auto` wrapper only — same overflow class as report, no card fallback.
- `.env-row` (Settings + SetupWizard Jellyfin step) is side-by-side flex
  (`gap:16px`, `.env-input flex:0 1 320px`) — squeezes label + input at 390px.
- `TopBar`: brand (40px logo + h1 1.25rem + 2-line subtitle) + `top-actions` wrap to a
  tall bar; buttons are 28–34px tall (small touch targets); scan-menu / dropdown-menu
  positioned `right:0` can clip.
- Modals (`.modal max-width:640px width:92% max-height:82vh`): `.modal-actions` stays
  row (Cancel/Start Move squeeze); `.browse-footer` (target + Cancel/Select) stays row;
  confirm FROM/TO rows use `white-space:nowrap` + ellipsis (OK) but title ellipsis only.
- Overlays: `.toast max-width:400px right:20px` (no vw cap); `.transfer-toasts
  width:380px max-width:calc(100vw-40px)` is OK; `CommandPalette` modal is inline
  `maxWidth:480px` with no vw cap.
- Forms: inputs are `0.79–0.92rem` — iOS zooms on focus below 16px; link-toggle is
  28×29px; `filter-chips`, `browse-crumbs`, `wiz-steps` (5 steps, `gap:14px`) overflow.

## Breakpoints

- `≤640px` — phones (390×844 target). Stack everything, tables → cards.
- `641–900px` — tablets. Tables scroll internally, two-col where safe.
- `>900px` — desktop unchanged.

All changes in `app/ui/react/src/styles/theme.css` (single stylesheet) + minimal JSX
class hooks where a table must become cards (HistoryPage). No color/brand changes.

## Global

- Body/panel: `body padding:0 12px 32px` stays; `.panel, .report-hero padding:12px 14px`
  → keep, tighten to `12px` at ≤640px (no 16px jump).
- Add safety: `img{max-width:100%}`, `table{display:block;overflow-x:auto}` fallback so no
  table widens the page before card conversion.
- Touch + iOS: buttons/inputs `min-height:36px` at ≤640px; text inputs
  (`target-input`, `#filterInput`, `.browse-search input`, login/cmd inputs)
  `font-size:16px` on mobile.
- Modal: at ≤640px `.modal{width:calc(100vw-24px);max-height:88vh}`,
  `.modal-actions{flex-direction:column-reverse} .modal-actions button{width:100%}`.

## Per page

### 1. TopBar (`TopBar.jsx`, `.top-bar`)
- ≤640px: `.top-bar{gap:8px;padding:10px 12px}`, `.brand-logo{32px}`, `.subtitle{display:none}`,
  `.top-actions{margin-left:0;width:100%}` buttons `flex:1 1 auto;min-height:36px`.
- Scan split + `LibraryScanDropdown` share row 1; History/Settings/Logout wrap row 2.
- Menus: keep `scan-menu`/`dropdown-menu`, add `left:0` fallback when `right:0` clips.
- Validate: logo+title one line, all buttons ≥36px, menus fully visible, no x-scroll.

### 2. Scan landing (`Dashboard.jsx` `.dash-bar`, `ActionsPanel.jsx` `.start-scan`)
- `.dash-bar` is flex-wrap: at ≤640px `.dash-actions{margin-left:0;width:100%}` buttons
  full-width; stats wrap to own line; `word-break:break-word` on library list.
- `.start-scan` is already a compact bar (not a hero): keep, `flex-wrap` stays;
  `.btn-start{width:100%;max-width:320px}` at ≤640px.
- Validate: Start Scan reachable without long scroll, no squeezed buttons.

### 3. Scan progress (`ScanProgressPanel.jsx`, `.progress-center`)
- Already column; `.progress-file{max-width:min(680px,90vw)}` is safe.
- ≤640px: `.progress-center{padding:24px 12px;min-height:40vh}`,
  `.progress-percent{font-size:1.5rem}`.
- Validate: bar shrinks, filename wraps, status readable.

### 4. Report (`ReportPanel.jsx` — existing 720px cards are the base)
- Keep current card conversion; extend at ≤640px: card rows order Action badges →
  path (input full-width 36px+) → Size+Delete row (Delete right-aligned ≥36px).
- `.report-bar`: search (`.report-search flex:0 1 200px min-width:140px`) →
  `flex:1 1 100%;max-width:none` own row.
- `.report-toolbar`: stack (`flex-direction:column;align-items:stretch`); filter chips
  wrap to 2 rows (or nowrap scroll fallback).
- `.group-header` (sticky): allow title wrap, keep `g-size` right, tap height 44px.
  `.group-toolbar`: `flex-wrap:wrap`.
- **Sticky offsets (mobile fix):** recompute or disable the `64/103/133px` stack at
  ≤640px (e.g. `group-header top:<measured-bar>`, or `position:static` for toolbar/thead
  on phones) — currently assumes single-row TopBar.
- Link-toggle 28×29px → 36×36px at ≤640px.
- Validate at 390px: page-width ≤390, thead hidden, cards readable, input fully visible,
  Delete tappable, badges on own lines.

### 5. History (`HistoryPage.jsx`)
- Same card pattern as report (needs new JSX hook — currently only `overflowX:auto`):
  hide thead at ≤640px; stack Action/Type/Path/Size/Trail/Status; Trail + Status +
  Delete full-width rows.
- Header row (inline flex: title + badges + date + id) → `flex-wrap:wrap`, date+id second
  line `0.7rem`.
- Trail popup (inline `width:92% max-width:920px`) → `width:calc(100vw-24px);padding:12px`,
  hide `#` column, Path `break-all` (already).
- Validate: header fits, cards readable, popup doesn't clip.

### 6. Settings (`SettingsPage.jsx`, `.admin-page`, `.env-row`)
- `.env-row{flex row;gap:16px}` → ≤640px `flex-direction:column;align-items:stretch;gap:8px`;
  `.env-input{flex:none;width:100%}`; secret-field buttons stay inline.
- Path/alias rows already column via inline style — keep.
- `StoragePathEditor` table (Path|Description|Remove) → stack Description below Path at
  ≤640px (or `overflow-x:auto`; prefer stacked inputs in modal).
- `admin-footer` Save → full-width `min-height:44px` at ≤640px. `McpClientSetup`
  code block already `overflow-x:auto` — keep.
- Validate: no label/input squeeze, inputs ≥36px, Save reachable, editor fits 390px.

### 7. SetupWizard (`SetupWizard.jsx`, `.wiz-*`)
- `.wiz-steps` (5 steps) → ≤640px `overflow-x:auto;gap:8px;font-size:0.75rem` (scroll, not wrap).
- `.wiz-crumbs code` ellipsis keep; Up button stays; `.wiz-dirs li` Select ≥36px.
- Jellyfin step reuses `.env-row` → inherits Settings fix. `.wiz-nav` footer wraps,
  Finish `flex:1 1 100%`.
- Validate: steps reachable, no page-level x-scroll.

### 8. Modals (Confirm `ConfirmModal.jsx`, Browse `BrowseModal.jsx`, StoragePathBrowser)
- Confirm: `.summary-strip` wraps; title 2-line max (`white-space:normal`) instead of
  single ellipsis; FROM/TO keep ellipsis + title attr; actions stacked (global).
- Browse: search input 16px + button ≥36px; `.browse-crumbs` wraps (already flex-wrap);
  `browse-row-sub` `break-all`; `.browse-footer` → column stretch, Select primary
  full-width.
- Validate: every modal fits 390px viewport, no clipped buttons.

### 9. Overlays (`Toasts.jsx`, `LogPanel.jsx`, `CommandPalette.jsx`, `LoginScreen.jsx`)
- `.toast` → add `max-width:calc(100vw-40px);right:12px;top:12px` at ≤640px.
  `.transfer-toasts` already capped — keep; counts wrap (already `anywhere`).
- Command palette inline `maxWidth:480px` → cap `calc(100vw-24px)`.
- `.log` fine (pre-wrap). Login card `max-width:400px` fits 390px; verify inputs 16px.
- Validate: toasts don't cover actions; login/palette usable at 390px.

## Validation (per element, per page)

1. `npm test` in `app/ui/react` + `python3 -m pytest tests/` (backend sanity).
2. `npm run build` in `app/ui/react` + `docker restart jellysort`.
3. SVG geometry at 390px (`browser_web_page_svg`, 390×844) for `/`, `/settings`,
   `/history`: page-width ≤390, no element `x+w>390` except intentional full-bleed,
   report thead hidden / rows are cards, skip-reason ≈ card width.
4. Screenshots at 390×844 for `/`, `/settings`, `/history`, Confirm + Browse modals open,
   SetupWizard step 1.
5. Repeat SVG + screenshots at 768×1024 (tables may scroll internally, no page overflow)
   and 1280×800 (desktop unchanged).
6. Touch: buttons/inputs ≥36px at ≤640px; inputs 16px (no iOS zoom).

## Out of scope

No color/typography rebrand, no new pages, no backend changes. Desktop pixel-identical
(all changes inside `@media` + History card hook at ≤640px).
