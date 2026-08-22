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
| `formatConfirmPhase(phase)` | Phase → label map (idle, preparing, stopping_seeding, moving, deleting_source, triggering_jellyfin, completed, failed). |
| `fileName(path)` | Last path segment. |
| `driveRoot(path)` | First path segment (`/media1`). |
| `isCrossDrive(sourcePath, targetPath)` | Different drive roots → cross-drive. |
| `splitDrive(path)` | `{drive, rest}` for highlighting. |
| `escHtml(s)` | Escape text via a DOM node. |

## `src/utils/report.js`

| Function | Purpose |
| --- | --- |
| `mapReportItems(report)` | Maps raw report items to rows; derives `title`/`season`/`episode` from the target path; skipped items get `title: "Skipped items"` and a `reason`. Passes through `suspect`/`corrected`/`flags`/`correctionNote`/`candidateTargets`. |
| `groupItems(items)` | Groups rows by title with `totalSize`; each row carries `_idx`. |
| `itemSearchText(item)` | Free-text search blob (title, episode, paths, reason). |
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
