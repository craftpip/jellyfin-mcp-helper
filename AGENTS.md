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

## Project Learnings

Keep this section for durable lessons that do not fit under commands, project rules, release workflow, or known patterns.

When learning new project knowledge:

1. Read the existing local AGENTS.md first.
2. Search for a matching section or related learning.
3. Update the closest existing section first.
4. Add a new block only if the learning is truly unrelated.
5. Do not create dated diary-style entries.
6. Do not duplicate information already stored in another section.
