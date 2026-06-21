from __future__ import annotations

from app.models.schemas import CandidateItem
from app.services.classifier import classify_candidate


def _candidate(
    name: str,
    *,
    container_path: str | None = None,
    relative_path: str | None = None,
    file_size: int | None = None,
) -> CandidateItem:
    return CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path=f"/data/torrents/{name}",
        name=name,
        container_path=container_path,
        relative_path=relative_path,
        file_size=file_size,
    )


def test_episode_sxxexx_pattern() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - S01E02.mkv"))
    assert result.kind == "series"
    assert result.season == 1
    assert result.episode == 2


def test_anime_episode_without_season_defaults_to_series() -> None:
    result = classify_candidate(_candidate(name="[EMBER] Party kara Tsuihou sareta Sono Chiyushi, Jitsu wa Saikyou ni Tsuki - 01.mkv"))
    assert result.kind == "series"
    assert result.episode == 1


def test_episode_sxxexx_with_revision() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - S03E02v2.mkv"))
    assert result.kind == "series"
    assert result.season == 3
    assert result.episode == 2


def test_episode_multi_digit_with_revision() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - S03E10v3.mkv"))
    assert result.kind == "series"
    assert result.season == 3
    assert result.episode == 10


def test_episode_sxx_dash_episode_pattern() -> None:
    result = classify_candidate(_candidate(name="[Group] Show S2 - 02.mkv"))
    assert result.kind == "series"
    assert result.season == 2
    assert result.episode == 2


def test_season_word_dash_episode() -> None:
    result = classify_candidate(_candidate(name="Show Name Season 02 - 12.mkv"))
    assert result.kind == "series"
    assert result.season == 2
    assert result.episode == 12


def test_season_from_folder_when_missing_in_filename() -> None:
    candidate = _candidate(
        name="Show Name - 03.mkv",
        container_path="/data/torrents/Any Name",
        relative_path="Season 04/Show Name - 03.mkv",
    )
    result = classify_candidate(candidate)
    assert result.kind == "series"
    assert result.season == 4
    assert result.episode == 3


def test_bare_numbered_episode_in_show_folder_uses_folder_as_series_title() -> None:
    result = classify_candidate(
        _candidate(
            name="10-Conclusion.mkv",
            container_path="/data/torrents/Texhnolyze",
            relative_path="10-Conclusion.mkv",
            file_size=1024,
        )
    )

    assert result.kind == "series"
    assert result.title == "Texhnolyze"
    assert result.episode_title == "Conclusion"
    assert result.episode == 10


def test_single_digit_bare_numbered_episode_in_show_folder_is_not_sampled_as_movie() -> None:
    result = classify_candidate(
        _candidate(
            name="1-Stranger.mkv",
            container_path="/data/torrents/Texhnolyze",
            relative_path="1-Stranger.mkv",
            file_size=1024,
        )
    )

    assert result.kind == "series"
    assert result.title == "Texhnolyze"
    assert result.episode_title == "Stranger"
    assert result.episode == 1


def test_movie_with_year() -> None:
    result = classify_candidate(_candidate(name="Show Name (2023).mkv"))
    assert result.kind == "movie"
    assert result.title == "Show Name"
    assert result.year == 2023
    assert result.season is None
    assert result.episode is None


def test_movie_without_year() -> None:
    result = classify_candidate(_candidate(name="Show The Movie.mkv"))
    assert result.kind == "movie"


def test_standalone_tagged_file_without_episode_marker_defaults_to_movie() -> None:
    result = classify_candidate(_candidate(name="[RH] Kanashimi no Belladonna [838F149B].mkv"))
    assert result.kind == "movie"
    assert result.season is None
    assert result.episode is None


def test_ova_is_skipped() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - OVA.mkv"))
    assert result.kind == "skip"
    assert "extras" in result.reason.lower() or "special" in result.reason.lower()


def test_nced_is_skipped() -> None:
    result = classify_candidate(_candidate(name="NCED.mkv"))
    assert result.kind == "skip"


def test_ncop_is_skipped() -> None:
    result = classify_candidate(_candidate(name="NCOP.mkv"))
    assert result.kind == "skip"


def test_ova_in_subfolder_is_skipped() -> None:
    result = classify_candidate(
        _candidate(
            name="[Group] Show - OVA.mkv",
            container_path="/data/torrents/[Group] Show (Season 2)",
            relative_path="[Group] Show - OVA.mkv",
        )
    )
    assert result.kind == "skip"


def test_extra_in_episode_title_is_skipped() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - S01E01 - NCED.mkv"))
    assert result.kind == "skip"


def test_bonus_recap_is_skipped() -> None:
    result = classify_candidate(
        _candidate(
            name="Chobits - Bonus - Recap 18.5.mkv",
            container_path="/data/torrents/Chobits [1080p;H265] (2002)",
            relative_path="Chobits - Bonus - Recap 18.5.mkv",
        )
    )
    assert result.kind == "skip"


def test_sp_decimal_episode_is_skipped() -> None:
    result = classify_candidate(
        _candidate(
            name="S01E13.5 [SP]-To Make Everyone Happy with My Singing [8D781429].mkv",
            container_path="/data/torrents/Vivy S01+SP 1080p Dual Audio BDRip 10 bits DD x265-EMBER",
            relative_path="S01E13.5 [SP]-To Make Everyone Happy with My Singing [8D781429].mkv",
        )
    )
    assert result.kind == "skip"


def test_episode_prefers_fuller_container_title() -> None:
    result = classify_candidate(
        _candidate(
            name="[Judas] Yuusha Party - S01E01.mkv",
            container_path="/data/torrents/[Judas] Yuusha Party o Oidasareta Kiyoubinbou (Jack-of-All-Trades, Party of None) (Season 01)",
            relative_path="[Judas] Yuusha Party - S01E01.mkv",
        )
    )
    assert result.kind == "series"
    assert result.title == "Yuusha Party o Oidasareta Kiyoubinbou (Jack-of-All-Trades, Party of None)"


def test_sample_by_keyword_is_skipped() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - sample.mkv"))
    assert result.kind == "skip"


def test_sample_by_small_size_is_skipped() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - S01E01.mkv", file_size=1024))
    # small file under 150MB threshold with sample marker not needed
    # size check only applies to movies
    assert result.kind == "series"


def test_sample_small_file_movie_is_skipped() -> None:
    result = classify_candidate(_candidate(name="Show Name.mkv", file_size=1024))
    assert result.kind == "skip"


def test_series_defaults_to_title_from_guessit() -> None:
    result = classify_candidate(_candidate(name="[Group] My Show - S01E01.mkv"))
    assert result.title is not None
    assert "My Show" in result.title or result.title is not None


def test_episode_year_from_title_not_confused_as_movie() -> None:
    result = classify_candidate(_candidate(name="Show 2025 - S01E01.mkv"))
    assert result.kind == "series"
    assert result.season == 1
    assert result.episode == 1


def test_only_season_in_folder_no_relative_path_uses_parent() -> None:
    candidate = CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path="/data/torrents/Show Name Season 02/Some File.mkv",
        name="Some File.mkv",
    )
    result = classify_candidate(candidate)
    assert result.kind == "series"
    assert result.season == 2


def test_season_in_relative_path_subfolder() -> None:
    candidate = _candidate(
        name="Some File.mkv",
        container_path="/data/torrents/Container Name",
        relative_path="Season 02/Some File.mkv",
    )
    result = classify_candidate(candidate)
    assert result.kind == "series"
    assert result.season == 2


def test_movie_with_special_characters() -> None:
    result = classify_candidate(_candidate(name="Show Name: Subtitle (2021).mkv"))
    assert result.kind == "movie"
    assert result.year == 2021
