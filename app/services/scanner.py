from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import PathsConfig
from app.models.schemas import CandidateItem


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"}
SKIP_DIR_MARKERS = {".trickplay"}
SAMPLE_SIZE_THRESHOLD = 150 * 1024 * 1024  # 150MB


@dataclass(slots=True)
class ScanPathError:
    path: str
    error: str


@dataclass(slots=True)
class ScanCandidatesResult:
    candidates: list[CandidateItem] = field(default_factory=list)
    errors: list[ScanPathError] = field(default_factory=list)


def _to_absolute_path(docker_path: str) -> str:
    """Path is already absolute in container format, return as-is."""
    return docker_path


def _should_skip_path(path: Path) -> bool:
    return any(marker in part for part in path.parts for marker in SKIP_DIR_MARKERS)


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
