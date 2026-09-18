# 11 — Scan Hints (per-folder authoritative metadata from JellyJake)

> **Status: IMPLEMENTED + LIVE-VERIFIED (Phase A backend).** No UI changes.

## Verification results (2026-09-17)

1. `python3 -m pytest tests/` → **402 passed** (incl. 6 new `tests/test_scan_hints.py`).
2. Live hinted scan over `hintverify.s01/s02.pack` (12 files each, neutral names):
   **24/24 items**, all `series`, reason `JellyJake hint (strict)`, grouped by
   `sourceFolder` 12+12, all under ONE show dir `/media1/series/Beacon Test`.
3. Confirm-by-itemIds on all 24 → `moved: 24, failed: 0`; history showed exactly
   ONE group (`Beacon Test`, 24 moved). Test files, show dir, and history group
   removed afterwards; Jellyfin `Shows` library re-scanned. No trace left.

## Implementation checklist (concrete edits)

## Goal

Let an external caller (JellyJake) trigger `move new downloads scan` WITH per-folder
metadata that the scan strictly follows instead of re-guessing. JellyJake knows the
truth at download time (exact title, movie vs series, year, season per torrent folder)
but today triggers a blind scan and fuzzy-matches one report item. With hints,
JellySort classifies those folders strictly per hints, the report groups by
`sourceFolder` as today, and JellyJake confirms by `itemIds` as usual.

Verified driver case: one card with 2 completed torrent folders × 12 files each;
the current worker only matched 1 item.

## Scope — Phase A (backend only)

### 1. `app/models/schemas.py`

- New model `SortHint`:
  - `source_prefix: str` (torrent folder basename, e.g. download container dirname)
  - `title: str` (canonical show/movie title — authoritative)
  - `kind: Literal["movie","series"]` (authoritative)
  - `year: int | None = None`
  - `season: int | None = None` (pack season when known)
  - `strict: bool = True`
- `ScanRequest` gains:
  - `hints: list[SortHint] = Field(default_factory=list)`
  - `hint_scope: Literal["additive","only"] = "additive"` (only "additive" must work in v1; "only" may 400 as not-implemented)
- `ScanPlan` gains `hints: list[SortHint] = Field(default_factory=list)` (audit trail; set it in `create_scan`).

### 2. `app/main.py` — MCP schema for `move new downloads scan`

- Add `hints` (array of `{source_prefix*, title*, kind*, year, season, strict}`) and
  `hintScope` (enum additive/only, default additive) to `inputSchema`.
- Handler passes them into `ScanRequest(...)`. REST `POST /api/scans` path
  (`app/ui/server.py` ~line 535) must pass through too if it constructs `ScanRequest`.

### 3. `app/services/scan_orchestrator.py` — honor hints

- Build a hint index at scan start from `request.hints`, keyed by normalized
  `source_prefix` (casefold, strip). Match each candidate by
  `Path(candidate.container_path).name` (fallback: parent dirname of `source_path`).
- On match with `strict=True`: BYPASS `classify_candidate()` for title/kind —
  construct `ClassificationResult(type=hint.kind, title=hint.title, year=hint.year,
  season=hint.season ?? parsed-from-filename, episode=parsed SxxEyy from filename,
  confidence=1.0, reason="JellyJake hint (strict)")`. Still parse season/episode
  from the filename's `SxxEyy` tag as today (hint.season is the default when the
  filename has no tag).
- Safety checks still apply BEFORE the bypass: in-progress markers, zero-byte,
  non-video extensions behave exactly as today.
- Mismatch policy: if filename `SxxEyy` season != hint.season, keep the file's tag
  for numbering but set `suspect=True`, `flags += ["hint-season-mismatch"]`.
- Non-matching candidates: today's pipeline 100% unchanged.
- Resolver: hint title must seed target resolution first so S01/S02 folders of
  the same show converge on one show dir (use existing `_pick_exact_path_match` /
  `_resolve_sync` path with the hint classification — do not invent a new mover).

### 4. Tests — new `tests/test_scan_hints.py` (neutral placeholder names only)

- strict kind/title override: a folder that guessit would misclassify gets
  hint.kind/hint.title in the report with reason containing "hint".
- episode parsing preserved: SxxEyy in filename still yields season/episode.
- season-mismatch flag: file tag S02 vs hint.season=1 → suspect + flag, filed
  under file's season.
- additive: non-hinted folder in the same scan classifies exactly as before.
- MCP schema round-trip: `move new downloads scan` accepts hints + hintScope.

What "season parsing" looks like today: the classifier already parses
`SxxEyy` from the filename (see `app/services/classifier.py`); hint path
reuses that parsing for season/episode, with `hint.season` as the default
only when the filename has no tag.

## Repo rules to honor

- NEVER put real media titles / release groups / real paths in code, comments,
  commit messages, or fixtures. Tests use neutral placeholders (`Show S01E01.mkv`,
  `[RlsGrp]`, `/media1/downloads/`); `tests/corpus/download_paths.json` stays obfuscated.
- Report retrieval in verification: MCP `get move new downloads scan report` or DB
  (`load_report`), NEVER `cat reports/current.json`.
- No hardcoded host: reach the service via `docker exec jellysort curl
  http://127.0.0.1:18327/mcp` or the discovered host port 18328.
- After `app/` changes: rebuild/restart (`docker compose build && docker compose restart`
  — or `docker restart jellysort` if bind-mounted live) and re-verify file content
  post-restart (known rollback hazard on this host).
- Only neutral placeholder names in fixtures; no hint by real media identity.

## Out of scope (do NOT build)

- No React UI changes. No new browse/retarget endpoints. No `hint_scope="only"`
  implementation (400 is fine). No Jellyfin changes. No auto-confirm.

## Verification

1. `python3 -m pytest tests/` green (incl. new `tests/test_scan_hints.py`).
2. Live: trigger a hinted scan over two season folders of one show (12 files each);
   report shows all 24 items under ONE show dir, reasons contain "hint", grouped
   by sourceFolder; non-hinted files in the same scan unchanged.
3. Confirm-by-itemIds on the 24 items works; history shows one group.

## Implementation checklist

### A. `app/models/schemas.py`
- [ ] Add `SortHint(BaseModel)`: `source_prefix: str` (alias `sourcePrefix`),
  `title: str`, `kind: Literal["movie","series"]`, `year: int | None = None`,
  `season: int | None = None`, `strict: bool = True`;
  `model_config = {"populate_by_name": True}` (accepts both snake + camel keys).
- [ ] `ScanRequest` gains `hints: list[SortHint] = Field(default_factory=list)` and
  `hint_scope: Literal["additive","only"] = Field(default="additive", alias="hintScope")`.
- [ ] `ScanPlan` gains `hints: list[SortHint] = Field(default_factory=list)`.

### B. `app/services/scan_manager.py` — `create_scan`
- [ ] At top: if `request.hint_scope == "only"` → `raise HTTPException(400, "hint_scope='only' is not implemented in v1")`
  (MCP handler already maps HTTPException → error response; REST maps to 400).
- [ ] Set `hints=[h.model_copy(deep=True) for h in request.hints]` on BOTH
  `ScanPlan(...)` constructions (incremental-seed path ~line 102, fresh path ~line 124).

### C. `app/main.py` — `move new downloads scan`
- [ ] `_mcp_tools()` inputSchema (~line 326): add `hints` array
  (items: object with `sourcePrefix`/`source_prefix`, `title*`, `kind*` enum
  movie/series, `year`, `season`, `strict` default true) and `hintScope`
  enum [additive, only], default additive.
- [ ] Handler (~line 796): build `[SortHint(**h) for h in arguments.get("hints", [])]`
  (pydantic aliases accept either key style; invalid hint → 400 via ValidationError→HTTPException)
  and pass `hints=` + `hintScope=arguments.get("hintScope", "additive")` into `ScanRequest(...)`.

### D. `app/ui/server.py` — `POST /api/scans` (~line 545)
- [ ] Pass `hints=[SortHint(**h) for h in payload.get("hints", [])]` and
  `hintScope=payload.get("hintScope", "additive")` into `ScanRequest(...)`;
  import `SortHint` from `app.models.schemas`.

### E. `app/services/scan_orchestrator.py` — `run_scan_sync`
- [ ] At scan start (after `clear_resolver_cache`, before candidate loop): build
  `hint_index = {h.source_prefix.casefold().strip(): h for h in getattr(request, "hints", [])}`.
  Only `strict=True` hints bypass; `strict=False` hints are ignored (today's pipeline).
- [ ] Per candidate, AFTER in-progress + zero-byte skips, BEFORE `classify_candidate()`:
  key = `Path(candidate.container_path).name` if container_path
  else `Path(candidate.source_path).parent.name`; lookup `key.casefold().strip()`.
- [ ] On hit: parse file tag with `classifier._extract_season_episode(candidate.name)`
  (same SxxEyy-family parsing as today); `season = file_season ?? hint.season`,
  `episode = file_episode` (movie hints force both None, mirroring classifier:185-187).
  Build `ClassificationResult(type=hint.kind, title=hint.title, year=hint.year,
  season=..., episode=..., confidence=1.0, reason="JellyJake hint (strict)")`.
  Confidence 1.0 clears the threshold skip-check; kind movie/series skips the skip-branch;
  flow continues into existing `_resolve_sync` → `_pick_exact_path_match` unchanged
  (hint title seeds resolution; no new mover).
- [ ] Mismatch: if `hint.season is not None and file_season is not None and file_season != hint.season`
  → thread a local `hint_flags=["hint-season-mismatch"]` into the `flags` list built
  at ~line 444 (file's tag still drives numbering via classification.season=file_season);
  item gets `suspect=True` via existing `suspect=bool(flags)`.
- [ ] Non-video extensions: untouched — scanner yields only video files, and the bypass
  sits after the safety checks, so behavior is identical to today.

### F. `tests/test_scan_hints.py` (neutral placeholders only)
Harness pattern (from `test_scan_errors.py`): tmp `downloads/` root +
`AppConfig(paths=PathsConfig(downloadRoots=[...], movieRoots={"movie_0": ...},
seriesRoots={"series_0": ...}), model=ModelConfig(), log_dir=tmp, report_dir=tmp)`,
`ScanManager(config)`, `asyncio.run` create_scan → poll to completed.
- [ ] strict override: hinted folder whose names guessit misclassifies → report items
  carry hint kind/title, reason contains "hint".
- [ ] episode parsing: SxxEyy filenames under a series hint → season/episode set.
- [ ] mismatch: file S02 vs hint season=1 → suspect + `hint-season-mismatch`, filed under S02.
- [ ] additive: unhinted folder in same scan classifies exactly as a no-hint control scan.
- [ ] MCP round-trip: `_mcp_tools()` scan entry schema has `hints` + `hintScope`;
  MCP-style args dict builds a validating `ScanRequest`.
- [ ] `hint_scope="only"` → 400 from `create_scan`.