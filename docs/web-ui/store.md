# State Store — `app/ui/react/src/store/AppStore.jsx`

A single `AppStoreProvider` (React Context + `useReducer`) drives the whole UI.
Components consume it via `useAppStore()` which returns `{ state, actions }`.

## State shape

| Field | Meaning |
| --- | --- |
| `connStatus` / `connMessage` | Backend connection state (`connecting`/`connected`/`error`). |
| `authRequired` / `authed` | Panel auth gate (`GET /api/status` → `auth.required`); `authed` unlocks the UI. |
| `jellyfinLibraries` | Library list from `GET /api/libraries`. |
| `libraryScanning` | Library currently being scanned (or `null`). |
| `scanId` | Active scan id. |
| `scanRunning` | Whether a scan is in progress. |
| `scanProgress` | Latest scan progress payload. |
| `reportVisible` / `reportAll` / `reportSummary` | Report state. |
| `currentItems` | Mapped, live items (with `_liveTarget`). |
| `reportGroups` | Grouped items (per title). |
| `currentFilter` / `rowLimit` | Filter key and row cap. |
| `selectedIds` | Selected confirmIds. |
| `expandedGroups` | Expanded group ids (`group-0`, …). |
| `confirmActive` / `confirmButtonLabel` / `confirmModal` | Confirm workflow state. |
| `logEntries` | In-memory log (capped at `LOG_LIMIT = 1000`). |
| `toasts` | Transient toast messages. |
| `page` | Active SPA page (`scan` / `settings`), from `window.location.pathname`. |
| `envSpec` / `envSaved` / `envEffective` | Settings page data (`GET /api/admin/env`). |

## Confirm queue (background moving)

The backend is the source of truth: `confirm_scan` **queues** batches when a
move is already running (see
[services/scan-manager](../services/scan-manager.md)) and reports
`queue_length`/`queue_items` in confirm progress. The store mirrors it:

- `openConfirmModal` / `confirmSelected` / `confirmGroup` always open the
  preflight modal — there is no "already running" rejection.
- `runConfirm` POSTs and reads `result.queue_length`: `> 0` → push
  `{itemIds}` to a `pendingBatches` ref, toast "Added to queue — will start
  after the current move finishes", and do **not** rebuild the transfer queue;
  `0` → start immediately as before.
- `pollConfirmProgress` keeps polling while `confirmActive` or a pending batch
  exists. When the next batch starts (`status === 'running'` with `processed`
  reset below the previous completed count) it pops `pendingBatches`, rebuilds
  the transfer queue, resets the confirm-state ref, and toasts "Queued move
  started". Completion still toasts + `fetchReport` after ~800 ms.
- The active header / button label append `· N queued` while batches wait.

## Key actions

| Action | Behavior |
| --- | --- |
| `checkConnection` | `GET /api/status`; sets auth state; on `auth.required` shows the login gate, otherwise loads libraries and auto-fetches the report. |
| `login` / `logout` | `POST /api/login` (stores the token via `setAuthToken`, persisted in `localStorage`), `POST /api/logout`. |
| `startScan` / `pollScanProgress` | `POST /api/scans`, then poll `GET /api/scans/current/progress` (or by scan id) every `POLL_INTERVAL_MS = 2000`; auto-loads the report 500 ms after `completed`. |
| `fetchReport` | Calls `GET /api/scans/current/report` (or by scan id), maps + groups items. |
| `loadLibraries` | `GET /api/libraries`, then fetches the report. |
| `triggerLibraryScan` | `POST /api/libraries/scan` with `{libraryName, ...}` in the body. |
| `setCheckedItems(mode)` | Select all / move / replace / existing (skipped always excluded). |
| `onTargetInputChange` | Live target-path editing with group-scoped smart sync (see utils/report.md). |
| `applyGroupTargetEdits` | Sends updated paths for one group via `PATCH /api/scans/current/items`. |
| `confirmSelected` / `confirmGroup` | Open the confirm modal with the matching itemIds. |
| `runConfirm` / `pollConfirmProgress` | `POST /api/scans/current/confirm`, then poll `GET /api/scans/current/confirm-progress` (or by scan id). Queued batches auto-start via the poll bridge — see "Confirm queue" above. |
| `retargetItem(confirmId, directory, applyToGroup, reclassifyAsMovie)` | `POST /api/scans/{scan_id}/items/retarget` — re-target an item/group to a browsed folder, then refresh the report. |
| `deleteSourceItem` / `deleteSelectedSkipped` | `DELETE /api/scans/current/items` after a confirm dialog. |
| `loadEnv` / `saveEnv` | Admin settings page: `/api/admin/env`. |
| `toast` / `log` / `copyText` | Feedback primitives. |

## Notes

- Polling uses recursive `setTimeout` (not `setInterval`) so a poll never stacks
  while the previous request is in flight.
- Timers are tracked in a ref (`timers.current`) and cleared on unmount.
- Any `ApiError` with status 401 clears the stored token, marks the app
  `authRequired`/`!authed` (login screen) and shows a "Session expired" toast.
- Skipped items are always excluded from selection for moves, but remain
  selectable for deletion.
- The report render computes `defaultSelection` (all actionable items checked),
  and `renderReport`/`setRowLimit` both rebuild `reportGroups`.
- "Update Paths" is shown per group while `hasPathEdits` is true and the
  Confirm button is hidden (the user must apply or discard the edit first);
  `applyGroupTargetEdits` clears the flag so Confirm returns.
- The report model passes through `suspect`/`corrected`/`flags`/
  `correctionNote`/`candidateTargets` from the backend (see
  [backend/models](../backend/models.md)); rows show Browse/suspect/corrected
  badges.
