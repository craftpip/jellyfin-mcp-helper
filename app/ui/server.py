from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_config, get_settings
from app.core.constants import (  # single source of truth — re-exported for tests that import from server
    BROWSE_IGNORED_DIR_NAMES,
    BROWSE_IGNORED_NAME_PARTS,
    BROWSE_SEARCH_CHILD_CAP,
    BROWSE_SEARCH_RESULT_CAP,
    BROWSE_VIDEO_COUNT_CAP,
    BROWSE_VIDEO_EXTENSIONS,
)
from app.core.logging import set_request_id
from app.core.version import VERSION
from app.models.schemas import ScanPlan, ScanRequest
from app.services.api_key_manager import ApiKeyManager
from app.services.env_manager import list_env, update_env
from app.services.jellyfin import JellyfinClient
from app.services.presenters import (
    format_confirm_progress,
    format_scan_progress,
    format_scan_report,
    is_cross_drive_transfer,
)
from app.services.release_tracker import ReleaseTracker
from app.services.resolver import PathResolver, normalize_text
from app.services.scan_history import list_history, load_report
from app.services.scan_manager import ScanManager
from app.ui.auth import login, logout, require_panel_auth

logger = logging.getLogger(__name__)

# SSE progress streams (plan 3.2): tick faster than the old 2s poll so the UI
# moves without the polling gap; hard lifetime cap avoids leaked generators.
SSE_TICK_SECONDS = 0.5
SSE_MAX_SECONDS = 900

HERE = Path(__file__).resolve().parent
REACT_INDEX_HTML = HERE / "react-dist" / "index.html"
REACT_ASSETS_DIR = HERE / "react-dist" / "assets"


def _browse_root_configs(config) -> list[dict]:
    roots = []
    for key, path in config.paths.movie_roots.items():
        roots.append({
            "key": key,
            "path": str(path),
            "kind": "movie",
            "description": config.paths.movie_root_descriptions.get(key, ""),
        })
    for key, path in config.paths.series_roots.items():
        roots.append({
            "key": key,
            "path": str(path),
            "kind": "series",
            "description": config.paths.series_root_descriptions.get(key, ""),
        })
    return roots


def _browse_root_for(path: Path, config) -> Path | None:
    for root in list(config.paths.movie_roots.values()) + list(config.paths.series_roots.values()):
        root_path = Path(root).resolve(strict=False)
        try:
            path.resolve(strict=False).relative_to(root_path)
            return root_path
        except ValueError:
            continue
    return None


def _browse_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _browse_video_count(dir_path: Path) -> int:
    if not dir_path.is_dir():
        return 0
    count = 0
    try:
        for entry in dir_path.iterdir():
            if entry.name.startswith("."):
                continue
            if count >= BROWSE_VIDEO_COUNT_CAP:
                return count
            if entry.is_file() and entry.suffix.lower() in BROWSE_VIDEO_EXTENSIONS:
                count += 1
    except OSError:
        return count
    return count


def _browse_subdir_count(dir_path: Path) -> int:
    count = 0
    try:
        for entry in dir_path.iterdir():
            if entry.name.startswith("."):
                continue
            if count >= BROWSE_VIDEO_COUNT_CAP:
                return count
            if entry.is_dir():
                count += 1
    except OSError:
        return count
    return count


def _browse_search_root(root_path: Path, query_norm: str, query_tokens: set[str], seen: set, results: list[dict], kind: str, cap: int) -> int:
    # Main-folder search only: the top-level show/movie folders directly under
    # each root. Season folders are not search targets — the user picks a show
    # (or movie) folder and the target resolves the season. Scanning only one
    # level is cheap (no walk), unlike the old depth-3 walk which also matched
    # "Season 01"-style folders inside shows.
    try:
        it = os.scandir(root_path)
    except OSError:
        return 0
    scanned = 0
    with it:
        for entry in it:
            if scanned >= BROWSE_SEARCH_CHILD_CAP:
                break
            scanned += 1
            name = entry.name
            if name.startswith(".") or name.lower() in BROWSE_IGNORED_DIR_NAMES:
                continue
            if any(junk in name.lower() for junk in BROWSE_IGNORED_NAME_PARTS):
                continue
            try:
                if not entry.is_dir(follow_symlinks=True):
                    continue
            except OSError:
                continue
            child = Path(entry.path)
            if child in seen:
                continue
            seen.add(child)
            name_norm = normalize_text(name)
            if query_tokens <= set(name_norm.split()) or query_norm in name_norm:
                results.append({
                    "name": name,
                    "path": str(child),
                    "root": str(root_path),
                    "kind": kind,
                    "seasonNumber": None,
                    "depth": 1,
                })
                if len(results) >= cap:
                    return cap
    return len(results)


def _browse_entries(dir_path: Path, root: Path) -> dict:
    entries = []
    for child in sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name.lower() in BROWSE_IGNORED_DIR_NAMES:
            continue
        try:
            resolved = child.resolve(strict=False)
            if not _browse_is_within(resolved, root):
                continue
        except OSError:
            continue
        season_number = PathResolver._season_number_from_name(name)
        has_subdirs = False
        has_videos = False
        try:
            for entry in child.iterdir():
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    has_subdirs = True
                    break
                if entry.is_file() and entry.suffix.lower() in BROWSE_VIDEO_EXTENSIONS:
                    has_videos = True
                    break
        except OSError:
            pass
        recursive = has_subdirs and not has_videos and season_number is None
        if recursive:
            # Show folder: no direct videos, seasons live in subdirectories.
            # Report the number of season subfolders (bounded, cheap) instead of
            # walking the whole tree — deep recursive walks hang on large series.
            video_count = _browse_subdir_count(child)
        else:
            video_count = _browse_video_count(child)
        entries.append({
            "name": name,
            "path": str(child),
            "isDir": True,
            "videoCount": video_count,
            "seasonNumber": season_number,
        })

    def sort_key(entry: dict):
        season = entry.get("seasonNumber")
        return (0 if season is not None else 1, season if season is not None else 0, entry["name"].lower())

    entries.sort(key=sort_key)
    return {
        "path": str(dir_path),
        "parent": str(dir_path.parent) if dir_path != root and _browse_is_within(dir_path.parent, root) else None,
        "root": str(root),
        "entries": entries,
    }


def _scan_started_response(scan: ScanPlan) -> dict:
    response = format_scan_progress(scan)
    response["message"] = "Scan started in the background. This tool returns immediately and does not wait for the scan to finish. No files were moved."
    response["tool_purpose"] = "Starts a background scan that classifies download candidates and builds a planned move/replace/skip report. It does not apply the plan or move files."
    response["what_happens_now"] = [
        "The service scans configured download folders in the background.",
        "Each candidate is classified as movie, series, or skip.",
        "The service resolves the destination path for planned movie/series items.",
        "The service records planned actions only; files are not moved by this tool.",
    ]
    response["available_now"] = [
        "scan_id",
        "status",
        "processed/total counters when available",
        "current file when processing has started",
        "elapsed time and ETA when enough progress exists",
    ]
    instructions = [
        "Tell the user the scan has started in the background.",
        "Ask the user if they want to check progress. Do not call any tool automatically.",
        "If the user says yes, call 'get move new downloads scan progress' with this scanId once.",
        "If still running, tell the user and ask if they want to check again later.",
        "Only after status='completed', call 'get move new downloads scan report' to review planned moves/replaces/skips.",
        "Do not call the confirm tool until the report has been reviewed and the user approves.",
    ]
    if is_cross_drive_transfer():
        instructions.insert(0, "This is a cross-drive transfer (downloads and media folders are on different drives). Moving files will take longer. Warn the user about this.")
    response["llm_instructions"] = instructions
    response["next"] = "Tell the user the scan started and ask if they want progress."
    return response


def _confirm_started_response(scan: ScanPlan) -> dict:
    response = format_confirm_progress(scan)
    queued = scan.confirm_queue_length > 0
    if queued:
        response["message"] = (
            f"A move is already running. This confirm was added to the queue "
            f"({scan.confirm_queue_items} item(s) behind the current move) and will "
            "start automatically when it finishes."
        )
        response["tool_purpose"] = "Apply a completed organizer scan plan. This tool performs write actions: it moves files and may stop active downloads before moving them. A move was already running, so this confirm was queued and will start automatically when the current move finishes."
        response["what_happens_now"] = [
            "The confirm was added to the queue behind the currently running move.",
            "It will start automatically when the current move finishes, without further action.",
            "Each planned item in the queued batch is then moved or replaced.",
        ]
        response["available_now"] = [
            "scan_id",
            "status",
            "queue_length (number of queued confirms behind the running move)",
            "queue_items (total item count across queued confirms)",
            "processed/total counters for the running move",
        ]
        instructions = [
            "Tell the user the confirm was queued behind the running move and will start automatically when it finishes.",
            "The user does not need to do anything else — do not call the confirm tool again.",
            "Ask the user if they want to check progress. Do not call any tool automatically.",
            "If the user says yes, call 'get move new downloads confirm progress' with this scanId once.",
            "If still running, tell the user and ask if they want to check again later.",
            "After the queued confirm is done, call 'get move new downloads scan report' to see the results.",
        ]
        if is_cross_drive_transfer():
            instructions.insert(0, "This is a cross-drive transfer (downloads and media folders are on different drives). Moving files will take longer. Warn the user about this.")
        response["llm_instructions"] = instructions
        response["next"] = "Tell the user the confirm was queued and will start automatically."
        return response

    response["message"] = "Confirm started in the background. This tool returns immediately. No files were moved yet."
    response["tool_purpose"] = "Apply a completed organizer scan plan. This tool performs write actions: it moves files and may stop active downloads before moving them. It returns immediately and processes in the background. Use the confirm progress tool to track progress."
    response["what_happens_now"] = [
        "The service stops seeding for each source file if qBittorrent is configured.",
        "Each planned item is moved or replaced.",
        "After all items are processed, Jellyfin library scans are triggered if items were moved.",
    ]
    response["available_now"] = [
        "scan_id",
        "status",
        "processed/total counters when available",
        "current_file when processing has started",
        "elapsed time and ETA when enough progress exists",
    ]
    instructions = [
        "Tell the user the confirm has started in the background.",
        "Ask the user if they want to check progress. Do not call any tool automatically.",
        "If the user says yes, call 'get move new downloads confirm progress' with this scanId once.",
        "If still running, tell the user and ask if they want to check again later.",
        "After confirm is done, call 'get move new downloads scan report' to see the results.",
    ]
    if is_cross_drive_transfer():
        instructions.insert(0, "This is a cross-drive transfer (downloads and media folders are on different drives). Moving files will take longer. Warn the user about this.")
    response["llm_instructions"] = instructions
    response["next"] = "Tell the user the confirm started and ask if they want progress."
    return response


def _current_scan_id(request: Request) -> str:
    manager: ScanManager = request.app.state.scan_manager
    scan = manager.get_current_scan()
    if not scan:
        raise HTTPException(status_code=404, detail="No current scan found. Run a scan first.")
    return scan.scan_id


def create_ui_app(
    scan_manager: ScanManager | None = None,
    release_tracker: ReleaseTracker | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scan_manager is None:
            app.state.scan_manager = ScanManager(get_config())
        else:
            app.state.scan_manager = scan_manager
        if release_tracker is None:
            app.state.release_tracker = ReleaseTracker()
        else:
            app.state.release_tracker = release_tracker
        yield

    ui_app = FastAPI(title="JellySort UI", lifespan=lifespan)

    if REACT_ASSETS_DIR.exists():
        ui_app.mount(
            "/assets",
            StaticFiles(directory=str(REACT_ASSETS_DIR)),
            name="react-assets",
        )
        # Backward-compat mount for bookmarks that pointed at /react/assets.
        ui_app.mount(
            "/react/assets",
            StaticFiles(directory=str(REACT_ASSETS_DIR)),
            name="react-assets-legacy",
        )

    def _serve_react() -> HTMLResponse:
        if not REACT_INDEX_HTML.exists():
            return HTMLResponse(
                "React UI not built yet. Run `npm run build` in app/ui/react/.",
                status_code=404,
            )
        return HTMLResponse(REACT_INDEX_HTML.read_text(encoding="utf-8"))

    @ui_app.get("/")
    async def index():
        return _serve_react()

    @ui_app.get("/scan")
    @ui_app.get("/settings")
    @ui_app.get("/apikeys")
    async def spa_page():
        return _serve_react()

    @ui_app.get("/react")
    async def react_redirect():
        return RedirectResponse(url="/", status_code=308)

    @ui_app.get("/react/")
    async def react_index():
        return RedirectResponse(url="/", status_code=308)

    # ── auth (public) ──────────────────────────────────────────────
    @ui_app.get("/api/status")
    async def api_status():
        settings = get_settings()
        roots_configured = any(
            (value or "").strip()
            for value in (
                settings.download_roots,
                settings.movie_roots,
                settings.series_roots,
            )
        )
        return {
            "service": "JellySort UI",
            "version": VERSION,
            "auth": {"required": bool(settings.ui_panel_password)},
            "roots_configured": roots_configured,
        }

    # ── setup wizard helpers (first run, before media roots exist) ──
    @ui_app.get("/api/setup/fs", dependencies=[Depends(require_panel_auth)])
    async def api_setup_fs(path: str = "/"):
        target = Path(path or "/")
        if not target.is_absolute():
            raise HTTPException(status_code=400, detail="path must be absolute")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail=f"Path '{path}' is not a directory")
        entries = []
        try:
            for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                if child.name.startswith("."):
                    continue
                try:
                    if child.is_dir():
                        entries.append({"name": child.name, "path": str(child)})
                except OSError:
                    continue
        except PermissionError:
            raise HTTPException(status_code=400, detail=f"Permission denied: {path}")
        parent = str(target.parent) if target.parent != target else None
        return {"path": str(target), "parent": parent, "entries": entries}

    @ui_app.post("/api/admin/test-jellyfin", dependencies=[Depends(require_panel_auth)])
    async def api_admin_test_jellyfin(payload: dict | None = None):
        data = payload or {}
        base_url = str(data.get("baseUrl") or "").strip().rstrip("/")
        api_key = str(data.get("apiKey") or "").strip()
        if not base_url:
            raise HTTPException(status_code=400, detail="baseUrl is required")
        headers = {"X-Emby-Token": api_key} if api_key else {}
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"{base_url}/System/Info/Public", headers=headers)
                resp.raise_for_status()
                info = resp.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Jellyfin unreachable at {base_url}: {exc}")
        return {"ok": True, "serverName": info.get("ServerName", ""), "version": info.get("Version", "")}

    @ui_app.post("/api/admin/test-download-client", dependencies=[Depends(require_panel_auth)])
    async def api_admin_test_download_client(payload: dict | None = None):
        data = payload or {}
        client_type = str(data.get("clientType") or data.get("downloadClient") or "").strip().lower()
        if not client_type:
            raise HTTPException(status_code=400, detail="clientType is required")
        # Build a temporary client config from payload
        base_url = str(data.get("url") or data.get("baseUrl") or data.get("webuiUrl") or "").strip()
        # Also support old field names for compat
        if not base_url:
            base_url = str(data.get("qbtMcpUrl") or data.get("qbtWebuiUrl") or "").strip()
        if client_type == "qbittorrent" and base_url.endswith("/mcp"):
            base_url = base_url[:-4].rstrip("/")
        user = str(data.get("user") or data.get("username") or "").strip() or None
        password = str(data.get("password") or "").strip() or None
        if client_type == "qbittorrent":
            if not base_url:
                raise HTTPException(status_code=400, detail="WebUI URL is required for qBittorrent")
            # Try to login and list torrents
            try:
                import httpx as _httpx

                async with _httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                    # Login
                    login_data = {}
                    if user:
                        login_data["username"] = user
                    if password:
                        login_data["password"] = password
                    resp = await client.post(f"{base_url.rstrip('/')}/api/v2/auth/login", data=login_data)
                    if resp.status_code not in (200, 403):
                        resp.raise_for_status()
                    # Try to list torrents
                    resp2 = await client.get(f"{base_url.rstrip('/')}/api/v2/torrents/info", params={"filter": "all"})
                    resp2.raise_for_status()
                    torrents = resp2.json()
                    count = len(torrents) if isinstance(torrents, list) else 0
                    return {"ok": True, "torrentCount": count, "clientType": client_type}
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"qBittorrent connection failed at {base_url}: {exc}")
        elif client_type == "transmission":
            if not base_url:
                raise HTTPException(status_code=400, detail="Transmission URL is required")
            try:
                import base64 as _b64

                import httpx as _httpx

                headers = {"Content-Type": "application/json"}
                if user and password:
                    token = _b64.b64encode(f"{user}:{password}".encode()).decode()
                    headers["Authorization"] = f"Basic {token}"
                async with _httpx.AsyncClient(timeout=8.0) as client:
                    # Get session id
                    resp = await client.post(base_url, json={"method": "session-get"}, headers=headers)
                    if resp.status_code == 409:
                        sid = resp.headers.get("X-Transmission-Session-Id", "")
                        if sid:
                            headers["X-Transmission-Session-Id"] = sid
                            resp = await client.post(base_url, json={"method": "session-get"}, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    if "result" in data and data["result"] == "success":
                        return {"ok": True, "clientType": client_type}
                    raise ValueError(f"Unexpected response: {data}")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Transmission connection failed at {base_url}: {exc}")
        elif client_type == "deluge":
            if not base_url:
                raise HTTPException(status_code=400, detail="Deluge URL is required")
            if not password:
                raise HTTPException(status_code=400, detail="Deluge password is required")
            try:
                import httpx as _httpx

                async with _httpx.AsyncClient(timeout=8.0) as client:
                    payload = {"method": "auth.login", "params": [password], "id": 1}
                    resp = await client.post(f"{base_url.rstrip('/')}/json", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("result") is True:
                        return {"ok": True, "clientType": client_type}
                    raise ValueError(f"Deluge login failed: {data}")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Deluge connection failed at {base_url}: {exc}")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown client type: {client_type}")

    @ui_app.post("/api/login")
    async def api_login(payload: dict | None = None):
        password = (payload or {}).get("password", "")
        return login(password)

    @ui_app.post("/api/logout")
    async def api_logout(
        authorization: str | None = Header(default=None),
        x_panel_token: str | None = Header(default=None),
    ):
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token and x_panel_token:
            token = x_panel_token.strip()
        logout(token)
        return {"ok": True}

    # ── admin: environment settings (Part E) ────────────────────────
    @ui_app.get("/api/admin/env", dependencies=[Depends(require_panel_auth)])
    async def admin_env():
        return list_env()

    @ui_app.post("/api/admin/env", dependencies=[Depends(require_panel_auth)])
    async def admin_env_update(payload: dict | None = None):
        payload = payload or {}
        updates = payload.get("updates")
        if not isinstance(updates, dict):
            raise HTTPException(status_code=400, detail="updates is required and must be an object")
        try:
            return update_env(updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ── admin: API keys (Part F) ────────────────────────────────────
    @ui_app.get("/api/admin/api-keys", dependencies=[Depends(require_panel_auth)])
    async def admin_api_keys():
        return {"keys": ApiKeyManager().list_keys()}

    @ui_app.post("/api/admin/api-keys", dependencies=[Depends(require_panel_auth)])
    async def admin_api_key_create(payload: dict | None = None):
        payload = payload or {}
        name = payload.get("name")
        if not name or not str(name).strip():
            raise HTTPException(status_code=400, detail="name is required")
        try:
            return ApiKeyManager().create_key(
                name=str(name),
                user=payload.get("user") or "default",
                scopes=payload.get("scopes"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @ui_app.patch("/api/admin/api-keys/{key_id}", dependencies=[Depends(require_panel_auth)])
    async def admin_api_key_toggle(key_id: str, payload: dict | None = None):
        payload = payload or {}
        if "enabled" not in payload:
            raise HTTPException(status_code=400, detail="enabled is required")
        manager = ApiKeyManager()
        if not manager.set_enabled(key_id, bool(payload["enabled"])):
            raise HTTPException(status_code=404, detail="key not found")
        return {"ok": True}

    @ui_app.get("/api/admin/api-keys/{key_id}/reveal", dependencies=[Depends(require_panel_auth)])
    async def admin_api_key_reveal(key_id: str):
        key = ApiKeyManager().reveal_key(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="key not found or not revealable — recreate the key")
        return {"key": key}

    @ui_app.delete("/api/admin/api-keys/{key_id}", dependencies=[Depends(require_panel_auth)])
    async def admin_api_key_delete(key_id: str):
        manager = ApiKeyManager()
        if not manager.delete_key(key_id):
            raise HTTPException(status_code=404, detail="key not found")
        return {"ok": True}

    # ── Jellyfin libraries ─────────────────────────────────────────
    @ui_app.get("/api/libraries", dependencies=[Depends(require_panel_auth)])
    async def api_libraries():
        client = JellyfinClient.from_env()
        if not client:
            return {
                "message": "Jellyfin integration is not configured. Set ENABLE_JELLYFIN_INTEGRATION=true and JELLYFIN_API_KEY in .env"
            }
        try:
            libraries = await client.list_libraries()
            return {"libraries": libraries}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @ui_app.post("/api/libraries/scan", dependencies=[Depends(require_panel_auth)])
    async def api_library_scan(payload: dict | None = None):
        payload = payload or {}
        library_name = payload.get("libraryName")
        if not library_name:
            raise HTTPException(status_code=400, detail="libraryName is required")
        client = JellyfinClient.from_env()
        if not client:
            return {
                "message": "Jellyfin integration is not configured. Set ENABLE_JELLYFIN_INTEGRATION=true and JELLYFIN_API_KEY in .env"
            }
        try:
            result = await client.scan_library(
                library_name=library_name,
                item_ids=payload.get("itemIds"),
                item_names=payload.get("itemNames"),
                recursive=payload.get("recursive", True),
                metadata_refresh_mode=payload.get("metadataRefreshMode", "Default"),
                image_refresh_mode=payload.get("imageRefreshMode", "Default"),
                replace_all_metadata=payload.get("replaceAllMetadata", False),
                replace_all_images=payload.get("replaceAllImages", False),
            )
            return {
                "message": f"Triggered Jellyfin library scan for '{result['name']}'",
                "library": result,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ── scan lifecycle ─────────────────────────────────────────────
    @ui_app.post("/api/scans", dependencies=[Depends(require_panel_auth)])
    async def api_start_scan(request: Request, payload: dict | None = None):
        payload = payload or {}
        manager: ScanManager = request.app.state.scan_manager
        try:
            scan = await manager.create_scan(
                ScanRequest(replaceExisting=payload.get("replaceExisting", True))
            )
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=exc.detail)
        return _scan_started_response(scan)

    @ui_app.get("/api/scans/current/progress", dependencies=[Depends(require_panel_auth)])
    async def api_current_scan_progress(request: Request):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_current_scan()
        if not scan:
            return {"hint": "No scan found. Ask the user if they want to start a new scan before doing anything."}
        return format_scan_progress(scan)

    # ── SSE progress streams (plan 3.2) ─────────────────────────────
    # EventSource cannot send headers, so the panel token arrives as ?token=.
    def _sse_authorized(token: str) -> bool:
        from app.ui.auth import _sessions, password_required

        if not password_required():
            return True
        return bool(token) and token in _sessions

    def _sse_event(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    @ui_app.get("/api/scans/progress/events")
    async def api_scan_progress_events(request: Request, token: str = ""):
        if not _sse_authorized(token):
            raise HTTPException(status_code=401, detail="not authenticated")
        manager: ScanManager = request.app.state.scan_manager

        async def stream():
            deadline = time.monotonic() + SSE_MAX_SECONDS
            last_payload = None
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    return
                scan = manager.get_current_scan()
                payload = format_scan_progress(scan) if scan else {"hint": "no scan"}
                terminal = bool(payload.get("hint")) or payload.get("status") in ("completed", "failed", "idle")
                if payload != last_payload or terminal:
                    yield _sse_event(payload)
                    last_payload = payload
                if terminal:
                    return
                await asyncio.sleep(SSE_TICK_SECONDS)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @ui_app.get("/api/scans/confirm/events")
    async def api_confirm_progress_events(request: Request, token: str = ""):
        if not _sse_authorized(token):
            raise HTTPException(status_code=401, detail="not authenticated")
        manager: ScanManager = request.app.state.scan_manager

        async def stream():
            deadline = time.monotonic() + SSE_MAX_SECONDS
            last_payload = None
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    return
                scan = manager.get_current_scan()
                payload = format_confirm_progress(scan) if scan else {"hint": "no scan"}
                queued = bool(payload.get("queue_length"))
                status = payload.get("status")
                # With batches still queued the backend flips straight back to
                # 'running', so keep streaming through intermediate completes.
                terminal = bool(payload.get("hint")) or (
                    status in ("completed", "failed", "idle") and not queued
                )
                if payload != last_payload or terminal:
                    yield _sse_event(payload)
                    last_payload = payload
                if terminal:
                    return
                await asyncio.sleep(SSE_TICK_SECONDS)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @ui_app.get("/api/scans/{scan_id}/progress", dependencies=[Depends(require_panel_auth)])
    async def api_scan_progress(request: Request, scan_id: str):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_scan(scan_id)
        return format_scan_progress(scan)

    @ui_app.get("/api/scans/current/report", dependencies=[Depends(require_panel_auth)])
    async def api_current_scan_report(request: Request):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_current_scan()
        if not scan:
            return {"hint": "No scan found. Ask the user if they want to start a new scan before doing anything."}
        return format_scan_report(scan)

    @ui_app.get("/api/scans/{scan_id}/report", dependencies=[Depends(require_panel_auth)])
    async def api_scan_report(request: Request, scan_id: str):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_scan(scan_id)
        return format_scan_report(scan)

    @ui_app.get("/api/scans/history", dependencies=[Depends(require_panel_auth)])
    async def api_scan_history(limit: int = 20):
        return {"history": list_history(limit=min(limit, 50))}

    @ui_app.get("/api/scans/history/{scan_id}", dependencies=[Depends(require_panel_auth)])
    async def api_scan_history_item(scan_id: str):
        report = load_report(scan_id)
        if not report:
            raise HTTPException(status_code=404, detail="History report not found")
        return report

    @ui_app.patch("/api/scans/current/items", dependencies=[Depends(require_panel_auth)])
    async def api_update_current_items(request: Request, payload: dict | None = None):
        payload = payload or {}
        items = payload.get("items")
        if not items or not isinstance(items, list):
            raise HTTPException(status_code=400, detail="items is required and must be a list")
        manager: ScanManager = request.app.state.scan_manager
        updated = manager.update_scan(_current_scan_id(request), items)
        return format_scan_report(updated)

    @ui_app.patch("/api/scans/{scan_id}/items", dependencies=[Depends(require_panel_auth)])
    async def api_update_scan_items(request: Request, scan_id: str, payload: dict | None = None):
        payload = payload or {}
        items = payload.get("items")
        if not items or not isinstance(items, list):
            raise HTTPException(status_code=400, detail="items is required and must be a list")
        manager: ScanManager = request.app.state.scan_manager
        updated = manager.update_scan(scan_id, items)
        return format_scan_report(updated)

    @ui_app.post("/api/scans/current/confirm", dependencies=[Depends(require_panel_auth)])
    async def api_confirm_current(request: Request, payload: dict | None = None):
        payload = payload or {}
        manager: ScanManager = request.app.state.scan_manager
        scan = await manager.confirm_scan(
            _current_scan_id(request),
            payload.get("itemIds"),
            payload.get("sourcePaths"),
            payload.get("sourcePrefixes"),
        )
        return _confirm_started_response(scan)

    @ui_app.post("/api/scans/{scan_id}/confirm", dependencies=[Depends(require_panel_auth)])
    async def api_confirm_scan(request: Request, scan_id: str, payload: dict | None = None):
        payload = payload or {}
        manager: ScanManager = request.app.state.scan_manager
        scan = await manager.confirm_scan(
            scan_id,
            payload.get("itemIds"),
            payload.get("sourcePaths"),
            payload.get("sourcePrefixes"),
        )
        return _confirm_started_response(scan)

    @ui_app.get("/api/scans/current/confirm-progress", dependencies=[Depends(require_panel_auth)])
    async def api_current_confirm_progress(request: Request):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_current_scan()
        if not scan:
            return {"hint": "No scan found. Ask the user if they want to start a new scan before doing anything."}
        return format_confirm_progress(scan)

    @ui_app.get("/api/scans/{scan_id}/confirm-progress", dependencies=[Depends(require_panel_auth)])
    async def api_confirm_progress(request: Request, scan_id: str):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_scan(scan_id)
        return format_confirm_progress(scan)

    # ── undo (plan 3.3) ─────────────────────────────────────────────
    def _undo_response(manager: ScanManager, scan_id: str):
        try:
            return manager.undo_scan(scan_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @ui_app.post("/api/scans/current/undo", dependencies=[Depends(require_panel_auth)])
    async def api_undo_current_scan(request: Request):
        manager: ScanManager = request.app.state.scan_manager
        scan = manager.get_current_scan()
        if not scan:
            raise HTTPException(status_code=404, detail="no current scan")
        return _undo_response(manager, scan.scan_id)

    @ui_app.post("/api/scans/{scan_id}/undo", dependencies=[Depends(require_panel_auth)])
    async def api_undo_scan(request: Request, scan_id: str):
        manager: ScanManager = request.app.state.scan_manager
        return _undo_response(manager, scan_id)

    @ui_app.delete("/api/scans/current/items", dependencies=[Depends(require_panel_auth)])
    async def api_delete_current_items(request: Request, payload: dict | None = None):
        payload = payload or {}
        item_ids = payload.get("itemIds")
        if not item_ids or not isinstance(item_ids, list):
            raise HTTPException(status_code=400, detail="itemIds is required and must be a list")
        manager: ScanManager = request.app.state.scan_manager
        scan = await manager.delete_items(_current_scan_id(request), item_ids)
        return format_scan_report(scan)

    @ui_app.delete("/api/scans/{scan_id}/items", dependencies=[Depends(require_panel_auth)])
    async def api_delete_scan_items(request: Request, scan_id: str, payload: dict | None = None):
        payload = payload or {}
        item_ids = payload.get("itemIds")
        if not item_ids or not isinstance(item_ids, list):
            raise HTTPException(status_code=400, detail="itemIds is required and must be a list")
        manager: ScanManager = request.app.state.scan_manager
        scan = await manager.delete_items(scan_id, item_ids)
        return format_scan_report(scan)

    # ── folder browse + retarget (smart correction UI) ────────────
    @ui_app.get("/api/browse/roots", dependencies=[Depends(require_panel_auth)])
    async def api_browse_roots(request: Request):
        manager: ScanManager = request.app.state.scan_manager
        return {"roots": _browse_root_configs(manager._config)}

    @ui_app.get("/api/browse", dependencies=[Depends(require_panel_auth)])
    async def api_browse(request: Request, path: str = ""):
        manager: ScanManager = request.app.state.scan_manager
        config = manager._config
        dir_path = Path(path)
        if not dir_path.is_absolute():
            raise HTTPException(status_code=400, detail="path must be absolute")
        root = _browse_root_for(dir_path, config)
        if not root:
            raise HTTPException(status_code=400, detail=f"Path '{path}' is not under any configured movie or series root")
        if not dir_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Path '{path}' is not a directory")
        return _browse_entries(dir_path, root)

    @ui_app.get("/api/browse/search", dependencies=[Depends(require_panel_auth)])
    async def api_browse_search(request: Request, q: str = ""):
        q = (q or "").strip()
        if not q:
            return {"results": []}
        manager: ScanManager = request.app.state.scan_manager
        config = manager._config
        query_norm = normalize_text(q)
        query_tokens = set(query_norm.split())
        results = []
        seen = set()
        for kind in ("movie", "series"):
            root_key_name = "movie_roots" if kind == "movie" else "series_roots"
            for key, root in getattr(config.paths, root_key_name).items():
                root_path = Path(root).resolve(strict=False)
                if not root_path.is_dir():
                    continue
                if _browse_search_root(root_path, query_norm, query_tokens, seen, results, kind, BROWSE_SEARCH_RESULT_CAP) >= BROWSE_SEARCH_RESULT_CAP:
                    break
        results.sort(key=lambda r: (r.get("depth", 9), r["kind"], r["name"].lower()))
        return {"results": results}

    @ui_app.post("/api/scans/current/items/retarget", dependencies=[Depends(require_panel_auth)])
    async def api_retarget_current_item(request: Request, payload: dict | None = None):
        return _retarget_payload(request, _current_scan_id(request), payload or {})

    @ui_app.post("/api/scans/{scan_id}/items/retarget", dependencies=[Depends(require_panel_auth)])
    async def api_retarget_item(request: Request, scan_id: str, payload: dict | None = None):
        return _retarget_payload(request, scan_id, payload or {})

    def _retarget_payload(request: Request, scan_id: str, payload: dict):
        confirm_id = payload.get("confirmId")
        directory = payload.get("directory")
        if not confirm_id or not directory:
            raise HTTPException(status_code=400, detail="confirmId and directory are required")
        manager: ScanManager = request.app.state.scan_manager
        try:
            updated = manager.retarget_item(
                scan_id,
                str(confirm_id),
                str(directory),
                apply_to_group=bool(payload.get("applyToGroup")),
                reclassify_as_movie=bool(payload.get("reclassifyAsMovie")),
            )
        except HTTPException as exc:
            raise exc
        return format_scan_report(updated)

    # ── request logging (D9) ───────────────────────────────────────
    @ui_app.middleware("http")
    async def log_requests(request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        request_id = uuid4().hex[:8]
        set_request_id(request_id)
        started = time.perf_counter()
        client_host = request.client.host if request.client else "unknown"
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            timestamp = datetime.now().strftime("%H:%M:%S")
            logger.exception(
                "[%s] ❌ %s %s failed — %sms, from %s",
                timestamp,
                request.method,
                request.url.path,
                duration_ms,
                client_host,
            )
            raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        timestamp = datetime.now().strftime("%H:%M:%S")
        logger.info(
            "[%s] ✅ %s %s completed — %sms, HTTP %s, from %s",
            timestamp,
            request.method,
            request.url.path,
            duration_ms,
            response.status_code,
            client_host,
        )
        return response

    return ui_app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_ui_app(), host="0.0.0.0", port=18328)
