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
SEASON_EPISODE_TOKEN_RE = re.compile(
    r"(?:^|[^a-z0-9])s(?P<season>\d{1,2})e(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
SEASON_DASH_EPISODE_RE = re.compile(
    r"(?:^|[^a-z0-9])s(?P<season>\d{1,2})\s*-\s*(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
SEASON_WORD_DASH_EPISODE_RE = re.compile(
    r"(?:^|[^a-z0-9])season\s*(?P<season>\d{1,2})\s*-\s*(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
SEASON_FOLDER_RE = re.compile(r"(?:^|[^a-z0-9])(?:season\s*|s)(?P<season>\d{1,2})(?:[^a-z0-9]|$)", re.IGNORECASE)
BARE_EPISODE_RE = re.compile(r"(?:^|[^a-z0-9])(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)", re.IGNORECASE)


def classify_candidate(candidate: CandidateItem) -> ClassificationResult:
    label = _candidate_label(candidate)
    parsed = _parse_guessit(label)

    title = _extract_title(parsed, candidate)
    episode_title = _extract_episode_title(parsed, candidate)
    year = _extract_int(parsed.get("year"))
    season = _extract_int(parsed.get("season"))
    episode = _extract_int(parsed.get("episode"))
    fallback_season, fallback_episode = _extract_season_episode(label)
    has_explicit_episode = fallback_episode is not None
    if season is None:
        season = fallback_season
    if episode is None:
        episode = fallback_episode
    season_from_folder = False
    if season is None:
        season = _extract_season_from_folder(candidate)
        season_from_folder = season is not None
    if episode is None and season_from_folder:
        episode = _extract_bare_episode_from_name(candidate.name)
        has_explicit_episode = episode is not None

    kind, confidence, reason = _infer_kind(label, parsed, season, episode, has_explicit_episode)
    if _looks_like_extra(label, parsed) and kind in ("series", "movie"):
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
        episode_title=episode_title,
        year=year,
        season=season,
        episode=episode,
        confidence=confidence,
        reason=reason,
    )


def _candidate_label(candidate: CandidateItem) -> str:
    if candidate.relative_path:
        return candidate.relative_path
    return candidate.name


def _parse_guessit(label: str) -> dict[str, Any]:
    return guessit(label, {"single_value": True})


def _extract_title(parsed: dict[str, Any], candidate: CandidateItem) -> str | None:
    series = parsed.get("series")
    if isinstance(series, str) and series.strip():
        return series.strip()
    title = parsed.get("title") or parsed.get("movie")
    if isinstance(title, str) and title.strip():
        if parsed.get("type") == "episode" or (parsed.get("season") is not None and parsed.get("episode") is not None):
            path_series = _extract_series_from_source(candidate)
            if path_series:
                return path_series
        return title.strip()
    if candidate.container_path:
        folder_name = Path(candidate.container_path).name
        if folder_name:
            return folder_name.strip()
    stem = Path(candidate.name).stem
    return stem.strip() if stem else None


_SEASON_MARKER_RE = re.compile(r"\s+S\d{1,2}(?:\+?P\d{1,2})?(?:\+SP)?(?:\s|$)", re.IGNORECASE)
_TECH_TAG_RE = re.compile(
    r"\s+(?:\d{3,4}p|(?:Dual\s+)?Audio|BDRip|BluRay|WEB[.-]?DL|WebRip|HDRip|x264|x265|HEVC|10\s*bit)",
    re.IGNORECASE,
)
_TRAILING_GROUP_RE = re.compile(r"\s*[-–]\s*[A-Za-z0-9]+$")
_TRAILING_BRACKET_RE = re.compile(r"\s*\[.*?\]\s*$")


_CRC_BRACKETS_RE = re.compile(r"\s*\[[A-Fa-f0-9]{6,10}\]\s*$")
_CRC_PAREN_RE = re.compile(r"\s*\([A-Fa-f0-9]{6,10}\)\s*$")
_FILENAME_EP_TITLE_RE = re.compile(r"S\d{1,2}E\d{1,3}[-. ]+(.+)", re.IGNORECASE)


def _extract_episode_title(parsed: dict[str, Any], candidate: CandidateItem) -> str | None:
    ep_title = parsed.get("episode_title")
    if isinstance(ep_title, str) and ep_title.strip():
        return ep_title.strip()
    name = candidate.name
    stem = Path(name).stem
    cleaned = _CRC_BRACKETS_RE.sub("", stem)
    cleaned = _CRC_PAREN_RE.sub("", cleaned)
    m = _FILENAME_EP_TITLE_RE.match(cleaned)
    if m:
        return m.group(1).strip()
    guessit_title = parsed.get("title")
    if isinstance(guessit_title, str) and guessit_title.strip():
        if not parsed.get("series"):
            return guessit_title.strip()
    return None


def _extract_series_from_source(candidate: CandidateItem) -> str | None:
    path_str = candidate.container_path
    if not path_str:
        parent = Path(candidate.source_path).parent
        if str(parent) != candidate.source_root:
            path_str = str(parent)
    if not path_str:
        return None
    raw_name = Path(path_str).name
    cleaned = _TRAILING_BRACKET_RE.sub("", raw_name)
    cleaned = _TRAILING_GROUP_RE.sub("", cleaned)
    parts = _SEASON_MARKER_RE.split(cleaned, maxsplit=1)
    if len(parts) > 1:
        result = parts[0].strip()
        if result:
            return result
    parts = _TECH_TAG_RE.split(cleaned, maxsplit=1)
    if len(parts) > 1:
        result = parts[0].strip()
        if result:
            return result
    return None


def _extract_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list) and value:
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_season_episode(label: str) -> tuple[int | None, int | None]:
    season: int | None = None
    episode: int | None = None

    for match in SEASON_EPISODE_TOKEN_RE.finditer(label):
        season = int(match.group("season"))
        episode = int(match.group("episode"))

    if season is None or episode is None:
        for match in SEASON_DASH_EPISODE_RE.finditer(label):
            season = int(match.group("season"))
            episode = int(match.group("episode"))

    if season is None or episode is None:
        for match in SEASON_WORD_DASH_EPISODE_RE.finditer(label):
            season = int(match.group("season"))
            episode = int(match.group("episode"))

    return season, episode


def _extract_bare_episode_from_name(name: str) -> int | None:
    stem = Path(name).stem
    for match in BARE_EPISODE_RE.finditer(stem):
        return int(match.group("episode"))
    return None


def _extract_season_from_folder(candidate: CandidateItem) -> int | None:
    if candidate.relative_path:
        parts = candidate.relative_path.split("/")
        if len(parts) > 1:
            for part in parts[:-1]:
                match = SEASON_FOLDER_RE.search(part)
                if match:
                    return int(match.group("season"))
    source = Path(candidate.source_path)
    if source.parent and source.parent.name:
        match = SEASON_FOLDER_RE.search(source.parent.name)
        if match:
            return int(match.group("season"))
    return None


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
    if guessed_type == "movie":
        return "movie", 0.9, "Matched movie pattern"
    if parsed.get("year") and not SEASON_EPISODE_RE.search(label):
        return "movie", 0.75, "Matched year without season/episode"
    return "movie", 0.65, "Defaulted standalone file to movie"


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
