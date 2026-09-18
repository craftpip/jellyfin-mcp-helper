"""JellyJake-ported robust S/E parsing — single-file collapse semantics.

Adapted from jellyjake tests/classify.test.js. JellySort keeps
series/movie/extra/skip kinds: ranges collapse to their start episode,
collections/lists stay season-only (folder logic), codec/resolution tails
never become episodes.
"""
from __future__ import annotations

from app.classification.episodes import _extract_season_episode
from app.models.schemas import CandidateItem
from app.services.classifier import classify_candidate


def _candidate(name: str, **kw) -> CandidateItem:
    return CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/downloads",
        source_path=f"/data/downloads/{name}",
        name=name,
        **kw,
    )


def test_x_notation() -> None:
    assert _extract_season_episode("Show 1x05 720p") == (1, 5)
    r = classify_candidate(_candidate("Show 1x05 720p.mkv"))
    assert (r.kind, r.season, r.episode) == ("series", 1, 5)


def test_x_notation_with_codec_tail_still_parses_episode() -> None:
    assert _extract_season_episode("Show 5x12.HDTV.x264-PROPER") == (5, 12)


def test_codec_tails_are_not_episodes() -> None:
    assert _extract_season_episode("Show 1x264 1080p") == (None, None)
    assert _extract_season_episode("Show 1 x264 1080p") == (None, None)
    assert _extract_season_episode("Show x264 AAC5.1 1080p") == (None, None)
    assert _extract_season_episode("Show 1920x1080") == (None, None)


def test_word_form_without_dash() -> None:
    assert _extract_season_episode("Show Season 1 Episode 5 1080p") == (1, 5)
    assert _extract_season_episode("Show Season 1 Ep 3") == (1, 3)
    r = classify_candidate(_candidate("Show Season 1 Episode 5 1080p.mkv"))
    assert (r.kind, r.season, r.episode) == ("series", 1, 5)


def test_bare_e_with_same_label_anchor() -> None:
    assert _extract_season_episode("Attack On Titan S04 Part2 e07 Jap 720p") == (4, 7)


def test_anime_part_episode() -> None:
    assert _extract_season_episode("Show S04 Part 2 - 06 1080p") == (4, 6)
    r = classify_candidate(_candidate("Show S04 Part 2 - 06 1080p.mkv"))
    assert (r.kind, r.season, r.episode) == ("series", 4, 6)


def test_finale_end_marker_is_single_episode() -> None:
    assert _extract_season_episode("Dandadan S2 - 12 END (BS4 4K 3840x2160 x265 AAC).mkv") == (2, 12)


def test_year_after_dash_is_not_an_episode() -> None:
    assert _extract_season_episode("Show S02 - 2019 1080p") == (None, None)
    r = classify_candidate(_candidate("Dark - Season 2 S02 - 2019 - 1080p - NF WEB-DL.mkv"))
    assert r.kind == "series"
    assert r.season == 2
    assert r.episode is None


def test_resolution_after_dash_is_not_an_episode() -> None:
    assert _extract_season_episode("Show Season 1 - 720p") == (None, None)
    r = classify_candidate(_candidate("Show Season 1 - 720p.mkv"))
    assert r.season == 1
    assert r.episode is None


def test_sxxeyy_range_collapses_to_start() -> None:
    assert _extract_season_episode("Show S01E01-E13 1080p") == (1, 1)
    r = classify_candidate(_candidate("Show.S01E01-E13.1080p.mkv"))
    assert (r.kind, r.season, r.episode) == ("series", 1, 1)


def test_s_bare_range_collapses_to_start() -> None:
    assert _extract_season_episode("Show S01 1-2 720p") == (1, 1)
    assert _extract_season_episode("Show S02 1 to 9 1080p") == (2, 1)
