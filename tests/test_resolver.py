from __future__ import annotations

import asyncio
from pathlib import Path

from app.models.schemas import CandidateItem, ClassificationResult
from app.services.resolver import (
    PathResolver,
    sanitize_name,
    normalize_text,
    normalize_series_text,
    season_dir_candidates,
)
from app.core.config import AppConfig, ModelConfig, PathsConfig


def test_sanitize_name_removes_invalid_chars() -> None:
    assert sanitize_name('Show: Name <bad> |pipe') == "Show Name bad pipe"


def test_sanitize_name_strips_trailing_dots() -> None:
    assert sanitize_name("Show Name...") == "Show Name"


def test_sanitize_name_defaults_to_unknown() -> None:
    assert sanitize_name("") == "Unknown"


def test_normalize_text_lowercases_and_joins() -> None:
    assert normalize_text("Show Name 2023") == "show name 2023"


def test_normalize_series_text_removes_trailing_year() -> None:
    assert normalize_series_text("Undone (2019)") == "undone"


def test_season_dir_candidates() -> None:
    candidates = season_dir_candidates(3)
    assert "season 3" in candidates
    assert "season 03" in candidates
    assert "s3" in candidates
    assert "s03" in candidates
    assert len(candidates) == 4


def test_movie_folder_name_with_year(tmp_path) -> None:
    config = _make_config()
    resolver = PathResolver(config)
    classification = ClassificationResult(
        type="movie", title="Test Movie", year=2023
    )
    name = resolver._movie_folder_name(classification)
    assert name == "Test Movie (2023)"


def test_movie_folder_name_without_year(tmp_path) -> None:
    config = _make_config()
    resolver = PathResolver(config)
    classification = ClassificationResult(type="movie", title="Test Movie")
    name = resolver._movie_folder_name(classification)
    assert name == "Test Movie"


def test_pick_existing_season_dir_finds_match(tmp_path) -> None:
    show_dir = tmp_path / "Show"
    (show_dir / "Season 01").mkdir(parents=True)
    config = _make_config()
    resolver = PathResolver(config)
    result = resolver._pick_existing_season_dir(show_dir, 1)
    assert result is not None
    assert result.name == "Season 01"


def test_pick_existing_season_dir_no_match(tmp_path) -> None:
    show_dir = tmp_path / "Show"
    show_dir.mkdir(parents=True)
    config = _make_config()
    resolver = PathResolver(config)
    result = resolver._pick_existing_season_dir(show_dir, 5)
    assert result is None


def test_pick_existing_season_dir_alternate_name(tmp_path) -> None:
    show_dir = tmp_path / "Show"
    (show_dir / "s01").mkdir(parents=True)
    config = _make_config()
    resolver = PathResolver(config)
    result = resolver._pick_existing_season_dir(show_dir, 1)
    assert result is not None
    assert result.name == "s01"


def test_resolve_movie_creates_target(tmp_path) -> None:
    config = _make_config(movie_roots=[str(tmp_path)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Test Movie (2023)/Test Movie (2023).mkv",
        name="Test Movie (2023).mkv",
    )
    classification = ClassificationResult(type="movie", title="Test Movie", year=2023)
    result = asyncio.run(resolver._resolve_movie(candidate, classification))
    assert str(tmp_path) in result.target_dir
    assert "Test Movie (2023)" in result.target_path
    assert result.created_movie_folder is True


def test_resolve_series_creates_target(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Name S01E01.mkv",
        name="Show Name S01E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Show Name", season=1, episode=1
    )
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert str(series_root) in result.target_dir
    assert "Season 01" in result.target_dir
    assert "S01E01" in result.target_path
    assert result.created_show_folder is True


def test_resolve_series_uses_existing_show_folder(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (series_root / "Show Name").mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Name S01E01.mkv",
        name="Show Name S01E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Show Name", season=1, episode=1
    )
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert result.existing_match is not None
    assert "Show Name" in result.existing_match
    assert result.created_show_folder is False


def test_resolve_series_matches_existing_folder_without_year(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (series_root / "Undone").mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Undone (2019) - S02E01.mkv",
        name="Undone (2019) - S02E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Undone (2019)", year=2019, season=2, episode=1
    )

    result = asyncio.run(resolver._resolve_series(candidate, classification))

    assert result.existing_match == str(series_root / "Undone")
    assert result.target_dir == str(series_root / "Undone" / "Season 02")
    assert result.created_show_folder is False


def test_resolve_series_uses_existing_season_folder(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    show_dir = series_root / "Show Name"
    show_dir.mkdir()
    (show_dir / "Season 01").mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Name S01E01.mkv",
        name="Show Name S01E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Show Name", season=1, episode=1
    )
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert "Show Name" in result.target_dir
    assert "Season 01" in result.target_dir
    assert "S01E01" in result.target_path


def test_resolve_movie_custom_file_extension(tmp_path) -> None:
    config = _make_config(movie_roots=[str(tmp_path)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Movie (2020)/Movie (2020).mp4",
        name="Movie (2020).mp4",
    )
    classification = ClassificationResult(type="movie", title="Movie", year=2020)
    result = asyncio.run(resolver._resolve_movie(candidate, classification))
    assert result.target_path.endswith(".mp4")


def test_series_show_name_normalization(tmp_path) -> None:
    config = _make_config(series_roots=[str(tmp_path / "series")])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/[Group] K-On!! - S01E01.mkv",
        name="[Group] K-On!! - S01E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="K-On!!", season=1, episode=1
    )
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert "K-On!" in result.target_path or "K-On!!" in result.target_path


def test_resolve_series_finds_existing_across_roots(tmp_path) -> None:
    root1 = tmp_path / "series1"
    root2 = tmp_path / "series2"
    root1.mkdir()
    root2.mkdir()
    (root2 / "Existing Show").mkdir()
    config = _make_config(series_roots=[str(root1), str(root2)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Existing Show S01E01.mkv",
        name="Existing Show S01E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Existing Show", season=1, episode=1
    )
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert result.existing_match is not None
    assert "Existing Show" in result.existing_match
    assert str(root2) in result.existing_match
    assert result.created_show_folder is False


def test_resolve_series_exact_match_across_many_roots(tmp_path) -> None:
    root1 = tmp_path / "series1"
    root2 = tmp_path / "series2"
    root1.mkdir()
    root2.mkdir()
    for i in range(30):
        (root1 / f"Different Show {i:02d}").mkdir()
    (root2 / "Rick and Morty").mkdir()
    config = _make_config(series_roots=[str(root1), str(root2)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Theres Something About Morty - S09E01.mkv",
        name="Theres Something About Morty - S09E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Rick and Morty", season=9, episode=1
    )
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert result.existing_match == str(root2 / "Rick and Morty")
    assert str(root2) in result.target_dir
    assert result.created_show_folder is False


def test_resolve_series_does_not_use_unsafe_fuzzy_existing_match(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (series_root / "Farming Life in Another World").mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Loner Life in Another World S01/S01E01-Loner with the Worst Skills.mkv",
        name="S01E01-Loner with the Worst Skills.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Loner Life in Another World", season=1, episode=1
    )

    result = asyncio.run(resolver._resolve_series(candidate, classification))

    assert result.existing_match is None
    assert "Loner Life in Another World" in result.target_dir
    assert "Farming Life in Another World" not in result.target_dir


def test_resolve_series_does_not_use_existing_short_prefix_folder(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    (series_root / "Mikata").mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Mikata ga Yowasugite Hojo Mahou/S01E01.mkv",
        name="S01E01.mkv",
    )
    classification = ClassificationResult(
        type="series", title="Mikata ga Yowasugite Hojo Mahou", season=1, episode=1
    )

    result = asyncio.run(resolver._resolve_series(candidate, classification))

    assert result.existing_match is None
    assert "Mikata ga Yowasugite Hojo Mahou" in result.target_dir
    assert result.target_dir != str(series_root / "Mikata" / "Season 01")


def test_resolve_movie_finds_existing_across_roots(tmp_path) -> None:
    root1 = tmp_path / "movies1"
    root2 = tmp_path / "movies2"
    root1.mkdir()
    root2.mkdir()
    (root2 / "Existing Movie (2020)").mkdir()
    config = _make_config(movie_roots=[str(root1), str(root2)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Existing Movie (2020)/Existing Movie (2020).mkv",
        name="Existing Movie (2020).mkv",
    )
    classification = ClassificationResult(
        type="movie", title="Existing Movie", year=2020
    )
    result = asyncio.run(resolver._resolve_movie(candidate, classification))
    assert result.existing_match is not None
    assert "Existing Movie (2020)" in result.existing_match
    assert str(root2) in result.existing_match
    assert result.created_movie_folder is False


def test_resolve_defaults_season_to_one(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show S01E01.mkv",
        name="Show S01E01.mkv",
    )
    classification = ClassificationResult(type="series", title="Show", season=None, episode=1)
    result = asyncio.run(resolver._resolve_series(candidate, classification))
    assert result.target_dir.endswith("Season 01")


def test_resolve_series_reuses_first_planned_show_path_within_same_scan(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    config = _make_config(series_roots=[str(series_root)])
    resolver = PathResolver(config)

    first_candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Alpha/Show Alpha - 01.mkv",
        name="Show Alpha - 01.mkv",
    )
    second_candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/SHOW ALPHA/Future Arc - 25.mkv",
        name="Science Future - 25.mkv",
    )

    first = asyncio.run(
        resolver._resolve_series(
            first_candidate,
            ClassificationResult(type="series", title="Show Alpha", season=1, episode=1),
        )
    )
    second = asyncio.run(
        resolver._resolve_series(
            second_candidate,
            ClassificationResult(type="series", title="Show. Alpha", season=4, episode=25),
        )
    )

    assert first.created_show_folder is True
    assert second.created_show_folder is False
    assert first.target_dir == str(series_root / "Show Alpha" / "Season 01")
    assert second.target_dir == str(series_root / "Show Alpha" / "Season 04")


def test_resolve_series_reuses_alias_season_within_same_scan(tmp_path) -> None:
    series_root = tmp_path / "series"
    series_root.mkdir()
    resolver = PathResolver(_make_config(series_roots=[str(series_root)]))

    explicit = asyncio.run(
        resolver._resolve_series(
            CandidateItem(
                source_root_key="downloads_0",
                source_root="/data/torrents",
                source_path="/data/torrents/[Group] Show Alpha - Future Arc - S04E01.mkv",
                name="[Group] Show Alpha - Future Arc - S04E01.mkv",
            ),
            ClassificationResult(
                type="series",
                title="Show Alpha",
                series_alias="Future Arc",
                season=4,
                episode=1,
            ),
        )
    )

    inferred = asyncio.run(
        resolver._resolve_series(
            CandidateItem(
                source_root_key="downloads_0",
                source_root="/data/torrents",
                source_path="/data/torrents/[sam] SHOW ALPHA - Future Arc - 25.mkv",
                name="[sam] SHOW ALPHA - Future Arc - 25.mkv",
            ),
            ClassificationResult(
                type="series",
                title="SHOW ALPHA",
                series_alias="Future Arc",
                season=None,
                episode=25,
            ),
        )
    )

    assert explicit.target_dir == str(series_root / "Show Alpha" / "Season 04")
    assert inferred.target_dir == str(series_root / "Show Alpha" / "Season 04")
    assert inferred.target_path.endswith("S04E25.mkv")


def _make_config(
    movie_roots: list[str] | None = None,
    series_roots: list[str] | None = None,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            downloadRoots=["/data/torrents"],
            movieRoots={f"movie_{i}": p for i, p in enumerate(movie_roots or ["/data/movies"])},
            seriesRoots={f"series_{i}": p for i, p in enumerate(series_roots or ["/data/series"])},
        ),
        model=ModelConfig(),
        log_dir=Path("/tmp/logs"),
        report_dir=Path("/tmp/reports"),
    )
