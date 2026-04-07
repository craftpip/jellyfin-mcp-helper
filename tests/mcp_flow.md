# MCP-Driven Test Plan

This document describes a Markdown-tested plan for validating the Jellyfin Download Organizer flow using MCP (JSON-RPC) end-to-end. It mirrors the MCP workflow you’ve been using in tests and aligns with AGENTS.md / SKILL.md guidance.

---

## Purpose

Validate the end-to-end flow of discovering torrents, building a scan plan, moving files, and edge-case handling via MCP:
- Create a test torrent file in the host torrents root
- Trigger an MCP scan (scan media library)
- Retrieve and inspect the scan report to ensure the test file is included
- Confirm the scan to apply the plan (move files)
- Verify the file moved to the expected media root
- Clean up test artifacts

---

## Prerequisites

- Jellyfin Download Organizer service is running (Docker Compose).
- MCP endpoint is reachable:
  - Base: http(s)://<host>/mcp (example: http://host.docker.internal:8093/mcp)
- MCP authentication key (X-MCP-Key header) is available and valid.
- Access to the movie library root used by the organizer:
  - MOVIE_ROOTS as configured in the repo (mounted volumes in docker-compose.yml).
- Path discovery mechanism:
  - You can set TEST_TORRENTS_ROOT to point to the host’s torrents root, or
  - The test will attempt to derive host paths from docker-compose.yml mappings.
- Testing environment has write permissions to:
  - The torrents root (to place the test file)
  - The movie root (to verify the move)

---

## Test Data and Artifacts

- Test artifact: a small file named sample_movie.mkv placed inside TEST_TORRENT_MOVIE (a subdirectory under the torrents root).
- Expected result: after confirm, sample_movie.mkv (or equivalent) appears under the movie root (or a subpath under it as per the organizer’s move logic).

---

## Workflow Steps

1. Health check
   - Call MCP health endpoint:
     - GET /health (or via MCP wrapper as appropriate)
   - If MCP is not healthy, skip the test gracefully and log the reason.

2. Discover torrent roots
   - Determine the host torrents root and host movies root.
   - Approach:
     - Check TEST_TORRENTS_ROOT environment variable (if provided)
     - Otherwise parse docker-compose.yml for /torrents1 and /torrents2 host paths
   - If paths cannot be determined, skip the test with a helpful message.

3. Create test data
   - Create a directory under the torrents root, e.g., <torrents_root>/TEST_TORRENT_MOVIE
   - Create a small file sample_movie.mkv inside that directory
   - Validate the file exists before proceeding

4. Trigger MCP scan (scan media library)
   - Call MCP tool: scan media library
   - Optional: use replaceExisting: true
   - Capture scanId if the response provides it

5. Retrieve scan report
   - Repeatedly request the scan report until it includes the test file
   - Method: MCP command get scan report (or equivalent)
   - Inspect the report’s files_to_move section for an entry containing sample_movie.mkv
   - If not found within a reasonable timeout (e.g., 60–120 seconds), fail with a clear log

6. Confirm scan
   - Use the scanId obtained previously
   - Call MCP tool: confirm scan with { scanId: "<id>" }
   - Validate that the confirmation step returns a success indication

7. Verify move
   - Inspect the host movie root for the moved file
   - Accept both possible outcomes:
     - Exactly sample_movie.mkv exists in the root
     - sample_movie.mkv exists somewhere within host_movies (nested folder)
   - If not found, fail with a diagnostic message

8. Cleanup
   - Remove the test file and test torrent directory
   - If possible, remove empty parent directories in both source and destination
   - Do not fail the entire test due to cleanup issues; log but continue

---

## Expected MCP Interactions (reference)

- List or call:
  - Tools list (to discover capabilities)
  - Tools call with name: “scan media library”
  - Tools call with name: “get scan report”
  - Tools call with name: “confirm scan”
- Example payloads (conceptual):
  - Scan:
    - jsonrpc: 2.0, method: tools/call, params: { name: "scan media library", arguments: { replaceExisting: true } }
  - Get scan report:
    - jsonrpc: 2.0, method: tools/call, params: { name: "get scan report", arguments: {} }
  - Confirm:
    - jsonrpc: 2.0, method: tools/call, params: { name: "confirm scan", arguments: { scanId: "<id>" } }

---

## Validation Criteria

- The scan report contains files_to_move with an entry matching sample_movie.mkv (or the test filename)
- Confirming the scan returns success
- After confirmation, the file exists in the movie root (either directly or within a nested folder)
- No unexpected or residual test files remain in the torrents root or movies root (where possible)

---

## Edge Cases and How to Handle

- MCP health check fails
  - Skip the test gracefully and report the reason
- Unable to discover host paths
  - Skip with a clear message; avoid false positives
- No test file created
  - Fail early with a diagnostic message
- Scan report never mentions the test file
  - Fail with a timeout/detailed log
- Cleanup fails
  - Do not fail the test; log the condition for debugging

---

## How to Run (Local)

- Ensure service is up:
  - docker compose up -d
- Run tests:
  - pytest -q
- Or focus on MCP flow test:
  - pytest tests/test_mcp_flow.py -q

---

## CI Considerations

- Run in a containerized CI environment where MCP endpoint is reachable from the runner.
- Use environment variables to configure:
  - MCP_URL
  - MCP_KEY
  - TEST_TORRENTS_ROOT (optional)
- Ensure test artifacts do not leak into subsequent runs by using unique torrent subfolders per run or by cleaning up in the test.

---

## Diagnostics and Logging

- Capture MCP responses for:
  - scan media library
  - get scan report
  - confirm scan
- Print the scan report content in logs to aid debugging
- Log the presence/absence of the test file in the torrent root and the final moved location

---

## File to Add

- tests/mcp_flow.md

---