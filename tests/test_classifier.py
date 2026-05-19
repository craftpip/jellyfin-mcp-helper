from app.models.schemas import CandidateItem
from app.services.classifier import classify_candidate


def _candidate(name: str, *, container_path: str | None = None, relative_path: str | None = None) -> CandidateItem:
    return CandidateItem(
        source_root_key="downloads_0",
        source_root="/data/torrents",
        source_path=f"/data/torrents/{name}",
        name=name,
        container_path=container_path,
        relative_path=relative_path,
    )


def test_extracts_episode_with_v_suffix() -> None:
    candidate = _candidate(
        name="[Group] Show Name - S03E02v2.mkv",
        container_path="/data/torrents/[Group] Show Name (Season 03)",
        relative_path="[Group] Show Name - S03E02v2.mkv",
    )

    result = classify_candidate(candidate)

    assert result.kind == "series"
    assert result.season == 3
    assert result.episode == 2


def test_extracts_multi_digit_episode_with_revision_suffix() -> None:
    candidate = _candidate(name="[Group] Show Name - S03E10v3.mkv")

    result = classify_candidate(candidate)

    assert result.kind == "series"
    assert result.season == 3
    assert result.episode == 10


def test_extracts_episode_from_s_dash_episode_pattern() -> None:
    candidate = _candidate(name="[Group] Show Name S2 - 02.mkv")

    result = classify_candidate(candidate)

    assert result.kind == "series"
    assert result.season == 2
    assert result.episode == 2


def test_extracts_episode_from_season_word_dash_episode_pattern() -> None:
    candidate = _candidate(name="Show Name Season 02 - 12.mkv")

    result = classify_candidate(candidate)

    assert result.kind == "series"
    assert result.season == 2
    assert result.episode == 12


def test_uses_folder_season_when_missing_in_filename() -> None:
    candidate = _candidate(
        name="Show Name - 03.mkv",
        container_path="/data/torrents/Show Name Season 04",
        relative_path="Show Name - 03.mkv",
    )

    result = classify_candidate(candidate)

    assert result.kind == "series"
    assert result.season == 4
    assert result.episode == 3
