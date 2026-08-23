from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import PathsConfig


class QbittorrentClient:
    """Download client for qBittorrent via standard WebUI API."""

    def __init__(self, base_url: str, username: str | None, password: str | None, paths_config: PathsConfig | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._paths_config = paths_config
        self._api_key = None

    @classmethod
    def from_env(cls, paths_config: PathsConfig | None = None) -> "QbittorrentClient | TransmissionClient | DelugeClient | None":
        import os

        from app.core.config import get_settings
        settings = get_settings()
        def _get(key: str, attr: str, default=None):
            if key in os.environ:
                return os.getenv(key)
            return getattr(settings, attr, default)
        enable_raw = _get("ENABLE_DOWNLOAD_CLIENT_CHECK", "enable_download_client_check", "true")
        if str(enable_raw).strip().lower() not in ("true", "1", "yes"):
            return None
        dc = (_get("DOWNLOAD_CLIENT", "download_client", "") or "").strip().lower()
        if dc == "qbittorrent":
            webui_url = (_get("QBT_WEBUI_URL", "qbt_webui_url", "") or "").strip()
            if not webui_url:
                webui_url = (_get("QBT_MCP_URL", "qbt_mcp_url", "") or "").strip()
                if webui_url.endswith("/mcp"):
                    webui_url = webui_url[:-4].rstrip("/")
            if not webui_url:
                return None
            user = _get("QBT_WEBUI_USER", "qbt_webui_user")
            passwd = _get("QBT_WEBUI_PASS", "qbt_webui_pass")
            return QbittorrentClient(base_url=webui_url, username=user, password=passwd, paths_config=paths_config)
        elif dc == "transmission":
            url = (_get("TRANSMISSION_URL", "transmission_url", "") or "").strip()
            if not url:
                return None
            user = _get("TRANSMISSION_USER", "transmission_user")
            passwd = _get("TRANSMISSION_PASS", "transmission_pass")
            return TransmissionClient(base_url=url, username=user, password=passwd, paths_config=paths_config)
        elif dc == "deluge":
            url = (_get("DELUGE_URL", "deluge_url", "") or "").strip()
            if not url:
                return None
            passwd = _get("DELUGE_PASSWORD", "deluge_password")
            return DelugeClient(base_url=url, password=passwd, paths_config=paths_config)
        return None

    async def _login(self, client: httpx.AsyncClient) -> None:
        data = {}
        if self._username:
            data["username"] = self._username
        if self._password:
            data["password"] = self._password
        try:
            resp = await client.post(f"{self._base_url}/api/v2/auth/login", data=data)
            if resp.status_code not in (200, 403):
                resp.raise_for_status()
        except Exception:
            pass

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
            await self._stop_torrents(hashes)
        return matches

    async def list_items(self, view: str) -> list[dict[str, Any]]:
        filter_map = {"all": None, "seeding": "seeding", "downloading": "downloading"}
        q_filter = filter_map.get(view)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            await self._login(client)
            params = {}
            if q_filter:
                params["filter"] = q_filter
            resp = await client.get(f"{self._base_url}/api/v2/torrents/info", params=params)
            resp.raise_for_status()
            try:
                data = resp.json()
                if isinstance(data, list):
                    return data
                return []
            except Exception:
                return []

    async def _stop_torrents(self, hashes: list[str]) -> None:
        if not hashes:
            return
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            await self._login(client)
            data = {"hashes": "|".join(hashes)}
            resp = await client.post(f"{self._base_url}/api/v2/torrents/stop", data=data)
            resp.raise_for_status()


class TransmissionClient:
    """Download client for Transmission via RPC API."""

    def __init__(self, base_url: str, username: str | None, password: str | None, paths_config: PathsConfig | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._paths_config = paths_config
        self._session_id = None

    @classmethod
    def from_env(cls, paths_config: PathsConfig | None = None) -> "TransmissionClient | None":
        # Handled via QbittorrentClient.from_env factory
        return None

    async def _get_session_id(self, client: httpx.AsyncClient) -> str:
        # Transmission requires X-Transmission-Session-Id header
        # Do a dummy request to get it from 409 response
        try:
            resp = await client.post(self._base_url, json={"method": "session-get"}, headers=self._auth_headers())
            if resp.status_code == 409:
                return resp.headers.get("X-Transmission-Session-Id", "")
            resp.raise_for_status()
            return resp.headers.get("X-Transmission-Session-Id", "")
        except Exception:
            return ""

    def _auth_headers(self) -> dict[str, str]:
        import base64
        headers = {"Content-Type": "application/json"}
        if self._username and self._password:
            token = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    async def list_items(self, view: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20) as client:
            session_id = await self._get_session_id(client)
            headers = self._auth_headers()
            if session_id:
                headers["X-Transmission-Session-Id"] = session_id
            # Use torrent-get with fields
            payload = {
                "method": "torrent-get",
                "arguments": {
                    "fields": ["hashString", "name", "percentDone", "status", "downloadDir", "isFinished"]
                }
            }
            # Add filter based on view
            resp = await client.post(self._base_url, json=payload, headers=headers)
            if resp.status_code == 409:
                # Retry with new session id
                session_id = resp.headers.get("X-Transmission-Session-Id", "")
                headers["X-Transmission-Session-Id"] = session_id
                resp = await client.post(self._base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            torrents = data.get("arguments", {}).get("torrents", [])
            # Filter by view
            if view == "seeding":
                # status 6 = seeding
                torrents = [t for t in torrents if t.get("status") == 6]
            elif view == "downloading":
                torrents = [t for t in torrents if t.get("status") in (0, 3, 4)]  # check, downloading, etc
            # Normalize to common format
            normalized = []
            for t in torrents:
                normalized.append({
                    "hash": t.get("hashString", ""),
                    "name": t.get("name", ""),
                    "progress": t.get("percentDone", 0),
                    "save_path": t.get("downloadDir", ""),
                    "status": t.get("status"),
                })
            return normalized

    async def list_in_progress_paths(self) -> list[str]:
        items = await self.list_items("all")
        items = [item for item in items if float(item.get("progress", 0)) < 0.999]
        return _extract_paths(items, self._paths_config)

    async def stop_seeding_for_paths(self, candidate_paths: list[str]) -> list[dict[str, Any]]:
        normalized_candidates = {_normalize_qbt_path(str(Path(path)).rstrip("/"), self._paths_config) for path in candidate_paths if path}
        if not normalized_candidates:
            return []
        items = await self.list_items("seeding")
        matches = [item for item in items if _item_matches_paths(item, normalized_candidates, self._paths_config)]
        hashes = [str(item.get("hash", "")).strip() for item in matches if str(item.get("hash", "")).strip()]
        if hashes:
            await self._stop_torrents(hashes)
        return matches

    async def _stop_torrents(self, hashes: list[str]) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            session_id = await self._get_session_id(client)
            headers = self._auth_headers()
            if session_id:
                headers["X-Transmission-Session-Id"] = session_id
            payload = {
                "method": "torrent-stop",
                "arguments": {"ids": hashes}
            }
            resp = await client.post(self._base_url, json=payload, headers=headers)
            if resp.status_code == 409:
                session_id = resp.headers.get("X-Transmission-Session-Id", "")
                headers["X-Transmission-Session-Id"] = session_id
                resp = await client.post(self._base_url, json=payload, headers=headers)
            resp.raise_for_status()


class DelugeClient:
    """Download client for Deluge via WebUI JSON-RPC API."""

    def __init__(self, base_url: str, password: str | None, paths_config: PathsConfig | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._password = password
        self._paths_config = paths_config

    @classmethod
    def from_env(cls, paths_config: PathsConfig | None = None) -> "DelugeClient | None":
        return None

    async def _login(self, client: httpx.AsyncClient) -> None:
        if not self._password:
            return
        payload = {"method": "auth.login", "params": [self._password], "id": 1}
        resp = await client.post(f"{self._base_url}/json", json=payload)
        resp.raise_for_status()

    async def list_items(self, view: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20) as client:
            await self._login(client)
            # Deluge: core.get_torrents_status with filter
            # For simplicity, get all and filter locally
            payload = {
                "method": "core.get_torrents_status",
                "params": [{}, ["hash", "name", "progress", "save_path", "state"]],
                "id": 1
            }
            resp = await client.post(f"{self._base_url}/json", json=payload)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            # result is dict of hash -> torrent dict
            torrents = []
            for h, info in result.items():
                info["hash"] = h
                # Normalize progress 0-100 to 0-1
                if "progress" in info:
                    try:
                        info["progress"] = float(info["progress"]) / 100.0
                    except Exception:
                        pass
                torrents.append(info)
            if view == "seeding":
                torrents = [t for t in torrents if str(t.get("state", "")).lower() == "seeding"]
            elif view == "downloading":
                torrents = [t for t in torrents if str(t.get("state", "")).lower() in ("downloading", "queued")]
            return torrents

    async def list_in_progress_paths(self) -> list[str]:
        items = await self.list_items("all")
        items = [item for item in items if float(item.get("progress", 0)) < 0.999]
        return _extract_paths(items, self._paths_config)

    async def stop_seeding_for_paths(self, candidate_paths: list[str]) -> list[dict[str, Any]]:
        normalized_candidates = {_normalize_qbt_path(str(Path(path)).rstrip("/"), self._paths_config) for path in candidate_paths if path}
        if not normalized_candidates:
            return []
        items = await self.list_items("seeding")
        matches = [item for item in items if _item_matches_paths(item, normalized_candidates, self._paths_config)]
        hashes = [str(item.get("hash", "")).strip() for item in matches if str(item.get("hash", "")).strip()]
        if hashes:
            await self._stop_torrents(hashes)
        return matches

    async def _stop_torrents(self, hashes: list[str]) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            await self._login(client)
            payload = {"method": "core.pause_torrent", "params": [hashes], "id": 1}
            resp = await client.post(f"{self._base_url}/json", json=payload)
            resp.raise_for_status()


def _extract_paths(items: list[dict[str, Any]], paths_config: PathsConfig | None) -> list[str]:
    paths: list[str] = []
    for item in items:
        paths.extend(_item_paths(item, paths_config))
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(Path(path)).rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


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

    if isinstance(name, str) and name.strip() and paths_config:
        torrent_name = name.strip().rstrip("/")
        for root in paths_config.download_roots:
            paths.append(str(Path(root) / torrent_name))

    return paths


def _normalize_qbt_path(qbt_path: str, paths_config: PathsConfig | None) -> str | None:
    if not paths_config:
        return qbt_path
    path_obj = Path(qbt_path)
    for part in path_obj.parts[-3:]:
        if part.startswith(".") or part.startswith("/"):
            continue
        matching_root = paths_config.find_download_root_for_folder(part)
        if matching_root:
            try:
                folder_index = list(path_obj.parts).index(part)
                remaining_parts = path_obj.parts[folder_index:]
                return str(Path(matching_root) / Path(*remaining_parts))
            except (ValueError, IndexError):
                return str(Path(matching_root) / part)
    return qbt_path
