# 12 — Group by Source Folder (instead of by match)

> **Current:** Groups are built by *match* — the classifier + resolver decide the target (e.g. `Show Name` → `/media1/series/Show`), and the UI groups items by that target’s parent (show folder). So two files from the **same torrent folder** can end up in different groups if they match different shows, and files from different folders can be merged into one group if they match the same show.

> **Wanted:** Groups are built by **the folder we are scanning** — the immediate child of a `DOWNLOAD_ROOTS` entry. All files that live in ` /media1/torrents/My Torrents/Show S01/` are one group, shown together, confirmed together, and moved together. No cross-folder merging.

---

## 1. What Changes

### 1.1 Definition of a group

* **New:** `group_key = container_path || Path(source_path).parent` — i.e. the torrent folder itself. If the torrent is a single file at `/media1/torrents/Movie.mkv` (no container), the group is that file’s parent (`/media1/torrents`) or just the file itself as a single-item group.
* **Old:** `group_key = target’s show folder` (`/media1/series/Show`) derived from the resolved target.

### 1.2 Where grouping happens

* **Scanner (`app/services/scanner.py`)** already provides `container_path` for each `CandidateItem` (the torrent folder) and `source_root`/`source_path`. No change needed there.
* **Scan orchestrator (`app/services/scan_orchestrator.py`)** currently builds `planned_targets`, `planned_episodes`, etc., and groups by `series_key` for the `group_retarget_pass`. That logic stays for *target* de-duplication, but the **UI grouping** must change.
* **Presenter (`app/services/presenters.py:format_report` + `format_report_items`)** is where `report.groups` are built. Today it groups by `Path(target_path).parent.parent` (show folder) or `Path(target_path).parent` (movie folder). Change it to group by `candidate.container_path` (or `source_path` itself if no container — per answer 1, single-file torrents are their own one-item group).

### 1.3 What the UI shows (per your answers)

* **ReportPanel + HistoryPage:** Each card’s header is the **source folder name only** (e.g. `[bonkai77] Millennium Actress…` or `Movie.mkv` for single-file torrents — per answer 1). For season packs (answer 2: 12 episodes → one group with one Confirm), the header is the torrent folder (`Show S01`), not each episode.
* **Counts:** `group.file_count` is the number of video files inside that source folder.

### 1.4 What confirmation does

* Confirming a group now means “confirm all items whose `container_path` == this group’s folder”. The `ScanManager.confirm_scan` already supports `sourcePrefixes` — we can pass the folder as a prefix, or just `sourcePaths` for the files in it. No new API needed, but the UI will call `confirm` with `sourcePrefixes: [group_key]` instead of `itemIds` per group.

### 1.5 What history stores (per your answers 3 & 4)

* `history_groups.group_key` becomes the **source folder** (`/media1/torrents/Show S01`), not the target show folder. `group_title` is the **source folder name only** (`Show S01` or `Movie.mkv`), same in Report and History. `pathHistory` per file stays `[source, target, target2…]` as before.

---

## 2. Angles & Edge Cases (per your answers)

* **Single-file torrents (answer 1):** No `container_path`; group is the file itself (`/media1/torrents/Movie.mkv`). Show as a one-item group named `Movie.mkv` (source folder name).
* **Season packs (answer 2):** `Show S01` with 12 episodes → **one group, one Confirm** as you confirmed.
* **Nested folders:** Torrent folder contains subfolders (e.g. `Show S01/Season 01/E01.mkv`). All files under the same top-level `container_path` are still one group, even though their `relative_path` differs.
* **Mixed classifications in one folder (answer 5: yes):** If a folder has both a movie and a series file, keep them **together** in one source-folder group (previously they’d be split). The user can still retarget per file inside the group via the table.
* **Cross-drive, replaces, skips:** No change — those are per-file, not per-group.
* **Existing history:** Old `history_groups` with `group_key = /media1/series/Show` will remain as is; new groups will use source folders (`/media1/torrents/Show S01`). No migration needed, just new groups will look different (both show source folder name per answer 3/4).

---

## 3. Implementation Steps

1. **Presenter** `app/services/presenters.py` — add `container_path` to `ScannedItem` (already in `CandidateItem`, just pass it through) and change `format_report`’s grouping from `target_path` parent to `container_path` (fallback to `source_path` parent).
2. **Schemas** `app/models/schemas.py:ScannedItem` — add `container_path: str | None = None` (alias `containerPath`) and `source_folder: str | None` (alias `sourceFolder`) for display.
3. **Scan orchestrator** `app/services/scan_orchestrator.py` — when creating `ScannedItem`, set `container_path = candidate.container_path` and `source_folder` accordingly.
4. **UI** `ReportPanel.jsx` + `HistoryPage.jsx` — group header uses `sourceFolder` / `containerPath` name instead of target’s show folder. Confirm button now sends `sourcePrefixes` for the group.
5. **Tests** — update `tests/test_scan_errors.py` and `tests/test_ui_api.py` that assert grouping by target to expect grouping by source folder.

---

**Status:** Ready — answers 1-5 incorporated (single-file = own group, season packs = one group, show source folder name only, keep mixed together). Awaiting your `go` to implement.
