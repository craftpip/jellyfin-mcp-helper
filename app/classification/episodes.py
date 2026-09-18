"""Season/episode number extraction.

JellyJake-ported robustness layered on top of the existing SxxEyy parsing:
x-notation, word-form S+E, E-only with same-label season anchor, finale and
Part-episode conventions, plus sane caps that reject years/resolutions and
codec tails. Single-file semantics: returns one (season, episode) pair —
no episodeEnd/seasonRange outputs, so JellySort kinds are unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.classification.patterns import (
    BARE_EPISODE_RE,
    CODEC_EPISODES,
    CONTAINED_BARE_EPISODE_RE,
    END_EPISODE_S_RE,
    END_EPISODE_WORD_RE,
    EP_ONLY_S_RE,
    EP_ONLY_WORD_RE,
    EPISODE_MAX,
    PART_EP_RE,
    SEASON_DASH_EPISODE_RE,
    SEASON_EPISODE_TOKEN_RE,
    SEASON_FOLDER_RE,
    SEASON_MAX,
    SEASON_WORD_DASH_EPISODE_RE,
    SEASON_WORD_EPISODE_RE,
    X_NOTATION_RE,
    YEAR_OR_RES_RE,
)


def _sane_season(value: int | None) -> int | None:
    if value is None:
        return None
    if 1 <= value <= SEASON_MAX:
        return value
    return None


def _sane_episode(value: int | None) -> int | None:
    if value is None:
        return None
    if 1 <= value <= EPISODE_MAX:
        return value
    return None


def _match_season_episode_token_re(label: str) -> tuple[int | None, int | None]:
    season: int | None = None
    episode: int | None = None
    for match in SEASON_EPISODE_TOKEN_RE.finditer(label):
        season = int(match.group("season"))
        episode = int(match.group("episode"))
    return _sane_season(season), _sane_episode(episode)


def _match_dash_form(pattern: re.Pattern[str], label: str) -> tuple[int | None, int | None]:
    """Dash forms (S02-12, Season 02-12) with year/resolution rejection.

    JellyJake trap: "S02 - 2019" / "Season 2 - 1080p" must NOT become an
    episode — 4-digit years and resolutions are never episode numbers.
    """
    season: int | None = None
    episode: int | None = None
    for match in pattern.finditer(label):
        ep_text = match.group("episode")
        # Reject when the "episode" slot is actually a year/resolution glued
        # after the dash (e.g. episode text "201" of "2019" + trailing "9").
        tail = label[match.end("episode"):match.end("episode") + 1]
        if len(ep_text) >= 3 and tail.isdigit():
            continue
        if len(ep_text) == 4:
            continue
        after = label[match.end():match.end() + 8]
        # Resolution glued right after ("- 720p") — not an episode.
        if re.match(r"\s*(?:480|576|720|1080|2160)p?\b", after, re.IGNORECASE):
            # Only reject when the episode itself looks like a resolution lead.
            if ep_text in ("480", "576", "720", "1080", "2160"):
                continue
        season = int(match.group("season"))
        episode = int(ep_text)
    return _sane_season(season), _sane_episode(episode)


def _match_word_episode(label: str) -> tuple[int | None, int | None]:
    """Word form without dash: "Season 1 Episode 5", "Season 2 Ep 03"."""
    season: int | None = None
    episode: int | None = None
    for match in SEASON_WORD_EPISODE_RE.finditer(label):
        season = int(match.group("season"))
        episode = int(match.group("episode"))
    return _sane_season(season), _sane_episode(episode)


def _match_x_notation(label: str) -> tuple[int | None, int | None]:
    """x-notation "1x05" with codec/dimension guards (JellyJake).

    Guards: season 1..60 (kills 1920x1080), episode never 264/265
    (codec tails like "1 x264"), no digit/dot directly before.
    """
    for match in X_NOTATION_RE.finditer(label):
        season = int(match.group("season"))
        episode = int(match.group("episode"))
        if not 1 <= season <= SEASON_MAX:
            continue
        if episode in CODEC_EPISODES:
            continue
        if not 1 <= episode <= EPISODE_MAX:
            continue
        # Dimension tail: "1920x1080" already excluded by season cap, but
        # also reject when the full token either side is 3-4 digits.
        start, end = match.span()
        before = label[max(0, start - 5):start]
        if re.search(r"\d{3,4}\s*$", before):
            continue
        return season, episode
    return None, None


def _match_end_episode(label: str) -> tuple[int | None, int | None]:
    """Anime finale "S2 - 12 END" / "Season 2 - 12 END" is S02E12."""
    for pattern in (END_EPISODE_WORD_RE, END_EPISODE_S_RE):
        match = pattern.search(label)
        if match:
            return (
                _sane_season(int(match.group("season"))),
                _sane_episode(int(match.group("episode"))),
            )
    return None, None


def _bare_season_anchor(label: str) -> int | None:
    """Standalone season anchor in the same label ("S04 ... e07").

    Only real anchors count (word-boundary S0N or "Season N") — never a
    glued token. Mirrors JellyJake bareSeasonAnchor.
    """
    word = re.search(r"\bseason\s*0*(\d{1,2})\b", label, re.IGNORECASE)
    if word and _sane_season(int(word.group(1))) is not None:
        return int(word.group(1))
    s_forms = list(re.finditer(r"\bs0*(\d{1,2})\b", label, re.IGNORECASE))
    for match in reversed(s_forms):
        season = _sane_season(int(match.group(1)))
        if season is not None:
            return season
    return None


def _match_ep_only(label: str) -> tuple[int | None, int | None]:
    """E-only markers ("E05", "Episode 5") carrying the same-label anchor."""
    episode: int | None = None
    for pattern in (EP_ONLY_WORD_RE, EP_ONLY_S_RE):
        match = pattern.search(label)
        if match:
            episode = _sane_episode(int(match.group("episode")))
            if episode is not None:
                break
    if episode is None:
        return None, None
    # Never fire on codec/resolution tails ("x264", "1080p").
    if YEAR_OR_RES_RE.search(label[max(0, label.lower().find(f"e{episode:02d}") - 2):]):
        pass  # informational only; anchor logic below still applies
    return _bare_season_anchor(label), episode


def _match_part_episode(label: str) -> tuple[int | None, int | None]:
    """Anime "Part N - EE" with a season anchor ("S04 Part 2 - 06" -> S4E6).

    Requires a season anchor; the ep number must be sane and never a
    resolution. A bare "Part N" without dash-number is not an episode.
    """
    match = PART_EP_RE.search(label)
    if not match:
        return None, None
    episode = _sane_episode(int(match.group("episode")))
    if episode is None:
        return None, None
    # Resolution glued after dash ("Part 2 - 1080p") is not an episode.
    after = label[match.end():match.end() + 4]
    if re.match(r"\s*p\b", after, re.IGNORECASE) and episode in (480, 576, 720, 1080, 2160):
        return None, None
    anchor = _bare_season_anchor(label)
    if anchor is None:
        return None, None
    return anchor, episode


def _match_s_bare_range(label: str) -> tuple[int | None, int | None]:
    """S-form + bare episode range ("S01 1-2", "S02 1 to 9").

    The S prefix applies to BOTH episodes (S01E01..S01E02). Single-file
    collapse: return the range start. The second number must be bare (no
    "s") and separated by whitespace — that keeps "S01-S03" a season
    collection (handled by folder logic, not here).
    """
    match = re.search(
        r"\bs0*(?P<season>\d{1,2})\s+0*(?P<episode>\d{1,3})\s*(?:(?:to|till|thru|through)\b|[-–])\s*0*\d{1,3}\b",
        label,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return (
        _sane_season(int(match.group("season"))),
        _sane_episode(int(match.group("episode"))),
    )


def _extract_season_episode(label: str) -> tuple[int | None, int | None]:
    """Extract one (season, episode) pair from a label.

    Priority mirrors JellyJake's cascade, collapsed to single-file
    semantics: explicit SxxEyy first, then word/dash/x forms, then E-only
    with anchor carry. Range/list outputs are intentionally NOT produced —
    a range file ("S01E01-E13") resolves to its start episode and the
    existing revision-dedup keeps behavior unchanged.
    """
    # 1. Anime finale marker first (never a range).
    season, episode = _match_end_episode(label)
    if season is not None or episode is not None:
        return season, episode

    # 2. Explicit SxxEyy tokens (existing behavior, now sane-capped).
    season, episode = _match_season_episode_token_re(label)
    if season is not None or episode is not None:
        return season, episode

    # 3. SxxEyy range start ("S01E01-E13" -> S1E1). Single-file collapse:
    # take the start; the file still represents that episode.
    range_start = re.search(
        r"(?:^|[^a-z0-9])s(?P<season>\d{1,2})e(?P<episode>\d{1,3})\s*(?:(?:to|till|thru|through)\b|[-–])\s*e?0*\d{1,3}(?:[^a-z0-9]|$)",
        label,
        re.IGNORECASE,
    )
    if range_start:
        return (
            _sane_season(int(range_start.group("season"))),
            _sane_episode(int(range_start.group("episode"))),
        )

    # 3b. S-form + bare episode range ("S01 1-2" -> S1E1).
    season, episode = _match_s_bare_range(label)
    if season is not None or episode is not None:
        return season, episode

    # 4. Dash forms with year/resolution rejection.
    for pattern in (SEASON_DASH_EPISODE_RE, SEASON_WORD_DASH_EPISODE_RE):
        season, episode = _match_dash_form(pattern, label)
        if season is not None or episode is not None:
            return season, episode

    # 5. Word form without dash ("Season 1 Episode 5").
    season, episode = _match_word_episode(label)
    if season is not None or episode is not None:
        return season, episode

    # 6. x-notation ("1x05") with codec/dimension guards.
    season, episode = _match_x_notation(label)
    if season is not None or episode is not None:
        return season, episode

    # 7. Anime Part-episode ("S04 Part 2 - 06" -> S4E6).
    season, episode = _match_part_episode(label)
    if season is not None or episode is not None:
        return season, episode

    # 8. E-only with same-label anchor carry ("S04 ... e07").
    season, episode = _match_ep_only(label)
    if episode is not None:
        return season, episode

    return None, None


def _extract_bare_episode_from_name(name: str) -> int | None:
    stem = Path(name).stem
    for match in BARE_EPISODE_RE.finditer(stem):
        return int(match.group("episode"))
    return None


def _extract_contained_bare_episode(name: str) -> int | None:
    match = CONTAINED_BARE_EPISODE_RE.match(Path(name).stem)
    if not match:
        return None
    return int(match.group("episode"))


def _extract_contained_bare_episode_title(stem: str) -> str | None:
    match = CONTAINED_BARE_EPISODE_RE.match(stem)
    if not match:
        return None
    return match.group("title").strip(" -._") or None


def _extract_season_from_folder(candidate) -> int | None:
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
