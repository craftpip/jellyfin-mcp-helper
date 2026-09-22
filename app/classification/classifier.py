"""Main classification entry point (orchestrator)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from guessit import guessit

from app.classification.episodes import (
    _extract_bare_episode_from_name,
    _extract_contained_bare_episode,
    _extract_season_episode,
    _extract_season_from_folder,
    _sanitize_episode,
    _sanitize_season,
)
from app.classification.kinds import (
    _extra_type,
    _infer_kind,
    _looks_like_extra,
    _looks_like_sample,
)
from app.classification.patterns import (
    EXTRA_MARKERS,
    FOREIGN_EPISODE_RE,
    FRANCHISE_MOVIE_MARKER_RE,
    MOVIE_MARKER_RE,
)
from app.classification.titles import (
    _apply_title_alias,
    _extract_container_series_for_bare_episode,
    _extract_episode_title,
    _extract_series_alias,
    _extract_series_from_source,
    _extract_title,
    _get_folder_title,
    _is_fuller_title,
    _is_generic_extra_title,
    _is_generic_folder_title,
    _normalize_title_key,
    _should_use_folder_title,
    _split_foreign_episode_title,
    _container_is_movie_folder,
    _has_container_episode_context,
)
from app.models.schemas import CandidateItem, ClassificationResult


def classify_candidate(candidate: CandidateItem, series_title_aliases: dict[str, str] | None = None) -> ClassificationResult:
    label = _candidate_label(candidate)
    parsed = _parse_guessit(label)

    title = _extract_title(parsed, candidate)
    title, foreign_episode, foreign_episode_title = _split_foreign_episode_title(title)
    episode_title = _extract_episode_title(parsed, candidate)
    title, episode_title = _apply_title_alias(title, episode_title, series_title_aliases or {})
    if foreign_episode_title and (not episode_title or FOREIGN_EPISODE_RE.search(episode_title)):
        episode_title = foreign_episode_title
    series_alias = _extract_series_alias(parsed, title)
    year = _extract_int(parsed.get("year"))
    # Year-first filtering: strip the year before trusting any season/episode
    # number. Guessit reads "(2021)" in "Show - 01 (2021)" as season 2021,
    # which previously flowed straight into Season 2021 / S2021E01 targets.
    season = _sanitize_season(_extract_int(parsed.get("season")), year)
    episode = _sanitize_episode(_extract_int(parsed.get("episode")), year)
    fallback_season, fallback_episode = _extract_season_episode(label)
    fallback_season = _sanitize_season(fallback_season, year)
    fallback_episode = _sanitize_episode(fallback_episode, year)
    has_explicit_episode = fallback_episode is not None
    # Prefer explicit SxxEyy found by regex over guessit's title-embedded
    # mis-parse (e.g. SAC_2045 → S20E45/2045 vs real S01E10.NET mis-identified as website)
    if fallback_season is not None:
        season = fallback_season
    if fallback_episode is not None:
        episode = fallback_episode
        has_explicit_episode = True
    season_from_folder = False
    if season is None:
        season = _sanitize_season(_extract_season_from_folder(candidate), year)
        season_from_folder = season is not None
    if episode is None and season_from_folder:
        episode = _sanitize_episode(_extract_bare_episode_from_name(candidate.name), year)
        has_explicit_episode = episode is not None
    if episode is None and _has_container_episode_context(candidate) and not _container_is_movie_folder(candidate):
        episode = _sanitize_episode(_extract_contained_bare_episode(candidate.name), year)
        has_explicit_episode = episode is not None
    if episode is None and foreign_episode is not None:
        episode = _sanitize_episode(foreign_episode, year)
        has_explicit_episode = episode is not None
    # Final guard: no unsanitized number may reach kind inference / resolver.
    season = _sanitize_season(season, year)
    episode = _sanitize_episode(episode, year)

    kind, confidence, reason = _infer_kind(label, parsed, season, episode, has_explicit_episode)
    if (
        not has_explicit_episode
        and kind in ("series", "movie")
        and _candidate_has_movie_marker(candidate)
    ):
        movie_marker_title = _extract_movie_marker_title(candidate, title)
        if movie_marker_title:
            title = movie_marker_title
            season = None
            episode = None
            kind = "movie"
            confidence = max(confidence, 0.85)
            reason = "Detected franchise movie marker"
    # Precompute folder title for hierarchy and false-positive guard (Level 1 vs Level 2)
    folder_title = _get_folder_title(candidate)
    extra_type = _extra_type(label, parsed) if _looks_like_extra(label, parsed) else None
    # Guard: show titles that contain a short extra marker as part of the title must not be mis-flagged when they are proper SxxEyy episodes
    if extra_type and has_explicit_episode and folder_title and not _is_generic_folder_title(folder_title):
        folder_words = set(_normalize_title_key(folder_title).split())
        m = EXTRA_MARKERS.search(label)
        if m and m.group(0).lower() in folder_words:
            # marker is part of show name — only keep as extra if there's an independent extra context (NC folder, extras/ path, or standalone OP/ED suffix)
            has_extra_folder = bool(re.search(r"(^|/)(NC|extras?|special|ova|ona)($|/|\\)", label, re.IGNORECASE))
            # Extra in a dedicated extra subfolder keeps the extra flag; otherwise clear for proper episodes.
            if not has_extra_folder:
                # also check if the file's trailing part after SxxEyy contains OP/ED as standalone suffix (e.g., "Show - S01E01 - OP")
                # For genuine episode without such suffix, clear extra_type
                if not re.search(r"S\d{1,2}E\d{1,3}.*\b(OP|ED|NCOP|NCED)\b", label, re.IGNORECASE):
                    extra_type = None
    if extra_type and kind in ("series", "movie"):
        kind = "extra"
        confidence = max(confidence, 0.85)
        reason = f"Detected {extra_type} extra/specials marker"

    # --- Level hierarchy: Level 1 (main folder = show identity) vs Level 2 (inner file/folder = season/episode/extra) ---
    # For series/extra the folder is authoritative. The file stem (ED/OP/NC) must not be used to look up the show.
    # For movie collections the folder is the collection name, so each inner file's title+year is authoritative.
    # folder_title already computed above
    if folder_title and kind in ("series", "extra"):
        if not _is_generic_folder_title(folder_title) and _should_use_folder_title(folder_title, title):
            if _is_generic_extra_title(title) or _is_fuller_title(folder_title, title):
                title = folder_title
                # keep year from folder if file had no year and folder does (e.g. "Show (2020)")
                if year is None:
                    m = re.search(r"\((19\d{2}|20\d{2})\)", folder_title)
                    if m:
                        try:
                            year = int(m.group(1))
                        except ValueError:
                            pass
    # movie collections: keep file title, do not override with collection folder
    # (no action for kind=="movie" — file-derived title stays)

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
        series_alias=series_alias,
        year=year,
        season=season,
        episode=episode,
        confidence=confidence,
        reason=reason,
        extra_type=extra_type,
    )


def _candidate_label(candidate: CandidateItem) -> str:
    if candidate.relative_path:
        return candidate.relative_path
    return candidate.name


def _has_movie_marker(value: str) -> bool:
    return bool(MOVIE_MARKER_RE.search(value) or FRANCHISE_MOVIE_MARKER_RE.search(value))


def _candidate_has_movie_marker(candidate: CandidateItem) -> bool:
    if _has_movie_marker(_candidate_label(candidate)):
        return True
    if candidate.container_path and _has_movie_marker(Path(candidate.container_path).name):
        return True
    return False


def _extract_movie_marker_number_text(value: str) -> str | None:
    match = MOVIE_MARKER_RE.search(value)
    if match:
        digits = re.search(r"\d{1,3}", match.group(0))
        return digits.group(0) if digits else None
    match = FRANCHISE_MOVIE_MARKER_RE.search(value)
    if match:
        digits = re.search(r"m\d{1,2}", match.group(0), re.IGNORECASE)
        return digits.group(0)[1:] if digits else None
    return None


def _extract_movie_marker_title(candidate: CandidateItem, title: str | None) -> str | None:
    container = candidate.container_path
    if container:
        container_name = Path(container).name
        if container_name and container_name != Path(candidate.source_root).name and _has_movie_marker(container_name):
            return _clean_source_folder_name(container_name) or title
    if not title:
        return None
    if re.search(r"\d", title):
        return title
    number = _extract_movie_marker_number_text(_candidate_label(candidate))
    if number is not None:
        return f"{title} {number}".strip()
    return title


def _clean_source_folder_name(raw_name: str) -> str | None:
    from app.classification.titles import _clean_source_folder_name as _clean

    return _clean(raw_name)


def _parse_guessit(label: str) -> dict[str, Any]:
    return guessit(label, {"single_value": True})


def _extract_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list) and value:
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
