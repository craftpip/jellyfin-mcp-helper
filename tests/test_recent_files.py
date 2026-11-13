from __future__ import annotations

import os
import time

from app.core.config import PathsConfig
from app.main import _build_recent_file_items
from app.services.scanner import RecentFile, recent_video_files


def test_build_recent_file_items_matches_jellyfin_item_shape() -> None:
    files = [
        RecentFile(
            source_root="/downloads",
            source_path="/downloads/Good.Movie.2026.1080p.mkv",
            name="Good.Movie.2026.1080p.mkv",
            extension=".mkv",
            file_size=2_000_000_000,
            modified_at=time.time(),
        ),
        RecentFile(
            source_root="/downloads",
            source_path="/downloads/[RlsGrp] Fine Show - S02E05.mkv",
            name="[RlsGrp] Fine Show - S02E05.mkv",
            extension=".mkv",
            file_size=500_000_000,
            modified_at=time.time(),
        ),
        RecentFile(
            source_root="/downloads",
            source_path="/downloads/Anime-OP01.mkv",
            name="Anime-OP01.mkv",
            extension=".mkv",
            file_size=300_000_000,
            modified_at=time.time(),
        ),
    ]

    items = _build_recent_file_items(files, series_title_aliases={})

    movie = next(i for i in items if i["type"] == "movie")
    assert movie["name"] == "Good Movie"
    assert movie["year"] == 2026
    assert movie["path"] == "/downloads/Good.Movie.2026.1080p.mkv"
    assert set(movie.keys()) == {"name", "type", "year", "path"}

    series = next(i for i in items if i["type"] == "series")
    assert series["name"] == "Fine Show"
    assert series["season_count"] == 1
    assert series["episode_count"] == 1
    assert series["ongoing"] is False
    assert series["path"] == "/downloads/[RlsGrp] Fine Show - S02E05.mkv"
    assert set(series.keys()) == {"name", "type", "ongoing", "path", "season_count", "episode_count"}

    skipped = next(i for i in items if i["type"] == "skip")
    assert skipped["path"] == "/downloads/Anime-OP01.mkv"


def test_recent_video_files_filters_by_mtime_and_extension(tmp_path) -> None:
    root = tmp_path / "downloads"
    root.mkdir()

    recent_file = root / "Recent.Show.S01E01.mkv"
    recent_file.write_bytes(b"video")
    old_file = root / "Old.Show.S01E01.mkv"
    old_file.write_bytes(b"video")
    non_video = root / "notes.txt"
    non_video.write_bytes(b"not video")
    hidden = root / ".hidden.mkv"
    hidden.write_bytes(b"hidden")

    now = time.time()
    os.utime(recent_file, (now, now))
    os.utime(non_video, (now, now))
    os.utime(hidden, (now, now))
    os.utime(old_file, (now - 72 * 3600, now - 72 * 3600))

    result = recent_video_files(PathsConfig(downloadRoots=[str(root)]), hours=24)

    assert [f.name for f in result] == ["Recent.Show.S01E01.mkv"]
    assert result[0].source_path == str(recent_file)
    assert result[0].extension == ".mkv"
    assert result[0].file_size == 5


def test_recent_video_files_includes_nested_dirs_and_skips_markers(tmp_path) -> None:
    root = tmp_path / "downloads"
    nested = root / "Release.Folder" / "Show.S01E01.mkv"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"nested video")
    trickplay = root / "Show" / ".trickplay" / "frames.mkv"
    trickplay.parent.mkdir(parents=True)
    trickplay.write_bytes(b"frames")

    now = time.time()
    os.utime(nested, (now, now))
    os.utime(trickplay, (now, now))

    result = recent_video_files(PathsConfig(downloadRoots=[str(root)]), hours=24)

    assert [f.name for f in result] == ["Show.S01E01.mkv"]
    assert result[0].container_path == str(nested.parent)


def test_recent_video_files_respects_hours_and_zero_guard(tmp_path) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    video = root / "New.Show.S01E01.mkv"
    video.write_bytes(b"video")

    now = time.time()
    os.utime(video, (now, now))

    assert recent_video_files(PathsConfig(downloadRoots=[str(root)]), hours=0) == []
    assert recent_video_files(PathsConfig(downloadRoots=[str(root)]), hours=-5) == []

    os.utime(video, (now - 2 * 3600, now - 2 * 3600))
    result = recent_video_files(PathsConfig(downloadRoots=[str(root)]), hours=1)
    assert result == []
