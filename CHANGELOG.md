# Changelog

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
