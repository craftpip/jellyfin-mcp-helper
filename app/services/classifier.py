from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from guessit import guessit

from app.models.schemas import CandidateItem, ClassificationResult


EXTRA_MARKERS = re.compile(r"\b(ncop|nced|op|ed|ova|ona|special|extras?)\b", re.IGNORECASE)
SAMPLE_MARKERS = re.compile(r"\bsample\b", re.IGNORECASE)
SAMPLE_SIZE_THRESHOLD = 150 * 1024 * 1024  # 150MB
SEASON_EPISODE_RE = re.compile(r"s\d{1,2}e\d{1,2}", re.IGNORECASE)
SEASON_ONLY_RE = re.compile(r"season\s*\d{1,2}|s\d{1,2}\b", re.IGNORECASE)


def classify_candidate(candidate: CandidateItem) -> ClassificationResult:
    label = _candidate_label(candidate)
    parsed = _parse_guessit(label)

    title = _extract_title(parsed, candidate)
    year = _extract_int(parsed.get("year"))
    season = _extract_int(parsed.get("season"))
    episode = _extract_int(parsed.get("episode"))

    kind, confidence, reason = _infer_kind(label, parsed, season, episode)
    if _looks_like_extra(label, parsed) and kind == "series":
        kind = "skip"
        confidence = max(confidence, 0.75)
        reason = "Detected extras/specials marker"

    if kind == "movie" and _looks_like_sample(label, parsed, candidate.file_size):
        kind = "skip"
        confidence = max(confidence, 0.75)
        reason = "Detected sample file"

    if kind == "movie":
        season = None
        episode = None

    return ClassificationResult(
        type=kind,
        title=title,
        year=year,
        season=season,
        episode=episode,
        confidence=confidence,
        reason=reason,
    )


def _candidate_label(candidate: CandidateItem) -> str:
    if candidate.container_path and candidate.relative_path:
        return f"{candidate.container_path}/{candidate.relative_path}"
    return candidate.name


def _parse_guessit(label: str) -> dict[str, Any]:
    return guessit(label, {"single_value": True})


def _extract_title(parsed: dict[str, Any], candidate: CandidateItem) -> str | None:
    title = parsed.get("title") or parsed.get("series") or parsed.get("movie")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if candidate.container_path:
        folder_name = Path(candidate.container_path).name
        if folder_name:
            return folder_name.strip()
    stem = Path(candidate.name).stem
    return stem.strip() if stem else None


def _extract_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list) and value:
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _infer_kind(label: str, parsed: dict[str, Any], season: int | None, episode: int | None) -> tuple[str, float, str]:
    guessed_type = parsed.get("type")
    if guessed_type == "episode" or season is not None or episode is not None:
        return "series", 0.9, "Matched episode/season pattern"
    if guessed_type == "movie":
        return "movie", 0.9, "Matched movie pattern"
    if parsed.get("year") and not SEASON_EPISODE_RE.search(label):
        return "movie", 0.75, "Matched year without season/episode"
    if SEASON_EPISODE_RE.search(label) or SEASON_ONLY_RE.search(label):
        return "series", 0.7, "Matched season/episode keyword"
    return "movie", 0.6, "Defaulted to movie"


def _looks_like_extra(label: str, parsed: dict[str, Any]) -> bool:
    if EXTRA_MARKERS.search(label):
        return True
    episode_title = parsed.get("episode_title")
    if isinstance(episode_title, str) and EXTRA_MARKERS.search(episode_title):
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
