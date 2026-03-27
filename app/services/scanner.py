from __future__ import annotations

from pathlib import Path

from app.core.config import PathsConfig
from app.models.schemas import CandidateItem


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"}
SKIP_DIR_MARKERS = {".trickplay"}


def _should_skip_path(path: Path) -> bool:
    return any(marker in part for part in path.parts for marker in SKIP_DIR_MARKERS)
def scan_candidates(paths_config: PathsConfig) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    for torrent_root in paths_config.torrent_roots:
        root_path = Path(torrent_root)
        if not root_path.exists():
            continue

        root_key = _infer_root_key(paths_config, torrent_root)
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
                    )
                )
    return candidates


def list_target_paths(root_path: str) -> list[str]:
    path = Path(root_path)
    if not path.exists():
        return []
    return [str(item) for item in sorted(path.iterdir()) if not item.name.startswith('.')]


def _infer_root_key(paths_config: PathsConfig, torrent_root: str) -> str:
    for key in paths_config.movie_roots:
        if key in torrent_root:
            return key
    return Path(torrent_root).parts[2] if len(Path(torrent_root).parts) > 2 else "default"
