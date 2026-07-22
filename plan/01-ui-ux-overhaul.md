# UI/UX Overhaul

Improve the web UI at http://10.69.1.164:18329/ based on the UX audit.

## Phase 1 — Report & Table Improvements

Backend + frontend changes to make the scan report usable at scale.

### Backend
- Pass `file_size` (formatted as GB/MB) and `source_name` to the report items payload
- Ensure the classification result (quality, codec) is available if already parsed

### Frontend — Report table
- [ ] Group rows by show/movie name with collapsible section headers
- [ ] Show total file size per group and for the entire scan
- [ ] Change badge text from `Season 01` to `Move` / `Replace` with distinct colors (green/orange/red)
- [ ] Replace `Show ✓, Season ✓, File ✗` with colored status pills or icons
- [ ] Add file size column to each row
- [ ] Add search/filter input — filter by title, path, status
- [ ] Add dropdown filter: All / Move / Replace / Path exists / Path new
- [ ] Add sort controls by title, size, path exists status

### Frontend — Report toolbar
- [ ] Rename `Select Existing Paths` to `Select files at existing paths` or `Select existing`
- [ ] Add "Select All Move" / "Select All Replace" buttons
- [ ] Show skipped items count in summary pills area (not hidden in toolbar)

### Frontend — Remove auto-refresh
- [ ] Remove `setTimeout(fetchReport, 1000)` after scan completes
- [ ] User must click Get Report manually

## Phase 2 — Scan Config & Confirm Improvements

### Scan config panel
- [ ] Add a collapsible "Scan Options" section before Start Scan
- [ ] Checkbox for `Replace existing files`
- [ ] Checkbox for `Allow medium confidence matches`
- [ ] Checkbox for `Use local AI classification`

### Confirm dialog
- [ ] Replace bare `confirm()` with a modal showing pre-flight summary:
  - [ ] Total items selected
  - [ ] Total file size
  - [ ] Count of move vs replace
  - [ ] Count of cross-drive moves (if detectable)
  - [ ] Destination paths summary

### Batch path editing
- [ ] Add "Redirect selected to..." button
- [ ] Opens a modal with source prefix → target prefix replacement
- [ ] Preview changes before applying

## Phase 3 — Polish & Quality of Life

### Report summary
- [ ] Make summary pills clickable — clicking `73 Series` filters table to series only
- [ ] Show scan_id in a copyable format (click to copy)

### Validation feedback
- [ ] Real-time validation on target path input — green border when valid, red when invalid
- [ ] Check path is under a configured root + has valid video extension

### Skipped items
- [ ] Show skipped count as a pill in summary strip alongside Movies/Series
- [ ] Inline expandable rows in the main table instead of a separate toggle

### Library scan buttons
- [ ] Show spinner or status text while a library scan is running
- [ ] Disable only the clicked button, not all buttons
- [ ] Show last scan time per library

### State persistence
- [ ] Store `scanId` in sessionStorage so page refresh preserves state
- [ ] Auto-reconnect to existing scan on page load

### General
- [ ] Change Start Scan button text to "Scanning..." while running
- [ ] Make progress panel scroll behavior optional (don't force focus)
- [ ] Add confirmation dialog before "Update Selected Paths" showing what changed
- [ ] After confirm, show confirmed items with a "✓ Moved" / "✓ Replaced" badge instead of hiding them
