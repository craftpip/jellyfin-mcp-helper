"""'get jellyfin series details' — per-season episodes, gaps and languages."""
import asyncio
import json

from fastapi.testclient import TestClient

from app.main import app
from app.services.jellyfin import JellyfinClient, _compact_ranges


def _stream(kind: str, lang: str | None) -> dict:
    return {"Type": kind, "Language": lang}


EPISODES = [
    {"ParentIndexNumber": 1, "IndexNumber": 1, "Name": "Pilot", "MediaStreams": [_stream("Audio", "jpn"), _stream("Subtitle", "eng")]},
    {"ParentIndexNumber": 1, "IndexNumber": 2, "Name": "Two", "MediaStreams": [_stream("Audio", "jpn"), _stream("Subtitle", "eng")]},
    {"ParentIndexNumber": 1, "IndexNumber": 4, "Name": "Four", "MediaStreams": [_stream("Audio", "jpn"), _stream("Audio", "eng"), _stream("Subtitle", "eng")]},
    {"ParentIndexNumber": 2, "IndexNumber": 1, "IndexNumberEnd": 2, "Name": "Double", "MediaStreams": [_stream("Audio", None)]},
    {"ParentIndexNumber": 0, "IndexNumber": 1, "Name": "Special", "MediaStreams": []},
]


def _patch(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_api_get(self, path, params=None):
        calls.append({"path": path, "params": params or {}})
        if path == "/Items":
            return {"Items": [
                {"Name": "Neutral Show", "Type": "Series", "Id": "s1", "Status": "Continuing", "Path": "/media1/series/Neutral Show"},
                {"Name": "Other Thing", "Type": "Series", "Id": "s2", "Status": "Ended"},
            ]}
        assert path == "/Shows/s1/Episodes"
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
    result = asyncio.run(_client().get_series_details("Shows", "neutral shwo"))

    assert result["name"] == "Neutral Show"
    assert result["season_count"] == 2  # specials excluded
    assert result["episode_count"] == 5  # 3 + 2 (double episode spans two)
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
    assert s2["episode_numbers"] == "1-2"
    assert s2["audio_languages"] == ["und"]
    assert "language_groups" not in s2


def test_series_details_season_filter_lists_episodes(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(_client().get_series_details("Shows", "Neutral Show", season=1))

    assert [s["season"] for s in result["seasons"]] == [1]
    eps = result["seasons"][0]["episode_list"]
    assert [e["episode"] for e in eps] == [1, 2, 4]
    assert eps[2] == {"episode": 4, "title": "Four", "audio_languages": ["eng", "jpn"], "subtitle_languages": ["eng"]}


def test_series_details_missing_season_and_no_match(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(_client().get_series_details("Shows", "Neutral Show", season=9))
    assert result["seasons"] == []
    assert "available seasons: [0, 1, 2]" in result["message"]

    try:
        asyncio.run(_client().get_series_details("Shows", "zzzz qqqq"))
    except ValueError as exc:
        assert "No series matching" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_library_items_stays_compact(monkeypatch) -> None:
    calls = _patch(monkeypatch)

    async def fake_seasons(self, series_id, user_id):
        return {"total_seasons": 2, "total_episodes": 5, "seasons": [{"season": 1, "episodes": 3}]}

    monkeypatch.setattr(JellyfinClient, "_get_series_seasons", fake_seasons)
    result = asyncio.run(_client().list_library_items("Shows", limit=1))
    series = result["items"][0]
    assert set(series) == {"name", "type", "ongoing", "path", "season_count", "episode_count"}
    assert not any(c["path"].endswith("/Episodes") for c in calls)


def test_mcp_series_details_tool(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr("app.main.JellyfinClient.from_env", lambda: _client())

    with TestClient(app) as client:
        tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
        assert "get jellyfin series details" in [t["name"] for t in tools["result"]["tools"]]

        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get jellyfin series details",
                       "arguments": {"libraryName": "Shows", "seriesName": "Neutral Show", "season": "1"}},
        })
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload["seasons"][0]["episode_list"][0]["title"] == "Pilot"

        bad = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get jellyfin series details", "arguments": {"libraryName": "Shows"}},
        })
        assert bad.json()["error"]["code"] == -32602
