# Utilities and Client — `src/utils/` and `src/api/`

Pure, unit-tested helpers (no DOM access) plus the REST API client.

## `src/api/apiClient.js`

- `apiCall(method, path, body)` — `fetch('/api' + path, ...)` with the stored
  Bearer token; throws `ApiError(status, message)` on non-2xx (message extracted
  from `detail` when present); returns parsed JSON (or `null` for 204).
- `apiGet` / `apiPost` / `apiPatch` / `apiDelete` — thin wrappers.
- `setAuthToken(token)` / `getAuthToken()` — token held in module state and
  persisted in `localStorage` under `jsort_panel_token`.

## `src/utils/format.js`

| Function | Purpose |
| --- | --- |
| `formatBytes(bytes)` | Human-readable size (`B`…`TB`). |
| `formatDuration(seconds)` | `2h 5m 10s` style. |
| `formatConfirmPhase(phase)` | Phase → label map (idle, preparing, moving, deleting_source, triggering_jellyfin, completed, failed). `stopping_seeding` remains as a legacy label but is never emitted. |
| `fileName(path)` | Last path segment. |
| `driveRoot(path)` | First path segment (`/media1`). |
| `isCrossDrive(sourcePath, targetPath)` | Different drive roots → cross-drive. |
| `splitDrive(path)` | `{drive, rest}` for highlighting. |
| `escHtml(s)` | Escape text via a DOM node. |

## `src/utils/report.js`

| Function | Purpose |
| --- | --- |
| `mapReportItems(report)` | Maps raw report items to rows; derives `title`/`season`/`episode` from the target path; computes `typeLabel` via `typeLabelFor` and passes through `extraType`; skipped items get `title: "Skipped items"` and a `reason`. Passes through `suspect`/`corrected`/`flags`/`correctionNote`/`candidateTargets`. |
| `groupItems(items)` | Groups rows by title with `totalSize`; each row carries `_idx`. Rows within a group sort ascending via `compareReportItemsAsc` (episodes numeric, then series → movie → extra); group order stays newest-first. |
| `itemSearchText(item)` | Free-text search blob (title, episode, type label/kind/extra-type, paths, reason). |
| `typeLabelFor(item)` | Single source for the `Type` column: series → `SxxEyy` (or `Series` fallback), movie → `Movie`, extra → `Extra` (+ `· extraType` when present), skip/other → `—`. Accepts camelCase report shapes and snake_case history shapes. |
| `compareReportItemsAsc(a, b)` | Within-group ascending comparator (kind rank, then numeric season/episode, then target path, then `_idx`). Shared by the report and history tables. |
| `matchesFilter(item, query, filterVal)` | Applies the query + action/fileExists axis (`move`, `replace`, `existing`, `new`). |
| `computePathSync(idx, oldPath, newPath, items)` | Group-scoped smart path sync — see below. |
| `defaultSelection(items)` | All actionable items checked. |
| `isCrossDriveItem(item)` | Live cross-drive check honoring edited targets. |
| `targetOptions(item)` | Builds the browse/retarget option list from `candidateTargets` (existing folders, "New folder", reclassify-as-movie). |

### Smart-correction passthrough

`candidateTargets` carry `{path, label, evidence, source, reclassifyAsMovie}`;
suspect rows render from `suspect` + `flags` (values
`phantom_show_folder | season_gap | episode_gap`) and `correctionNote` (see
[backend/models](../backend/models.md)).

### `computePathSync` — smart path sync

Given an edited row:

- No change → `null`.
- Finds the shared prefix and suffix between old and new target, computing the
  changed chunk (`oldChunk` → `newChunk`).
- For same-title sibling rows whose live path starts with the same prefix and
  contains the old chunk, it replaces the chunk → `{ updates: [{idx, value}] }`.
- **Solo groups** (no same-title sibling) → `null` (keep the edit, no revert) —
  this is what makes per-movie path editing persist.
- Siblings exist but none matched → `{ revert: true }` (revert the edit).

### `isCrossDriveItem`

When the target was edited in the UI (`_liveTarget !== originalTarget`), the
backend-computed `crossDrive` flag is stale, so it re-derives from drive roots
only; otherwise it trusts the backend flag first (real device check) and falls
back to the drive-root comparison.
