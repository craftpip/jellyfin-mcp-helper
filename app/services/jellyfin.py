from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

import httpx

logger = logging.getLogger(__name__)


ONGOING_STATUSES = {"continuing", "returning series", "in production"}


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str, movie_library: str | None, series_library: str | None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._movie_library = (movie_library or "").strip() or None
        self._series_library = (series_library or "").strip() or None

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f'MediaBrowser Token="{self._api_key}"'}

    @classmethod
    def from_env(cls) -> "JellyfinClient | None":

        from app.core.config import get_settings

        settings = get_settings()

        def _get(key: str, attr: str, default: str | None = None) -> str | None:
            if key in os.environ:
                return os.getenv(key)
            return getattr(settings, attr, default)

        enable_raw = _get("ENABLE_JELLYFIN_INTEGRATION", "enable_jellyfin_integration", "true")
        enable_jellyfin = str(enable_raw).strip().lower() in ("true", "1", "yes")
        if not enable_jellyfin:
            return None
        
        api_key = (_get("JELLYFIN_API_KEY", "jellyfin_api_key", "") or "").strip()
        if not api_key:
            return None
        base_url = (_get("JELLYFIN_BASE_URL", "jellyfin_base_url", "http://host.docker.internal:8096") or "").strip()
        return cls(
            base_url=base_url,
            api_key=api_key,
            movie_library=_get("JELLYFIN_MOVIE_LIBRARY_NAME", "jellyfin_movie_library_name"),
            series_library=_get("JELLYFIN_SERIES_LIBRARY_NAME", "jellyfin_series_library_name"),
        )

    def library_name_for_kind(self, kind: str) -> str | None:
        if kind == "movie":
            return self._movie_library
        if kind == "series":
            return self._series_library
        return None

    async def list_libraries(self) -> list[dict]:
        """Returns all available Jellyfin libraries."""
        libraries = await self._api_get("/Library/VirtualFolders")
        return [{"name": item.get("Name", ""), "id": item.get("ItemId", "")} for item in libraries]

    async def libraries_for_paths(self, target_paths: list[str], movie_roots: list[str], series_roots: list[str]) -> list[dict]:
        """Find Jellyfin libraries that contain the given target paths by folder name.

        Jellyfin's VirtualFolders use host paths like /mnt/media1t/downloads/series-r
        while JellySort uses container paths like /media1/series-r. Only the final
        folder name (e.g. 'series-r') is compared, as the user noted.
        """
        if not target_paths:
            return []
        try:
            virtual = await self._api_get("/Library/VirtualFolders")
        except Exception:
            return []
        # Build folder-name -> library map from Jellyfin's Locations
        folder_to_lib: dict[str, dict] = {}
        for lib in virtual:
            name = lib.get("Name", "")
            lib_id = lib.get("ItemId", "")
            locations = lib.get("Locations") or []
            for loc in locations:
                # Host path last component e.g. 'series-r' from '/mnt/.../series-r'
                folder = loc.rstrip("/").split("/")[-1].lower()
                if folder:
                    folder_to_lib[folder] = {"name": name, "id": lib_id}
        # For each target path, find which configured root it belongs to
        found: dict[str, dict] = {}
        all_roots = [(p.rstrip("/"), p.rstrip("/").split("/")[-1].lower()) for p in (movie_roots + series_roots) if p]
        for tpath in target_paths:
            tpath_norm = tpath.rstrip("/").lower()
            # Find the longest matching root prefix
            best_folder = None
            best_len = -1
            for root_path, folder in all_roots:
                if tpath_norm == root_path.lower() or tpath_norm.startswith(root_path.lower() + "/"):
                    if len(root_path) > best_len:
                        best_len = len(root_path)
                        best_folder = folder
            if best_folder and best_folder in folder_to_lib:
                lib = folder_to_lib[best_folder]
                found[lib["id"]] = lib
        return list(found.values())

    async def scan_library(
        self,
        library_name: str,
        item_ids: list[str] | None = None,
        item_names: list[str] | None = None,
        recursive: bool = True,
        metadata_refresh_mode: str = "Default",
        image_refresh_mode: str = "Default",
        replace_all_metadata: bool = False,
        replace_all_images: bool = False,
    ) -> dict:
        target = await self._resolve_library(library_name)
        resolved_ids: list[str] = []
        scanned_names: list[str] = []
        not_found: list[str] = []

        if item_ids:
            resolved_ids.extend(item_ids)

        if item_names:
            user_id = await self._get_user_id()
            for name in item_names:
                params: dict[str, str] = {
                    "ParentId": target["id"],
                    "Recursive": "true",
                    "SearchTerm": name,
                    "IncludeItemTypes": "Series,Movie",
                    "Limit": "10",
                    "UserId": user_id,
                }
                data = await self._api_get("/Items", params)
                items = data.get("Items", [])
                if items:
                    resolved_ids.append(items[0]["Id"])
                    scanned_names.append(items[0].get("Name", name))
                else:
                    not_found.append(name)

        refresh_params = {
            "Recursive": str(recursive).lower(),
            "MetadataRefreshMode": metadata_refresh_mode,
            "ImageRefreshMode": image_refresh_mode,
            "ReplaceAllMetadata": str(replace_all_metadata).lower(),
            "ReplaceAllImages": str(replace_all_images).lower(),
        }

        async with httpx.AsyncClient(timeout=120) as httpx_client:
            if resolved_ids:
                async def _refresh_one(item_id: str) -> None:
                    r = await httpx_client.post(
                        f"{self._base_url}/Items/{item_id}/Refresh",
                        params=refresh_params,
                        headers=self._auth_headers,
                    )
                    r.raise_for_status()

                await asyncio.gather(*[_refresh_one(iid) for iid in resolved_ids])
            else:
                response = await httpx_client.post(
                    f"{self._base_url}/Items/{target['id']}/Refresh",
                    params=refresh_params,
                    headers=self._auth_headers,
                )
                response.raise_for_status()

        result: dict = {"name": target["name"], "id": target["id"]}
        if scanned_names:
            result["scanned_items"] = scanned_names
        elif item_ids and not scanned_names:
            result["scanned_items"] = item_ids
        if not_found:
            result["not_found"] = not_found
        return result

    async def notify_media_updated(self, paths: list[str]) -> dict:
        unique_paths = [path for path in dict.fromkeys(path.strip() for path in paths) if path]
        if not unique_paths:
            return {"updated_paths": []}

        payload = {"updates": [{"path": path} for path in unique_paths]}
        async with httpx.AsyncClient(timeout=120) as httpx_client:
            response = await httpx_client.post(
                f"{self._base_url}/Library/Media/Updated",
                json=payload,
                headers=self._auth_headers,
            )
            response.raise_for_status()

        return {"updated_paths": unique_paths}

    async def _resolve_library(self, library_name: str) -> dict:
        libraries = await self.list_libraries()
        needle = library_name.strip().lower()
        exact = [item for item in libraries if str(item.get("name", "")).strip().lower() == needle]
        if len(exact) == 1:
            return {"name": exact[0].get("name", ""), "id": exact[0].get("id", "")}
        contains = [item for item in libraries if needle in str(item.get("name", "")).strip().lower()]
        if len(contains) == 1:
            return {"name": contains[0].get("name", ""), "id": contains[0].get("id", "")}
        if not contains:
            raise ValueError(f"Jellyfin library not found: {library_name}")
        names = ", ".join(str(item.get("name", "")) for item in contains)
        raise ValueError(f"Ambiguous Jellyfin library name '{library_name}': {names}")

    async def _api_get(self, path: str, params: dict[str, str] | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self._base_url}{path}",
                params=params,
                headers=self._auth_headers,
            )
            response.raise_for_status()
        return response.json()

    async def _get_user_id(self) -> str:
        users = await self._api_get("/Users")
        if not isinstance(users, list) or len(users) == 0:
            raise ValueError("Could not resolve Jellyfin user for item queries")

        for user in users:
            uid = user.get("Id")
            if uid and (user.get("Policy") or {}).get("EnableAllFolders"):
                return uid

        uid = users[0].get("Id")
        if uid:
            return uid
        raise ValueError("Could not resolve Jellyfin user for item queries")

    @staticmethod
    def _fuzzy_score(query: str, name: str) -> float:
        q = query.lower().strip()
        n = name.lower().strip()

        if not q or not n:
            return 0.0

        if q == n:
            return 1.0

        if q in n or n in q:
            return 0.85 + 0.15 * (min(len(q), len(n)) / max(len(q), len(n)))

        q_tokens = set(re.findall(r"\w+", q))
        n_tokens = set(re.findall(r"\w+", n))
        overlap = len(q_tokens & n_tokens) / max(len(q_tokens), 1) if q_tokens else 0.0

        seq_ratio = SequenceMatcher(None, q, n).ratio()

        return (overlap * 0.45) + (seq_ratio * 0.55)

    async def list_library_items(
        self,
        library_name: str,
        search: str | None = None,
        limit: int = 10,
        ongoing_only: bool = False,
        hours: float | None = None,
    ) -> dict:
        """Compact list of movies and series, most recently added first.

        Deliberately small: no languages, no per-season data. Use
        ``get_item_details`` for one item's episodes, files and languages.
        Series totals come from one library-wide Season query instead of
        one ``/Shows/{id}/Seasons`` call per series.
        """
        library = await self._resolve_library(library_name)
        user_id = await self._get_user_id()

        fetch_limit = 5000 if search else limit

        params: dict[str, str] = {
            "ParentId": library["id"],
            "Recursive": "true",
            "IncludeItemTypes": "Series,Movie",
            "Fields": "ProductionYear,EndDate,Status,Path,DateCreated",
            "Limit": str(fetch_limit),
            "UserId": user_id,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
        }

        data = await self._api_get("/Items", params)
        items = data.get("Items", [])
        if hours is not None and hours > 0:
            from datetime import datetime, timedelta, timezone

            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            items = [
                item
                for item in items
                if (created := item.get("DateCreated"))
                and datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc) >= cutoff
            ]

        selected: list[tuple[dict, float]] = []
        for item in items:
            item_type = item.get("Type", "").lower()
            if item_type not in ("movie", "series"):
                continue
            score = 0.0
            if search:
                score = self._fuzzy_score(search, item.get("Name", ""))
                if score < 0.3:
                    continue
            if ongoing_only and (item_type != "series" or not self._is_ongoing_series(item)):
                continue
            selected.append((item, score))

        if search:
            selected.sort(key=lambda pair: pair[1], reverse=True)
            selected = selected[:limit]

        season_totals: dict[str, tuple[int, int]] = {}
        if any(it.get("Type", "").lower() == "series" for it, _ in selected):
            try:
                season_totals = await self._library_season_totals(library["id"], user_id)
            except Exception as exc:
                logger.warning("Failed to fetch season totals for library %s: %s", library_name, exc)

        result_items: list[dict] = []
        for item, _score in selected:
            item_name = item.get("Name", "")
            if item.get("Type", "").lower() == "movie":
                result_items.append({
                    "name": item_name,
                    "type": "movie",
                    "year": item.get("ProductionYear"),
                    "path": item.get("Path") or "",
                })
            else:
                seasons, episodes = season_totals.get(item.get("Id"), (0, 0))
                result_items.append({
                    "name": item_name,
                    "type": "series",
                    "ongoing": self._is_ongoing_series(item),
                    "path": item.get("Path") or "",
                    "season_count": seasons,
                    "episode_count": episodes,
                })

        return {
            "library_name": library_name,
            "returned_items": len(result_items),
            "search": search,
            "ongoing_only": ongoing_only,
            "items": result_items,
        }

    async def _library_season_totals(self, library_id: str, user_id: str) -> dict[str, tuple[int, int]]:
        """``{series_id: (season_count, episode_count)}`` for a whole library in one call.

        Specials (season 0) and
        unnumbered seasons are excluded; episode count is the sum of
        season ``ChildCount``.
        """
        data = await self._api_get("/Items", {
            "ParentId": library_id,
            "Recursive": "true",
            "IncludeItemTypes": "Season",
            "Fields": "ChildCount",
            "UserId": user_id,
        })
        totals: dict[str, tuple[int, int]] = {}
        for season in data.get("Items", []):
            series_id = season.get("SeriesId")
            if not series_id or season.get("IndexNumber") in (None, 0):
                continue
            seasons, episodes = totals.get(series_id, (0, 0))
            totals[series_id] = (seasons + 1, episodes + (season.get("ChildCount") or 0))
        return totals

    async def get_item_details(
        self,
        library_name: str,
        name: str,
        season: int | None = None,
    ) -> dict:
        """Detailed view of ONE movie or series (best fuzzy name match).

        Series: per season the episode numbers present, gaps, aired-but-not-
        downloaded and upcoming episodes (when Jellyfin has that metadata),
        audio/subtitle languages and which episodes have which set. With
        ``season``, only that season plus one row per episode.

        Movie: year, runtime and each file/version with size, container,
        resolution, video codec, audio tracks and subtitle languages.
        """
        library = await self._resolve_library(library_name)
        user_id = await self._get_user_id()
        data = await self._api_get("/Items", {
            "ParentId": library["id"],
            "Recursive": "true",
            "IncludeItemTypes": "Series,Movie",
            "Fields": "Path,Status,EndDate,ProductionYear",
            "UserId": user_id,
        })
        scored = sorted(
            ((self._fuzzy_score(name, it.get("Name", "")), it) for it in data.get("Items", [])),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scored or scored[0][0] < 0.3:
            raise ValueError(f"No movie or series matching '{name}' in library '{library_name}'")
        best = scored[0][1]
        others = [it.get("Name", "") for sc, it in scored[1:4] if sc >= 0.5]

        if best.get("Type", "").lower() == "movie":
            result = await self._movie_details(best, user_id)
        else:
            details = await self._get_series_episodes(best["Id"], user_id, episode_detail_season=season)
            seasons = details["seasons"]
            if season is not None:
                seasons = [s for s in seasons if s["season"] == season]
            result = {
                "type": "series",
                "name": best.get("Name", ""),
                "path": best.get("Path") or "",
                "ongoing": self._is_ongoing_series(best),
                "season_count": details["total_seasons"],
                "episode_count": details["total_episodes"],
                "seasons": seasons,
            }
            if season is not None and not seasons:
                available = [s["season"] for s in details["seasons"]]
                result["message"] = f"Season {season} not found; available seasons: {available}"
        result = {"library_name": library_name, **result}
        if others:
            result["other_matches"] = others
        return result

    async def _movie_details(self, movie: dict, user_id: str) -> dict:
        data = await self._api_get("/Items", {
            "Ids": movie["Id"],
            "Fields": "MediaSources,Path,ProductionYear",
            "UserId": user_id,
        })
        full = (data.get("Items") or [movie])[0]
        versions = []
        for src in full.get("MediaSources") or []:
            streams = src.get("MediaStreams") or []
            video = next((s for s in streams if s.get("Type") == "Video"), {})
            version: dict = {
                "path": src.get("Path") or "",
                "size_gb": round((src.get("Size") or 0) / 1024**3, 2),
                "container": src.get("Container"),
            }
            if src.get("Name") and len(full.get("MediaSources") or []) > 1:
                version["version"] = src["Name"]
            if video:
                if video.get("Width") and video.get("Height"):
                    version["resolution"] = f"{video['Width']}x{video['Height']}"
                version["video_codec"] = video.get("Codec")
            version["audio_tracks"] = [
                s.get("DisplayTitle") or (s.get("Language") or "und")
                for s in streams if s.get("Type") == "Audio"
            ]
            version["audio_languages"] = _stream_languages(streams, "Audio")
            version["subtitle_languages"] = _stream_languages(streams, "Subtitle")
            versions.append(version)
        ticks = full.get("RunTimeTicks") or movie.get("RunTimeTicks")
        result: dict = {
            "type": "movie",
            "name": full.get("Name") or movie.get("Name", ""),
            "year": full.get("ProductionYear") or movie.get("ProductionYear"),
            "path": full.get("Path") or movie.get("Path") or "",
        }
        if ticks:
            result["runtime_minutes"] = round(ticks / 600_000_000)
        result["versions"] = versions
        return result

    async def recently_added_items(
        self,
        library_name: str,
        hours: float = 72,
        limit: int = 10,
    ) -> dict:
        """List the individual episode and movie files most recently added to a library."""
        from datetime import datetime, timedelta, timezone

        library = await self._resolve_library(library_name)
        user_id = await self._get_user_id()

        params: dict[str, str] = {
            "ParentId": library["id"],
            "Recursive": "true",
            "IncludeItemTypes": "Episode,Movie",
            "Fields": "SeriesName,SeasonName,IndexNumber,ParentIndexNumber,Path,DateCreated,ProductionYear,MediaStreams",
            "Limit": str(500),
            "UserId": user_id,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
        }

        data = await self._api_get("/Items", params)
        items = data.get("Items", [])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result_items: list[dict] = []

        for item in items:
            created_raw = item.get("DateCreated")
            if created_raw:
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
                if created < cutoff:
                    continue
            else:
                created = None

            item_type = item.get("Type", "").lower()
            streams = item.get("MediaStreams") or []
            if item_type == "episode":
                season = item.get("ParentIndexNumber")
                episode = item.get("IndexNumber")
                label = ""
                if season is not None and episode is not None:
                    label = f"S{int(season):02d}E{int(episode):02d}"
                entry = {
                    "type": "episode",
                    "name": item.get("Name", ""),
                    "series": item.get("SeriesName", ""),
                    "season": season,
                    "episode": episode,
                    "label": label,
                    "path": item.get("Path") or "",
                }
            else:
                entry = {
                    "type": "movie",
                    "name": item.get("Name", ""),
                    "year": item.get("ProductionYear"),
                    "path": item.get("Path") or "",
                    "audio_languages": sorted(set(s.get("Language") or "und" for s in streams if s.get("Type") == "Audio")),
                    "subtitle_languages": sorted(set(s.get("Language") or "und" for s in streams if s.get("Type") == "Subtitle")),
                }
            entry["addedAt"] = created.isoformat() if created else None
            result_items.append(entry)

        result_items = result_items[:limit]
        return {
            "library_name": library_name,
            "returned_items": len(result_items),
            "hours": hours,
            "cutoffUtc": cutoff.isoformat(),
            "items": result_items,
        }

    async def list_ongoing_series_latest_episodes(
        self,
        library_name: str,
        search: str | None = None,
        limit: int = 10,
    ) -> dict:
        normalized_search = None if search in (None, "", "all") else search
        library = await self._resolve_library(library_name)
        user_id = await self._get_user_id()

        params: dict[str, str] = {
            "ParentId": library["id"],
            "Recursive": "true",
            "IncludeItemTypes": "Series",
            "Fields": "EndDate,Status",
            "Limit": str(limit),
            "UserId": user_id,
            "SortBy": "ProductionYear,SortName",
            "SortOrder": "Descending",
        }
        if normalized_search:
            params["SearchTerm"] = normalized_search

        data = await self._api_get("/Items", params)
        items = data.get("Items", [])
        result_items: list[dict] = []

        for item in items:
            if not self._is_ongoing_series(item):
                continue

            latest_episode = await self._get_latest_episode(item.get("Id", ""), user_id)
            result_items.append(
                {
                    "seriesId": item.get("Id", ""),
                    "name": item.get("Name", ""),
                    "type": "series",
                    "ongoing": True,
                    "latest_episode": latest_episode,
                }
            )

        return {
            "library_name": library_name,
            "returned_items": len(result_items),
            "search": normalized_search,
            "items": result_items,
        }

    @staticmethod
    def _is_ongoing_series(item: dict) -> bool:
        status = str(item.get("Status", "")).strip().lower()
        if status in ONGOING_STATUSES:
            return True

        end_date = item.get("EndDate")
        if not end_date:
            return True

        try:
            parsed_end_date = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
        except ValueError:
            return False

        return parsed_end_date >= datetime.now(UTC)

    async def _get_series_episodes(
        self, series_id: str, user_id: str, episode_detail_season: int | None = None
    ) -> dict:
        """Per-season breakdown built from the episodes actually on disk.

        Each season lists its episode numbers (compacted to ranges like
        ``"1-12, 14"``), the gaps between 1 and the highest episode, and the
        audio/subtitle languages. When episodes in a season differ in
        languages, ``language_groups`` says which episodes have which set.
        ``episode_detail_season`` additionally returns one row per episode
        (number, title, languages) for that season.
        """
        params: dict[str, str] = {
            "UserId": user_id,
            "Fields": "IndexNumber,ParentIndexNumber,MediaStreams,PremiereDate",
        }
        data = await self._api_get(f"/Shows/{series_id}/Episodes", params)

        now = datetime.now(UTC)
        seasons: dict[int, list[dict]] = {}
        # Virtual (metadata-only) episodes: aired but not on disk, or upcoming.
        # Jellyfin only has these when missing-episode metadata is available.
        not_downloaded: dict[int, set[int]] = {}
        upcoming: dict[int, list[dict]] = {}
        for ep in data.get("Items", []):
            season_number = ep.get("ParentIndexNumber")
            if season_number is None:
                continue
            if ep.get("LocationType") == "Virtual" or ep.get("IsMissing"):
                number = ep.get("IndexNumber")
                if number is None:
                    continue
                premiere = _parse_jf_date(ep.get("PremiereDate"))
                if premiere is not None and premiere > now:
                    upcoming.setdefault(season_number, []).append(
                        {"episode": number, "title": ep.get("Name", ""), "air_date": premiere.date().isoformat()}
                    )
                else:
                    not_downloaded.setdefault(season_number, set()).add(number)
                continue
            streams = ep.get("MediaStreams") or []
            seasons.setdefault(season_number, []).append({
                "start": ep.get("IndexNumber"),
                "end": ep.get("IndexNumberEnd"),
                "title": ep.get("Name", ""),
                "audio": _stream_languages(streams, "Audio"),
                "subs": _stream_languages(streams, "Subtitle"),
            })

        season_list: list[dict] = []
        total_episodes = 0
        for season_number in sorted(set(seasons) | set(not_downloaded) | set(upcoming)):
            eps = seasons.get(season_number, [])
            numbers: set[int] = set()
            groups: dict[tuple[tuple[str, ...], tuple[str, ...]], set[int]] = {}
            audio_all: set[str] = set()
            subs_all: set[str] = set()
            for ep in eps:
                audio_all.update(ep["audio"])
                subs_all.update(ep["subs"])
                if ep["start"] is None:
                    continue
                span = range(ep["start"], max(ep["start"], ep["end"] or ep["start"]) + 1)
                numbers.update(span)
                groups.setdefault((tuple(ep["audio"]), tuple(ep["subs"])), set()).update(span)

            ordered = sorted(numbers)
            count = len(ordered) + sum(1 for ep in eps if ep["start"] is None)
            entry: dict = {
                "season": season_number,
                "episodes": count,
                "episode_numbers": _compact_ranges(ordered),
                "audio_languages": sorted(audio_all),
                "subtitle_languages": sorted(subs_all),
            }
            if ordered:
                missing = sorted(set(range(1, ordered[-1] + 1)) - numbers)
                if missing:
                    entry["missing_episodes"] = _compact_ranges(missing)
            aired = sorted(not_downloaded.get(season_number, set()) - numbers)
            if aired:
                entry["aired_not_downloaded"] = _compact_ranges(aired)
            if upcoming.get(season_number):
                entry["upcoming"] = sorted(upcoming[season_number], key=lambda e: e["episode"])
            if len(groups) > 1:
                entry["language_groups"] = [
                    {
                        "episodes": _compact_ranges(sorted(nums)),
                        "audio_languages": list(audio),
                        "subtitle_languages": list(subs),
                    }
                    for (audio, subs), nums in sorted(groups.items(), key=lambda g: min(g[1]))
                ]
            if season_number == episode_detail_season:
                entry["episode_list"] = [
                    {
                        "episode": ep["start"],
                        **({"episode_end": ep["end"]} if ep["end"] and ep["end"] != ep["start"] else {}),
                        "title": ep["title"],
                        "audio_languages": ep["audio"],
                        "subtitle_languages": ep["subs"],
                    }
                    for ep in sorted(eps, key=lambda e: (e["start"] is None, e["start"] or 0))
                ]
            if season_number == 0:
                entry["specials"] = True
            season_list.append(entry)
            if season_number != 0:
                total_episodes += count

        return {
            "total_seasons": sum(1 for s in season_list if s["season"] != 0),
            "total_episodes": total_episodes,
            "seasons": season_list,
        }

    async def _get_latest_episode(self, series_id: str, user_id: str) -> dict | None:
        params: dict[str, str] = {
            "UserId": user_id,
            "Fields": "IndexNumber,ParentIndexNumber",
            "IsMissing": "false",
        }
        data = await self._api_get(f"/Shows/{series_id}/Episodes", params)
        items = data.get("Items", [])
        if not items:
            return None

        def episode_key(item: dict) -> tuple[int, int]:
            season = item.get("ParentIndexNumber") or 0
            episode_number = item.get("IndexNumber") or 0
            return season, episode_number

        episode = max(items, key=episode_key)
        return {
            "season": episode.get("ParentIndexNumber"),
            "episode": episode.get("IndexNumber"),
            "title": episode.get("Name", ""),
        }


def _parse_jf_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _stream_languages(streams: list[dict], stream_type: str) -> list[str]:
    return sorted({s.get("Language") or "und" for s in streams if s.get("Type") == stream_type})


def _compact_ranges(numbers: list[int]) -> str:
    """Render sorted ints as ``"1-3, 5, 7-9"``."""
    parts: list[str] = []
    i = 0
    while i < len(numbers):
        j = i
        while j + 1 < len(numbers) and numbers[j + 1] == numbers[j] + 1:
            j += 1
        parts.append(str(numbers[i]) if i == j else f"{numbers[i]}-{numbers[j]}")
        i = j + 1
    return ", ".join(parts)
