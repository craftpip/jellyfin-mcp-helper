from __future__ import annotations

from pathlib import Path

from app.core.config import PathsConfig
from app.models.schemas import CandidateItem


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"}
SKIP_DIR_MARKERS = {".trickplay"}
SAMPLE_SIZE_THRESHOLD = 150 * 1024 * 1024  # 150MB


def _to_absolute_path(docker_path: str) -> str:
    """Path is already absolute in container format, return as-is."""
    return docker_path


def _should_skip_path(path: Path) -> bool:
    return any(marker in part for part in path.parts for marker in SKIP_DIR_MARKERS)
def scan_candidates(paths_config: PathsConfig) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    for download_root in paths_config.download_roots:
        root_path = Path(download_root)
        if not root_path.exists():
            continue

        root_key = _infer_root_key(paths_config, download_root)
        for child in sorted(root_path.iterdir()):
            if child.name.startswith('.'):
                continue
            if _should_skip_path(child):
                continue
            if child.is_file():
                if child.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                candidates.append(
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

            for file_path in sorted(child.rglob("*")):
                if _should_skip_path(file_path):
                    continue
                if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                candidates.append(
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
    return candidates


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
