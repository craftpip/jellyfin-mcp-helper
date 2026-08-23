"""Path validation helpers — extracted from ScanManager for testability.

Single responsibility: decide if a proposed target path is allowed.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.core.constants import VIDEO_EXTENSIONS


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_target_path(target: str, allowed_roots: list[Path]) -> Path:
    """Validate that target is absolute, has a video extension, and lives under an allowed root.

    Returns the resolved Path on success, raises HTTPException(400) on failure.
    """
    target_path = Path(target)
    if not target_path.is_absolute():
        raise HTTPException(status_code=400, detail=f"Target path '{target}' must be absolute")
    resolved = target_path.resolve(strict=False)
    if not any(is_within_root(resolved, root) for root in allowed_roots):
        raise HTTPException(
            status_code=400,
            detail=f"Target path '{target}' is not under any configured movie or series root",
        )
    if resolved.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Target path '{target}' does not have a valid video extension",
        )
    return resolved


def validate_directory(directory: str, allowed_roots: list[Path]) -> Path:
    """Validate that a directory (for retarget) is absolute and under an allowed root."""
    dir_path = Path(directory)
    if not dir_path.is_absolute():
        raise HTTPException(status_code=400, detail="directory must be an absolute path")
    resolved = dir_path.resolve(strict=False)
    if not any(is_within_root(resolved, root) for root in allowed_roots):
        raise HTTPException(status_code=400, detail=f"Directory '{directory}' is not under any configured movie or series root")
    return resolved
