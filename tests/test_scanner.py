from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.core.config import PathsConfig
from app.services.scanner import (
    RecentFile,
    ScanCandidatesResult,
    ScanPathError,
    _collect_recent_file,
    _infer_root_key,
    _iter_child_files,
    _should_skip_path,
    list_target_paths,
    recent_video_files,
    scan_candidates,
)


# ---------------------------------------------------------------------------
# _should_skip_path
# ---------------------------------------------------------------------------

class TestShouldSkipPath:
    def test_trickplay_marker(self) -> None:
        assert _should_skip_path(Path("/data/.trickplay")) is True

    def test_nested_trickplay(self) -> None:
        assert _should_skip_path(Path("/data/show/.trickplay")) is True

    def test_normal_path(self) -> None:
        assert _should_skip_path(Path("/data/show/season01")) is False

    def test_sample_marker(self) -> None:
        assert _should_skip_path(Path("/data/sample")) is False


# ---------------------------------------------------------------------------
# _infer_root_key
# ---------------------------------------------------------------------------

class TestInferRootKey:
    def test_first_root(self, tmp_path: Path) -> None:
        config = PathsConfig(downloadRoots=[str(tmp_path)])
        assert _infer_root_key(config, str(tmp_path)) == "movie_0"

    def test_second_root(self, tmp_path: Path) -> None:
        root1 = tmp_path / "a"
        root2 = tmp_path / "b"
        root1.mkdir()
        root2.mkdir()
        config = PathsConfig(downloadRoots=[str(root1), str(root2)])
        assert _infer_root_key(config, str(root2)) == "movie_1"

    def test_unknown_root(self, tmp_path: Path) -> None:
        config = PathsConfig(downloadRoots=[str(tmp_path / "other")])
        assert _infer_root_key(config, str(tmp_path / "nonexistent")) == "default"


# ---------------------------------------------------------------------------
# list_target_paths
# ---------------------------------------------------------------------------

class TestListTargetPaths:
    def test_lists_children(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / ".hidden").mkdir()
        result = list_target_paths(str(tmp_path))
        assert len(result) == 2
        assert all(not Path(p).name.startswith(".") for p in result)

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        assert list_target_paths(str(tmp_path / "nope")) == []


# ---------------------------------------------------------------------------
# scan_candidates
# ---------------------------------------------------------------------------

class TestScanCandidates:
    def test_collects_video_files(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show S01E01.mkv"
        video.write_bytes(b"video")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].name == "Show S01E01.mkv"

    def test_skips_non_video_files(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        (root / "readme.txt").write_text("hello")
        (root / "image.jpg").write_bytes(b"img")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 0

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        hidden = root / ".hidden_show"
        hidden.mkdir()
        (hidden / "S01E01.mkv").write_bytes(b"video")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 0

    def test_skips_trickplay_dirs(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        show = root / "Show"
        show.mkdir()
        trickplay = show / ".trickplay"
        trickplay.mkdir()
        (trickplay / "S01E01.mkv").write_bytes(b"video")
        (show / "S01E01.mkv").write_bytes(b"video")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1

    def test_collects_nested_video_files(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        show = root / "Show Season 01"
        show.mkdir()
        nested = show / "Subfolder"
        nested.mkdir()
        video = nested / "episode.mkv"
        video.write_bytes(b"video")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].container_path == str(show)
        assert "Subfolder/episode.mkv" in result.candidates[0].relative_path

    def test_nonexistent_root_skipped(self, tmp_path: Path) -> None:
        result = scan_candidates(PathsConfig(downloadRoots=[str(tmp_path / "nope")]))
        assert len(result.candidates) == 0
        assert len(result.errors) == 0

    @pytest.mark.parametrize("marker", [".!qB", ".!qb", ".!UT", ".!ut", ".!bt", ".!BT", ".PART", ".part", ".PaRt", ".partial", ".PARTIAL", ".parts"])
    def test_flags_in_progress_by_partial_marker(self, tmp_path: Path, marker: str) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show.S01E01.mkv"
        video.write_bytes(b"video")
        (root / f"Show.S01E01.mkv{marker}").write_bytes(b"partial")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].in_progress is True

    @pytest.mark.parametrize("prefix", ["Incomplete.", "incomplete.", "INCOMPLETE$"])
    def test_flags_in_progress_by_partial_prefix(self, tmp_path: Path, prefix: str) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show.S01E01.mkv"
        video.write_bytes(b"video")
        (root / f"{prefix}Show.S01E01.mkv").write_bytes(b"partial")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].in_progress is True

    def test_not_in_progress_without_partial_marker(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show.S01E01.mkv"
        video.write_bytes(b"video")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].in_progress is False

    def test_prefix_marker_does_not_mask_unrelated_sibling(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show.S01E01.mkv"
        video.write_bytes(b"video")
        (root / "incomplete.Some.Other.Show.mkv").write_bytes(b"partial")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].in_progress is False

    def test_os_error_recorded(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        bad_dir = root / "Broken"
        bad_dir.mkdir()

        real_walk = os.walk

        def fake_walk(top, *args, **kwargs):
            onerror = kwargs.get("onerror")
            if Path(top) == bad_dir:
                def broken():
                    if onerror:
                        onerror(OSError(5, "I/O error", str(bad_dir / "file")))
                    yield from ()
                return broken()
            return real_walk(top, *args, **kwargs)

        import app.services.scanner as scanner_mod
        original = scanner_mod.os.walk
        scanner_mod.os.walk = fake_walk
        try:
            result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
            assert len(result.errors) == 1
            assert "I/O error" in result.errors[0].error
        finally:
            scanner_mod.os.walk = original

    def test_all_video_extensions(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        for ext in [".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv"]:
            (root / f"file{ext}").write_bytes(b"v")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 7

    def test_candidate_has_file_size(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show.mkv"
        video.write_bytes(b"x" * 100)
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert result.candidates[0].file_size == 100

    def test_direct_file_in_root(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Movie.mkv"
        video.write_bytes(b"video")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 1
        assert result.candidates[0].container_path is None

    def test_multiple_roots(self, tmp_path: Path) -> None:
        root1 = tmp_path / "downloads1"
        root2 = tmp_path / "downloads2"
        root1.mkdir()
        root2.mkdir()
        (root1 / "A.mkv").write_bytes(b"v")
        (root2 / "B.mkv").write_bytes(b"v")
        result = scan_candidates(PathsConfig(downloadRoots=[str(root1), str(root2)]))
        assert len(result.candidates) == 2

    def test_root_with_no_children(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        result = scan_candidates(PathsConfig(downloadRoots=[str(root)]))
        assert len(result.candidates) == 0


# ---------------------------------------------------------------------------
# recent_video_files
# ---------------------------------------------------------------------------

class TestRecentVideoFiles:
    def test_returns_recent_files(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Show.mkv"
        video.write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert len(result) == 1
        assert result[0].name == "Show.mkv"

    def test_excludes_old_files(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Old.mkv"
        video.write_bytes(b"video")
        old_time = time.time() - 86400 * 10
        os.utime(video, (old_time, old_time))
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert len(result) == 0

    def test_zero_hours_returns_empty(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        (root / "Show.mkv").write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=0,
        )
        assert len(result) == 0

    def test_negative_hours_returns_empty(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        (root / "Show.mkv").write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=-1,
        )
        assert len(result) == 0

    def test_nonexistent_root_skipped(self, tmp_path: Path) -> None:
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(tmp_path / "nope")]),
            hours=24,
        )
        assert len(result) == 0

    def test_skips_non_video_files(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        (root / "readme.txt").write_text("hello")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert len(result) == 0

    def test_includes_container_path(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        show = root / "Show"
        show.mkdir()
        (show / "S01E01.mkv").write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert len(result) == 1
        assert result[0].container_path == str(show)

    def test_direct_file_has_no_container(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        (root / "Movie.mkv").write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert result[0].container_path is None

    def test_errors_collected(self, tmp_path: Path) -> None:
        errors: list[ScanPathError] = []
        root = tmp_path / "downloads"
        root.mkdir()
        (root / "Show.mkv").write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
            errors=errors,
        )
        assert isinstance(errors, list)

    def test_sorted_by_mtime_descending(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        old_file = root / "Old.mkv"
        old_file.write_bytes(b"old")
        new_file = root / "New.mkv"
        new_file.write_bytes(b"new")
        old_time = time.time() - 3600
        os.utime(old_file, (old_time, old_time))
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert len(result) == 2
        assert result[0].name == "New.mkv"
        assert result[1].name == "Old.mkv"

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        hidden = root / ".hidden"
        hidden.mkdir()
        (hidden / "Show.mkv").write_bytes(b"video")
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        assert len(result) == 0

    def test_recent_file_attributes(self, tmp_path: Path) -> None:
        root = tmp_path / "downloads"
        root.mkdir()
        video = root / "Test.mkv"
        video.write_bytes(b"x" * 500)
        result = recent_video_files(
            PathsConfig(downloadRoots=[str(root)]),
            hours=24,
        )
        rf = result[0]
        assert rf.source_root == str(root)
        assert rf.source_path == str(video)
        assert rf.name == "Test.mkv"
        assert rf.extension == ".mkv"
        assert rf.file_size == 500
        assert rf.modified_at > 0


# ---------------------------------------------------------------------------
# _iter_child_files
# ---------------------------------------------------------------------------

class TestIterChildFiles:
    def test_yields_sorted_files(self, tmp_path: Path) -> None:
        child = tmp_path / "show"
        child.mkdir()
        (child / "z.mkv").write_bytes(b"z")
        (child / "a.mkv").write_bytes(b"a")
        errors: list[ScanPathError] = []
        files = list(_iter_child_files(child, errors))
        names = [f.name for f in files]
        assert names == ["a.mkv", "z.mkv"]

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        child = tmp_path / "show"
        child.mkdir()
        (child / ".hidden.mkv").write_bytes(b"h")
        (child / "visible.mkv").write_bytes(b"v")
        errors: list[ScanPathError] = []
        files = list(_iter_child_files(child, errors))
        assert len(files) == 1
        assert files[0].name == "visible.mkv"

    def test_skips_hidden_subdirs(self, tmp_path: Path) -> None:
        child = tmp_path / "show"
        child.mkdir()
        hidden = child / ".hidden_dir"
        hidden.mkdir()
        (hidden / "file.mkv").write_bytes(b"v")
        (child / "visible.mkv").write_bytes(b"v")
        errors: list[ScanPathError] = []
        files = list(_iter_child_files(child, errors))
        assert len(files) == 1

    def test_traverse_nested_dirs(self, tmp_path: Path) -> None:
        child = tmp_path / "show"
        child.mkdir()
        nested = child / "subdir"
        nested.mkdir()
        (nested / "deep.mkv").write_bytes(b"d")
        errors: list[ScanPathError] = []
        files = list(_iter_child_files(child, errors))
        assert len(files) == 1
        assert files[0].name == "deep.mkv"
