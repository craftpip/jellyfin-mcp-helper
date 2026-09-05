# 08 — Episode/Type column labels + ascending sort

> **Status: IMPLEMENTED 2026-09-05 — header is `Type` per user confirmation.**
>
> Deviations from proposal: column named `Type` (not `Type / Episode`).
> Backend also required a fix: `extra_type` was never persisted on
> `ScannedItem` (orchestrator now sets it; presenters/history/DB carry it).

## Goal

In the listing, the "Episode" column currently only appears for series groups
and only shows `SxxEyy`. Extend it so every row states its kind:

- series episode → `SxxEyy` (existing, e.g. `S01E04`)
- movie → `Movie`
- extra → `Extra` (plus `extra_type` detail when present, e.g. `Extra · trailer`)
- skip rows → same labels (derived from `itemType`, not blank)

And order rows within each group in **ascending** order (S01E01 before S01E02,
etc.) instead of the current newest-first order.

Applies to both the Scan report (`ReportPanel`) and confirm history
(`HistoryPage`), which duplicate the same column logic.

## Current behavior (evidence)

- `app/ui/react/src/components/ReportPanel.jsx:213` — `isSeries = group.items[0].itemType === 'series'`; header at `:276` (`{isSeries && <th>Episode</th>}`) and cell at `:383` (`{isSeries && <td>{item.episode}</td>}`) only render for series-first groups. Movie/extra groups have **no** column at all; mixed groups (grouped by `sourceFolder`, can mix kinds) mis-render.
- `app/ui/react/src/components/ReportPanel.jsx:321`, `:383` — skip rows render an empty `<td />` for the episode slot.
- `app/ui/react/src/components/HistoryPage.jsx:199,207,223-224,253` — same pattern: `isGroupSeries = items.some(...=== 'series')`, conditional `<th>Episode</th>`, cell derived from `target_path.match(/S\d{2}E\d{2,3}/i)` only.
- `app/ui/react/src/utils/report.js:6-53` (`mapReportItems`) — derives `episode` for series only; drops `extraType` (backend `ScannedItem.extra_type` in `app/models/schemas.py:44` never reaches the UI); no `typeLabel` field.
- `app/ui/react/src/utils/report.js:75-100` (`groupItems`) — inner sort is **newest-first descending**: `g.items.sort((a,b) => (b._idx ?? 0) - (a._idx ?? 0))`, groups likewise descending by max `_idx`. So S01E04 shows above S01E01.

## Proposed behavior

### 1. Column: always visible, renamed "Type / Episode"

- Header: always render (both panels), label `Type / Episode` (width ~110px). Keeps table alignment stable across movie/series/extra/mixed groups.
- Cell value via new `item.typeLabel` computed in `mapReportItems` (single source of truth, both panels consume it):
  - `itemType === 'series'` + `episode` present → `episode.toUpperCase()` (e.g. `S01E04`)
  - `itemType === 'series'` without parseable episode → `Series` (fallback, never blank)
  - `itemType === 'movie'` → `Movie`
  - `itemType === 'extra'` → `Extra` or `Extra · {extraType}` when `extraType` non-empty
  - `itemType === 'skip'` / unknown → `—` for skip rows without a kind, else the kind label above
- Skip rows in `ReportPanel` show the label too (replaces the empty `<td />`).
- `HistoryPage` uses the same helper instead of its inline regex (also fixes lowercase `s01e04` → uppercase display).
- Search (`itemSearchText`) includes `itemType` + `typeLabel` so `movie`/`extra`/`s01e04` queries match.

### 2. Sort: ascending within each group, group order unchanged

- **Within-group** sort (both panels) by sort key ascending:
  1. kind rank: `series (0)` → `movie (1)` → `extra (2)` → `skip/other (3)`
  2. series: numeric `(season, episode)` parsed from `SxxEyy` (fallback: `episode` string, then `targetPath`)
  3. movie/extra: `targetPath` (fallback `sourcePath`) alphabetical, case-insensitive
  4. tiebreak: `_idx` ascending (stable, oldest candidate first)
- **Group order unchanged** (still newest group first by max `_idx` descending) — only row order inside a group flips from descending to ascending. Rationale: group recency is the scan-discovery order users rely on; changing it would bury new downloads.
- `HistoryPage` items arrive pre-ordered from the backend per confirm; apply the same comparator client-side on render so both listings agree.

### 3. Files to change

1. `app/ui/react/src/utils/report.js`
   - `mapReportItems`: passthrough `extraType: item.extraType || item.extra_type || ''`; compute `typeLabel` via new exported `typeLabelFor(item)`; include `typeLabel`/`itemType` in `itemSearchText`.
   - `groupItems`: replace descending inner sort with `sortGroupItemsAsc()` comparator above; keep outer group sort descending. Export comparator for reuse + tests.
   - `HistoryPage` needs the same mapping: export `mapHistoryItemType(item)` (accepts snake_case `item_type`/`target_path`/`extra_type`) or normalize history items through `typeLabelFor`.
2. `app/ui/react/src/components/ReportPanel.jsx`
   - Remove `isSeries` gating: always render `<th>Type / Episode</th>`; row cell `{item.typeLabel}` (both actionable + skip branches).
3. `app/ui/react/src/components/HistoryPage.jsx`
   - Remove `isGroupSeries` gating; always render the column; cell from shared helper; sort `group.items` with the shared comparator before render.
4. Tests (frontend, run via `npm test` in `app/ui/react` — never root `npx vitest`):
   - `report.test.js`: `typeLabelFor` cases (series/movie/extra+extraType/series-no-episode/skip); ascending comparator cases (S01E02 after S01E01, S02E01 after S01E10, movie after series, extra last, stable tiebreak); `groupItems` inner order ascending while outer group order stays newest-first; `itemSearchText` matches `movie`/`extra`.
   - Component test (`ReportPanel` or `HistoryPage` level): column header present for a movie-only group; cell shows `Movie` / `Extra` / `S01E01`.
5. Docs (per plan 07 sync procedure, after implementation):
   - `docs/web-ui/components.md` — ReportPanel + HistoryPage rows: `Type / Episode` column + ascending row order.
   - `docs/web-ui/utils.md` — `mapReportItems`/`groupItems` new fields + comparator.
   - `AGENTS.md` — only if a durable pattern emerges (e.g. shared type-label helper); prefer updating the closest existing section.

No backend change needed (`item_type` + `extra_type` already in `ScannedItem`; `history_items.item_type` already stored). No `.env`/MCP change. After React change: `npm run build` in `app/ui/react` + `docker restart jellysort` (bind-mount pickup), then re-verify column + order live.

## Verification

1. `cd app/ui/react && npm test` — all suites green (incl. new label/sort cases).
2. `python3 -m pytest tests/` — backend untouched, stays green (388 tests).
3. Manual: scan with a multi-episode series + a movie + an extra in one `sourceFolder`; confirm the group shows `S01E01, S01E02, …` top-to-bottom, movie rows show `Movie`, extra rows show `Extra`, and `HistoryPage` shows the same after confirm.

## Open questions (confirm before `go`)

1. Column header: `Type / Episode` (proposed) vs keeping `Episode`? Proposed rename avoids confusion for movie-only groups.
2. Extra detail: `Extra` alone vs `Extra · {extraType}` when the backend provides one (e.g. trailer/theme)? Proposed: show the suffix when present.
3. Sort rank series → movie → extra: acceptable, or should movies/extras sort purely alphabetically interleaved with episodes?
