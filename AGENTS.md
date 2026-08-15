# Agents

This is the local project AGENTS.md for the JellySort repository.

Use this file as the project handbook. Keep it compact and practical. Update existing sections when new related learning is added. Do not turn this file into a dated chat log.

## Skills

No jellysort skill is installed in this environment yet — do not try to load one. The repo-root `SKILL.md` that used to describe one was a stale, unfinished template (unfilled `{{PLACEHOLDER}}` values, old REST-only workflow) and has been removed. The service is MCP-first (JSON-RPC 2.0 on port 18328) with legacy REST scan endpoints still present for compatibility.

## Commands

- Test: python3 -m pytest tests/
- Rebuild after source changes: docker compose build && docker compose restart
- Web UI: enabled via WEB_UI_ENABLED=true in .env, served on the MCP port (single port)
- MCP API: port 18328 (external), 18327 (internal). The Web UI is mounted at `/` on the same server, so UI (``/``, `/settings`, `/apikeys`, `/api/*`) and MCP (`/mcp`) all share port 18328.

## Project Structure

- app/core/config.py: settings and config models
- app/core/logging.py: logging setup
- app/core/auth.py: MCP auth dependency (require_mcp_auth, ADMIN_UI_TOKEN as admin key)
- app/models/schemas.py: Pydantic models
- app/services/api_key_manager.py: hashed MCP API-key store (state in config/mcp_keys.json)
- app/services/classifier.py: guessit-based and regex media classification
- app/services/download_client.py: qBittorrent MCP client
- app/services/env_manager.py: ENV_SPEC manifest + .env read/write/reload (settings page backend)
- app/services/jellyfin.py: Jellyfin API client
- app/services/normalizer.py: file and folder renaming
- app/services/ollama.py: Ollama LLM client
- app/services/openrouter.py: OpenRouter LLM client
- app/services/organizer.py: scan, classify, resolve, and move orchestration
- app/services/release_tracker.py: ongoing-release tracking (state in config/ongoing_releases.json)
- app/services/resolver.py: PathResolver path-matching logic
- app/services/run_manager.py: legacy run management
- app/services/scan_manager.py: scan-plan workflow, scan then confirm
- app/services/scanner.py: filesystem scanner
- app/main.py: FastAPI entry point and MCP handlers
- app/ui/server.py: Web UI FastAPI server (serves React bundle, native `/api` routes, panel auth, `/api/admin/*` env+key endpoints); mounted at `/` on the MCP app in `main.py` so UI and MCP share one port
- app/ui/react/: React.js web UI (Vite build, source)
- app/ui/react-dist/: built React bundle served at `/` (`/react` and `/react/assets` are backward-compat mounts that 308-redirect/re-serve)
- app/ui/react/src/store/AppStore.jsx: Context + useReducer store
- app/ui/react/src/api/apiClient.js: REST API client (apiGet/Post/Patch/Delete, auth token)
- app/ui/react/src/components/: React components (ReportPanel, ConfirmModal, PathPills, LoginScreen, SettingsPage, ApiKeysPage, etc.)
- app/ui/react/src/utils/report.js: pure helpers (item mapping, grouping, filters, smart path sync)
- plans/: project plans and roadmap documents (markdown)
- tests/: pytest test suite
- config/: config files plus runtime state (`current_scan.json`, `ongoing_releases.json`, `mcp_keys.json`)
- logs/: runtime logs
- reports/: generated reports
- .env: active configuration
- docker-compose.yml: container orchestration
- Dockerfile: image build definition
- requirements.txt: Python dependencies
- README.md: project documentation

## Web UI (React)

Current state: **the React app is the main UI at `/`**. Old `/react` bookmarks 308-redirect to `/`. The legacy HTML panel (`app/ui/index.html`, served at `/legacy`) has been deleted.

- React source lives in `app/ui/react/` (Vite, JavaScript, no TS). `npm run build` outputs to `app/ui/react-dist/`.
- `server.py` serves `react-dist/` as static files under `/assets` (plus backward-compat `/react/assets`) and routes `GET /` to the built `index.html`; `GET /react` redirects to `/` (308). `main.py` mounts this UI app at `/` on the MCP app, so UI and MCP share the single port 18328.
- The React client calls native `/api` REST routes on the UI server (`app/ui/server.py`), which share the backend `ScanManager`/`ReleaseTracker`. The old `/mcp` JSON-RPC proxy has been **removed** — the panel is fully independent of the MCP server. Dev: `npm run dev` in `app/ui/react` with a Vite proxy to `http://localhost:18328` (`/api`).
- Panel auth: `UI_PANEL_PASSWORD` in `.env`. When set, `/api` routes except `/api/status`, `/api/login`, and static assets require a Bearer token from `POST /api/login`; the React app shows `LoginScreen` and stores the token in `localStorage`. When empty, `GET /api/status` reports `auth.required: false` and the panel is open.
- Frontend tests: `npm test` from `app/ui/react` (Vitest + React Testing Library, jsdom). **Run vitest via `npm test` in `app/ui/react`, never via `npx vitest` from the repo root** — the root install has no jsdom/vite config and fails confusingly.
- After any React source change: `npm run build` in `app/ui/react`, then `docker restart jellysort` (the compose file bind-mounts `.` into `/app`, so the built `react-dist/` and edited `server.py` are picked up on restart).

## Project Rules

### Docker rebuild after code changes

The app code is copied into the Docker image at build time. Editing source files on the host does not update the running container unless the container is rebuilt.

After changing any app/ source file, run: docker compose build && docker compose restart

Verify by rerunning the affected scan or API behavior after restart.

### Corpus fixtures must be obfuscated before commit

The classifier is the central point of this project. Every time a classifier issue appears, the affected real paths are added to the regression corpus so the same bug cannot come back.

`tests/corpus/download_paths.json` is committed, so it must never contain anything that reveals what media the user actually downloaded:

- Replace real series names with random words (they do NOT need to look like plausible shows).
- Replace real release groups with neutral fakes (e.g. `[RlsGrp]`) — real release groups are recognizable as torrent group tags.
- Replace real root paths like `/media3/torrents/` with neutral ones (e.g. `/media1/downloads/`). The generic word "torrents" is fine when it refers to the download-root concept in code/config; the repo must never contain the user's real download paths, real media names, or real release groups.
- Keep the formatting tokens identical so the classifier runs on the same patterns: `SxxEyy`, `v2`, `REPACK`/`REPACK2`, years in parens (year value may change), `1_2`-style underscore junk, dot-separated long titles, bracket-wrapped tags, codec/resolution strings (`1080p`, `x265`, `FLAC`, `Opus 2.0`), episode-per-folder counts and per-season splits.
- Keep `2.5`-style leading decimals because they are formatting, not identification.
- Update the container-name-based regression tests (e.g. the underscore-junk consistency test) to match the obfuscated names.
- Do not commit any reverse mapping back to the real names.

### Release workflow

Use a two-branch release model:

- dev for active development
- prod for stable production releases

Feature and fix branches merge into dev first.

When ready to release:

1. Merge or fast-forward dev into prod.
2. Update version in app/core/version.py.
3. Run python3 -m pytest tests/.
4. Run docker compose build.
5. Create the release commit.
6. Tag from prod as vX.Y.Z.

app/core/version.py is the single source of truth for the service version.

## Known Patterns And Fixes

### Anime extra classification patterns

Problem:

Some anime extra files are classified as normal series episodes. Some real episodes can also be incorrectly skipped when codec or version strings look like decimal episode numbers.

Affected file:

- app/services/classifier.py

Cause:

- Regex boundaries were too strict for short markers followed by digits.
- Decimal episode matching was too loose because bare decimals like 2.0 could match.

Correct approach:

- Keep short extra markers explicit with optional digits.
- Require an SxxE prefix for decimal episode matching.
- Update this same section when new related anime extra patterns are discovered.
- Do not create a new standalone learning block for each new marker.

Current regex guidance:

- EXTRA_MARKERS should include ncop\d*, nced\d*, op\d*, ed\d*, sp\d*, ova, ona, special, extras?, bonus, recap, trailer.
- DECIMAL_EPISODE_RE should require an SxxE prefix before decimal episode numbers.

Known examples:

- NCED1: should be kind=skip. Numbered creditless ending.
- NCOP2: should be kind=skip. Numbered creditless opening.
- OP1: should be kind=skip. Numbered opening extra.
- ED3: should be kind=skip. Numbered ending extra.
- SP01: should be kind=skip. Special marker followed by digits.
- SP02: should be kind=skip. Special marker followed by digits.
- S01E01 with Opus 2.0: should be kind=series. Codec decimals must not be treated as special or decimal episodes.
- S01E01 with DDP2.0: should be kind=series. Audio format decimals must not trigger skip logic.
- spider.mkv: should not be skipped because of sp.
- space.mkv: should not be skipped because of sp.

Verification:

1. Run python3 -m pytest tests/.
2. Manually test the known examples above.
3. Confirm real episodes with codec decimals remain series.
4. Confirm numbered anime extras are skipped.

### Decimal-style titles and numeric junk in classifier

**Problem:** Series with a decimal in the title (e.g., `2.5`-prefixed titles) and folders with underscore numeric junk (e.g., `Nimbus 7_9 (2020)`) were mangled.

**Affected file:** `app/services/classifier.py`

**Cause:**

- `CONTAINED_BARE_EPISODE_RE` matched `2.5` (in `2.5.Crumpled.Staircase...`) as a bare episode number with title `5.Crumpled...`, mangling every episode title.
- `_is_fuller_title` preferred the container folder name over the parsed title, so junk like `7_9` (from `Nimbus 7_9 (2020)`) won over the clean title `Nimbus`.
- `_has_container_episode_context` treated a leading number in a file inside a folder as a bare episode even when the folder was the movie's own title folder — `3 Idiots (2009)` containing `3 Idiots (2009).mkv` became kind=series episode 3 with title `3 Idiots (2009)`.

**Regex change:**

- `CONTAINED_BARE_EPISODE_RE` requires `\.` to NOT be followed by a digit, so floats never match:
```python
r"^(?P<episode>\d{1,3})(?:v\d+)?\s*(?:[-_ ]|\.(?!\d))\s*(?P<title>\S.*)$"
```

**Title preference changes:**

- `_extract_title` prefers the parsed title over the folder name when the folder name contains extra numeric words that are not years (1900-2100), via `_is_fuller_title`.
- The parsed title is also skipped in favor of the folder name when the parsed title has no alphabetic characters (e.g., bare-episode files whose guessit title is just `1`).

**Contained bare-episode guard:**

- `_container_is_movie_folder(candidate)` returns True when the container folder tokens are a prefix of the file stem tokens (e.g. folder `3 Idiots (2009)` + file `3.Idiots.2009.1080p.BluRay.mkv`). In that shape the leading number is part of the movie title, not an episode number.
- The contained-bare-episode inference in `classify_candidate`, `_extract_container_series_for_bare_episode`, and the `_extract_episode_title` bare-title path are all skipped when `_container_is_movie_folder` is True, so the folder name is not stolen as the title either.

**Correct behavior (names below are the obfuscated corpus equivalents):**

- `2.5.Crumpled.Staircase.2021.S01E01...` → title `2.5 Crumpled Staircase (2021)`, kind=series, episode 1.
- `[RlsGrp] Nimbus 7_9 (2020) (Season 02) ...` → title `Nimbus`, season 2, not `Nimbus 7_9 (2020)`.
- Both Nimbus S01 and S02 folders must resolve to the same title `Nimbus` so they merge into one series.
- `4.The.Conclusion.mkv` in a show folder → kind=series, episode 4. Dot-separated bare episodes still work.
- `3 Idiots (2009).mkv` inside a `3 Idiots (2009)` folder → kind=movie, title `3 Idiots`, year 2009, season/episode None. The leading `3` is a title prefix, not episode 3.

**Verification:**

1. Run python3 -m pytest tests/.
2. The corpus regression tests in `tests/test_classifier.py` classify every path in `tests/corpus/download_paths.json` and fail if any title/episode_title contains release junk (codecs, resolutions, group names) or brackets.
3. `tests/corpus/download_paths.json` is the full snapshot of real download-roots paths — refresh it after significant scanner/config changes with a sweep over `scan_candidates(cfg.paths)`. Obfuscate the snapshot before committing (see the "Corpus fixtures must be obfuscated before commit" rule).

### Pattern fixes must be documented with examples

Whenever fixing a pattern-based bug, update the closest existing pattern section instead of creating a new standalone learning block.

For each new pattern, document:

- Actual input that failed
- Old behavior
- Correct behavior
- Code or regex change
- Verification command or manual check

Prefer adding the new case to the existing examples list.

### Update scan path validation bug

**Problem:** `update move new downloads scan` failed with `tuple expected at most 1 argument, got 7`.

**Cause:** `app/services/scan_manager.py:388` used `tuple(".mkv", ".mp4", ...)` but `tuple()` accepts at most 1 positional argument.

**Fix:** Remove the `tuple()` call — the parenthesised literals already form a tuple.

**Before:**
```python
if not new_target.endswith(tuple(".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv")):
```

**After:**
```python
if not new_target.endswith((".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv")):
```

**Verification:** `python3 -m pytest tests/` and call update with at least one item.

### Replace existing checkbox default

**Problem:** Good candidates like Mortal Kombat (1995) were skipped with reason "Matched movie pattern" despite being correctly classified as a movie.

**Cause:** The legacy `app/ui/index.html` (now deleted) had the "Replace existing files" checkbox unchecked by default, sending `replaceExisting: false` to the backend. When the target path already exists AND `replaceExisting` is false, the scan manager (line 281 in `scan_manager.py`) sets the action to `"skip"`.

**Fix:** Set `checked` on the checkbox input so it defaults to ON, matching the backend default of `replace_existing=True` in `ScanRequest`. The React UI has no such checkbox and relies on the backend default `replace_existing=True`.

**The checkbox label matters:** Use clear labels like "Replace existing files" not "Override existing scan".

**Verification:** After rebuild, a file whose target already exists should show as "replace" not "skip" when the checkbox is left at its default state.

### Jellyfin library scan trigger endpoint

**Problem:** `trigger jellyfin library scan` can return success while Jellyfin does not show a real library scan if the handler calls the wrong update path or only trusts a fast HTTP response.

**Correct approach:** For a named library scan, resolve the library through `GET /Library/VirtualFolders`, then call Jellyfin's library item refresh endpoint using the library `ItemId`:

```http
POST /Items/{libraryItemId}/Refresh?Recursive=true&ImageRefreshMode=Default&MetadataRefreshMode=Default&ReplaceAllImages=false&ReplaceAllMetadata=false
```

Use `JellyfinClient.scan_library()` for the MCP tool `trigger jellyfin library scan`. Do not replace this with the global scheduled task endpoint or with `Library/Media/Updated` for named library scans.

**Path update distinction:** `Library/Media/Updated` is useful after moving or replacing known media files because it can notify Jellyfin about specific updated paths. Keep this for organizer/confirm flows that already know the changed target paths.

**Verification:** After changing scan behavior, run `python3 -m pytest tests/`, rebuild/restart Docker, and manually trigger a real library such as `Movies` or `Shows R` to confirm Jellyfin shows the scan.

### Resolver scan hang with sorted(rglob) in series_aliases

**Problem:** Scan hangs for minutes on the first candidate during the "resolving target" step. No progress past 0%.

**Cause:** `app/services/resolver.py:59` used `sorted(root.rglob("*"))` in `series_aliases()`. `sorted()` consumes the entire rglob iterator before the `break at 12` takes effect. On a series folder with thousands of files (e.g., One Piece with 20+ seasons), this walks and sorts every file. With 132+ existing series folders, the first resolution takes minutes.

**Affected files:**
- `app/services/resolver.py` (`series_aliases`, `_pick_exact_path_match`)
- `app/services/download_client.py` (qBittorrent view filter)

**Fixes (four parts):**

1. **Remove `sorted()` from `series_aliases`** — let `rglob("*")` stop at the `break` naturally.
2. **Use targeted extension globs** (`root.rglob(f"*{ext}")` for each extension) instead of `root.rglob("*")` — only yields video files, no directory entries to filter.
3. **Token overlap check in `_pick_exact_path_match`** — before calling `series_aliases(path)` (which walks the dir tree), check if `tokenize(title) & tokenize(folder_name)` is non-empty. Non-matching directories like "One Piece" when searching for "Mushoku Tensei" skip the walk entirely. This is the most impactful optimization.
4. **Token overlap check in `_shortlist_target_paths`** — same check before calling `series_aliases(path)` during the shortlist scoring loop. The shortlist runs across all existing paths when no exact match is found. Without this check, every path's directory tree is walked even when the folder name shares no tokens with the target title.

**Before (resolver.py) — series_aliases:**
```python
for file_path in sorted(root.rglob("*")):
    if sample_count >= 12:
        break
    if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
        continue
    ...
```

**After:**
```python
for ext in VIDEO_EXTENSIONS:
    for file_path in root.rglob(f"*{ext}"):
        if sample_count >= 12:
            break
        ...
    if sample_count >= 12:
        break
```

**Before (resolver.py) — _pick_exact_path_match:**
```python
alias_values = series_aliases(path) if media_kind == "series" else {folder_name}
```

**After:**
```python
if not tokenize(title) & tokenize(folder_name):
    continue
alias_values = series_aliases(path)
```

**Additional performance logging added:**
- `[resolver] resolving series=... season=... episode=...` — shows what's being resolved
- `[resolver] existing paths count: N` — number of existing paths to match against
- `[resolver] exact path match looking for TITLE among N paths` — when matching starts
- `[resolver] exact match checked 50/132 paths...` — progress every 50 paths
- `[resolver] exact match via folder name: PATH` — match found by folder name
- `[resolver] exact match via file alias in FOLDER: PATH` — match found by file alias fallback

**Verification:** Scan 226 candidates with 132 existing series folders completes in ~3 seconds (previously stuck for 5+ minutes). Run `python3 -m pytest tests/` to confirm no regressions.

### Docker bind mount I/O error (Errno 5) on scan

**Problem:** Scan fails with `OSError: [Errno 5] Input/output error` on a `/media*/` path. Host can access the path fine.

**Cause:** Docker bind mount can enter a stale I/O state when the underlying filesystem has a transient error. The container's view of the mount becomes broken even though the host can still access files.

**Fix:** Restart the container with `docker compose down && docker compose up -d` (or `docker compose restart`). This re-establishes the bind mount and resolves the I/O error without rebuilding the image.

**Verification:** `docker exec jellysort ls /media3/series/` should list directories. Then run the scan again.

**Note:** If a full restart doesn't help, check the host mount (`mount | grep media3`), disk health (`smartctl -H /dev/sdX`), and kernel messages (`sudo dmesg | grep -iE "sdX|EXT4-fs error"`) for hardware or filesystem issues.

### Apostrophe normalization in path matching

**Problem:** Series with apostrophes in the name (e.g., `Fox's Den`) would not match the same show classified without apostrophes (e.g., `Foxs Den` from dot-separated filenames). `normalize_series_text("Fox's Den")` produced `"fox s den"` (3 tokens) while `normalize_series_text("Foxs Den")` produced `"foxs den"` (2 tokens). This caused folder matching to fail.

**Affected file:** `app/services/resolver.py` (`normalize_text`)

**Fix:** Strip apostrophes in `normalize_text()` so punctuation is ignored during normalization:
```python
def normalize_text(value: str) -> str:
    value = value.replace("'", "")
    return " ".join(WORD_RE.findall(value.lower()))
```

This is global — `normalize_series_text` calls `normalize_text`, so both series and movie matching benefit.

**Verification:** `normalize_series_text("Fox's Den")` now returns `"foxs den"` matching `normalize_series_text("Foxs Den")`.

### File existence by episode number in resolver

**Problem:** The resolver constructed target filenames from scratch using a template (`{episode_title} - S{ss}E{ee}{ext}`) but never checked if a file for that episode already existed in the season directory under a different name. Existing files like `[RlsGrp] Fox Den - S01E04v2.mkv` were missed because the constructed path `Fox Den - S01E04.mkv` didn't match, causing `file_exists=False` and action `"move"` instead of `"replace"`.

**Affected file:** `app/services/resolver.py` (`_resolve_series`)

**Fix:** After constructing the target path, scan `season_dir` for existing video files containing the same `S{ss}E{ee}` pattern with optional `v\d+` suffix. If found, use that file's path as `target_path`:
```python
episode_tag = f"s{season_number:02d}e{episode_number:02d}"
if season_dir.exists():
    for f in season_dir.iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            if re.search(rf"{re.escape(episode_tag)}(?:v\d+)?(?=[^a-z0-9]|$)", f.stem.lower()):
                target_path = str(f)
                break
```

This ensures `Path(target_path).exists()` returns `True` in `scan_manager.py`, correctly setting `file_exists=True` and action to `"replace"`.

**Edge cases handled:**
- `S01E04v2` → matches (v2 suffix captured)
- `S01E04 - Title` → matches (space after is non-alphanumeric)
- `S01E0423` → no match (digit after would need to be non-alphanumeric)

### Group-scoped path sync in Web UI

**Problem:** Smart path sync changed root-level segments (e.g., `/media1/` → `/media2/`) across ALL groups, not just the current show.

**Fix:** `syncPathChanges` (the legacy panel, now deleted) filtered by `item.title !== groupTitle` so changes only propagate within the same show group. `computePathSync` in `app/ui/react/src/utils/report.js` keeps this behavior.

### Path editing for solo groups

**Problem:** Editing the target path of any row whose title group has no other rows always reverts immediately — `syncPathChanges` reverts the input when `anySynced` is false, and there are no siblings to sync. Since every movie is its own group, **Update Paths was broken for all movies** (and single-episode series).

**Correct behavior:** Only revert when the group actually has other rows that could have been synced but none matched. A row alone in its group keeps the edit.

**Change:** `computePathSync` in `app/ui/react/src/utils/report.js` tracks `hasSameGroupSibling`:
- No same-group sibling → return `null` (keep the edit, no sync, no revert).
- Siblings exist but none share the changed prefix/chunk → `{ revert: true }`.
- Siblings synced → `{ updates: [...] }`.

The store's `onTargetInputChange` (AppStore.jsx) already skips revert when `computePathSync` returns `null`.

**Verification:** Unit test `keeps the edit (no revert) when the row is alone in its group` in `report.test.js`. Live check: type a change into a movie's target input — it persists instead of snapping back.

### Confirm progress tool name mismatch (React UI)

**Problem:** After clicking "Start Move" in the confirm modal, the progress never updated and the backend logged `TOOL xxx get move new downloads scan confirm progress (not found)` on every poll. The cross-drive copy ran fine in the background; only the UI polling failed.

**Cause:** `app/ui/react/src/store/AppStore.jsx` `pollConfirmProgress()` called the tool `'get move new downloads scan confirm progress'`, but the backend registers `'get move new downloads confirm progress'` (`app/main.py` tool list + handler dispatch).

**Fix:** `AppStore.jsx:484` → `'get move new downloads confirm progress'`.

**Verification:** After `npm run build` + container restart, confirm a cross-drive move and watch the modal update live (Phase, Copied, Speed, File %). Backend logs show `✅ Ran "get move new downloads confirm progress"` with no `(not found)`.

### Confirm progress counts were cumulative across confirms

**Problem:** Confirming items in multiple batches on one scan showed wrong progress in the confirm modal — e.g. after confirming 4 movies one-by-one, the last 1-item confirm showed `Overall: 5/1 (100%)` and `Counts: Moved: 5`. The processed/moved counts accumulated across confirms while the total reset per confirm.

**Cause:** `_format_confirm_progress` (`app/main.py`) computed `processed = scan.counts.moved + scan.counts.replaced + scan.counts.failed` — but `scan.counts` is cumulative for the whole scan (used by the final report), while `total = scan.confirm_total` is per-confirm.

**Fix (per-confirm scoped progress):**
- `ScanPlan` (`app/models/schemas.py`) gained `confirm_processed`, `confirm_start_moved`, `confirm_start_replaced`, `confirm_start_failed`.
- `run_confirm` (`scan_manager.py`) resets `confirm_processed = 0` and snapshots the cumulative counts as baselines when a confirm starts.
- The move loop increments `confirm_processed` in a `finally` block per item.
- `_format_confirm_progress` now reports `processed = confirm_processed` and per-confirm counts as `counts.* - confirm_start_*`.

The scan report still uses the cumulative `scan.counts` (unchanged), so the post-confirm report summary stays correct.

**Verification:** `python3 -m pytest tests/` (the confirm-progress test in `tests/test_scan_errors.py` now asserts `processed`/`total` and per-confirm `counts`). Live: after several one-by-one confirms, each modal shows `Overall: N/N (100%)` with per-batch counts, never `5/1`.

### Auto-load report on scan complete and page load

**Pattern:** The report should load automatically without requiring the user to click "Get Report". Two triggers:
1. `pollScanProgress` calls `setTimeout(fetchReport, 500)` when `result.status === 'completed'`
2. `checkConnection` calls `fetchReport()` after loading libraries on page load

`fetchReport` uses a `finally` block to re-enable the "Get Report" button so it never stays disabled on error.

### React UI routes: path-based SPA routing

**Problem:** The app used hash routing (`/#/settings`). Direct links to `/settings` returned FastAPI's `{"detail": "Not Found"}`. Relative build asset URLs (`./assets/...`) also break on nested paths.

**Fix (current):** Path-based routing. The React app is the **main UI at `/`**:
- `app/ui/react/src/store/AppStore.jsx` reads `window.location.pathname` (`pageFromPath`) and navigates with `window.history.pushState` + a `popstate` listener (no server round-trip on nav).
- `vite.config.js` builds with `base: '/'` (absolute asset URLs) so the bundle loads on any route.
- `app/ui/server.py`: `GET /` serves `react-dist/index.html`, and `/scan`, `/settings`, `/apikeys` serve the same SPA page (deep-link refresh). `/assets` and `/react/assets` both mount `react-dist/assets` (backward compat); `GET /react` and `GET /react/` 308-redirect to `/`.

**Verification:** `curl -s -o /dev/null -w '%{http_code}' http://host:18328/settings` returns 200 with the React HTML; `http://host:18328/react` returns 308 → `/`; frontend tests assert `window.location.pathname` (`/apikeys`, `/`) after navigation.

### React UI tests must run via npm test in app/ui/react

**Problem:** Running `npx vitest` from the repo root (no local vitest, no vite config with jsdom) installs a fresh vitest, runs with the node environment, and fails confusingly (no `document`, real network attempts, hung polls).

**Fix:** Always run frontend tests with `npm test` in `app/ui/react`. The local `vitest.config` (jsdom + `src/test/setup.js`) is picked up only there. Frontend test files live next to the code (`src/*.test.jsx`, `src/utils/*.test.js`, `src/components/*.test.jsx`).

**Verification:** `cd app/ui/react && npm test` → all test files green.

### Filesystem rollback hazard on this host

**Problem:** Edits under `/www1/...` occasionally reverted after a container restart (lost `server.py` changes, lost frontend test files), with no error reported by the edit/write tools.

**Fix:** After making changes and before relying on them, re-verify the file content (e.g. `grep`/`cat`), rebuild React (`npm run build`), and restart the container. Keep changes small and re-appliable; re-check critical files after each `docker restart jellysort`.

**Verification:** After a restart, confirm `grep react_redirect app/ui/server.py` and `grep -c 'rel="icon"' app/ui/react/index.html` still match.

### MCP auth + admin pages (plan 03)

**Design:** `MCP_ALLOW_UNAUTHENTICATED` defaults to `true`. When `false`, `/mcp` requests must present a valid API key (`Authorization: Bearer` or `X-API-Key`) or `ADMIN_UI_TOKEN`; the activity log line appends `as <user>`. Keys live hashed in `config/mcp_keys.json` (gitignored); the full key is returned exactly once at creation. Unauthenticated rejections are HTTP 401 with a JSON-RPC body `{code: -32001, message: "unauthorized"}` keeping the request `id`.

**Key code locations:**
- `app/core/auth.py` — `require_mcp_auth` dependency + `MCPUnauthorizedError`; handler in `app/main.py:273`.
- `app/services/api_key_manager.py` — hashed store, atomic writes, `threading.Lock`.
- `app/services/env_manager.py` — `ENV_SPEC` manifest drives the Settings page. `apply` classification: Jellyfin/download/MCP-UI vars are `live` (read from `os.environ` per call); model/paths/`WEB_UI_*` vars are `restart` (baked into the `ScanManager` snapshot). `update_env` validates via `Settings(**merged)`, rewrites `.env` preserving comments, and returns `{appliedLive, needsRecreate}`.
- `app/ui/server.py` — `/api/admin/env` + `/api/admin/api-keys` (CRUD). **Routes are under `/api/admin/*`, not `/admin/*`**, because the React apiClient prepends `/api`. All admin routes use `require_panel_auth` (the UI login), not a separate token.
- React: `TopBar.jsx` nav (Scan & Move / Settings / API Keys), `SettingsPage.jsx`, `ApiKeysPage.jsx`, page switching in `App.jsx` via `state.page`.

**Live config reload:** `.env` is bind-mounted into `/app`, so Settings saves take effect on disk instantly. `reload_settings()` patches `os.environ` from `.env`, resets `_settings`, and clears `get_config` — this is what makes `live` vars work without a restart. `restart` vars need `docker compose up -d --force-recreate`.

**Verification:** `python3 -m pytest tests/` (184 tests incl. `test_api_key_manager.py`, `test_mcp_auth.py`, `test_env_manager.py`, admin endpoint tests in `test_ui_api.py`). Frontend: `npm test` in `app/ui/react` (56 tests incl. `AdminPages.test.jsx`).

### Test suite counts

Backend `python3 -m pytest tests/` runs **184 tests** (uses the container: `docker exec jellysort python3 -m pytest`). Frontend `npm test` in `app/ui/react` runs **64 tests**. Keep both green after changes.

## Plans

The `plans/` directory is the central location for all project plans and roadmap documents. Each plan is a markdown file, named with a leading number (e.g. `03-mcp-auth-and-config-pages.md`). When working on a plan, reference the plan file path in conversations and use it as a checklist. Plans can be created, implemented incrementally, and marked complete within the same file.

## Project Learnings

Keep this section for durable lessons that do not fit under commands, project rules, release workflow, or known patterns.

When learning new project knowledge:

1. Read the existing local AGENTS.md first.
2. Search for a matching section or related learning.
3. Update the closest existing section first.
4. Add a new block only if the learning is truly unrelated.
5. Do not create dated diary-style entries.
6. Do not duplicate information already stored in another section.
