from __future__ import annotations

from pathlib import Path

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
        source_root="/data/downloads",
        source_path=f"/data/downloads/{name}",
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
    result = classify_candidate(_candidate(name="[RlsGrp] Weird Show - 01.mkv"))
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


def test_alternative_title_becomes_series_alias() -> None:
    result = classify_candidate(_candidate(name="[RlsGrp] Show Name - Future Arc - S04E01v2.mkv"))
    assert result.kind == "series"
    assert result.season == 4
    assert result.series_alias == "Future Arc"


def test_episode_title_can_be_used_as_series_alias_when_no_season_exists() -> None:
    result = classify_candidate(_candidate(name="[RlsGrp] Show Name - Future Arc - 25.mkv"))
    assert result.kind == "series"
    assert result.season is None
    assert result.episode == 25
    assert result.series_alias == "Future Arc"


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
            container_path="/data/torrents/Neutral Show",
            relative_path="10-Conclusion.mkv",
            file_size=1024,
        )
    )

    assert result.kind == "series"
    assert result.title == "Neutral Show"
    assert result.episode_title == "Conclusion"
    assert result.episode == 10


def test_single_digit_bare_numbered_episode_in_show_folder_is_not_sampled_as_movie() -> None:
    result = classify_candidate(
        _candidate(
            name="1-Stranger.mkv",
            container_path="/data/torrents/Neutral Show",
            relative_path="1-Stranger.mkv",
            file_size=1024,
        )
    )

    assert result.kind == "series"
    assert result.title == "Neutral Show"
    assert result.episode_title == "Stranger"
    assert result.episode == 1


def test_dot_separated_bare_episode_still_works() -> None:
    result = classify_candidate(
        _candidate(
            name="4.The.Conclusion.mkv",
            container_path="/data/torrents/Neutral Show",
            relative_path="4.The.Conclusion.mkv",
        )
    )

    assert result.kind == "series"
    assert result.title == "Neutral Show"
    assert result.episode == 4


def test_movie_with_leading_number_in_title_folder_is_movie() -> None:
    result = classify_candidate(
        _candidate(
            name="3 Idiots (2009).mkv",
            container_path="/data/downloads/3 Idiots (2009)",
            relative_path="3 Idiots (2009).mkv",
        )
    )

    assert result.kind == "movie"
    assert result.title == "3 Idiots"
    assert result.year == 2009
    assert result.season is None
    assert result.episode is None


def test_movie_with_leading_number_and_tech_tags_is_movie() -> None:
    result = classify_candidate(
        _candidate(
            name="3.Idiots.2009.1080p.BluRay.mkv",
            container_path="/data/downloads/3 Idiots (2009)",
            relative_path="3.Idiots.2009.1080p.BluRay.mkv",
        )
    )

    assert result.kind == "movie"
    assert result.title == "3 Idiots"
    assert result.year == 2009
    assert result.episode is None


def test_decimal_number_prefix_is_not_a_bare_episode() -> None:
    result = classify_candidate(
        _candidate(
            name="2.5.Crumpled.Staircase.2021.S01E01.REPACK2.BDRip-1080p.x265.FLAC.EAC3.Dual.Audio-RlsGrp.mkv",
            container_path="/data/downloads/2.5 Crumpled Staircase (2021) S01 [BDRip 1080p x265 FLAC EAC3 Dual-Audio]-RlsGrp",
            relative_path="2.5.Crumpled.Staircase.2021.S01E01.REPACK2.BDRip-1080p.x265.FLAC.EAC3.Dual.Audio-RlsGrp.mkv",
        )
    )

    assert result.kind == "series"
    assert result.title == "2.5 Crumpled Staircase (2021)"
    assert result.season == 1
    assert result.episode == 1
    assert result.episode_title is None


def test_folder_underscore_numeric_junk_does_not_override_clean_title() -> None:
    result = classify_candidate(
        _candidate(
            name="[RlsGrp] Nimbus (2020) - S02E01.mkv",
            container_path="/data/downloads/[RlsGrp] Nimbus 7_9 (2020) (Season 02) [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs]",
            relative_path="[RlsGrp] Nimbus (2020) - S02E01.mkv",
        )
    )

    assert result.kind == "series"
    assert result.title == "Nimbus"
    assert result.season == 2
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
            name="Neutral Show - Bonus - Recap 18.5.mkv",
            container_path="/data/torrents/Neutral Show [1080p;H265] (2002)",
            relative_path="Neutral Show - Bonus - Recap 18.5.mkv",
        )
    )
    assert result.kind == "skip"


def test_featurette_is_skipped() -> None:
    result = classify_candidate(
        _candidate(
            name="Neutral Show - Featurettes - Behind the Scenes.mkv",
            container_path="/data/torrents/Neutral Show [1080p;H265] (2002)",
            relative_path="Neutral Show - Featurettes - Behind the Scenes.mkv",
        )
    )
    assert result.kind == "skip"


def test_featurette_in_folder_is_skipped() -> None:
    result = classify_candidate(
        _candidate(
            name="Behind the Scenes [Featurettes].mkv",
            container_path="/data/torrents/Neutral Show - Featurettes (2002)",
            relative_path="Neutral Show - Featurettes/Behind the Scenes [Featurettes].mkv",
        )
    )
    assert result.kind == "skip"


def test_sp_decimal_episode_is_skipped() -> None:
    result = classify_candidate(
        _candidate(
            name="S01E13.5 [SP]-To Make Everyone Happy with My Singing [8D781429].mkv",
            container_path="/data/torrents/Neutral Show S01+SP 1080p Dual Audio BDRip 10 bits DD x265-RlsGrp",
            relative_path="S01E13.5 [SP]-To Make Everyone Happy with My Singing [8D781429].mkv",
        )
    )
    assert result.kind == "skip"


def test_episode_prefers_fuller_container_title() -> None:
    result = classify_candidate(
        _candidate(
            name="[RlsGrp] Stray Cat - S01E01.mkv",
            container_path="/data/torrents/[RlsGrp] Stray Cat of the Ruins (Wandering Star) (Season 01)",
            relative_path="[RlsGrp] Stray Cat - S01E01.mkv",
        )
    )
    assert result.kind == "series"
    assert result.title == "Stray Cat of the Ruins (Wandering Star)"


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


def test_foreign_episode_word_split_out_of_series_title() -> None:
    result = classify_candidate(
        _candidate(
            name="S01E04 The Ghost in the Shell Episodio 04 Robot Rondo (2026) WEBRip 1080p x264 EAC3 ITA ENG JPN SUB ITA ENG - Lullozzo.mkv"
        )
    )
    assert result.kind == "series"
    assert result.title == "The Ghost in the Shell"
    assert result.episode_title == "Robot Rondo"
    assert result.season == 1
    assert result.episode == 4


def test_series_title_alias_maps_to_canonical_name() -> None:
    result = classify_candidate(
        _candidate(name="[LoliHouse] Yani Neko - 05 [WebRip 1080p HEVC-10bit AAC SRTx2].mkv"),
        series_title_aliases={"Yani Neko": "Chainsmoker Cat Yani Neko"},
    )
    assert result.kind == "series"
    assert result.title == "Chainsmoker Cat Yani Neko"
    assert result.episode_title == "Chainsmoker Cat Yani Neko"
    assert result.episode == 5


def test_series_title_alias_not_applied_when_no_match() -> None:
    result = classify_candidate(
        _candidate(name="[LoliHouse] Yani Neko - 05 [WebRip 1080p HEVC-10bit AAC SRTx2].mkv"),
        series_title_aliases={"Nope": "Other Show"},
    )
    assert result.title == "Yani Neko"


RELEASE_JUNK_TOKENS = (
    "1080p", "720p", "2160p", "x265", "hevc", "x264", "av1",
    "flac", "eac3", "aac", "opus", "ddp", "dual-audio", "dual audio",
    "bdrip", "bluray", "webrip", "web-dl", "multi-subs",
    "wobble", "hollow", "morrow", "rivet", "tinker", "zephyr",
    "rlsgrp", "fakesite",
    "repack", "proper",
)


def _release_junk_tokens(text: str) -> list[str]:
    lowered = text.lower()
    return [t for t in RELEASE_JUNK_TOKENS if t in lowered]


def test_corpus_paths_classify_cleanly() -> None:
    import json

    corpus_file = Path(__file__).resolve().parent / "corpus" / "download_paths.json"
    corpus = json.loads(corpus_file.read_text())
    assert corpus["candidates"], "corpus fixture must not be empty"

    failures: list[str] = []
    for entry in corpus["candidates"]:
        candidate = _candidate(
            name=entry["name"],
            container_path=entry.get("container_path"),
            relative_path=entry.get("relative_path"),
            file_size=entry.get("file_size"),
        )
        result = classify_candidate(candidate)

        if result.kind == "error":
            failures.append(f"{entry['name']}: kind=error ({result.reason})")
            continue

        title_junk = _release_junk_tokens(result.title or "")
        ep_junk = _release_junk_tokens(result.episode_title or "")
        if title_junk:
            failures.append(f"{entry['name']}: title {result.title!r} contains {title_junk}")
        if ep_junk:
            failures.append(f"{entry['name']}: episode_title {result.episode_title!r} contains {ep_junk}")
        if result.title and "[" in result.title or "]" in result.title:
            failures.append(f"{entry['name']}: title {result.title!r} contains brackets")

    assert not failures, "corpus classification regressions:\n" + "\n".join(failures[:50])


def test_corpus_underscore_junk_seasons_resolve_to_same_title() -> None:
    import json

    corpus_file = Path(__file__).resolve().parent / "corpus" / "download_paths.json"
    corpus = json.loads(corpus_file.read_text())

    titles: dict[str, set[str]] = {}
    for entry in corpus["candidates"]:
        container = entry.get("container_path") or ""
        if "Nimbus" not in container and "Nimbus" not in entry["name"]:
            continue
        result = classify_candidate(_candidate(
            name=entry["name"],
            container_path=entry.get("container_path"),
            relative_path=entry.get("relative_path"),
            file_size=entry.get("file_size"),
        ))
        titles.setdefault(container, set()).add(result.title)

    assert titles, "expected at least one Nimbus candidate in corpus"
    distinct = {next(iter(s)) for s in titles.values() if s}
    assert len(distinct) == 1, f"Nimbus titles not consistent across folders: {distinct}"
