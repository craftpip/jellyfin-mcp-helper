# 13 — Port report responsive/mobile treatment to the History page

## Status

Report page responsive work is DONE (mobile cards, sticky headers, no inflated inputs — see
`app/ui/react/src/styles/theme.css` `@media` blocks below). The History page only has a partial
mobile fallback at `≤640px` and none of the report's card chrome / sticky stack. This plan ports
the report's responsive treatment 1:1 to `HistoryPage`.

Part of plan `10-responsive-panel.md` §5 (History) was never finished; this is the completion,
scoped to exactly what the report already does.

## Current state — what the report has (source of truth, theme.css)

1. `@media (max-width:730px)` card conversion (theme.css:776-785):
   `#reportItems table thead { display:none }`, table/tbody/tr/td → `display:block;width:100%`,
   `#reportItems tbody tr` = card (`border:1px solid var(--jf-border-soft); border-radius:12px;
   margin-bottom:8px; padding:4px 6px; background:rgba(255,255,255,0.015)`), `td { border:none;
   padding:5px 10px }`.
2. `@media (max-width:730px)` 2-line card grid (theme.css:787-813): `tbody tr` =
   `display:grid; grid-template-columns:auto minmax(0,1fr) auto auto; gap:4px 4px;
   align-items:center`; td nth-child placements (checkbox/action/…/size line 1, full-width path
   line 2); `.action-cell { flex-direction:row; flex-wrap:wrap }`, `.action-top { flex:none }`,
   `.action-type` ellipsis.
3. Sticky stack KEPT on mobile (recent fix): `.group-header` (top:64px), `.group-toolbar`
   (top:103px), `#reportItems thead th` (top:133px) have **no** `position:static` override.
4. `@media (max-width:640px)`: `.target-input` font-size kept at `0.78rem` (no 16px inflation),
   report target-input `min-height:38px` bump removed, `.group-toolbar` no `min-height`,
   row checkbox `transform:translate(3px,3px)`.
5. Report toolbar stacks (`.report-toolbar` column, `.filter-chips` wrap, `.report-search`/
   `.report-actions` full-width).

History today (theme.css:894-909): `≤640px` only — thead hidden, `tbody tr` grid
`minmax(0,1fr) auto auto` `gap:4px 10px` with Action/Path full-width rows + Size/Trail/Status row 3,
`.history-header` wraps, `.trail-paths` first col hidden. No card chrome, no `≤730px` block,
no sticky headers, action-cell not flattened.

## Scope

Port the report's responsive treatment to the History page. CSS only, single file
`app/ui/react/src/styles/theme.css`, plus one JSX class hook on the table's scroll wrapper so
sticky can work. Desktop (`>730px`) must stay pixel-identical.

## Tasks

1. **Card conversion at `≤730px` (mirror report block 1).**
   Move history's thead hide from the `≤640px` block up to a new `@media (max-width:730px)` block
   and add the same card chrome scoped to `.history-page`:
   ```css
   @media (max-width: 730px) {
     .history-page .report-table thead { display: none; }
     .history-page .report-table, .history-page .report-table tbody,
     .history-page .report-table tr, .history-page .report-table td { display: block; width: 100%; }
     .history-page .report-table tbody tr {
       border: 1px solid var(--jf-border-soft); border-radius: 12px;
       margin-bottom: 8px; padding: 4px 6px; background: rgba(255,255,255,0.015);
     }
     .history-page .report-table td { border: none; padding: 5px 10px; }
   }
   ```
   Delete the now-dup `thead` hide from the `≤640px` block.

2. **2-line card grid at `≤730px` (mirror report block 2), 5 columns.**
   History has no checkbox but adds Trail + Status, so use
   `grid-template-columns: auto minmax(0,1fr) auto auto auto` (5 cells, path spans line 2):
   ```css
   @media (max-width: 730px) {
     .history-page .report-table tbody tr {
       display: grid;
       grid-template-columns: auto minmax(0, 1fr) auto auto auto;
       gap: 4px 4px;
       align-items: center;
     }
     .history-page .report-table td { width: auto; overflow: visible; }
     .history-page .report-table td:nth-child(1) { grid-column: 1; grid-row: 1; }          /* Action */
     .history-page .report-table td:nth-child(2) { grid-column: 1 / -1; grid-row: 2; }      /* Source→Target */
     .history-page .report-table td:nth-child(3) { grid-column: 3; grid-row: 1; text-align: right; } /* Size */
     .history-page .report-table td:nth-child(4) { grid-column: 4; grid-row: 1; }           /* Trail */
     .history-page .report-table td:nth-child(5) { grid-column: 5; grid-row: 1; text-align: right; } /* Status */
   }
   ```

3. **Flatten `.action-cell` (mirror report §2).** Same row direction + wrap + `action-top
   flex:none` + `action-type` ellipsis, scoped `.history-page .action-cell` (+ `.action-top`,
   `.action-type`). History's extra badges (cross-drive / suspect / corrected / PathPills) wrap
   inside the cell on phones just like report does.

4. **Sticky headers on mobile (user directive — sticky is wanted, no `position:static`).**
   History currently has no sticky at all. Mirror the report stack:
   - `.history-page .history-header { position: sticky; top: 64px; z-index: 20; }` (mirror
     `.group-header`, theme.css:438) — needs an opaque background (set the panel bg).
   - `.history-page .report-table thead th { position: sticky; top: 103px; z-index: 19; }`
     (mirror `.group-toolbar`, theme.css:467) with opaque bg `#141b2d` like report's thead.
   - **JSX hook:** the table is wrapped in an inline `overflowX:'auto'` div (HistoryPage.jsx:216),
     which creates a scroll container and kills sticky. Add `className="table-scroll"` to that
     wrapper and at `≤730px` set `.history-page .table-scroll { overflow: visible; }`. This is the
     only JSX change and it is required for sticky to function.
   - Do not add any `position:static` override on mobile.

5. **`≤640px` input parity (mostly done).** `.history-page .target-input` already keeps
   `0.78rem` (theme.css:832-835) — keep. No `min-height:38px` bump exists for history — do not add
   one. No checkboxes in history — the report checkbox `translate(3px,3px)` rule does not apply
   (it is scoped `#reportItems .report-table`).

6. **Keep existing `≤640px` history rules beyond tds/grid** once their equivalents move to
   `≤730px`: `.history-header { flex-wrap:wrap }` (+ strong full-width), `.trail-paths`
   first-column hide. Keep history-only columns/rows/badges per the report/history sync rule
   (Trail/Status, Undo + Save & Move Again, conditional Delete) — do not remove.

## Decisions to confirm (implementer asks before coding)

1. Grid mapping: the report-style **2-line** card above (Action + Size + Trail + Status on line 1,
   full-width path line 2) replaces the current 3-line layout. Recommended — closest to the report.
   Alternative: keep 3 lines (unchanged structure + card chrome only).
2. Sticky offsets reuse the report's `64px`/`103px` (same sticky TopBar). Confirm they look right
   on a phone; adjust only if the numbers measured differ.

## Validation

1. `python3 -m pytest tests/` (backend sanity) — should be untouched/green.
2. `npm test` in `app/ui/react` (frontend, incl. `HistoryPage.test.jsx`).
3. `npm run build` in `app/ui/react` + `docker restart jellysort`.
4. Grep the built bundle for the new scoped rules (`.history-page .report-table tbody tr` grid,
   `.history-header` sticky, missing `position:static`).
5. SVG geometry at 390×844 on `/history`: page-width ≤390, no x-scroll, thead hidden, rows are
   cards, path line readable, sticky header sticks while scrolling, status/trail tappable.
6. Repeat at 768×1024 (tables may scroll internally, no page overflow) and 1280×800 (desktop
   unchanged). No element `x+w>viewport` except intentional full-bleed.

## Out of scope

No color/typography rebrand, no backend changes, no changes to the Report page, no new pages.
Desktop History stays pixel-identical.