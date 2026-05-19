from __future__ import annotations

import os

import httpx


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
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self._base_url}/Library/VirtualFolders",
                headers={"X-Emby-Token": self._api_key},
            )
            response.raise_for_status()
        libraries = response.json()
        return [{"name": item.get("Name", ""), "id": item.get("ItemId", "")} for item in libraries]

    async def scan_library(self, library_name: str) -> dict:
        target = await self._resolve_library(library_name)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._base_url}/Items/{target['id']}/Refresh",
                params={
                    "Recursive": "true",
                    "MetadataRefreshMode": "FullRefresh",
                    "ImageRefreshMode": "FullRefresh",
                    "ReplaceAllMetadata": "false",
                    "ReplaceAllImages": "false",
                },
                headers={"X-Emby-Token": self._api_key},
            )
            response.raise_for_status()
        return target

    async def _resolve_library(self, library_name: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self._base_url}/Library/VirtualFolders",
                headers={"X-Emby-Token": self._api_key},
            )
            response.raise_for_status()
        libraries = response.json()
        needle = library_name.strip().lower()
        exact = [item for item in libraries if str(item.get("Name", "")).strip().lower() == needle]
        if len(exact) == 1:
            return {"name": exact[0].get("Name", ""), "id": exact[0].get("ItemId", "")}
        contains = [item for item in libraries if needle in str(item.get("Name", "")).strip().lower()]
        if len(contains) == 1:
            return {"name": contains[0].get("Name", ""), "id": contains[0].get("ItemId", "")}
        if not contains:
            raise ValueError(f"Jellyfin library not found: {library_name}")
        names = ", ".join(str(item.get("Name", "")) for item in contains)
        raise ValueError(f"Ambiguous Jellyfin library name '{library_name}': {names}")
