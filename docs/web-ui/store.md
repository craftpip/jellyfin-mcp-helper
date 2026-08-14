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

## Key actions

| Action | Behavior |
| --- | --- |
| `checkConnection` | `GET /api/status`; sets auth state; on `auth.required` shows the login gate, otherwise loads libraries and auto-fetches the report. |
| `login` / `logout` | `POST /api/login` (stores the token via `setAuthToken`, persisted in `localStorage`), `POST /api/logout`. |
| `startScan` / `pollScanProgress` | `POST /api/scans`, then poll `GET /api/scans/current/progress` (or by scan id) every `POLL_INTERVAL_MS = 2000`; auto-loads the report 500 ms after `completed`. |
| `fetchReport` | Calls `GET /api/scans/current/report` (or by scan id), maps + groups items. |
| `loadLibraries` | `GET /api/libraries`, then fetches the report. |
| `triggerLibraryScan` | `POST /api/libraries/{name}/scan`. |
| `setCheckedItems(mode)` | Select all / move / replace / existing (skipped always excluded). |
| `onTargetInputChange` | Live target-path editing with group-scoped smart sync (see utils/report.md). |
| `applyGroupTargetEdits` | Sends updated paths for one group via `PATCH /api/scans/current/items`. |
| `confirmSelected` / `confirmGroup` | Open the confirm modal with the matching itemIds. |
| `runConfirm` / `pollConfirmProgress` | `POST /api/scans/current/confirm`, then poll `GET /api/scans/current/confirm-progress` (or by scan id). |
| `deleteSourceItem` / `deleteSelectedSkipped` | `DELETE /api/scans/current/items` after a confirm dialog. |
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
