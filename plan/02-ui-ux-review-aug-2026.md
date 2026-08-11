# UI/UX Review — Aug 2026

Professional UX audit of http://10.69.1.164:18329/ (app/ui/index.html) performed against a live, populated scan report. All findings verified in source or on the running app.

## Priority 1 — Information architecture & layout

### 1.1 Tab bar is a dead control
Only one tab ("Scan & Move") is rendered (`index.html:294`), but a full tab bar exists. Remove it, or give it real siblings (Library Scans, Log).

### 1.2 Operational noise mixed into the user flow
Page mixes four concerns: actions → progress → report → log → library scans. The Log (developer tooling) sits between the user's work and the Library Scan buttons.
- Move the Log into a collapsible `<details>` or its own tab.
- Move "Jellyfin Library Scans" (`index.html:370`) directly under the Actions panel — it's the natural next step after confirming a move, currently buried at the bottom.

### 1.3 Reorder to task sequence
1. Header (title, status, version)
2. Actions (sticky on scroll)
3. Progress (appears when running)
4. Report (appears when ready)
5. Library scans
6. Log (collapsed by default)

## Priority 2 — Actions & state affordances

### 2.1 Buttons error instead of reflecting state
"Get Report" with no scan → toast error; "Check Progress" does nothing visible when idle. Disable Get Report until a scan exists; show idle hints, not errors.

### 2.2 Three Confirm entry points
`Confirm Selected` (top), `Confirm` (per group), `Confirm Selected` (bottom of report, `index.html:1066`). Keep per-group; make the top one delegate to the report.

### 2.3 "Confirm Selected" styled danger red
It's the app's primary positive action. Use amber/blue to separate from Delete (destructive) red.

### 2.4 Browser `confirm()` dialogs
Replace with a styled modal (`.modal-overlay`/`.modal` CSS already exists unused, `index.html:154-162`) showing item list preview + counts. Optionally require typed confirmation for deletes.

## Priority 3 — Report table clarity

### 3.1 Last column header says "Source" but holds only a Delete button
`index.html:1022` — rename to "Actions". Add a copy button for source/target paths.

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
Show→hide between Actions and Report pushes content. Reserve space or overlay/sticky.

### 4.3 No empty state for report area
Show a placeholder card ("No scan yet — click Start Scan") before the first scan.

## Priority 5 — Polish & code hygiene

- Favicon 404 (`favicon.ico`) — add inline SVG favicon.
- `renderPathExistsPill` defined twice (`index.html:931` and `:947`) — delete one.
- `toggleAll` dead code (`index.html:1139`).
- Unused `.field` / `.modal` CSS and single-tab tab-switching code — use or remove.
- Add `max-width` (~1600px) so tables don't stretch on 4K monitors.
- Add `:focus-visible` styles for keyboard nav.
- Branding: "Jellyfin MCP Organizer" vs JellySort — pick one.

## Suggested implementation order
1. IA restructure (1.1–1.3)
2. State-aware buttons + single confirm path (2.1–2.3)
3. Report table fixes (3.1–3.5)
4. Toast transition-only + layout stability (4.1–4.3)
5. Cleanup pass (P5)

## Related
Existing plan from the prior audit: `plan/01-ui-ux-overhaul.md` (July). Many of its unchecked items are already implemented in the current build; remaining actionable items there (confirm modal, batch redirect, real-time path validation, sessionStorage state persistence, per-library scan button disabling) should be reconciled with this review before implementation.
