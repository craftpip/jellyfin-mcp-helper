from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_config, get_settings
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
from app.services.scan_manager import ScanManager
from app.ui.auth import login, logout, require_panel_auth

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
REACT_INDEX_HTML = HERE / "react-dist" / "index.html"
REACT_ASSETS_DIR = HERE / "react-dist" / "assets"


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
        return {
            "service": "JellySort UI",
            "version": VERSION,
            "auth": {"required": bool(settings.ui_panel_password)},
        }

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

    # ── request logging (D9) ───────────────────────────────────────
    @ui_app.middleware("http")
    async def log_requests(request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        request_id = uuid4().hex[:8]
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
