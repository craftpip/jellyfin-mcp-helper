# Agents

This project includes a skill file for managing the jellyfin-mcp-helper service.

## Skills

Load the `jellyfin-mcp-helper` skill to access full documentation for the API and MCP endpoints. The skill contains:
- Base configuration and URLs
- All API endpoints
- MCP protocol details (JSON-RPC 2.0)
- Log interpretation
- Workflow guidance

Use the skill tool to load it when working with this codebase.

## Project Structure

```
jellyfin-mcp-helper/
├── app/
│   ├── api/__init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py          # Settings, PathsConfig, ModelConfig, AppConfig
│   │   └── logging.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py         # Pydantic models (CandidateItem, ClassificationResult, etc.)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── classifier.py      # guessit-based + regex media classification
│   │   ├── download_client.py # qBittorrent MCP client
│   │   ├── jellyfin.py        # Jellyfin API client
│   │   ├── normalizer.py      # File/folder renaming
│   │   ├── ollama.py          # Ollama LLM client
│   │   ├── openrouter.py      # OpenRouter LLM client
│   │   ├── organizer.py       # Orchestrates scan → classify → resolve → move
│   │   ├── resolver.py        # PathResolver — path-matching logic
│   │   ├── run_manager.py     # Legacy run management
│   │   ├── scan_manager.py    # Scan-plan workflow (scan → confirm)
│   │   └── scanner.py         # Filesystem scanner — finds candidates
│   └── main.py                # FastAPI entry point + MCP endpoint handlers
├── tests/
│   ├── test_classifier.py
│   ├── test_mcp_errors.py
│   ├── test_resolver.py
│   └── test_scan_errors.py
├── config/
├── logs/
├── reports/
├── .env                       # Active configuration
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── INSTALL.md
├── README.md
└── SKILL.md
```

## Project Learnings

### Extra markers regex: numbered NCED/NCOP/OP/ED and decimal episode false positives

**Created:** 2026-06-19  
**Last updated:** 2026-06-19

**Trigger:** User noticed NCED1/NCOP2 files were classified as series instead of skip, and real episodes with an audio codec version string in the filename were incorrectly skipped as extras.

**Mistake / Problem:** Two regex bugs in `app/services/classifier.py`:

1. `EXTRA_MARKERS = r"\b(ncop|nced|op|ed|ova|ona|special|extras?|bonus|recap)\b"` — the trailing `\b` fails when the marker is followed by a digit (e.g. `NCED1`, `NCOP2`) because both the letter and digit are `\w` chars, so there's no word boundary between them.

2. `DECIMAL_EPISODE_RE = r"(?:^|[^a-z0-9])(?:s\d{1,2}e)?\d{1,3}\.\d+(?:[^a-z0-9]|$)"` — the optional `(?:s\d{1,2}e)?` group means bare decimals like `2.0` in audio codec strings (e.g. a filename like `... Opus 2.0 ...` or `... DDP2.0 ...`) matched as decimal episode numbers, causing real episodes to be skipped as "extras/specials".

**Correct Approach:**

1. `EXTRA_MARKERS` — append `\d*` to the short markers so the regex becomes:
   ```
   r"\b(ncop\d*|nced\d*|op\d*|ed\d*|ova|ona|special|extras?|bonus|recap)\b"
   ```
   This allows `NCED1`, `NCOP2`, `OP1`, `ED3` etc. to still match while maintaining the word boundary after the optional digits.

2. `DECIMAL_EPISODE_RE` — remove the `?` so the `s\d{1,2}e` prefix becomes required:
   ```
   r"(?:^|[^a-z0-9])s\d{1,2}e\d{1,3}\.\d+(?:[^a-z0-9]|$)"
   ```
   Now only patterns like `S01E1.5` match as decimal episodes, not bare `2.0`.

**Verification:** Run `pytest tests/` — all 63 tests must pass. Then manually test:
- NCED1/NCOP2 → `kind=skip` (was series before)
- S01E01 with Opus 2.0 → `kind=series` (was skip before)
- Standalone OP/ED → `kind=skip` (unchanged)

**Scope:** Applies to `app/services/classifier.py` when modifying classification patterns.

**Related terms:** classifier, extra markers, EXTRA_MARKERS, DECIMAL_EPISODE_RE, NCED, NCOP, Opus, codec version, decimal episode, regex, word boundary, false positive

### Always document patterns encountered when fixing

**Created:** 2026-06-19  
**Last updated:** 2026-06-19

**Trigger:** After fixing regex patterns for NCED/NCOP/Opus, user said "from now on all the patterns that we fixed we will also write it down what pattern we encountered."

**Mistake / Problem:** Without writing down the exact patterns encountered and how they were fixed, the same bugs could be reintroduced by future changes, or the reasoning behind a fix gets lost.

**Correct Approach:** Whenever fixing any pattern-based bug (regex, filename pattern, media naming convention, etc.), add a Project Learning entry that documents:
- What the problematic pattern was (the actual input that failed)
- What the old code matched/did
- What the fix was and why it works
- How to verify the fix

**Verification:** The AGENTS.md file contains a clear record of the pattern problem, the fix, and the verification steps.

**Scope:** Applies to any pattern-based fix in this project — regex, classification, path resolution, etc.

**Related terms:** pattern, regex, documentation, learning, AGENTS.md, classification, filename

### Rebuild Docker after code changes

**Created:** 2026-06-19  
**Last updated:** 2026-06-19

**Trigger:** User ran a new scan after classifier.py fixes on the host, but the Docker container ran the old code because the image wasn't rebuilt.

**Mistake / Problem:** The code runs inside a Docker container. Editing files on the host does not affect the running container. The Dockerfile copies `app/` into the image at build time (no volume mount for the app code).

**Correct Approach:** After modifying any `app/` source file, rebuild and restart the container:
```
docker compose build
docker compose restart
```

**Verification:** Check that the container is running the new code (e.g., run a scan and verify behavior changed).

**Scope:** Applies whenever changing any source code in this project (classifier, resolver, schemas, etc.).

**Related terms:** Docker, build, rebuild, restart, container, docker compose, deploy
