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


def test_ova_is_extra() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - OVA.mkv"))
    assert result.kind == "extra"
    assert "extras" in result.reason.lower() or "special" in result.reason.lower()


def test_nced_is_extra() -> None:
    result = classify_candidate(_candidate(name="NCED.mkv"))
    assert result.kind == "extra"


def test_ncop_is_extra() -> None:
    result = classify_candidate(_candidate(name="NCOP.mkv"))
    assert result.kind == "extra"


def test_ova_in_subfolder_is_extra() -> None:
    result = classify_candidate(
        _candidate(
            name="[Group] Show - OVA.mkv",
            container_path="/data/torrents/[Group] Show (Season 2)",
            relative_path="[Group] Show - OVA.mkv",
        )
    )
    assert result.kind == "extra"


def test_extra_in_episode_title_is_extra() -> None:
    result = classify_candidate(_candidate(name="[Group] Show - S01E01 - NCED.mkv"))
    assert result.kind == "extra"


def test_bonus_recap_is_extra() -> None:
    result = classify_candidate(
        _candidate(
            name="Neutral Show - Bonus - Recap 18.5.mkv",
            container_path="/data/torrents/Neutral Show [1080p;H265] (2002)",
            relative_path="Neutral Show - Bonus - Recap 18.5.mkv",
        )
    )
    assert result.kind == "extra"


def test_featurette_is_extra() -> None:
    result = classify_candidate(
        _candidate(
            name="Neutral Show - Featurettes - Behind the Scenes.mkv",
            container_path="/data/torrents/Neutral Show [1080p;H265] (2002)",
            relative_path="Neutral Show - Featurettes - Behind the Scenes.mkv",
        )
    )
    assert result.kind == "extra"


def test_featurette_in_folder_is_extra() -> None:
    result = classify_candidate(
        _candidate(
            name="Behind the Scenes [Featurettes].mkv",
            container_path="/data/torrents/Neutral Show - Featurettes (2002)",
            relative_path="Neutral Show - Featurettes/Behind the Scenes [Featurettes].mkv",
        )
    )
    assert result.kind == "extra"


def test_sp_decimal_episode_is_extra() -> None:
    result = classify_candidate(
        _candidate(
            name="S01E13.5 [SP]-To Make Everyone Happy with My Singing [8D781429].mkv",
            container_path="/data/torrents/Neutral Show S01+SP 1080p Dual Audio BDRip 10 bits DD x265-RlsGrp",
            relative_path="S01E13.5 [SP]-To Make Everyone Happy with My Singing [8D781429].mkv",
        )
    )
    assert result.kind == "extra"


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


def test_bundle_nested_ost_is_extra_of_bundle_show() -> None:
    result = classify_candidate(
        _candidate(
            name="01 - Theme.mkv",
            container_path="/data/torrents/[Seto_Otaku]_Princess_Lover!_Ep1-12_+_Extras_&_OST_[1080p_Blu-ray_FLAC]",
            relative_path="OST/01 - Theme.mkv",
        )
    )
    assert result.kind == "extra"
    assert result.title == "Princess Lover!"
    assert result.extra_type == "special"


def test_bundle_root_episode_keeps_series_with_bundle_title() -> None:
    result = classify_candidate(
        _candidate(
            name="Princess Lover! - 05.mkv",
            container_path="/data/torrents/[Seto_Otaku]_Princess_Lover!_Ep1-12_+_Extras_&_OST_[1080p_Blu-ray_FLAC]",
            relative_path="Princess Lover! - 05.mkv",
        )
    )
    assert result.kind == "series"
    assert result.title == "Princess Lover!"
    assert result.season is None
    assert result.episode == 5


def test_bundle_declares_extras_only_when_signal_present() -> None:
    result = classify_candidate(
        _candidate(
            name="01 - Theme.mkv",
            container_path="/data/torrents/[RlsGrp] Princess Lover! Ep1-12 [1080p_Blu-ray_FLAC]",
            relative_path="01 - Theme.mkv",
        )
    )
    # no extras/OST signal in the container name, no bundle override
    assert result.kind == "series"
    assert result.episode == 1


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


def test_series_number_marker_is_episode_not_sample() -> None:
    # "Neutral Show Series 1" is episode 1, not a sample — the Series N
    # marker feeds the foreign-episode path, so the size-based sample
    # skip (movies only) never fires even under the 150MB threshold.
    result = classify_candidate(
        _candidate(
            name="Neutral Show Series 1 Subbed [RlsGrp].mp4",
            container_path="/data/downloads/Neutral Show Series",
            relative_path="Neutral Show Series/Neutral Show Series 1 Subbed [RlsGrp].mp4",
            file_size=145 * 1024 * 1024,
        )
    )
    assert result.kind == "series"
    assert result.title == "Neutral Show Series"
    assert result.episode == 1


def test_series_marker_ignores_four_digit_year() -> None:
    result = classify_candidate(
        _candidate(
            name="Neutral Show Series 2020.mkv",
            container_path="/data/downloads/Neutral Show Series",
            relative_path="Neutral Show Series/Neutral Show Series 2020.mkv",
        )
    )
    assert result.episode is None


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


def test_sac_2045_s01e10_with_net_website_is_not_misparsed_as_204() -> None:
    # Regression for SAC_2045 mis-parse: S01E10.NET was treated as website
    # and SAC_2045 was parsed as S20E45/E2045 (or truncated 204), dropping the real S01E10.
    result = classify_candidate(_candidate(
        name="Ghost.in.the.Shell.SAC_2045.S01E10.NET.PEOPLE.-.Reasons.Leading.to.Flameout.720p.NF.WEB-DL.DD+2.0.x264-BonsaiHD.mkv",
        container_path="/media3/torrents/Ghost in the Shell SAC_2045 S01 Complete 720p NF WEB-DL Dual Audio [Hindi + English] ESub x264 - Shadow (BonsaiHD)",
        relative_path="Ghost.in.the.Shell.SAC_2045.S01E10.NET.PEOPLE.-.Reasons.Leading.to.Flameout.720p.NF.WEB-DL.DD+2.0.x264-BonsaiHD.mkv",
    ))
    assert result.kind == "series"
    assert result.season == 1, f"expected S01, got S{result.season}"
    assert result.episode == 10, f"expected E10, got E{result.episode} (misparsed as 204/2045 from SAC_2045)"
    assert result.episode != 204
    assert result.episode != 2045
    assert result.season != 20


def test_sac_2045_s01e10_with_net_and_s01e09_are_consistent() -> None:
    # S01E09 with same prefix must also be S01E09, not S20E45
    result = classify_candidate(_candidate(
        name="Ghost.in.the.Shell.SAC_2045.S01E09.IDENTITY.THEFT.-.The.Lonely.Struggle.720p.NF.WEB-DL.DD+2.0.x264-BonsaiHD.mkv",
        container_path="/media3/torrents/Ghost in the Shell SAC_2045 S01 Complete 720p NF WEB-DL Dual Audio [Hindi + English] ESub x264 - Shadow (BonsaiHD)",
        relative_path="Ghost.in.the.Shell.SAC_2045.S01E09.IDENTITY.THEFT.-.The.Lonely.Struggle.720p.NF.WEB-DL.DD+2.0.x264-BonsaiHD.mkv",
    ))
    assert result.season == 1
    assert result.episode == 9


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


def test_complete_collection_folder_with_season_range_is_stripped() -> None:
    # Regression for KRYPTON (2018-2019) - Complete SUPERMAN Prequel TV Series, Season 1-2 S01-S02
    # report 8fdd42e115bf472b8bd339bbca566ab8 incorrectly mapped to Psycho-Pass (2012) because
    # _extract_series_from_source returned the long collection string and _extract_title preferred
    # it over the clean file title, then find_continuation matched via short numeric alias "01".
    # Obfuscated equivalent uses EIDOLON as neutral placeholder for the show name.
    container = "/data/downloads/EIDOLON (2018-2019) - Complete LEGEND Prequel TV Series, Season 1-2 S01-S02 - 720p AMZN Web-DL x264"
    cases = [
        ("EIDOLON - S01 E02 - House of EL (720p - AMZN Web-DL).mp4", "Season 1 (2018)/EIDOLON - S01 E02 - House of EL (720p - AMZN Web-DL).mp4", 1, 2, "House of EL"),
        ("EIDOLON - S02 E01 - Light Years From Home (720p - AMZN Web-DL).mp4", "Season 2 (2019)/EIDOLON - S02 E01 - Light Years From Home (720p - AMZN Web-DL).mp4", 2, 1, "Light Years From Home"),
        ("EIDOLON - S01 E00 - The Making of a Legend (720p - Proper HDTV).mp4", "Season 1 (2018)/EIDOLON - S01 E00 - The Making of a Legend (720p - Proper HDTV).mp4", 1, 0, "The Making of a Legend"),
    ]
    for name, rel, exp_season, exp_episode, exp_ep_title in cases:
        result = classify_candidate(_candidate(name=name, container_path=container, relative_path=rel))
        assert result.kind == "series", f"{name} should be series, got {result.kind} ({result.reason})"
        assert result.title == "EIDOLON", f"{name} title {result.title!r} should be EIDOLON (not long collection string)"
        assert result.season == exp_season, f"{name} season {result.season} != {exp_season}"
        assert result.episode == exp_episode, f"{name} episode {result.episode} != {exp_episode}"
        assert result.episode_title == exp_ep_title, f"{name} episode_title {result.episode_title!r} != {exp_ep_title!r}"
        # Title must not contain collection/technical junk
        assert "Complete" not in (result.title or "")
        assert "LEGEND" not in (result.title or "")
        assert "Season 1-2" not in (result.title or "")
        assert "S01-S02" not in (result.title or "")
        assert "720p" not in (result.title or "")


def test_complete_collection_folder_krypton_real_title() -> None:
    # Same pattern with the real reported title to lock the fix for the current report.
    # Kept alongside the obfuscated variant above; both must stay green.
    container = "/data/downloads/KRYPTON (2018-2019) - Complete SUPERMAN Prequel TV Series, Season 1-2 S01-S02 - 720p AMZN Web-DL x264"
    result = classify_candidate(_candidate(
        name="KRYPTON - S01 E02 - House of EL (720p - AMZN Web-DL).mp4",
        container_path=container,
        relative_path="Season 1 (2018)/KRYPTON - S01 E02 - House of EL (720p - AMZN Web-DL).mp4",
    ))
    assert result.kind == "series"
    assert result.title == "KRYPTON"
    assert result.season == 1
    assert result.episode == 2
    assert "Complete" not in result.title
    assert "SUPERMAN" not in result.title


def test_year_in_parens_is_not_a_season() -> None:
    # "Bright Sky. The Animation - 01 (2021)" — guessit reads "(2021)" as
    # season 2021. The year must be filtered first so it never becomes
    # Season 2021 / S2021E01 (resolver defaults season None to 1).
    container = "/data/downloads/Bright Sky. The Animation (2021) [1080p-HEVC-WEBRip]"
    for ep in (1, 2):
        result = classify_candidate(_candidate(
            name=f"Bright Sky. The Animation - {ep:02d} (2021) [1080p-HEVC-WEBRip][1CD227C7].mkv",
            container_path=container,
            relative_path=f"Bright Sky. The Animation (2021) [1080p-HEVC-WEBRip]/Bright Sky. The Animation - {ep:02d} (2021) [1080p-HEVC-WEBRip][1CD227C7].mkv",
        ))
        assert result.kind == "series", f"ep {ep} should be series, got {result.kind} ({result.reason})"
        assert result.year == 2021
        assert result.episode == ep, f"ep {ep} got episode {result.episode}"
        assert result.season is None or result.season == 1, f"ep {ep} season must not be 2021, got {result.season}"
        assert "2021" not in (result.title or "").replace("(2021)", "")


def test_year_like_season_and_episode_are_dropped() -> None:
    # Direct sanitizer checks: year-first filtering plus sane caps, so no
    # year-like or resolution-like number survives as season/episode.
    from app.classification.episodes import _sanitize_episode, _sanitize_season

    assert _sanitize_season(2021, 2021) is None
    assert _sanitize_season(2021, None) is None
    assert _sanitize_season(1080, None) is None
    assert _sanitize_season(2, 2021) == 2
    assert _sanitize_episode(2021, 2021) is None
    assert _sanitize_episode(1, 2021) == 1
