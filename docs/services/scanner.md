# Scanner — `app/services/scanner.py`

Walks the configured download roots and produces the raw candidate list. It is
stateless; every scan starts from the filesystem.

## Constants

| Constant | Value | Purpose |
| --- | --- | --- |
| `VIDEO_EXTENSIONS` | `.mkv .mp4 .avi .mov .m4v .wmv .flv` | Extensions treated as media candidates. |
| `SKIP_DIR_MARKERS` | `{".trickplay"}` | Directory name fragments to skip. |
| `SAMPLE_SIZE_THRESHOLD` | `150 * 1024 * 1024` (150 MB) | Files smaller than this are treated as possible samples. |
| `PARTIAL_FILE_MARKERS` | `.!qb .!ut .!bt .utpart .part .partial .parts .bc! .bc .bt! .az! .td .xltd .aria2 .incomplete .downloading .crdownload .download .opdownload .tmp .temp` | Incomplete-file suffix markers written by download clients (matched case-insensitively) — a sibling named `<candidate name><marker>` marks a download as in-progress; a file whose own name is `<video><marker>` (the rename shape most clients use, e.g. qBittorrent `Show.mkv.!qB`) is itself reported as an in-progress candidate. |
| `PARTIAL_FILE_PREFIXES` | `incomplete.`, `incomplete$` | Name prefixes some clients prepend to the real filename while downloading (e.g. `incomplete.Show.S01E01.mkv`). |

## Types

- `ScanPathError` — `(path, error)` from a failed walk/stat.
- `ScanCandidatesResult` — `candidates: list[CandidateItem]` plus
  `errors: list[ScanPathError]`.
- `RecentFile` — `(source_root, source_path, name, extension, file_size,
  modified_at, container_path)` for the "recently added" tool.

## Functions

### `scan_candidates(paths_config) -> ScanCandidatesResult`

Full scan used by the scan/plan workflow:

1. For each `download_root` in `PathsConfig.download_roots`:
   - Skip roots that don't exist (recording an error).
   - Derive the root key via `_infer_root_key`.
   - Iterate top-level children (dotfiles skipped).
   - A top-level **video file** becomes a candidate with `container_path=None`.
   - A **directory** is walked recursively (`_iter_child_files`) and each video
     file becomes a candidate with `container_path` set to the top-level folder.
2. Control sidecars are hidden (`_is_hidden_sidecar`, e.g. aria2's `.aria2`),
   renamed in-progress files (`_candidate_in_progress`: own name is
   `<video><marker>` or `<prefix><video>`) are reported as candidates with
   `in_progress=True`, and every normal video candidate gets an `in_progress`
   flag via `_is_in_progress_by_marker` — True when the parent directory
   holds a sibling `<name><marker>` or `<prefix><name>`
   (see [download-client.md](download-client.md)). The scan skips flagged
   candidates while `ENABLE_INCOMPLETE_DOWNLOAD_DETECTION` is on.
3. Filesystem errors are recorded as `ScanPathError` and never abort the scan.

### `recent_video_files(paths_config, hours, errors) -> list[RecentFile]`

Bounded listing for `downloads_recent_files`: walks each download
root's top-level entries (and their children), keeping only video files whose
mtime is within the last `hours` hours, newest first. Dotfiles, skipped
directories, and errors handled the same way as `scan_candidates`.

### `list_target_paths(root_path) -> list[str]`

Sorted list of a root's top-level entries (excluding dotfiles); used when
browsing candidate target roots.

## Error handling

Every place that can raise `OSError` (root existence, `iterdir`, `stat`, walk)
is wrapped so a single broken path (e.g. a stale bind mount returning `Errno 5`)
produces a `ScanPathError` instead of failing the whole scan. The `onerror`
handler of `os.walk` feeds errors into the same collection.

## Notes

- `_infer_root_key` maps a download root to `movie_{index}` style keys; unknown
  roots fall back to `"default"`.
- Traversal skips hidden files/dirs (`startswith(".")`) and any path segment
  containing a `SKIP_DIR_MARKERS` fragment.
