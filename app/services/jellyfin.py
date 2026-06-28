from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import httpx


ONGOING_STATUSES = {"continuing", "returning series", "in production"}


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str, movie_library: str | None, series_library: str | None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._movie_library = (movie_library or "").strip() or None
        self._series_library = (series_library or "").strip() or None

    @classmethod
    def from_env(cls) -> "JellyfinClient | None":
        enable_jellyfin = os.getenv("ENABLE_JELLYFIN_INTEGRATION", "true").strip().lower() in ("true", "1", "yes")
        if not enable_jellyfin:
            return None
        
        api_key = os.getenv("JELLYFIN_API_KEY", "").strip()
        if not api_key:
            return None
        base_url = os.getenv("JELLYFIN_BASE_URL", "http://host.docker.internal:8096").strip()
        return cls(
            base_url=base_url,
            api_key=api_key,
            movie_library=os.getenv("JELLYFIN_MOVIE_LIBRARY_NAME"),
            series_library=os.getenv("JELLYFIN_SERIES_LIBRARY_NAME"),
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
                        headers={"X-Emby-Token": self._api_key},
                    )
                    r.raise_for_status()

                await asyncio.gather(*[_refresh_one(iid) for iid in resolved_ids])
            else:
                response = await httpx_client.post(
                    f"{self._base_url}/Items/{target['id']}/Refresh",
                    params=refresh_params,
                    headers={"X-Emby-Token": self._api_key},
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
                headers={"X-Emby-Token": self._api_key},
            )
            response.raise_for_status()
        return response.json()

    async def _get_user_id(self) -> str:
        users = await self._api_get("/Users")
        if isinstance(users, list) and len(users) > 0:
            uid = users[0].get("Id")
            if uid:
                return uid
        raise ValueError("Could not resolve Jellyfin user for item queries")

    async def list_library_items(
        self,
        library_name: str,
        search: str | None = None,
        limit: int = 10,
        ongoing_only: bool = False,
    ) -> dict:
        library = await self._resolve_library(library_name)
        user_id = await self._get_user_id()

        params: dict[str, str] = {
            "ParentId": library["id"],
            "Recursive": "true",
            "IncludeItemTypes": "Series,Movie",
            "Fields": "ProductionYear,EndDate,Status",
            "Limit": str(limit),
            "UserId": user_id,
            "SortBy": "ProductionYear,SortName",
            "SortOrder": "Descending",
        }
        if search:
            params["SearchTerm"] = search

        data = await self._api_get("/Items", params)
        items = data.get("Items", [])
        result_items: list[dict] = []

        for item in items:
            item_type = item.get("Type", "").lower()
            if item_type == "movie":
                result_items.append({
                    "name": item.get("Name", ""),
                    "type": "movie",
                    "year": item.get("ProductionYear"),
                })
            elif item_type == "series":
                series_id = item.get("Id")
                ongoing = self._is_ongoing_series(item)

                if ongoing_only and not ongoing:
                    continue

                seasons_info = {"total_seasons": 0, "total_episodes": 0, "seasons": []}
                try:
                    seasons_info = await self._get_series_seasons(series_id, user_id)
                except Exception:
                    pass

                result_items.append({
                    "name": item.get("Name", ""),
                    "type": "series",
                    "ongoing": ongoing,
                    "season_count": seasons_info["total_seasons"],
                    "episode_count": seasons_info["total_episodes"],
                    "seasons": seasons_info["seasons"],
                })

        return {
            "library_name": library_name,
            "returned_items": len(result_items),
            "search": search,
            "ongoing_only": ongoing_only,
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

    async def _get_series_seasons(self, series_id: str, user_id: str) -> dict:
        params: dict[str, str] = {
            "UserId": user_id,
            "Fields": "ChildCount,IndexNumber",
        }
        data = await self._api_get(f"/Shows/{series_id}/Seasons", params)
        seasons = data.get("Items", [])

        season_list: list[dict] = []
        total_episodes = 0

        for season in seasons:
            season_number = season.get("IndexNumber")
            if season_number is None or season_number == 0:
                continue
            child_count = season.get("ChildCount", 0) or 0
            season_list.append({
                "season": season_number,
                "episodes": child_count,
            })
            total_episodes += child_count

        season_list.sort(key=lambda s: s["season"])

        return {
            "total_seasons": len(season_list),
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
