# Changelog

## v0.0.1 - 2026-06-29

### Changed
- Changed scan report guidance to emphasize target-path validation and root curation before confirm.
- Changed confirm handling to run in the background and return immediate progress-oriented MCP guidance instead of a final synchronous scan payload.
- Improved resolver performance for large series libraries by limiting alias sampling to video-extension globs and skipping alias walks for non-overlapping titles.
- Refreshed the README to match the current `/scans` endpoints, MCP tool names, port mapping, and configuration model.

### Added
- Added confirm progress tracking fields to `ScanPlan` and a new MCP tool: `get move new downloads confirm progress`.
- Added startup Jellyfin library-name caching so `get available jellyfin libraries list` can advertise configured library names in tool descriptions.
- Added targeted update/report guidance for pre-confirm path corrections and root selection.

### Verified
- `python3 -m pytest tests/` passed with 80 tests.

## v0.2.0 - 2026-06-01

### Changed
- Replaced the blocking `move new downloads scan` behavior with a background scan start that returns immediately.
- Updated scan status handling to use `running`, `completed`, `confirmed`, and `failed`.
- Added scan progress tracking for total candidates, processed candidates, current file, current index, elapsed time, and ETA.
- Added protection against starting a second scan while another scan is running.
- Prevented confirming a scan while it is still running.
- Changed scan report responses to return compact progress instructions while a scan is running instead of returning an incomplete full report.
- Expanded MCP scan responses with LLM-facing guidance explaining what the tool is doing, what information is available, and which tool to call next.

### Added
- Added MCP tool `get move new downloads scan progress`.
- Added HTTP endpoints `GET /scans/current/progress` and `GET /scans/{scan_id}/progress`.
- Added tests for non-blocking scan start, duplicate running-scan rejection, progress formatting, running-report behavior, confirm rejection during running scans, and MCP progress-tool guidance.

### Verified
- `python3 -m pytest` passed with 59 tests.
