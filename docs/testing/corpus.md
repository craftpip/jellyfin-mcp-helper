# Corpus Fixtures

`tests/corpus/download_paths.json` is the committed regression corpus for the
classifier. It is a snapshot of real download-root paths (obfuscated), and the
corpus tests classify every entry, failing if any title contains release junk.

## The obfuscation rule (must be maintained)

This file is committed, so it must **never** reveal the user's actual media:

- Replace real series names with random words (they do not need to look
  plausible).
- Replace real release groups with neutral fakes (e.g. `[RlsGrp]`).
- Replace real root paths with neutral ones (e.g. `/media/downloads` →
  `/media1/downloads/`). Use the generic word "downloads" for the download-root
  concept; only keep a folder literally named "torrents" when it is real path
  data in a fixture.
- Keep the formatting tokens identical so the classifier runs on the same
  patterns: `SxxEyy`, `v2`, `REPACK`/`REPACK2`, years in parens, `1_2`-style
  underscore junk, dot-separated long titles, bracket-wrapped tags,
  codec/resolution strings (`1080p`, `x265`, `FLAC`, `Opus 2.0`),
  episode-per-folder counts and per-season splits.
- Keep `2.5`-style leading decimals — that is formatting, not identification.
- Update container-name-based regression tests (e.g. the underscore-junk
  consistency test) to match the obfuscated names.
- Never commit any reverse mapping back to the real names.

## Refreshing the corpus

After significant scanner or config changes, refresh the snapshot with a sweep
over `scan_candidates(cfg.paths)`, then obfuscate the new entries before
committing (see the rule above).

## Frontend tests

The React UI has its own tests, run **only** via `npm test` from
`app/ui/react` (Vitest + React Testing Library, jsdom). Do not run `npx vitest`
from the repo root — the root install has no jsdom/vite config and fails
confusingly. Test files are co-located:

- `src/utils/format.test.js`
- `src/utils/report.test.js` (includes the solo-group "keeps the edit" path-sync case)
- `src/utils/transfer.test.js`
- `src/components/PathPills.test.jsx`
- `src/components/ScanProgressPanel.test.jsx`
- `src/components/Toasts.test.jsx`
- `src/components/BrowseModal.test.jsx`
- `src/AdminPages.test.jsx`
- `src/App.test.jsx`
