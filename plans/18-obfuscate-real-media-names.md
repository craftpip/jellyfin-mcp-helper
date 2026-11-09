# 18 — Remove real media names from code (behavior-preserving obfuscation sweep)

> **Status: PROPOSED — awaiting `go`.**
>
> Per AGENTS.md rules ("Never mention real file/media names in code" and "Corpus
> fixtures must be obfuscated before commit"), real show/movie titles must not
> appear in code, comments, tests, docs, or commit messages. This plan scrubs
> them with **no behavior change** to the classifier, resolver, or MCP service.

## Research summary (why this is behavior-safe)

1. **Every real-name hit in runtime `app/` source is a comment or docstring
   only** (`titles.py:241`, `scan_orchestrator.py:728`, `resolver.py:78`,
   `report.js:284`) — none is compared, matched, or branched on. Renaming them
   cannot change runtime behavior.
2. **`.env` is gitignored and holds the only *live* real-name config**:
   `SERIES_TITLE_ALIASES=Zboj Oflp::Dibjotnplfs Dbu Zboj Oflp`. It is real
   operational data read at runtime by the alias feature — **do NOT touch it.**
   Replacing the alias there would actually change behavior.
3. **Test fixtures are renamed in pairs** (input + expected assertion). The
   classifier is pattern-driven; structural tokens (`SxxEyy`, years in parens,
   codec strings, bracket groups) drive classification, not title words — so
   swapping title words to neutral ones preserves every classification result
   provided the paired assertion is renamed with the input.
4. **The one measurable-behavior surface is `_fuzzy_score` bounds** in
   `tests/test_mcp_errors.py:146-153` (`FUZZY_SCORE_CASES`: exact-match 1.0,
   typo 0.65, etc. are literal numbers derived from string similarity). The
   algorithm is untouched; the bounds only need re-measuring against the
   placeholder names after renaming (or keep daylight in the min bounds).
5. **Audit caveat — phrase matching is insufficient.** The exact-phrase sweep
   (full library folder names) misses token/partial leaks ("Pof Qjfdf" leaked
   from library entries like "Pof Qjfdf Gjmn Sfe (2022)"). The re-sweep must
   use multi-word substring + a curated franchise wordlist.

## Verified inventory of leaks (Sep 2026)

Confirmed real (present in the on-disk library at `/mnt/media*t/downloads/*` or
the `torrents/` root):

| Where | Real name(s) leaked |
| --- | --- |
| `app/classification/titles.py:241` (comment) | `3 Jejput (2009)` |
| `app/services/scan_orchestrator.py:728` (comment) | `Lszqupo` |
| `app/services/resolver.py:78` (docstring) | `Nimbus` — already neutral, verify only |
| `app/ui/react/src/utils/report.js:284` (comment) | `Mboufsot` |
| `app/ui/react/src/utils/report.test.js:404,408,412` | `Mboufsot (2026)` |
| `app/ui/react/src/utils/report.test.js:480-482` | `Uptij Efotfutv Tfsjft` |
| `app/ui/react/src/components/TargetPathEditor.test.jsx` | `Uptij Efotfutv Tfsjft` |
| `tests/test_classifier.py:144-146,161` | `3 Jejput (2009)` |
| `tests/test_classifier.py:480-484` | `Zboj Oflp` / `Dibjotnplfs Dbu Zboj Oflp` |
| `tests/test_classifier.py:596-597,625` | `LSZQUPO (2018-2019)`, `Qtzdip-Qbtt (2012)`, real report id `8fdd42e11…` |
| `tests/test_ui_api.py:517,526` | `Bohfm't Fhh (1985)` |
| `tests/test_mcp_errors.py:146-175,187-218,436-663` | `Pof Qjfdf`, `Pof-Qvodi Nbo`, `Nvtiplv Ufotfj`, `Buubdl po Ujubo`, `Cmfbdi`, `Tqjefs-Nbo`, `Esbhpo Cbmm`, `Eboebebo`, `Uif Pggjdf` |
| `docs/architecture/media-flow.md:36` | `3 Jejput (2009)` |
| `docs/services/classifier.md:60-61,116` | `3 Jejput (2009)` |
| `docs/getting-started/configuration.md:87` + `.env.example` | `Zboj Oflp::Dibjotnplfs Dbu Zboj Oflp` |
| `AGENTS.md:221,237,246` | `3 Jejput (2009)` |
| `AGENTS.md:354` | `Npsubm Lpncbu (1995)` |
| `AGENTS.md:424,433` | `Pof Qjfdf`, `Nvtiplv Ufotfj` |
| `AGENTS.md:548` | `Mboufsot` (solo-row example) |
| `plans/archive/11` (`Beacon Test`), `12` n/a, `16` (`Uptij`), `17` (`Efyufs`) | archived-plan examples |

Known non-leaks (do NOT change): `Nimbus`, `3 Fossil Geese`,
`2.5 Crumpled Staircase` (obfuscated corpus placeholders), `RlsGrp`. The corpus
fixture `tests/corpus/download_paths.json` is already clean.

## Proposed behavior — deterministic neutral placeholder map

Replace every occurrence of a real name with one fixed random-word placeholder
(repo-wide, so paired assertions and docs stay consistent). Random words must
**not look like plausible show titles** (per corpus rule). Structural tokens are
preserved exactly (number prefixes, year in parens, `SxxEyy`, bracket groups).

**Shape preservation (user-confirmed):** each placeholder keeps the real name's
*feel* — the exact **word count** (a hyphenated compound counts as one word) and
the exact **casing scheme** (ALL-CAPS stays ALL-CAPS, Title Case stays Title
Case, possessive `'s` kept). Never add/remove words; never change case.

| Real name | Neutral placeholder |
| --- | --- |
| `3 Jejput (2009)` | `3 Lemurs (2009)` |
| `Npsubm Lpncbu (1995)` | `Wrangler Sceptre (1995)` |
| `LSZQUPO (2018-2019)` | `HAKMAR (2018-2019)` |
| `Qtzdip-Qbtt (2012)` | `Iris-Gate (2012)` |
| `Zboj Oflp` → `Dibjotnplfs Dbu Zboj Oflp` | `Rokin Neko` → `Velvet Tamarin Rokin Neko` |
| `Mboufsot (2026)` | `Whistler (2026)` |
| `Bohfm't Fhh (1985)` | `Shepherd's Fern (1985)` |
| `Uptij Efotfutv Tfsjft` | `Clatter Mesa Series` |
| `Pof Qjfdf` | `Great Norther` |
| `Pof-Qvodi Nbo` | `Solo-Slam Man` |
| `Nvtiplv Ufotfj` | `Wild Restart` |
| `Buubdl po Ujubo` | `Raid on Breaker` |
| `Cmfbdi` | `Mangle` |
| `Tqjefs-Nbo: Op Xbz Ipnf` | `Crawler: No Way Home` |
| `Esbhpo Cbmm Z` | `Ember Sphere Z` |
| `Eboebebo` | `Doddadan` |
| `Uif Pggjdf` | `The Bureau` |

Replacement rules:

0. **Casing variants.** Replace each variant with the same-cased placeholder:
   `LSZQUPO` → `HAKMAR`, `Lszqupo` → `Hakmar`; `3 Jejput` → `3 Lemurs` stays Title
   Case. Never collapse an ALL-CAPS container name to Title Case or vice versa.
1. **Paired renames in tests.** Any test that feeds the name into the
   classifier/resolver/MCP AND asserts it (or its derivative) back must rename
   both sides. Example: `test_ui_api.py` moves `Bohfm't Fhh (1985).mkv` and
   asserts `targetPath.name == "Bohfm't Fhh (1985).mkv"` — rename the sample
   file and the expected string together.
2. **Re-measure fuzzy bounds.** After renaming
   `tests/test_mcp_errors.py::test_fuzzy_score` inputs, run the unchanged
   `_fuzzy_score` over the new pairs and update `FUZZY_SCORE_CASES` min bounds.
   Intent preserved: exact→1.0, near-typo→moderate, unrelated→low.
   (`test_fuzzy_score_unrelated_is_low` keeps `("tubs xbst", "Uif Pggjdf")` →
   both names obfuscated; assert `< 0.3` still.)
3. **Remove the real report id** `8fdd42e115bf472b8bd339bbca566ab8` from the
   `test_classifier.py:596-597` comment — reference the shape, not the id.
4. **Comments/docstrings:** pure text replace, no logic touched.
5. **Docs/AGENTS:** replace names and soften the "obfuscated corpus
   equivalents" claim wording so it can't be mistaken for real titles. Confirm
   `docs/getting-started/configuration.md` and `.env.example` stay in sync with
   each other (both obfuscated); the live gitignored `.env` keeps its real
   alias (unchanged behavior).
6. **Archived plans:** scrub the example names in `plans/archive/` too (they are
   committed repo content); `Beacon Test` was a harness folder, switch it to a
   neutral one for consistency.
7. **Commit messages going forward:** no real names (rule). Current history is
   clean on the scanned names — history rewrite is out of scope.

## Files to change

| File | Change |
| --- | --- |
| `app/classification/titles.py` | comment `3 Jejput (2009)` → placeholder |
| `app/services/scan_orchestrator.py` | comment `Lszqupo` → `Hakmar` |
| `app/ui/react/src/utils/report.js` | comment `Mboufsot` → placeholder |
| `app/ui/react/src/utils/report.test.js` | `Mboufsot (2026)` + `Uptij Efotfutv Tfsjft` fixtures |
| `app/ui/react/src/components/TargetPathEditor.test.jsx` | `Uptij Efotfutv Tfsjft` fixture |
| `tests/test_classifier.py` | `3 Jejput`, `Zboj Oflp` alias, `LSZQUPO`/`Qtzdip-Qbtt` (+ report id) |
| `tests/test_ui_api.py` | `Bohfm't Fhh` sample + assert |
| `tests/test_mcp_errors.py` | fuzzy fixtures + Jellyfin/MCP `seriesName` payloads |
| `docs/architecture/media-flow.md`, `docs/services/classifier.md` | `3 Jejput` examples |
| `docs/getting-started/configuration.md`, `.env.example` | `Zboj Oflp` alias example |
| `AGENTS.md` | leak lines + wording |
| `plans/archive/11,16,17` | example names |

Not touched: `.env` (live config, gitignored), `reports/`, `logs/`,
`config/app.db` (runtime data), `tests/corpus/download_paths.json` (clean).

## Verification

1. **Re-sweep with tokenized matching, not phrase matching:**
   `grep -rEi` over `app/ tests/ docs/ plans/ *.md` for each placeholder's real
   counterpart list split into multi-word substrings AND a curated franchise
   wordlist (`ness`, `ujubo`, `npsubm`, `lszqupo`, `qtzdip`, `mboufso`,
   `uptij`, `eboebebo`, `pof qjfdf`, `pof-qvodi`, `nvtiplv`, `efyufs`,
   `cmfbdi`, `esbhpo cbmm`, `tqjefs-nbo`, `bohfm.*fhh`, `zboj`, `dibjotnplfs`,
   `3 jejpu`) → **zero hits**, excluding `.env`, `reports/`, `logs/`,
   `.pytest_cache/`, `.ruff_cache/`, `node_modules/`, `react-dist/`.
2. `docker exec jellysort python3 -m pytest tests/` → green, same count as
   before (behavior unchanged; only fixture strings + doc text moved).
3. `cd app/ui/react && npm test` → green; then `npm run build` +
   `docker restart jellysort`; re-grep the built bundle for the banned list → 0.
4. Spot-check live behavior: a hinted/alias scan + a classify still produce the
   same titles/actions as pre-change (resolver + alias features untouched).

## Out of scope

- `.env` values and any runtime data files (reports, logs, SQLite).
- Git history rewrite (repo history is already clean on the scanned names;
  going forward the rule applies). Offer `git filter-repo` only if later find.
- Any classifier/resolver/MCP algorithm, regex, or reclassification logic.
- The corpus fixture file (already obfuscated).

## Release workflow (AGENTS.md)

Branch feature/18-… off `dev`, merge to `dev` on completion, then
dev → prod + version bump + `docker compose build` (plan 07-style sync of
docs after; update the "Last synced commit" line in README).