# Agents

This is the local project AGENTS.md for the jellyfin-mcp-helper repository.

Use this file as the project handbook. Keep it compact and practical. Update existing sections when new related learning is added. Do not turn this file into a dated chat log.

## Skills

Load the jellyfin-mcp-helper skill when working with this codebase.

The skill contains:

- Base configuration and URLs
- API endpoints
- MCP protocol details using JSON-RPC 2.0
- Log interpretation
- Workflow guidance

## Commands

- Test: python3 -m pytest tests/
- Rebuild after source changes: docker compose build && docker compose restart

## Project Structure

- app/core/config.py: settings and config models
- app/core/logging.py: logging setup
- app/models/schemas.py: Pydantic models
- app/services/classifier.py: guessit-based and regex media classification
- app/services/download_client.py: qBittorrent MCP client
- app/services/jellyfin.py: Jellyfin API client
- app/services/normalizer.py: file and folder renaming
- app/services/ollama.py: Ollama LLM client
- app/services/openrouter.py: OpenRouter LLM client
- app/services/organizer.py: scan, classify, resolve, and move orchestration
- app/services/resolver.py: PathResolver path-matching logic
- app/services/run_manager.py: legacy run management
- app/services/scan_manager.py: scan-plan workflow, scan then confirm
- app/services/scanner.py: filesystem scanner
- app/main.py: FastAPI entry point and MCP handlers
- tests/: pytest test suite
- config/: config files
- logs/: runtime logs
- reports/: generated reports
- .env: active configuration
- docker-compose.yml: container orchestration
- Dockerfile: image build definition
- requirements.txt: Python dependencies
- INSTALL.md: install documentation
- README.md: project documentation
- SKILL.md: project skill documentation

## Project Rules

### Docker rebuild after code changes

The app code is copied into the Docker image at build time. Editing source files on the host does not update the running container unless the container is rebuilt.

After changing any app/ source file, run: docker compose build && docker compose restart

Verify by rerunning the affected scan or API behavior after restart.

### Release workflow

Use a two-branch release model:

- dev for active development
- prod for stable production releases

Feature and fix branches merge into dev first.

When ready to release:

1. Merge or fast-forward dev into prod.
2. Update version in app/core/version.py.
3. Update CHANGELOG.md.
4. Run python3 -m pytest tests/.
5. Run docker compose build.
6. Create the release commit.
7. Tag from prod as vX.Y.Z.

app/core/version.py is the single source of truth for the service version.

RELEASE.md is the canonical workflow document.

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

**Fixes (three parts):**

1. **Remove `sorted()` from `series_aliases`** — let `rglob("*")` stop at the `break` naturally.
2. **Use targeted extension globs** (`root.rglob(f"*{ext}")` for each extension) instead of `root.rglob("*")` — only yields video files, no directory entries to filter.
3. **Token overlap check in `_pick_exact_path_match`** — before calling `series_aliases(path)` (which walks the dir tree), check if `tokenize(title) & tokenize(folder_name)` is non-empty. Non-matching directories like "One Piece" when searching for "Mushoku Tensei" skip the walk entirely. This is the most impactful optimization.

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

## Project Learnings

Keep this section for durable lessons that do not fit under commands, project rules, release workflow, or known patterns.

When learning new project knowledge:

1. Read the existing local AGENTS.md first.
2. Search for a matching section or related learning.
3. Update the closest existing section first.
4. Add a new block only if the learning is truly unrelated.
5. Do not create dated diary-style entries.
6. Do not duplicate information already stored in another section.
