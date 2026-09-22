from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from app.core.config import PathsConfig
from app.core.constants import VIDEO_EXTENSIONS
from app.models.schemas import CandidateItem

SKIP_DIR_MARKERS = {".trickplay"}

# Incomplete-file markers (suffixes) that download clients append to a file
# while a download is still in progress, removed once the file completes.
# All are matched case-insensitively. Most clients RENAME the file itself
# (file.mkv -> file.mkv.!qB), so the renamed file must be reported as an
# in-progress candidate — not silently skipped (see _renamed_marker_suffix).
#   qBittorrent   -> .!qB   (file.mkv -> file.mkv.!qB)
#   uTorrent      -> .!ut / .utpart
#   BitTorrent    -> .!bt   (Windows mainline client)
#   BitComet      -> .bc! / .bc
#   BitSpirit     -> .bt!
#   Vuze/Azureus  -> .az! (+ .part)
#   Transmission  -> .part
#   rTorrent      -> .part  (split_suffix, default .part), plus .partial for split parts
#   Vuze/Azureus  -> .part
#   Deluge        -> no main-filename marker (keeps libtorrent .parts files
#                    only), so it cannot be detected via a sibling suffix.
#   Xunlei/Thunder-> .td / .xltd
#   aria2         -> .aria2 control sidecar (sibling marker only, never a candidate)
#   Browsers/managers -> .crdownload (Chrome), .download (Safari),
#                    .opdownload (Opera), .tmp/.temp (generic temp)
#   Generic       -> .incomplete, .downloading
PARTIAL_FILE_MARKERS = (
    ".!qb",
    ".!ut",
    ".!bt",
    ".utpart",
    ".part",
    ".partial",
    ".parts",
    ".bc!",
    ".bc",
    ".bt!",
    ".az!",
    ".td",
    ".xltd",
    ".aria2",
    ".incomplete",
    ".downloading",
    ".crdownload",
    ".download",
    ".opdownload",
    ".tmp",
    ".temp",
)

# Sidecar control files that are never video data and must stay invisible,
# even though stripping them would yield a video-looking stem
# (Show.mkv.aria2 -> Show.mkv). The real (preallocated) video file next to
# them is flagged in-progress via the sibling check instead.
HIDDEN_SIDECAR_SUFFIXES = (".aria2",)

# Incomplete-file name prefixes (Tixati appends "incomplete." before the real
# filename while the file is still downloading: file.mkv -> incomplete.file.mkv).
PARTIAL_FILE_PREFIXES = ("incomplete.", "incomplete$")


@dataclass(slots=True)
class ScanPathError:
    path: str
    error: str


@dataclass(slots=True)
class ScanCandidatesResult:
    candidates: list[CandidateItem] = field(default_factory=list)
    errors: list[ScanPathError] = field(default_factory=list)


@dataclass(slots=True)
class RecentFile:
    source_root: str
    source_path: str
    name: str
    extension: str
    file_size: int
    modified_at: float
    container_path: str | None = None


def recent_video_files(
    paths_config: PathsConfig,
    hours: float,
    errors: list[ScanPathError] | None = None,
) -> list[RecentFile]:
    """List video files in the download roots whose mtime falls within the last `hours` hours."""
    if hours <= 0:
        return []
    cutoff = time.time() - hours * 3600
    collected_errors = errors if errors is not None else []
    files: list[RecentFile] = []

    for download_root in paths_config.download_roots:
        root_path = Path(download_root)
        try:
            if not root_path.exists():
                continue
        except OSError as exc:
            _record_scan_error(collected_errors, root_path, exc)
            continue

        try:
            children = sorted(root_path.iterdir())
        except OSError as exc:
            _record_scan_error(collected_errors, root_path, exc)
            continue

        for child in children:
            if child.name.startswith('.'):
                continue
            if _should_skip_path(child):
                continue
            try:
                if child.is_file():
                    _collect_recent_file(child, None, cutoff, root_path, files)
                    continue

                if not child.is_dir():
                    continue

                for file_path in _iter_child_files(child, collected_errors):
                    if _should_skip_path(file_path):
                        continue
                    _collect_recent_file(file_path, child, cutoff, root_path, files)
            except OSError as exc:
                _record_scan_error(collected_errors, child, exc)

    files.sort(key=lambda f: f.modified_at, reverse=True)
    return files


def _collect_recent_file(
    file_path: Path,
    child: Path | None,
    cutoff: float,
    root_path: Path,
    files: list[RecentFile],
) -> None:
    if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
        return
    stat = file_path.stat()
    if stat.st_mtime < cutoff:
        return
    files.append(
        RecentFile(
            source_root=str(root_path),
            source_path=str(file_path),
            name=file_path.name,
            extension=file_path.suffix,
            file_size=stat.st_size,
            modified_at=stat.st_mtime,
            container_path=str(child) if child is not None else None,
        )
    )


def _to_absolute_path(docker_path: str) -> str:
    """Path is already absolute in container format, return as-is."""
    return docker_path


def _should_skip_path(path: Path) -> bool:
    return any(marker in part for part in path.parts for marker in SKIP_DIR_MARKERS)


def _is_in_progress_by_marker(path: Path) -> bool:
    """True when a sibling partial-file marker exists for this file.

    The marker file is case-insensitive (qBittorrent writes `.!qB`, so the
    sibling is e.g. `file.mkv.!qB`, but the marker format varies by client and
    the filesystem may or may not be case-sensitive). We scan the parent dir
    once and treat any sibling whose name ends with ``<candidate name><marker>``
    (suffix markers, e.g. ``.!qB``/``.part``) as an in-progress marker. We also
    check prefix markers (Tixati writes ``incomplete.file.mkv``).
    """
    name_lower = path.name.lower()
    try:
        with os.scandir(path.parent) as entries:
            for entry in entries:
                entry_name = entry.name.lower()
                for marker in PARTIAL_FILE_MARKERS:
                    if entry_name == name_lower + marker:
                        return True
                for prefix in PARTIAL_FILE_PREFIXES:
                    if entry_name == prefix + name_lower:
                        return True
    except OSError:
        return False
    return False


def _renamed_marker_suffix(name_lower: str) -> str | None:
    """Marker suffix when the file itself was renamed in-progress.

    Most clients rename (file.mkv -> file.mkv.!qB) instead of writing a
    sibling sidecar, so the renamed file is the only trace on disk. It ends
    in a non-video extension and would otherwise be silently skipped by the
    extension filter — invisible in the report. When stripping the marker
    leaves a video extension, the file is incomplete video data and must be
    reported as an in-progress candidate. Longer markers match first so
    `.parts` wins over `.part`-style prefixes. Sidecar control files
    (HIDDEN_SIDECAR_SUFFIXES, e.g. aria2's `.aria2`) are excluded — they are
    never video data and stay hidden.
    """
    for marker in sorted(PARTIAL_FILE_MARKERS, key=len, reverse=True):
        if marker in HIDDEN_SIDECAR_SUFFIXES:
            continue
        if name_lower.endswith(marker) and Path(name_lower[: -len(marker)]).suffix in VIDEO_EXTENSIONS:
            return marker
    return None


def _renamed_prefix(name_lower: str) -> str | None:
    """Prefix marker when the file itself was renamed in-progress
    (Tixati: file.mkv -> incomplete.file.mkv)."""
    for prefix in PARTIAL_FILE_PREFIXES:
        if name_lower.startswith(prefix) and Path(name_lower[len(prefix):]).suffix in VIDEO_EXTENSIONS:
            return prefix
    return None


def _is_hidden_sidecar(path: Path) -> bool:
    """True for control sidecars that must never become candidates
    (e.g. Show.mkv.aria2 — the preallocated Show.mkv next to it carries
    the in-progress flag via the sibling check instead)."""
    return path.name.lower().endswith(HIDDEN_SIDECAR_SUFFIXES)


def _candidate_in_progress(path: Path) -> bool:
    """True when the file itself is a renamed in-progress download
    (suffix or prefix marker with a video stem left after stripping)."""
    name_lower = path.name.lower()
    return _renamed_marker_suffix(name_lower) is not None or _renamed_prefix(name_lower) is not None


def _append_candidate(
    result: ScanCandidatesResult,
    file_path: Path,
    root_key: str,
    root_path: Path,
    container: Path | None,
    relative: str,
    in_progress: bool,
) -> None:
    result.candidates.append(
        CandidateItem(
            source_root_key=root_key,
            source_root=str(root_path),
            source_path=str(file_path),
            name=file_path.name,
            extension=file_path.suffix,
            container_path=str(container) if container is not None else None,
            relative_path=relative,
            file_size=file_path.stat().st_size,
            in_progress=in_progress,
        )
    )


def scan_candidates(paths_config: PathsConfig) -> ScanCandidatesResult:
    result = ScanCandidatesResult()
    for download_root in paths_config.download_roots:
        root_path = Path(download_root)
        try:
            if not root_path.exists():
                continue
        except OSError as exc:
            _record_scan_error(result.errors, root_path, exc)
            continue

        root_key = _infer_root_key(paths_config, download_root)
        try:
            children = sorted(root_path.iterdir())
        except OSError as exc:
            _record_scan_error(result.errors, root_path, exc)
            continue

        for child in children:
            if child.name.startswith('.'):
                continue
            if _should_skip_path(child):
                continue
            try:
                if child.is_file():
                    if _is_hidden_sidecar(child):
                        continue
                    if _candidate_in_progress(child):
                        # Renamed in-progress file (Show.mkv.!qB,
                        # incomplete.Show.mkv, Show.mkv.part, ...): the only
                        # trace on disk. Report it so the scan shows an
                        # "In-progress download" skip instead of hiding it.
                        _append_candidate(result, child, root_key, root_path, None, child.name, True)
                        continue
                    if child.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    result.candidates.append(
                        CandidateItem(
                            source_root_key=root_key,
                            source_root=str(root_path),
                            source_path=str(child),
                            name=child.name,
                            extension=child.suffix,
                            container_path=None,
                            relative_path=child.name,
                            file_size=child.stat().st_size,
                            in_progress=_is_in_progress_by_marker(child),
                        )
                    )
                    continue

                if not child.is_dir():
                    continue

                for file_path in _iter_child_files(child, result.errors):
                    if _should_skip_path(file_path):
                        continue
                    try:
                        if _is_hidden_sidecar(file_path):
                            continue
                        if _candidate_in_progress(file_path):
                            _append_candidate(
                                result,
                                file_path,
                                root_key,
                                root_path,
                                child,
                                str(file_path.relative_to(child)),
                                True,
                            )
                            continue
                        if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                            continue
                        result.candidates.append(
                            CandidateItem(
                                source_root_key=root_key,
                                source_root=str(root_path),
                                source_path=str(file_path),
                                name=file_path.name,
                                extension=file_path.suffix,
                                container_path=str(child),
                                relative_path=str(file_path.relative_to(child)),
                                file_size=file_path.stat().st_size,
                                in_progress=_is_in_progress_by_marker(file_path),
                            )
                        )
                    except OSError as exc:
                        _record_scan_error(result.errors, file_path, exc)
            except OSError as exc:
                _record_scan_error(result.errors, child, exc)
    return result


def _iter_child_files(child: Path, errors: list[ScanPathError]):
    def on_error(exc: OSError) -> None:
        error_path = Path(exc.filename) if exc.filename else child
        _record_scan_error(errors, error_path, exc)

    for dirpath, dirnames, filenames in os.walk(child, onerror=on_error):
        dirpath_path = Path(dirpath)
        dirnames[:] = [
            dirname
            for dirname in sorted(dirnames)
            if not dirname.startswith(".") and not _should_skip_path(dirpath_path / dirname)
        ]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            yield dirpath_path / filename


def _record_scan_error(errors: list[ScanPathError], path: Path, exc: OSError) -> None:
    error_path = str(path)
    error_message = str(exc)
    errors.append(ScanPathError(path=error_path, error=error_message))


def list_target_paths(root_path: str) -> list[str]:
    path = Path(root_path)
    if not path.exists():
        return []
    return [str(item) for item in sorted(path.iterdir()) if not item.name.startswith('.')]


def _infer_root_key(paths_config: PathsConfig, download_root: str) -> str:
    normalized_download = str(Path(download_root).resolve())
    
    for i, root in enumerate(paths_config.download_roots):
        if normalized_download == str(Path(root).resolve()):
            return f"movie_{i}"
    
    return "default"
