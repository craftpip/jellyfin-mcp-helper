"""'jellyfin_item_details' + compact 'jellyfin_library_items' + MCP dispatch rules."""
import asyncio
import json

from fastapi.testclient import TestClient

from app.main import _format_mcp_activity_line, _resolve_tool_name, app
from app.services.jellyfin import JellyfinClient, _compact_ranges


def _stream(kind: str, lang: str | None, **extra) -> dict:
    return {"Type": kind, "Language": lang, **extra}


EPISODES = [
    {"ParentIndexNumber": 1, "IndexNumber": 1, "Name": "Pilot", "LocationType": "FileSystem", "MediaStreams": [_stream("Audio", "jpn"), _stream("Subtitle", "eng")]},
    {"ParentIndexNumber": 1, "IndexNumber": 2, "Name": "Two", "LocationType": "FileSystem", "MediaStreams": [_stream("Audio", "jpn"), _stream("Subtitle", "eng")]},
    {"ParentIndexNumber": 1, "IndexNumber": 4, "Name": "Four", "LocationType": "FileSystem", "MediaStreams": [_stream("Audio", "jpn"), _stream("Audio", "eng"), _stream("Subtitle", "eng")]},
    {"ParentIndexNumber": 2, "IndexNumber": 1, "IndexNumberEnd": 2, "Name": "Double", "LocationType": "FileSystem", "MediaStreams": [_stream("Audio", None)]},
    {"ParentIndexNumber": 0, "IndexNumber": 1, "Name": "Special", "LocationType": "FileSystem", "MediaStreams": []},
    # Metadata-only (virtual) episodes: aired but not downloaded, and upcoming.
    {"ParentIndexNumber": 2, "IndexNumber": 3, "Name": "Aired", "LocationType": "Virtual", "PremiereDate": "2020-01-01T00:00:00Z"},
    {"ParentIndexNumber": 2, "IndexNumber": 4, "Name": "Future", "LocationType": "Virtual", "PremiereDate": "2999-01-01T00:00:00Z"},
]

MOVIE_FULL = {
    "Id": "m1", "Name": "Neutral Movie", "Type": "Movie", "ProductionYear": 2020, "Path": "/media1/movies/Neutral Movie (2020)/Neutral Movie (2020).mkv",
    "RunTimeTicks": 72_000_000_000,
    "MediaSources": [{
        "Path": "/media1/movies/Neutral Movie (2020)/Neutral Movie (2020).mkv", "Size": 4 * 1024**3, "Container": "mkv", "Name": "1080p",
        "MediaStreams": [
            _stream("Video", None, Width=1920, Height=1080, Codec="hevc"),
            _stream("Audio", "eng", DisplayTitle="English - AAC - 5.1"),
            _stream("Subtitle", "eng"), _stream("Subtitle", "spa"),
        ],
    }],
}


def _patch(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_api_get(self, path, params=None):
        params = params or {}
        calls.append({"path": path, "params": params})
        if path == "/Items" and params.get("Ids") == "m1":
            return {"Items": [MOVIE_FULL]}
        if path == "/Items" and params.get("IncludeItemTypes") == "Season":
            return {"Items": [
                {"SeriesId": "s1", "IndexNumber": 1, "ChildCount": 3},
                {"SeriesId": "s1", "IndexNumber": 2, "ChildCount": 2},
                {"SeriesId": "s1", "IndexNumber": 0, "ChildCount": 1},
            ]}
        if path == "/Items":
            return {"Items": [
                {"Name": "Neutral Show", "Type": "Series", "Id": "s1", "Status": "Continuing", "Path": "/media1/series/Neutral Show"},
                {"Name": "Other Thing", "Type": "Series", "Id": "s2", "Status": "Ended"},
                {"Name": "Neutral Movie", "Type": "Movie", "Id": "m1", "ProductionYear": 2020, "Path": MOVIE_FULL["Path"]},
            ]}
        assert path == "/Shows/s1/Episodes"
        assert "IsMissing" not in params  # virtual episodes come back in the same call
        return {"Items": EPISODES}

    async def fake_user(self):
        return "u1"

    async def fake_lib(self, name):
        return {"name": name, "id": "lib-1"}

    monkeypatch.setattr(JellyfinClient, "_api_get", fake_api_get)
    monkeypatch.setattr(JellyfinClient, "_get_user_id", fake_user)
    monkeypatch.setattr(JellyfinClient, "_resolve_library", fake_lib)
    return calls


def _client() -> JellyfinClient:
    return JellyfinClient("http://jellyfin.local:8096", "secret", "Movies", "Shows")


def test_compact_ranges() -> None:
    assert _compact_ranges([1, 2, 3, 5, 7, 8]) == "1-3, 5, 7-8"
    assert _compact_ranges([]) == ""


def test_series_details_per_season_breakdown(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(_client().get_item_details("Shows", "neutral shwo"))

    assert result["type"] == "series"
    assert result["name"] == "Neutral Show"
    assert result["season_count"] == 2  # specials excluded
    assert result["episode_count"] == 5  # 3 + 2 (double episode spans two); virtual excluded
    s0, s1, s2 = result["seasons"]
    assert s0["specials"] is True
    assert s1["episode_numbers"] == "1-2, 4"
    assert s1["missing_episodes"] == "3"
    assert s1["audio_languages"] == ["eng", "jpn"]
    assert s1["subtitle_languages"] == ["eng"]
    assert s1["language_groups"] == [
        {"episodes": "1-2", "audio_languages": ["jpn"], "subtitle_languages": ["eng"]},
        {"episodes": "4", "audio_languages": ["eng", "jpn"], "subtitle_languages": ["eng"]},
    ]
    assert "episode_list" not in s1
    assert "aired_not_downloaded" not in s1
    assert s2["episode_numbers"] == "1-2"
    assert s2["audio_languages"] == ["und"]
    assert "language_groups" not in s2


def test_series_details_reports_aired_and_upcoming_virtual_episodes(monkeypatch) -> None:
    _patch(monkeypatch)
    s2 = asyncio.run(_client().get_item_details("Shows", "Neutral Show"))["seasons"][2]
    assert s2["aired_not_downloaded"] == "3"
    assert s2["upcoming"] == [{"episode": 4, "title": "Future", "air_date": "2999-01-01"}]
    assert s2["episodes"] == 2  # virtual episodes never count as on disk


def test_series_details_season_filter_lists_episodes(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(_client().get_item_details("Shows", "Neutral Show", season=1))

    assert [s["season"] for s in result["seasons"]] == [1]
    eps = result["seasons"][0]["episode_list"]
    assert [e["episode"] for e in eps] == [1, 2, 4]
    assert eps[2] == {"episode": 4, "title": "Four", "audio_languages": ["eng", "jpn"], "subtitle_languages": ["eng"]}


def test_series_details_missing_season_and_no_match(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(_client().get_item_details("Shows", "Neutral Show", season=9))
    assert result["seasons"] == []
    assert "available seasons: [0, 1, 2]" in result["message"]

    try:
        asyncio.run(_client().get_item_details("Shows", "zzzz qqqq"))
    except ValueError as exc:
        assert "No movie or series matching" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_movie_details_lists_versions_and_languages(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(_client().get_item_details("Movies", "Neutral Movie"))

    assert result["type"] == "movie"
    assert result["year"] == 2020
    assert result["runtime_minutes"] == 120
    (version,) = result["versions"]
    assert version == {
        "path": MOVIE_FULL["Path"],
        "size_gb": 4.0,
        "container": "mkv",
        "resolution": "1920x1080",
        "video_codec": "hevc",
        "audio_tracks": ["English - AAC - 5.1"],
        "audio_languages": ["eng"],
        "subtitle_languages": ["eng", "spa"],
    }


def test_library_items_stays_compact_and_batches_season_counts(monkeypatch) -> None:
    calls = _patch(monkeypatch)
    result = asyncio.run(_client().list_library_items("Shows", limit=10))

    by_name = {i["name"]: i for i in result["items"]}
    show = by_name["Neutral Show"]
    assert set(show) == {"name", "type", "ongoing", "path", "season_count", "episode_count"}
    assert (show["season_count"], show["episode_count"]) == (2, 5)  # season 0 excluded
    assert (by_name["Other Thing"]["season_count"], by_name["Other Thing"]["episode_count"]) == (0, 0)
    assert set(by_name["Neutral Movie"]) == {"name", "type", "year", "path"}
    # One list call + one library-wide Season call, never one call per series.
    assert len(calls) == 2
    assert not any(c["path"].startswith("/Shows/") for c in calls)
    assert "MediaStreams" not in calls[0]["params"]["Fields"]


def test_resolve_tool_name_routes_aliases_and_release_tracker_modes() -> None:
    assert _resolve_tool_name("jellyfin_library_items", {}) == "get jellyfin library items"
    assert _resolve_tool_name("get jellyfin library items", {}) == "get jellyfin library items"
    assert _resolve_tool_name("release_tracker_lookup", {"seriesName": "X"}) == "get ongoing series next release"
    assert _resolve_tool_name("release_tracker_lookup", {"dueOnly": True}) == "get due ongoing series releases"
    assert _resolve_tool_name("release_tracker_lookup", {}) == "get ongoing series next releases"
    assert _resolve_tool_name("release_tracker_update", {}) == "store ongoing series next release"
    assert _resolve_tool_name("release_tracker_update", {"action": "delete"}) == "delete ongoing series next release"


def _call(client: TestClient, name: str, arguments: dict) -> dict:
    return client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments},
    }).json()


def test_mcp_item_details_tool(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr("app.main.JellyfinClient.from_env", lambda: _client())

    with TestClient(app) as client:
        payload = json.loads(_call(client, "jellyfin_item_details", {"libraryName": "Shows", "name": "Neutral Show", "season": "1"})["result"]["content"][0]["text"])
        assert payload["seasons"][0]["episode_list"][0]["title"] == "Pilot"

        # Legacy name + legacy seriesName argument still work.
        legacy = json.loads(_call(client, "get jellyfin series details", {"libraryName": "Shows", "seriesName": "Neutral Show"})["result"]["content"][0]["text"])
        assert legacy["name"] == "Neutral Show"

        bad = _call(client, "jellyfin_item_details", {"libraryName": "Shows"})
        assert bad["result"]["isError"] is True
        assert "name are required" in json.loads(bad["result"]["content"][0]["text"])["error"]


def test_tool_failures_are_is_error_results_but_unknown_tool_is_protocol_error() -> None:
    with TestClient(app) as client:
        bad_action = _call(client, "release_tracker_update", {"action": "nope", "libraryName": "Shows", "seriesName": "X"})
        assert bad_action["result"]["isError"] is True
        assert "store' or 'delete" in json.loads(bad_action["result"]["content"][0]["text"])["error"]

        unknown = _call(client, "no_such_tool", {})
        assert unknown["error"]["code"] == -32601


def test_release_tracker_merged_tools_round_trip(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.services.release_tracker.DEFAULT_RELEASE_TRACKER_PATH", tmp_path / "ongoing_releases.json")
    with TestClient(app) as client:
        stored = _call(client, "release_tracker_update", {"libraryName": "Shows", "seriesName": "Neutral Show", "nextReleaseDate": "2000-01-01"})
        assert stored["result"]["isError"] is False

        one = json.loads(_call(client, "release_tracker_lookup", {"libraryName": "Shows", "seriesName": "Neutral Show"})["result"]["content"][0]["text"])
        assert one["found"] is True
        due = json.loads(_call(client, "release_tracker_lookup", {"dueOnly": True})["result"]["content"][0]["text"])
        assert any(r["seriesName"] == "Neutral Show" for r in due["items"])

        deleted = json.loads(_call(client, "release_tracker_update", {"action": "delete", "libraryName": "Shows", "seriesName": "Neutral Show"})["result"]["content"][0]["text"])
        assert deleted["deleted"] is True
        gone = json.loads(_call(client, "release_tracker_lookup", {"libraryName": "Shows", "seriesName": "Neutral Show"})["result"]["content"][0]["text"])
        assert gone["found"] is False


def test_initialize_negotiates_protocol_version() -> None:
    with TestClient(app) as client:
        def version(requested):
            params = {"protocolVersion": requested} if requested else {}
            return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}).json()["result"]["protocolVersion"]

        assert version("2025-06-18") == "2025-06-18"
        assert version("2025-03-26") == "2025-03-26"
        assert version("1999-01-01") == "2024-11-05"
        assert version(None) == "2024-11-05"


def test_activity_log_marks_is_error_results_as_failures() -> None:
    request = json.dumps({"method": "tools/call", "params": {"name": "jellyfin_library_items", "arguments": {}}}).encode()
    response = json.dumps({"result": {"isError": True, "content": [{"type": "text", "text": json.dumps({"error": "libraryName is required"})}]}}).encode()
    line = _format_mcp_activity_line(request, response, 5, 200, "unknown")
    assert "❌" in line and "libraryName is required" in line
