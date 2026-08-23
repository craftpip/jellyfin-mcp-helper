# 09 — External Orchestrator (simple)

> Goal: Let the external orchestrator (owns the torrent folder) drive *scan → check → fix → confirm one-by-one* and always know **which torrent folder → where** it will be organized.

## What the orchestrator needs (and will get)

Every `report.items[]` entry will contain **all** of:

* `confirmId`, `sourcePath` (file), **`sourceFolder` (torrent folder)**, `sourceName`, `targetPath`, `action` (`move`/`replace`/`skip`), `item_type` (`movie`/`series`/`skip`), `confidence`, `reason`, `fileSize`, `candidateTargets`
* `sourceFolder` is the **actual torrent name/folder** on disk — e.g. `Show.S01E01 [Group]` for `/media1/torrents/Show.S01E01 [Group]/Show.S01E01.mkv`, or `Movie.2024.mkv` itself if it’s a single-file torrent. It comes from `CandidateItem.container_path` (or the file’s parent) and is returned as a sibling to `sourcePath` so the orchestrator can `log(sourceFolder + " → " + targetPath)` without parsing paths.

`confirm` already accepts `itemIds` / `sourcePaths` / `sourcePrefixes` and queues, so one-by-one works.

## Flow the orchestrator will use

```
orchestrator adds torrent → /media1/torrents/Show.S01E01 [Group]  (knows the folder name it just created)
  → POST /mcp "move new downloads scan"
  → poll "get move new downloads scan progress" until completed
  → GET "get move new downloads scan report"
    → find items where sourceFolder == "Show.S01E01 [Group]"  (or sourcePath startsWith that folder)
    → log "Show.S01E01 [Group] (/media1/torrents/Show.S01E01 [Group]/Show.S01E01.mkv) → /media1/series/Show/Season 01/Show - S01E01.mkv (move)"
    → POST "confirm move new downloads scan" with itemIds: ["i7"]  // one by one
```

No retarget needed for the simple “fix = choose which to confirm” case.

## Changes to make (small, backwards-compatible)

* `app/models/schemas.py:ScannedItem` add `source_folder: str | None = Field(alias="sourceFolder")` derived from `candidate.container_path` (or `Path(source_path).parent.name` when it’s a single file)
* `app/services/scan_orchestrator.py` populate it when building `ScannedItem`
* `app/services/presenters.py:format_report_items` already passes through `ScannedItem` fields, so `sourceFolder` appears automatically in `report.items[]`
* Keep `retarget`/`undo`/`history` UI-only for now

## Verification

* `python3 -m pytest tests/` still green (new `sourceFolder` field is optional, existing tests ignore it)
* Manual `curl /mcp` 4-step loop and assert `sourceFolder` == the just-added torrent folder and `sourcePath → targetPath` is present, then confirm single `confirmId` moves that file

---
**Status:** Draft — tell me “looks good” and I’ll mark it `Ready` and not touch code until you say `go`.
