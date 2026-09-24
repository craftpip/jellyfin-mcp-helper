"""Kind inference: series / movie / extra / skip."""
from __future__ import annotations

import re
from typing import Any

from app.classification.patterns import (
    DECIMAL_EPISODE_RE,
    EXTRA_MARKERS,
    MARKER_LOOKAHEAD,
    MARKER_LOOKBEHIND,
    SAMPLE_MARKERS,
    SEASON_EPISODE_RE,
    SPECIAL_TAG_RE,
)
from app.core.constants import SAMPLE_SIZE_THRESHOLD


def _infer_kind(
    label: str,
    parsed: dict[str, Any],
    season: int | None,
    episode: int | None,
    has_explicit_episode: bool,
) -> tuple[str, float, str]:
    guessed_type = parsed.get("type")
    if has_explicit_episode:
        return "series", 0.9, "Matched episode/season pattern"
    if guessed_type == "episode" and episode is not None:
        return "series", 0.9, "Matched episode pattern"
    if season is not None:
        return "series", 0.8, "Matched season pattern"
    if guessed_type == "movie":
        return "movie", 0.9, "Matched movie pattern"
    if parsed.get("year") and not SEASON_EPISODE_RE.search(label):
        return "movie", 0.75, "Matched year without season/episode"
    return "movie", 0.65, "Defaulted standalone file to movie"


def _looks_like_extra(label: str, parsed: dict[str, Any]) -> bool:
    if EXTRA_MARKERS.search(label):
        return True
    if SPECIAL_TAG_RE.search(label):
        return True
    if DECIMAL_EPISODE_RE.search(label):
        return True
    episode_title = parsed.get("episode_title")
    if isinstance(episode_title, str) and EXTRA_MARKERS.search(episode_title):
        return True
    return False


def _extra_type(label: str, parsed: dict[str, Any]) -> str | None:
    # Determine the specific extra type for routing to extras/ folder
    text = label.lower()
    episode_title = parsed.get("episode_title")
    if isinstance(episode_title, str):
        text += " " + episode_title.lower()
    # Check for specific markers in order of specificity (underscore-tolerant
    # boundaries — see MARKER_LOOKBEHIND in patterns.py).
    _LB = MARKER_LOOKBEHIND
    _LA = MARKER_LOOKAHEAD
    if re.search(_LB + r"sample" + _LA, text):
        return "sample"
    if re.search(_LB + r"trailer" + _LA, text):
        return "trailer"
    if re.search(_LB + r"behindthescenes" + _LA, text) or re.search(r"behind.*scene", text):
        return "behind"
    if re.search(_LB + r"deleted", text):
        return "deleted"
    if re.search(_LB + r"interview" + _LA, text):
        return "interview"
    if re.search(_LB + r"featurette" + _LA, text):
        return "featurette"
    if re.search(_LB + r"short" + _LA, text):
        return "short"
    if re.search(_LB + r"sp\d*" + _LA, text) or re.search(_LB + r"special" + _LA, text):
        return "special"
    if re.search(_LB + r"extra" + _LA, text):
        return "extra"
    # Fallback for any extra marker
    if EXTRA_MARKERS.search(label) or SPECIAL_TAG_RE.search(label) or DECIMAL_EPISODE_RE.search(label):
        return "special"
    return None


def _sample_marker_hit(label: str, parsed: dict[str, Any]) -> bool:
    """True when a `sample` word marker names the file (not a size guess).

    Marker-only split of `_looks_like_sample`: the size heuristic below stays
    in `_looks_like_sample` for the size-only suspect path in the classifier.
    """
    if SAMPLE_MARKERS.search(label):
        return True
    title = parsed.get("title") or parsed.get("movie")
    if isinstance(title, str) and SAMPLE_MARKERS.search(title):
        return True
    other = parsed.get("other")
    if isinstance(other, str) and SAMPLE_MARKERS.search(other):
        return True
    return False


def _looks_like_sample(label: str, parsed: dict[str, Any], file_size: int | None = None) -> bool:
    if SAMPLE_MARKERS.search(label):
        return True
    title = parsed.get("title") or parsed.get("movie")
    if isinstance(title, str) and SAMPLE_MARKERS.search(title):
        return True
    other = parsed.get("other")
    if isinstance(other, str) and SAMPLE_MARKERS.search(other):
        return True
    if file_size is not None and file_size < SAMPLE_SIZE_THRESHOLD:
        return True
    return False
