"""Central media constants — single source of truth for video extensions and browse caps.

Import from here instead of re-defining in scanner / resolver / server / scan_manager.
"""
from __future__ import annotations

VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"})
VIDEO_EXTENSIONS_TUPLE: tuple[str, ...] = (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv")

# Browse UI caps — keep cheap listings (resolver hang post-mortem: never rglob full tree)
BROWSE_VIDEO_EXTENSIONS: tuple[str, ...] = VIDEO_EXTENSIONS_TUPLE
BROWSE_IGNORED_DIR_NAMES: frozenset[str] = frozenset({".trickplay", ".thumbs", ".thumbnails", ".stfolder", "extrafanart", "extrathumbs"})
BROWSE_VIDEO_COUNT_CAP: int = 500
BROWSE_SEARCH_RESULT_CAP: int = 50
BROWSE_SEARCH_CHILD_CAP: int = 600
BROWSE_IGNORED_NAME_PARTS: tuple[str, ...] = (
    "trickplay",
    "extras",
    "featurettes",
    "behind the scenes",
    "deleted scenes",
    "deleted scene",
    "sample",
    "bonus",
    "trailers",
    "thumbs",
    "scraped",
    "chapter",
)

# Classifier / scanner thresholds
SAMPLE_SIZE_THRESHOLD: int = 150 * 1024 * 1024  # 150MB
