from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.release_tracker import ReleaseTracker, _normalize_name


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_lowercases(self) -> None:
        assert _normalize_name("My Series") == "my series"

    def test_strips_whitespace(self) -> None:
        assert _normalize_name("  My  Series  ") == "my series"

    def test_collapses_internal_whitespace(self) -> None:
        assert _normalize_name("Show   Name") == "show name"

    def test_empty_string(self) -> None:
        assert _normalize_name("") == ""

    def test_casefold(self) -> None:
        assert _normalize_name("STRÜMPFE") == "strümpfe"


# ---------------------------------------------------------------------------
# Upert / CRUD lifecycle
# ---------------------------------------------------------------------------

class TestReleaseTrackerCRUD:
    def test_upsert_creates_record(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        record = tracker.upsert_release({
            "libraryName": "TV Shows",
            "seriesName": "My Show",
            "nextReleaseDate": "2026-09-01",
        })
        assert record["libraryName"] == "TV Shows"
        assert record["seriesName"] == "My Show"
        assert record["nextReleaseDate"].startswith("2026-09-01")

    def test_upsert_updates_existing_record(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-01",
        })
        updated = tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-10-01",
        })
        assert updated["nextReleaseDate"].startswith("2026-10-01")
        listing = tracker.list_releases()
        assert listing["tracked_count"] == 1

    def test_upsert_requires_library_name(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="libraryName"):
            tracker.upsert_release({"seriesName": "X", "nextReleaseDate": "2026-01-01"})

    def test_upsert_requires_series_name(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="seriesName"):
            tracker.upsert_release({"libraryName": "X", "nextReleaseDate": "2026-01-01"})

    def test_upsert_requires_next_release_date(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="nextReleaseDate"):
            tracker.upsert_release({"libraryName": "X", "seriesName": "Y"})

    def test_list_releases_empty(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        listing = tracker.list_releases()
        assert listing["tracked_count"] == 0
        assert listing["items"] == []

    def test_list_releases_filters_by_library(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "Movies",
            "seriesName": "Film A",
            "nextReleaseDate": "2026-06-01",
        })
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show B",
            "nextReleaseDate": "2026-07-01",
        })
        movies = tracker.list_releases(library_name="Movies")
        assert movies["tracked_count"] == 1
        assert movies["items"][0]["seriesName"] == "Film A"

    def test_list_releases_respects_limit(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        for i in range(5):
            tracker.upsert_release({
                "libraryName": "TV",
                "seriesName": f"Show {i}",
                "nextReleaseDate": f"2026-{6 + i:02d}-01",
            })
        result = tracker.list_releases(limit=3)
        assert result["tracked_count"] == 3

    def test_list_releases_sorted_by_date(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Later",
            "nextReleaseDate": "2026-12-01",
        })
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Earlier",
            "nextReleaseDate": "2026-01-01",
        })
        result = tracker.list_releases()
        assert result["items"][0]["seriesName"] == "Earlier"
        assert result["items"][1]["seriesName"] == "Later"

    def test_get_release_found(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "My Show",
            "nextReleaseDate": "2026-09-01",
            "seriesId": "jellyfin-123",
        })
        result = tracker.get_release({
            "libraryName": "TV",
            "seriesName": "My Show",
        })
        assert result is not None
        assert result["seriesId"] == "jellyfin-123"

    def test_get_release_not_found(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        result = tracker.get_release({
            "libraryName": "TV",
            "seriesName": "Nonexistent",
        })
        assert result is None

    def test_get_release_requires_library_name(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="libraryName"):
            tracker.get_release({"seriesName": "X"})

    def test_get_release_requires_series_name(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="seriesName"):
            tracker.get_release({"libraryName": "X"})

    def test_delete_release_found(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "To Delete",
            "nextReleaseDate": "2026-09-01",
        })
        deleted = tracker.delete_release({
            "libraryName": "TV",
            "seriesName": "To Delete",
        })
        assert deleted is not None
        assert deleted["seriesName"] == "To Delete"
        assert tracker.list_releases()["tracked_count"] == 0

    def test_delete_release_not_found(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        result = tracker.delete_release({
            "libraryName": "TV",
            "seriesName": "Nonexistent",
        })
        assert result is None

    def test_delete_requires_library_name(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="libraryName"):
            tracker.delete_release({"seriesName": "X"})

    def test_delete_requires_series_name(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="seriesName"):
            tracker.delete_release({"libraryName": "X"})


# ---------------------------------------------------------------------------
# series_id based lookup
# ---------------------------------------------------------------------------

class TestSeriesIdLookup:
    def test_upsert_by_series_id(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Old Name",
            "seriesId": "jellyfin-42",
            "nextReleaseDate": "2026-09-01",
        })
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "New Name",
            "seriesId": "jellyfin-42",
            "nextReleaseDate": "2026-10-01",
        })
        listing = tracker.list_releases()
        assert listing["tracked_count"] == 1
        assert listing["items"][0]["seriesName"] == "New Name"

    def test_get_by_series_id(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "seriesId": "jf-99",
            "nextReleaseDate": "2026-09-01",
        })
        result = tracker.get_release({
            "libraryName": "TV",
            "seriesName": "Different Name",
            "seriesId": "jf-99",
        })
        assert result is not None

    def test_delete_by_series_id(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "seriesId": "jf-99",
            "nextReleaseDate": "2026-09-01",
        })
        deleted = tracker.delete_release({
            "libraryName": "TV",
            "seriesName": "Different",
            "seriesId": "jf-99",
        })
        assert deleted is not None


# ---------------------------------------------------------------------------
# get_due_releases
# ---------------------------------------------------------------------------

class TestGetDueReleases:
    def test_returns_past_releases(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Past Show",
            "nextReleaseDate": "2020-01-01",
        })
        result = tracker.get_due_releases(before="2026-08-18")
        assert result["due_count"] == 1
        assert result["items"][0]["seriesName"] == "Past Show"

    def test_excludes_future_releases(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Future Show",
            "nextReleaseDate": "2099-01-01",
        })
        result = tracker.get_due_releases(before="2026-08-18")
        assert result["due_count"] == 0

    def test_days_overdue(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Old Show",
            "nextReleaseDate": "2026-01-01",
        })
        result = tracker.get_due_releases(before="2026-08-18")
        assert result["items"][0].get("daysOverdue") is not None
        assert result["items"][0]["daysOverdue"] >= 200

    def test_hours_overdue(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Recent Show",
            "nextReleaseDate": "2026-08-18T08:00:00",
        })
        result = tracker.get_due_releases(before="2026-08-18T12:00:00")
        assert result["items"][0].get("hoursOverdue") is not None
        assert result["items"][0]["hoursOverdue"] == pytest.approx(4.0, abs=0.5)

    def test_limit(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        for i in range(10):
            tracker.upsert_release({
                "libraryName": "TV",
                "seriesName": f"Show {i}",
                "nextReleaseDate": f"2020-01-{i + 1:02d}",
            })
        result = tracker.get_due_releases(before="2026-08-18", limit=3)
        assert result["due_count"] == 3

    def test_filters_by_library(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "Movies",
            "seriesName": "Film",
            "nextReleaseDate": "2020-01-01",
        })
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2020-01-01",
        })
        result = tracker.get_due_releases(library_name="TV", before="2026-08-18")
        assert result["due_count"] == 1
        assert result["items"][0]["seriesName"] == "Show"

    def test_before_now(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-08-18",
        })
        result = tracker.get_due_releases(before="now")
        assert result["due_count"] == 1

    def test_before_none_defaults_to_now(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2020-01-01",
        })
        result = tracker.get_due_releases(before=None)
        assert result["due_count"] == 1


# ---------------------------------------------------------------------------
# datetime parsing
# ---------------------------------------------------------------------------

class TestDatetimeParsing:
    def test_date_only_uses_midnight(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        record = tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-15",
        })
        dt = datetime.fromisoformat(record["nextReleaseDate"])
        assert dt.hour == 0
        assert dt.minute == 0

    def test_datetime_with_time(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        record = tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-15T20:30:00",
        })
        dt = datetime.fromisoformat(record["nextReleaseDate"])
        assert dt.hour == 20
        assert dt.minute == 30

    def test_timezone_preserved(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        record = tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-15T20:00:00+05:00",
            "timezone": "Asia/Karachi",
        })
        dt = datetime.fromisoformat(record["nextReleaseDate"])
        assert dt.tzinfo is not None

    def test_invalid_timezone_raises(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        with pytest.raises(ValueError, match="Invalid timezone"):
            tracker.upsert_release({
                "libraryName": "TV",
                "seriesName": "Show",
                "nextReleaseDate": "2026-09-15",
                "timezone": "Not/A/Timezone",
            })


# ---------------------------------------------------------------------------
# Persistence / store format
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_records_persist_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "releases.json"
        tracker1 = ReleaseTracker(store_path=path)
        tracker1.upsert_release({
            "libraryName": "TV",
            "seriesName": "Persistent Show",
            "nextReleaseDate": "2026-09-01",
        })
        tracker2 = ReleaseTracker(store_path=path)
        listing = tracker2.list_releases()
        assert listing["tracked_count"] == 1
        assert listing["items"][0]["seriesName"] == "Persistent Show"

    def test_empty_store_file(self, tmp_path: Path) -> None:
        path = tmp_path / "releases.json"
        path.write_text("")
        tracker = ReleaseTracker(store_path=path)
        assert tracker.list_releases()["tracked_count"] == 0

    def test_missing_store_file(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "nonexistent.json")
        assert tracker.list_releases()["tracked_count"] == 0

    def test_corrupt_store_file(self, tmp_path: Path) -> None:
        path = tmp_path / "releases.json"
        path.write_text("{not valid json")
        tracker = ReleaseTracker(store_path=path)
        # With SQLite, corrupt JSON file is ignored and a new DB is created
        assert tracker.list_releases()["tracked_count"] == 0

    def test_store_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "dir" / "releases.json"
        tracker = ReleaseTracker(store_path=path)
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-01",
        })
        # SQLite uses test.db in the same dir
        assert (tmp_path / "sub" / "dir" / "test.db").exists() or path.parent.exists()

    def test_updated_at_is_set(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        record = tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-01",
        })
        assert "updatedAt" in record
        dt = datetime.fromisoformat(record["updatedAt"])
        assert dt.tzinfo is not None

    def test_source_preserved_from_existing(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-01",
            "source": "tvdb",
        })
        tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-10-01",
        })
        listing = tracker.list_releases()
        assert listing["items"][0]["source"] == "tvdb"

    def test_optional_fields(self, tmp_path: Path) -> None:
        tracker = ReleaseTracker(store_path=tmp_path / "releases.json")
        record = tracker.upsert_release({
            "libraryName": "TV",
            "seriesName": "Show",
            "nextReleaseDate": "2026-09-01",
            "nextSeason": 5,
            "nextEpisode": 3,
            "notes": "Season finale",
        })
        assert record["nextSeason"] == 5
        assert record["nextEpisode"] == 3
        assert record["notes"] == "Season finale"
