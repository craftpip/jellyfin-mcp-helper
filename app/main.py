from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from app.core.config import get_config
from app.core.logging import configure_logging
from app.models.schemas import ScanLogEntry, ScanPlan, ScanRequest
from app.services.jellyfin import JellyfinClient
from app.services.scan_manager import ScanManager


logger = logging.getLogger(__name__)


def _mcp_error_response(request_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _format_scan_report(scan: ScanPlan) -> dict:
    items_by_action = {"move": [], "replace": [], "skip": []}
    for item in scan.items:
        if item.action in items_by_action:
            items_by_action[item.action].append(item)

    summary = {
        "scan_id": scan.scan_id,
        "status": scan.status,
        "total": scan.counts.total,
        "movies": scan.counts.movies,
        "series": scan.counts.series,
        "skipped": scan.counts.skipped,
        "action_required": len(items_by_action["move"]) + len(items_by_action["replace"]),
    }

    movies = []
    series = []

    for item in items_by_action["move"]:
        entry = {
            "name": item.name,
            "destination": Path(item.target_path).parent.name,
            "full_destination": item.target_path,
        }
        if item.item_type == "movie":
            movies.append(entry)
        elif item.item_type == "series":
            series.append(entry)

    for item in items_by_action["replace"]:
        entry = {
            "name": item.name,
            "destination": Path(item.target_path).parent.name,
            "full_destination": item.target_path,
        }
        if item.item_type == "movie":
            movies.append(entry)
        elif item.item_type == "series":
            series.append(entry)

    report = {
        "summary": summary,
        "movies": movies,
        "series": series,
    }

    if items_by_action["skip"]:
        report["skipped"] = [
            {
                "name": item.name,
                "reason": item.reason,
                "source_path": item.source_path,
                "error": item.error,
            }
            for item in items_by_action["skip"]
        ]

    if scan.service_errors:
        report["service_errors"] = scan.service_errors

    next_step = f"To apply: call 'confirm move new downloads scan' with scanId={scan.scan_id}. To re-scan: call 'move new downloads scan'."
    if "Filesystem" in scan.service_errors:
        next_step += " Some download paths could not be scanned due to filesystem errors; review skipped items for the exact paths."
    report["next"] = next_step
    return report


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Organizer service starting up")
    config = get_config()
    app.state.scan_manager = ScanManager(config)
    yield
    logger.info("Organizer service shutting down")


app = FastAPI(title="Jellyfin Library Organizer", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    request_id = uuid4().hex[:8]
    started = time.perf_counter()
    client_host = request.client.host if request.client else "unknown"

    logger.info("[%s] >>> %s %s from %s", request_id, request.method, request.url.path, client_host)

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.exception("[%s] xxx %s %s failed after %sms", request_id, request.method, request.url.path, duration_ms)
        raise

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info("[%s] <<< %s %s finished in %sms with status %s", request_id, request.method, request.url.path, duration_ms, response.status_code)
    response.headers["X-Request-ID"] = request_id
    return response


def _mcp_tools() -> list[dict[str, object]]:
    return [
        {
            "name": "move new downloads scan",
            "description": "Scans downloads, creates plan with targets. Does NOT move files. Call this first.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "replaceExisting": {
                        "type": "boolean",
                        "default": True,
                        "description": "Replace existing files at target"
                    }
                }
            },
        },
        {
            "name": "confirm move new downloads scan",
            "description": "Applies the scan plan: moves files, stops active downloads. Use after reviewing plan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "scan_id from move new downloads scan"
                    }
                },
                "required": ["scanId"]
            },
        },
        {
            "name": "get move new downloads scan report",
            "description": "Returns scan details: items with actions (move/replace/skip). Use to review plan. Omits scanId for last scan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "scan_id (optional)"
                    }
                }
            },
        },
        {
            "name": "trigger jellyfin library scan",
            "description": "Triggers a library scan in Jellyfin for the specified library.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library name (e.g., 'Movies' or 'Shows')"
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "get available jellyfin libraries list",
            "description": "Returns all available Jellyfin libraries.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


@app.post("/mcp")
async def mcp(request: dict) -> JSONResponse:
    method = request.get("method")
    request_id = request.get("id")

    if method != "notifications/initialized":
        logger.info("MCP request received: method=%s id=%s", method, request_id)

    if method == "notifications/initialized":
        return Response(status_code=204)

    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "jellyfin-download-organizer", "version": "0.2.0"},
                },
            }
        )

    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {}})

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"tools": _mcp_tools()}})

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        logger.info("TOOL >>> %s", name)

        manager: ScanManager = app.state.scan_manager

        if name == "move new downloads scan":
            scan = await manager.create_scan(
                ScanRequest(
                    replaceExisting=arguments.get("replaceExisting", True),
                )
            )
            logger.info("TOOL <<< %s (scan_id=%s)", name, scan.scan_id)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(_format_scan_report(scan)),
                            }
                        ],
                        "isError": False,
                    },
                }
            )

        if name == "confirm move new downloads scan":
            scan_id = arguments.get("scanId")
            if not scan_id:
                return _mcp_error_response(request_id, -32602, "scanId is required")

            try:
                scan = await manager.confirm_scan(scan_id)
                logger.info("TOOL <<< %s (scan_id=%s)", name, scan_id)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(scan.model_dump(mode="json")),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except HTTPException as exc:
                logger.warning("TOOL xxx %s (%s)", name, exc.detail)
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "get move new downloads scan report":
            scan_id = arguments.get("scanId")
            try:
                if scan_id:
                    scan = manager.get_scan(scan_id)
                else:
                    scan = manager.get_current_scan()
                if not scan:
                    logger.info("TOOL <<< %s (no active scan)", name)
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps({"hint": "No scan. Call 'move new downloads scan' to start."}),
                                    }
                                ],
                                "isError": False,
                            },
                        }
                    )
                logger.info("TOOL <<< %s", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(_format_scan_report(scan)),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except HTTPException as exc:
                logger.warning("TOOL xxx %s (%s)", name, exc.detail)
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "trigger jellyfin library scan":
            library_name = arguments.get("libraryName")
            if not library_name:
                return _mcp_error_response(request_id, -32602, "libraryName is required")

            client = JellyfinClient.from_env()
            if not client:
                logger.warning("TOOL xxx %s (Jellyfin not configured)", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "message": "Jellyfin integration is not configured. Set ENABLE_JELLYFIN_INTEGRATION=true and JELLYFIN_API_KEY in .env"
                                        }
                                    ),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )

            try:
                target = await client.scan_library(library_name)
                logger.info("TOOL <<< %s (library=%s)", name, library_name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "message": f"Triggered Jellyfin library scan for '{target.get('name', library_name)}'",
                                            "library": target,
                                        }
                                    ),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get available jellyfin libraries list":
            client = JellyfinClient.from_env()
            if not client:
                logger.warning("TOOL xxx %s (Jellyfin not configured)", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "message": "Jellyfin integration is not configured. Set ENABLE_JELLYFIN_INTEGRATION=true and JELLYFIN_API_KEY in .env"
                                        }
                                    ),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )

            try:
                libraries = await client.list_libraries()
                logger.info("TOOL <<< %s", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps({"libraries": libraries}),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        logger.warning("TOOL xxx %s (not found)", name)
        return _mcp_error_response(request_id, -32601, "Tool not found")

    logger.warning("MCP method not found: %s", method)
    return _mcp_error_response(request_id, -32601, "Method not found")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scans", response_model=ScanPlan, status_code=202)
async def create_scan(request: ScanRequest) -> ScanPlan:
    manager: ScanManager = app.state.scan_manager
    return await manager.create_scan(request)


@app.get("/scans/current/report")
async def get_current_scan_report():
    manager: ScanManager = app.state.scan_manager
    scan = manager.get_current_scan()
    if not scan:
        raise HTTPException(status_code=404, detail="No active scan. Run 'scan library' to create one.")
    return _format_scan_report(scan)


@app.get("/scans/{scan_id}/report")
async def get_scan_report(scan_id: str):
    manager: ScanManager = app.state.scan_manager
    scan = manager.get_scan(scan_id)
    return _format_scan_report(scan)


@app.get("/scans/current", response_model=ScanPlan)
async def get_current_scan() -> ScanPlan:
    manager: ScanManager = app.state.scan_manager
    scan = manager.get_current_scan()
    if not scan:
        raise HTTPException(status_code=404, detail="No active scan. Run 'scan library' to create one.")
    return scan


@app.get("/scans/{scan_id}", response_model=ScanPlan)
async def get_scan(scan_id: str) -> ScanPlan:
    manager: ScanManager = app.state.scan_manager
    return manager.get_scan(scan_id)


@app.post("/scans/{scan_id}/confirm", response_model=ScanPlan)
async def confirm_scan(scan_id: str) -> ScanPlan:
    manager: ScanManager = app.state.scan_manager
    return await manager.confirm_scan(scan_id)


@app.delete("/scans/current")
async def delete_current_scan() -> dict[str, str]:
    manager: ScanManager = app.state.scan_manager
    manager.delete_scan()
    return {"status": "deleted"}


# Legacy endpoints - kept for backward compatibility
@app.get("/runs/current")
async def get_current_run():
    manager: ScanManager = app.state.scan_manager
    scan = manager.get_current_scan()
    if not scan:
        raise HTTPException(status_code=404, detail="No runs have been started yet")
    return scan


@app.post("/runs")
async def start_run(request: dict):
    manager: ScanManager = app.state.scan_manager
    dry_run = request.get("dryRun", True)
    if dry_run:
        return await manager.create_scan(ScanRequest(replaceExisting=request.get("replaceExisting", True)))
    else:
        scan = await manager.create_scan(ScanRequest(replaceExisting=request.get("replaceExisting", True)))
        return await manager.confirm_scan(scan.scan_id)
