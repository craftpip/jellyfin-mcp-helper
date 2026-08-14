# Components — `app/ui/react/src/components/`

`App.jsx` composes the top-level layout from these components.

| Component | Role |
| --- | --- |
| `TopBar` | Header: connection status, auth-aware "Log out" button, scan/report/confirm actions. |
| `ActionsPanel` | Scan start, "Get Report", library list with per-library "Scan" buttons. |
| `ScanProgressPanel` | Live scan progress (percent, processed/total, current file). |
| `ReportPanel` | The report table: grouped rows, filters, selection, path editing. |
| `ConfirmModal` | Confirm flow modal with a preflight view and a live progress view. |
| `LogPanel` | In-memory event log. |
| `Toasts` | Transient toast notifications. |
| `PathPills` | Reusable path/source/target rendering with drive-root highlighting. |
| `LoginScreen` | Password gate shown when `authRequired && !authed` (also after a 401). |

## ReportPanel

The main table (`ReportGroup` / `ReportRow`):

- Groups by title; each group header shows the count and total size, and offers
  select-all / confirm-group / apply-edits actions.
- Rows show source name, source path, target path, type, action, file size,
  cross-drive indicator, and status pills.
- Target paths are **editable**; edits go through `onTargetInputChange` (smart
  sync) and are submitted per group via `applyGroupTargetEdits`.
- Filtering (`all`/`move`/`replace`/`existing`/`new`) via `matchesFilter`;
  selection modes via `setCheckedItems`.

## ConfirmModal

- `PreflightView` — shows what will happen: item list, counts of moves vs
  replaces, cross-drive count, total size, and a warning when cross-drive
  transfers will take longer.
- `ProgressView` — renders the confirm progress payload (status, phase label via
  `formatConfirmPhase`, processed/total, elapsed, ETA, per-file copied/speed/%).

## PathPills

Renders a path with the drive root styled separately (`splitDrive`); `StatusPill`
renders exists/type/action hints with tooltips.
