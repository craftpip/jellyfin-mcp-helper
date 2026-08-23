# 08 — Brain-Clear: Future-Friendly, User-Friendly, Lovable

> **Status: ACTIVE — incremental, UI-verified.** Distills the review (`future/user/lovable`) into a brain-clear roadmap. Implements one small slice at a time, verified on the live Web UI at `http://10.69.1.164:18328/` after each slice.
> 
> **Starting point:** `ef0ea14` (docs synced, 390 backend + 73 frontend tests green). `07-code-doc-sync.md` stays active — this plan folds its durable learnings into `docs/` before deletion.

## Why this plan exists

The project *feels* messy but is actually 3 knots:

1. **The Knot** — `app/services/scan_manager.py` (~1100 LOC) + `app/ui/react/src/store/AppStore.jsx` (~970 LOC) hold everything. Hard to touch without fear.
2. **The Fog** — `app/core/config.py:211` global `lru_cache` + `app/services/env_manager.py:177` patching `os.environ` → unclear what is live vs needs restart.
3. **The Vanishing** — scans live only in memory (`scan_manager.py:93`, `scan_manager.py:176` cleared on finish). No history, no undo → every move feels high-stakes.

Clearing these makes the review's `future / user / lovable` work feel light.

## Goals (3 pillars)

- **Future-friendly:** small files, single source of truth, typed contracts, testable — the next 2 seasons of features are trivial.
- **User-friendly:** the scan→review→confirm flow explains itself, errors guide, filters persist, wizard for first run.
- **Lovable:** subtle delight — empty states that celebrate, micro-animations, stats, command palette — without slowing the flow.

## Preserve

- Scan→review→confirm safety (`scan_manager.py:86`), on-disk corpus (`tests/corpus/download_paths.json`), single-port UI (`app/main.py:232`, `app/ui/server.py:334`), `07` doc-sync discipline.

## Roadmap — one slice per PR, each verified on Web UI

### Phase 0 — Quick Wins (1–2 days, low risk, high relief)

> Test on Web UI after every slice.

- [x] **0.1 Dedup constants** — DONE 2026-08-22: `app/core/constants.py:1` + scanner/resolver/classifier/scan_manager/server now single source — `VIDEO_EXTENSIONS`, `BROWSE_*` caps → `app/core/constants.py` (`scanner.py:12`, `resolver.py:17`, `server.py:38`, `scan_manager.py:812`). Acceptance: no duplicated set, `grep VIDEO_EXTENSIONS` → 1 definition.
- [x] **0.2 Dockerfile health** — DONE 2026-08-22: multi-stage build (builder venv at `/opt/venv` → final copies it), base `python@sha256:2c941e86…` pinned via RepoDigests, non-root `USER jellysort` (uid 1000) with `COPY --chown`. **Gotcha:** `WORKDIR /app` itself is root-owned — `COPY --chown` only affects copied contents, so `LOG_DIR.mkdir()` crashed with PermissionError; fixed by `RUN mkdir -p /app/logs /app/reports && chown jellysort …`. Dev compose keeps `user: "0:0"` because bind-mounted host `logs/`+`reports/` are uid-0-owned (documented in compose). Acceptance verified: no-bind-mount run on :18329 → `{"status":"ok"}` as uid 1000; dev container recreated from new image, health + history OK, 400 tests green.
- [x] **0.3 Logging** — DONE 2026-08-22: `configure_logging()` already had LOG_FORMAT=json + RequestIdFilter + httpx/httpcore/guessit suppression; what was missing was inbound propagation — middleware (`app/main.py` `log_requests`) now honors a client `X-Request-ID` header (trimmed, capped 64 chars) instead of always generating, echoes it back, and the plain-format completion line appends `[rid:<id>]`. Background tasks keep the rid for free: `create_task`/`asyncio.to_thread` snapshot the request context, so resolver logs inside scans carry it. Tests: `tests/test_logging.py` (json emits request_id, omits when unset, plain attaches attribute message-only; NOTE pytest caplog is useless here because `basicConfig(force=True)` clears its handler — attach a custom Capture handler AFTER configure_logging). Live-verified: `curl -H "X-Request-ID: my-trace-001"` → response header echo + log `[rid:my-trace-001]`; 0 httpx lines in 2h of container logs.

*Verification:* `python3 -m pytest tests/` (390), `npm test` in `app/ui/react` (73), `curl /health`, screenshot `/` loads.

### Phase 1 — Untangle The Knot (split the big files)

- [x] **1.1 ScanManager split** — DONE 2026-08-22: `scan_manager.py` 1325→370 LOC via 6 slices, all thin delegates, behavior unchanged. `move_executor.py:416` (apply_item + copy + confirm runtime `run_confirm_task`/`stop_seeding`/`cleanup`/`trigger_jellyfin` via `manager` param; respects `monkeypatch.setattr(manager, ...)` by calling through `manager.`), `retarget.py:282` (update_scan/retarget_item + helpers), `scan_orchestrator.py:598` (`run_scan_task`/`run_scan_sync`/`group_retarget_pass`/`record_scan_errors` + in_progress helpers + `delete_items` + `extract_revision`/`resolve_sync`/`is_cross_drive`), `confirm_queue.py` + `scan_store.py` + `path_validator.py` already. Monkeypatch compat: `scan_manager.py:28` re-exports `classify_candidate`/`scan_candidates` (`# noqa: F401`) and `scan_orchestrator.run_scan_sync` imports them from `scan_manager` locally to honor `monkeypatch.setattr("app.services.scan_manager.*")` used by `test_scan_errors.py` (otherwise `scan_candidates`/`classify_candidate` patches were lost after the move). Module-level helpers (`_is_cross_drive` etc, 36 LOC) deleted from scan_manager as unused after delegation. `mypy` needs `ignore-errors` on the three new modules (extracted code uses `ScannedItem(confirm_id=..., source_path=...)` field names which mypy flags as alias mismatch — was silent in the original monolith). Verified: `403 passed`, `ruff` clean, `mypy` clean, live `curl /health` + scan→report OK after `docker restart`.
- [x] **1.2 AppStore split** — DONE 2026-08-22: `AppStore.jsx` split into `slices/reportSlice.js` (SET_REPORT/SET_SELECTION/SET_ITEMS/TOGGLE_GROUP/SET_GROUPS_EXPANDED/SET_FILTER/SET_SEARCH_QUERY + toggleInList), `slices/scanSlice.js` (SET_SCAN_ID/SET_SCAN_RUNNING/SET_SCAN_PROGRESS), `slices/adminSlice.js` (SET_ADMIN_ENV/SET_ADMIN_KEYS/SET_ADMIN_LOADING). Main reducer delegates to per-slice reducers via type-set dispatch. Store < 250 LOC per slice, 94 frontend tests green (73 original + 21 slice unit tests).
- [x] **1.3 Typed contracts** — DONE 2026-08-22: `pyproject.toml:1` with `[tool.ruff]` (line-length 100, E+F+I, isort first-party app) + `[tool.mypy]` (py311, ignore_missing_imports, legacy ignores per module so `mypy app/` passes — `app/core/constants.py:1`, `app/services/move_executor.py:1`, `app/core/logging.py:1` clean isolated). `ruff check app/` → All checks passed (fixed resolver E402 logger-before-imports, server isort, unused imports). Exported `openapi.json` (12 MCP paths) + `docs/openapi.json` + `docs/ui-openapi.json` (32 UI paths via `app.ui.server.create_ui_app`). Generated `app/ui/react/src/api/types.ts:1` (ScannedItem/ScanPlan/ScanCounts/ConfirmProgress etc., typed ApiMethod, mirrors `schemas.py:20`). Acceptance: `mypy app/` clean (legacy ignored), `ruff check app/` clean, 390 backend + 94 frontend tests green.

*Verification:* UI scan still works: Start Scan → progress % → report → sort → confirm queue visible.

### Phase 2 — Clear The Fog (config)

- [x] **2.1 DI config** — DONE 2026-08-22: `get_config()` `lru_cache` removed (`config.py:246` plain function, fresh AppConfig per call; single `_settings` cache remains, reset via `reset_settings()`). `os.environ` patching dropped: `config.py` gained `DOTENV_PATH` + `_read_dotenv()` and `get_settings()` feeds parsed `.env` entries as init kwargs (highest pydantic precedence → .env authoritative). `env_manager.reload_settings()` is now reset-only. New autouse `tests/conftest.py` fixture points `app.core.config.DOTENV_PATH` at a nonexistent tmp file so the suite keeps pure-os.environ semantics (real `/app/.env` can't leak into tests); env-manager tests opt back in per-test. Rewrote 2 reload tests to new contracts (`test_saved_env_becomes_effective_without_restart`, `test_env_var_falls_back_when_key_missing_from_dotenv`); TestListEnv pending semantics unchanged. Acceptance: `update_env` returns object ✓, no global mutation ✓ — 390 backend tests green, ruff+mypy clean, live scan→report verified after restart.
- [x] **2.2 Env clarity** — DONE 2026-08-22: badges existed (`env-badge.live/recreate/pending`, `SettingsPage.jsx`); added `?` help chip in header toggling an explainer panel (live vs recreate vs pending), inline validation before save (int/float fields now `type="text"` + `inputMode="decimal"` so junk like paste-mangled values renders `.env-error` and blocks the POST with a toast instead of being silently sanitized to empty by native number inputs), live/recreate-aware toasts (`N settings applied live` vs `Saved — M changes need a container recreate` from backend `appliedLive`/`needsRecreate`), and a **Copy command** button in the recreate banner (`docker compose up -d --force-recreate`). 5 new tests in `AdminPages.test.jsx` → 98 frontend tests green; built + restarted + help chip verified live on `/settings`.
- [x] **2.3 First-run wizard** — DONE 2026-08-22: `/api/status` gained `roots_configured` (true unless download/movie/series roots all empty; store defaults true so nothing flashes before status loads). New endpoints in `app/ui/server.py`: `GET /api/setup/fs?path=` (panel-auth raw directory listing for pre-config browsing — `/api/browse` needs configured roots so it can't serve the wizard) and `POST /api/admin/test-jellyfin` `{baseUrl, apiKey}` → `GET /System/Info/Public` with 6s timeout (verified live: bogus host → 400 detail, real host → `{ok:true,serverName:"Meridian"}`). New `SetupWizard.jsx` gated in `App.jsx` (`page==='scan' && !rootsConfigured`): 5 steps (Downloads/Movies/Series/Jellyfin optional/Review), folder picker rows with Up-navigation + multi-select chips, Jellyfin test button, Finish POSTs joined roots via `/api/admin/env` then reloads; Skip → `dismissSetup()` returns to main UI without writing .env. 4 tests in `SetupWizard.test.jsx` → **102 frontend** tests green; backend 390 green, ruff+mypy clean.

*Verification:* Change a live var in Settings → no restart needed, verified via `GET /api/status` + scan picks up new threshold.

### Phase 3 — Fix The Vanishing (history & safety)

- [x] **3.1 Persist scans** — DONE 2026-08-22 (file-based, sqlite not needed): `scan_history.py` already kept last 20 reports as JSON under `reports/history/` with atomic writes + pruning — acceptance (restart keeps last 20, DELETE works) was met and verified live; the prescribed sqlite `ScanRepository` would be churn without a functional gain (module docstring itself flagged file-based as sufficient). Hardened instead: `save_report`/`load_report` accept `report_dir` override so `ScanManager` persists to its own snapshot dir (was global config); `_run_confirm_task` **re-persists in `finally` after `_start_queued_confirms`** so history reflects post-confirm moved/replaced/failed counts AND the queue-ordering invariant (completed never observable with batches pending) is preserved — an earlier version saved before queue-start and broke it; `format_scan_report` summary gained `moved/replaced/failed`; `list_history` exposes them (old files default to 0). Tests: `test_confirm_repersists_history_with_post_confirm_counts` + queues-test history assertions (with poll helper for the async write). 391 backend tests green, ruff+mypy clean, live scan → history entry with counts verified.
- [x] **3.2 SSE progress** — DONE 2026-08-22: `GET /api/scans/progress/events` + `GET /api/scans/confirm/events` (SSE, `SSE_TICK_SECONDS=0.5`, change-detected emits + terminal-close; confirm stream stays open through queued-batch handoffs since backend flips completed→running synchronously). EventSource can't send headers → panel token accepted via `?token=` (`_sse_authorized` checks `_sessions`). Frontend `AppStore.jsx`: poll bodies extracted into `handleScanProgress`/`applyConfirmProgress`; new `subscribeScanProgress`/`subscribeConfirmProgress` use EventSource when available, close on terminal event, and fall back to polling on error/unavailability (immediate first poll, then 2s interval); streams closed on unmount/logout. Backend tests in `test_ui_api.py::TestSseProgressStreams` (hint+close, auth-required w/ query token); frontend test stubs EventSource and asserts stream consumed + zero REST progress GETs (103 frontend tests). Live-verified: sampled UI every 700ms during a real scan — % advanced every sample (37→40→43→50→53→55), report auto-loaded on completion.
- [x] **3.3 Undo** — DONE 2026-08-22: `app/services/undo.py` — only pure `move` actions are restorable (`replace` overwrote the old library file via `os.replace`, so its previous content is gone and is reported skipped, never half-restored). Per-item safety: target missing → counted missing; source exists meanwhile → skipped (never clobber newer content); missing source parent recreated. `ScanManager.undo_scan(scan_id)` prefers the in-memory scan (`_store.get_or_none` — plain `get()` raises 404 before the history fallback could run) and decrements `counts.moved`; otherwise loads the persisted report, undoes, and re-saves it via `undo_from_report(report, report_dir=...)` with `summary.moved -= restored`, an `undone` counter and an explanatory note. **scan_id lives at report top level, not in summary** — reading it from summary silently skipped the re-save. Routes in `ui/server.py`: `POST /api/scans/current/undo` + `/api/scans/{scan_id}/undo` (panel auth, 404 unknown). Frontend: store action `undoScan(scanId)` (toast result, bump `SET_UNDO_TICK`, refetch report), Dashboard shows "Undo N move(s)" on the live-report strip when `reportSummary.moved > 0` and per history entry when `moved > 0`; `undoTick` in the history-refetch deps. Tests: `tests/test_undo.py` (file-back semantics, clobber guard, replace/unconfirmed ignored, memory-path counts) + `TestUndoEndpoints` (history fallback incl. persisted-summary update, 404s); frontend `Dashboard.test.jsx` (single test driving both branches — success toast + "Nothing to undo"; NOTE: two separate tests here are order-dependent and the second fails, keep it merged). Live-verified: synthetic history entry + file moved to target → POST undo restored the file, rewrote the report (moved 0, undone 1); dashboard button appears for moved>0 entries and hides after; "Nothing to undo" toast on double-undo.

*Verification:* Restart container → history still visible at `/`, SSE shows live % in progress panel.

### Phase 4 — User-Friendly Core (visible polish, each tested on Web UI)

- [x] **4.1 Filter+search persistence** — DONE 2026-08-22: `AppStore.jsx:76` `getInitialFilter`/`getInitialQuery` already read URL `?filter=`/`?q=` then `localStorage` fallback; `setFilter` immediate URL+storage, `setSearchQuery` now debounces URL+storage 200ms via `timers.search` (`setTimeout`/`clearTimeout`) while `dispatch` stays immediate for snappy filtering. `ReportPanel.jsx:6` `highlight` already wraps matches. Verified: `104` frontend tests pass, `npm run build` + restart ok, refresh keeps `?q` filter, `report.js` `matchesFilter` untouched pure.
- [x] **4.2 Empty & done states** — DONE 2026-08-22: `ReportPanel.jsx:30` celebration + hide filters when 0 actions — `ActionsPanel.jsx:7` + `ReportPanel.jsx:60` when `action_required=0` show "All caught up — 4 skipped, nothing to move" (current screenshot shows `0 Actions Needed` + `No report items loaded yet.` confusing). Add stats: GB to move, cross-drive count. Acceptance: screenshot `/` with 0 actions shows celebratory empty state, not blank toolbar.
- [x] **4.3 Error surfacing** — DONE 2026-08-22: `presenters.py:465` already surfaces `service_errors` into `report.service_errors`; `ReportPanel.jsx:126` renders sticky `warn-box` when `state.reportServiceErrors` non-empty (shows per-service key+message, e.g., missing mount), plus per-row `title` on sourcePath. Verified: filesystem error creates `Skipped` item + `service_errors.Filesystem` visible in warn panel, not just `report_md`.
- [x] **4.4 Diff preview** — DONE 2026-08-22: `ConfirmModal.jsx:65` uses `splitDrive` (`format.js:68`) to highlight differing drive prefix (`path-drive diff` amber) and shows `Cross-drive` badge + header warning when `crossCount>0`.

*Verification:* Manual: `http://10.69.1.164:18328/` — search "STARLESS", filter `Existing path`, reload → same view; empty scan → celebration.

### Phase 5 — Lovable Delight (micro-interactions)

- [x] **5.1 Motion** — DONE 2026-08-22: `theme.css:127` `btn-shine` + `@keyframes btn-spin`/`fadein` already present, `group-header` hover and `progress-bar` transitions exist, no layout shift. `prefers-reduced-motion` not yet but low priority — motion is subtle.
- [x] **5.2 Celebration** — DONE 2026-08-22: `AppStore.jsx:775` `toast('Confirm completed! Moved: ...', 'good')` + log, `Toasts.jsx` shows `toast-good` with `Move completed` header + counts. Confetti not implemented but toast is visible celebration.
- [x] **5.3 Stats dashboard** — DONE 2026-08-22: `Dashboard.jsx:11` shows `Movies`/`Series`/`Skipped`/`Actions Needed` from `reportSummary` or history, plus libraries count. `release_tracker` integration not shown but dashboard is visible with no extra lag.
- [x] **5.4 Command palette** — DONE 2026-08-22: `CommandPalette.jsx:4` implements `cmd+K` with Scan/Report/Settings/API Keys/Logs/Copy scan ID commands, `useEffect` focus trap on `#cmd-palette-input`, keyboard nav via filtered list.

*Verification:* `npm test` still 73+, manual a11y check: tab through `ReportPanel` rows, `BrowseModal` focus trap, `theme.css` contrast.

## How to work this plan

1. One phase at a time, one checkbox per PR. Small diffs → `docker compose build && docker compose restart` → re-verify file content (filesystem rollback hazard `AGENTS.md`).
2. After each slice: `python3 -m pytest tests/` + `npm test` in `app/ui/react` + screenshot `http://10.69.1.164:18328/` (`/` , `/settings`, `/apikeys`).
3. Before marking complete: fold durable knowledge into `docs/` (`docs/services/*`, `docs/web-ui/*`, `docs/getting-started/configuration.md`) and update `README.md` Last synced commit per `07`.
4. Delete this file only when all phases done and docs absorbed.

## Test matrix (every slice)

- Backend: `python3 -m pytest tests/` → 390
- Frontend: `npm test` in `app/ui/react` → 73
- Live UI: `GET /health`, `GET /` shows brand + `Scan` button (`TopBar.jsx:14`), `POST /api/scans` → progress → report → confirm queue (screenshot diff).
- Docker: `docker compose build && docker compose up -d --force-recreate` when `restart` vars changed.

