# UI/UX Review — Aug 2026

Professional UX audit of http://10.69.1.164:18329/ (app/ui/index.html) performed against a live, populated scan report. All findings verified in source or on the running app. This plan includes the owner's design decisions (marked DECIDED).

## Decisions (from owner, Aug 2026)

- **Remove "Check Progress" entirely.** Progress is managed internally — the UI auto-polls. No manual progress button. `Check Progress` is a dead/confusing button that does not fit the UI.
- **Jellyfin Library Scans panel moves INSIDE the Actions panel** (not a separate panel at the bottom).
- **Confirm flow is modal and blocking.** When the user confirms, a modal popup opens showing confirmation progress and stays until done — nothing else can be done on screen while it runs.
- **Cross-drive moves must be clearly communicated.** Confirmation can take a long time for cross-drive moves; this must be explicit in the UI (badge + ETA), not buried in a small note.

## Priority 1 — Information architecture & layout

### 1.1 Tab bar is a dead control
Only one tab ("Scan & Move") is rendered (`index.html:294`), but a full tab bar exists. Remove the tab bar and the tab-switching JS (`index.html:588`).

### 1.2 Reorder to a single, task-sequenced flow
1. Header (title, status, version)
2. Actions panel — Start Scan + Confirm Selected + **Jellyfin Library Scans (DECIDED: inside this panel)**
3. Progress (appears automatically while scan runs)
4. Report (appears when scan completes)
5. Log (collapsed by default, at bottom)

### 1.3 Log panel
Move the Log into a collapsible `<details>` at the bottom of the page — it is developer tooling, not user flow.

## Priority 2 — Actions & flow (DECIDED changes)

### 2.1 Remove "Check Progress" button (DECIDED)
Delete `btnProgress` (`index.html:313`, handler at `:717`). Progress is auto-polled:
- Scan: auto-poll after Start Scan, progress panel shows automatically.
- Confirm: auto-poll inside the blocking modal.

### 2.2 Jellyfin Library Scans inside Actions panel (DECIDED)
Merge the library-scan buttons (`index.html:370-375`) into the Actions panel as a sub-section, placed after the action buttons.

### 2.3 Confirm flow is a blocking modal (DECIDED)
Replace `confirm()` dialogs and the inline confirm-progress section (`confirmProgressExtra`) with a single modal:
- Pre-flight summary: items selected, total size, move vs replace counts, **cross-drive indicator**, destination paths preview.
- On confirm: the SAME modal switches to progress view (phase, current file, per-file + overall %, speed, ETA).
- Modal is non-dismissable while running — nothing else on screen is usable until it completes (per owner).
- On completion: success/failure summary (moved/replaced/failed), then auto-fetch report.

### 2.4 Cross-drive clarity (DECIDED)
- Show a prominent "Cross-drive move" badge/warning on each affected row and in the confirm modal, with explanatory text that it takes longer.
- Keep live per-file and overall ETA visible in the modal progress view.

### 2.5 State-aware buttons
Buttons must reflect state instead of erroring:
- Disable "Get Report" until a scan exists; idle hints instead of toast errors.
- "Confirm Selected" disabled until selections exist (already does this).
- Single confirm entry point — top "Confirm Selected" delegates to the report; remove the redundant bottom one.

### 2.6 Recolor "Confirm Selected"
It is the primary positive action but styled `danger` red (`index.html:43-44`). Use amber/blue so destructive Delete stays visually distinct.

## Priority 3 — Report table clarity

### 3.1 Last column header says "Source" but holds only a Delete button
`index.html:1022` — rename to "Actions". Add copy affordance for source/target paths.

### 3.2 pathExists glyphs are cryptic
`✓/✗ folder/file` icons rely on tooltips. Use readable text pills ("Show ✓", "Season ✓", "File ✗") or add a legend.

### 3.3 Filter dropdown labels ambiguous
"New only / Existing only / Path exists / Path new" mixes two axes. Use filter chips with live counts: `All | New | Replace | Existing path | New path`.

### 3.4 Redundant summary
`reportSummary` pipes line (`index.html:339`) duplicates the summary pills. Keep pills, drop the text line.

### 3.5 Skipped rows default checked but excluded from selection
A checked box that "doesn't count" confuses. Default them unchecked or visually mark the group as "not selected".

### 3.6 No pagination/virtualization at scale
226+ candidates render as one giant table. Add pagination or a row limit control.

## Priority 4 — Feedback & notifications

### 4.1 Toast spam during polling
Every 2s poll fires a toast (`index.html:708`, `index.html:1522`). Toast only on state transitions (started/completed/failed), not every tick.

### 4.2 Progress panel causes layout shift
Show→hide between Actions and Report pushes content. Reserve space or make it sticky.

### 4.3 No empty state for report area
Show a placeholder card ("No scan yet — click Start Scan") before the first scan.

## Priority 5 — Polish & code hygiene

- Favicon 404 (`favicon.ico`) — add inline SVG favicon.
- `renderPathExistsPill` defined twice (`index.html:931` and `:947`) — delete one.
- `toggleAll` dead code (`index.html:1139`).
- Unused `.field` / `.modal` CSS and single-tab tab-switching code — use or remove (modal becomes used by 2.3).
- Add `max-width` (~1600px) so tables don't stretch on 4K monitors.
- Add `:focus-visible` styles for keyboard nav.
- Branding: "Jellyfin MCP Organizer" vs JellySort — pick one.

## Suggested implementation order
1. IA restructure + Check Progress removal + library scans into Actions (1.1–1.3, 2.1–2.2)
2. Blocking confirm modal with cross-drive clarity (2.3–2.4)
3. State-aware buttons + single confirm path + recolor (2.5–2.6)
4. Report table fixes (3.1–3.5)
5. Toast transition-only + layout stability (4.1–4.3)
6. Cleanup pass (P5)

## Related
Existing plan from the prior audit: `plan/01-ui-ux-overhaul.md` (July). Many of its unchecked items are already implemented in the current build; remaining actionable items there (confirm modal, batch redirect, real-time path validation, sessionStorage state persistence, per-library scan button disabling) should be reconciled with this review before implementation.
