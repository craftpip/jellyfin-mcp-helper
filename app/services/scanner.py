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
# All are matched case-insensitively.
#   qBittorrent   -> .!qB   (file.mkv -> file.mkv.!qB)
#   Transmission  -> .part
#   rTorrent      -> .part  (split_suffix, default .part), plus .partial for split parts
#   Vuze/Azureus  -> .part
#   uTorrent      -> .!ut
#   BitTorrent    -> .!bt   (Windows mainline client)
#   Deluge        -> no main-filename marker (keeps libtorrent .parts files
#                    only), so it cannot be detected via a sibling suffix.
PARTIAL_FILE_MARKERS = (".!qb", ".!ut", ".!bt", ".part", ".partial", ".parts")

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


def _is_partial_marker_file(path: Path) -> bool:
    """True when this candidate's own name is a partial-file marker,
    so it should never be treated as a real candidate.

    Suffix markers (`.!qB`, `.part`, ...) already end in non-video extensions
    and are filtered by the extension check, but Tixati's prefix markers
    (`incomplete.Show.S01E01.mkv`) still look like a normal video file, so we
    must skip them explicitly.
    """
    name_lower = path.name.lower()
    for marker in PARTIAL_FILE_MARKERS:
        if name_lower.endswith(marker):
            return True
    for prefix in PARTIAL_FILE_PREFIXES:
        if name_lower.startswith(prefix):
            return True
    return False


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
                    if child.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    if _is_partial_marker_file(child):
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
                        if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                            continue
                        if _is_partial_marker_file(file_path):
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
