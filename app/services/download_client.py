from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx

from app.core.config import PathsConfig


class QbittorrentClient:
    """Download client for qBittorrent via MCP."""

    def __init__(self, base_url: str, api_key: str | None, user: str | None, password: str | None, paths_config: PathsConfig | None = None) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._user = user
        self._password = password
        self._paths_config = paths_config

    @classmethod
    def from_env(cls, paths_config: PathsConfig | None = None) -> "QbittorrentClient | None":
        enable_check = os.getenv("ENABLE_DOWNLOAD_CLIENT_CHECK", "true").strip().lower() in ("true", "1", "yes")
        if not enable_check:
            return None
        
        download_client = os.getenv("DOWNLOAD_CLIENT", "").strip().lower()
        if download_client != "qbittorrent":
            return None
        base_url = os.getenv("QBT_MCP_URL", "").strip()
        if not base_url:
            return None
        api_key = os.getenv("QBT_MCP_API_KEY")
        user = os.getenv("QBT_WEBUI_USER")
        password = os.getenv("QBT_WEBUI_PASS")
        return cls(base_url=base_url, api_key=api_key, user=user, password=password, paths_config=paths_config)

    async def list_in_progress_paths(self) -> list[str]:
        items = await self.list_items("all")
        items = [item for item in items if _is_incomplete(item)]
        return _extract_paths(items, self._paths_config)

    async def stop_seeding_for_paths(self, candidate_paths: list[str]) -> list[dict[str, Any]]:
        normalized_candidates = {_normalize_qbt_path(str(Path(path)).rstrip("/"), self._paths_config) for path in candidate_paths if path}
        if not normalized_candidates:
            return []

        items = await self.list_items("seeding")
        matches = [item for item in items if _item_matches_paths(item, normalized_candidates, self._paths_config)]
        hashes = [str(item.get("hash", "")).strip() for item in matches if str(item.get("hash", "")).strip()]
        if hashes:
            await self._call_tool("stop_torrents", {"hashes": hashes})
        return matches

    async def list_items(self, view: str) -> list[dict[str, Any]]:
        data = await self._call_tool("list_torrents", {"view": view})
        result = data.get("result", {})
        content = result.get("content", [])
        if not content:
            return []
        text_payload = content[0].get("text", "[]")
        return json.loads(text_payload)

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-MCP-Key"] = self._api_key
        elif self._user and self._password:
            token = base64.b64encode(f"{self._user}:{self._password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._base_url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()


def _extract_paths(items: list[dict[str, Any]], paths_config: PathsConfig | None) -> list[str]:
    paths: list[str] = []
    for item in items:
        paths.extend(_item_paths(item, paths_config))
    return paths


def _item_matches_paths(item: dict[str, Any], candidate_paths: set[str], paths_config: PathsConfig | None) -> bool:
    item_paths = {str(Path(path)).rstrip("/") for path in _item_paths(item, paths_config)}
    for candidate in candidate_paths:
        for item_path in item_paths:
            if candidate == item_path:
                return True
            if candidate.startswith(item_path + "/"):
                return True
            if item_path.startswith(candidate + "/"):
                return True
    return False


def _is_incomplete(item: dict[str, Any]) -> bool:
    try:
        progress = float(item.get("progress") or 0)
    except (TypeError, ValueError):
        progress = 0.0
    return progress < 0.999


def _item_paths(item: dict[str, Any], paths_config: PathsConfig | None) -> list[str]:
    paths: list[str] = []
    for key in ("content_path", "root_path", "download_path"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            normalized = _normalize_qbt_path(value.strip(), paths_config)
            if normalized:
                paths.append(normalized)
    
    save_path = item.get("save_path")
    name = item.get("name")
    if isinstance(save_path, str) and isinstance(name, str) and save_path and name:
        combined = str(Path(save_path) / name)
        normalized = _normalize_qbt_path(combined, paths_config)
        if normalized:
            paths.append(normalized)
    
    return paths


def _normalize_qbt_path(qbt_path: str, paths_config: PathsConfig | None) -> str | None:
    """Normalize qBittorrent path to container path by finding matching download root.
    
    Strategy: Extract folder name from qBittorrent path and search for it in download_roots.
    
    Example:
        qbt_path: /config/Downloads/Show Name - Season 4
        → Extract: "Show Name - Season 4"
        → Find in download_roots: /data/torrents
        → Return: /data/torrents/Show Name - Season 4
    """
    if not paths_config:
        # If no config provided, return path as-is (already in container format)
        return qbt_path
    
    path_obj = Path(qbt_path)
    
    # Try to find the folder name in any of our download roots
    # Start with direct children, then try parents if needed
    for part in path_obj.parts[-3:]:  # Check last 3 parts of the path
        if part.startswith(".") or part.startswith("/"):
            continue
        
        # Check if this folder exists in any download root
        matching_root = paths_config.find_download_root_for_folder(part)
        if matching_root:
            # Found it! Return the path relative to this root
            # If qbt_path has more parts after the folder, include them
            try:
                folder_index = list(path_obj.parts).index(part)
                remaining_parts = path_obj.parts[folder_index:]
                return str(Path(matching_root) / Path(*remaining_parts))
            except (ValueError, IndexError):
                # Fallback: just use the folder in the root
                return str(Path(matching_root) / part)
    
    # If no match found, return as-is (might already be correct)
    return qbt_path
