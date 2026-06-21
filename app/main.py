from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
    if scan.status == "running":
        progress = _format_scan_progress(scan)
        return {
            "tool_purpose": "Returns the completed scan report. While a scan is running, this response is intentionally compact and redirects the LLM to the progress tool.",
            "summary": {
                "scan_id": scan.scan_id,
                "status": scan.status,
            },
            "progress": progress,
            "llm_instructions": [
                "Do not review or summarize the full report yet because the scan is still running.",
                "Call 'get move new downloads scan progress' with this scanId to check current progress and ETA.",
                "After progress status is completed, call 'get move new downloads scan report' again to review planned actions.",
                "Do not confirm/apply anything until the completed report has been reviewed and the user explicitly approves.",
            ],
            "next": "Scan is still running. Call 'get move new downloads scan progress' until status is completed, then call this report tool again.",
        }

    items_by_action = {"move": [], "replace": [], "skip": []}
    for item in scan.items:
        if item.confirmed:
            continue
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
            "confirmId": item.confirm_id,
            "name": item.name,
            "destination": Path(item.target_path).parent.name,
            "full_destination": item.target_path,
            "sourcePath": item.source_path,
        }
        if item.item_type == "movie":
            movies.append(entry)
        elif item.item_type == "series":
            series.append(entry)

    for item in items_by_action["replace"]:
        entry = {
            "confirmId": item.confirm_id,
            "name": item.name,
            "destination": Path(item.target_path).parent.name,
            "full_destination": item.target_path,
            "sourcePath": item.source_path,
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
                "confirmId": item.confirm_id,
                "name": item.name,
                "reason": item.reason,
                "sourcePath": item.source_path,
                "error": item.error,
            }
            for item in items_by_action["skip"]
        ]

    if scan.service_errors:
        report["service_errors"] = scan.service_errors

    unconfirmed = len(items_by_action["move"]) + len(items_by_action["replace"])
    if unconfirmed > 0 and scan.status != "confirmed":
        next_step = (
            f"To apply all remaining items: call 'confirm move new downloads scan' with scanId={scan.scan_id}. "
            f"To apply specific items only: call 'confirm move new downloads scan' with scanId={scan.scan_id} "
            f"and preferably itemIds=[list of confirmId values from the report], or use either sourcePaths=[list of sourcePath values from the report] or "
            f"sourcePrefixes=[common parent folder prefixes from the report]. "
            f"After confirming, call 'get move new downloads scan report' again to review remaining items."
        )
    else:
        next_step = "All items have been confirmed. Run 'move new downloads scan' for a new scan."
    if "Filesystem" in scan.service_errors:
        next_step += " Some download paths could not be scanned due to filesystem errors; review skipped items for the exact paths."
    report["next"] = next_step
    return report


def _format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds_int = max(int(seconds), 0)
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_scan_progress(scan: ScanPlan) -> dict:
    now = datetime.now(UTC)
    started_at = scan.started_at or scan.created_at
    finished_at = scan.finished_at or now
    elapsed_seconds = max((finished_at - started_at).total_seconds(), 0.0)
    processed = scan.processed_candidates
    total = scan.total_candidates
    percent = round((processed / total) * 100, 1) if total else 0.0
    eta_seconds = None
    if scan.status == "running" and processed > 0 and total > processed:
        seconds_per_item = elapsed_seconds / processed
        eta_seconds = seconds_per_item * (total - processed)

    next_step = "Scan is complete. Call 'get move new downloads scan report' to review planned moves before confirming."
    if scan.status == "running":
        next_step = "Scan is running. Call 'get move new downloads scan progress' again later. Do not confirm until status is completed and the report has been reviewed."
    elif scan.status == "failed":
        next_step = "Scan failed. Review the error, then run 'move new downloads scan' again after fixing the issue."

    return {
        "tool_purpose": "Reports progress for a background download-organizer scan. This progress tool is read-only and does not move files.",
        "scan_id": scan.scan_id,
        "status": scan.status,
        "processed": processed,
        "total": total,
        "current_index": scan.current_candidate_index,
        "current_file": scan.current_candidate,
        "percent": percent,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "elapsed": _format_duration(elapsed_seconds),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        "eta": _format_duration(eta_seconds),
        "counts": scan.counts.model_dump(mode="json"),
        "available_information": {
            "current_file": "The file path currently being processed, or null if the scan is not actively processing a file.",
            "processed": "How many candidate files have been processed so far.",
            "total": "How many candidate files were found for this scan.",
            "eta": "Estimated remaining time based on elapsed time and processed candidate count. It is approximate.",
        },
        "next": next_step,
    }


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
            "description": "Starts a background scan and returns immediately. Does NOT move files. Use progress tool until completed, then review report before confirming.",
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
            "description": "Applies the scan plan: moves files, stops active downloads. Use after reviewing plan. To confirm specific items only, prefer itemIds; sourcePaths and sourcePrefixes are also supported.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "scan_id from move new downloads scan"
                    },
                    "itemIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of compact confirmId values from the report to confirm selectively. Omit to confirm all remaining items."
                    },
                    "sourcePaths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of sourcePath values from the report to confirm selectively. Omit to confirm all remaining items."
                    },
                    "sourcePrefixes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of source path prefixes to confirm selectively, such as a shared download folder path for one release."
                    }
                },
                "required": ["scanId"]
            },
        },
        {
            "name": "get move new downloads scan progress",
            "description": "Returns current scan progress: status, current file, processed/total counts, elapsed time, and ETA.",
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
            "name": "get move new downloads scan report",
            "description": "Returns completed scan details: items with actions (move/replace/skip). If scan is still running, returns progress instructions instead.",
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
            try:
                scan = await manager.create_scan(
                    ScanRequest(
                        replaceExisting=arguments.get("replaceExisting", True),
                    )
                )
                logger.info("TOOL <<< %s (scan_id=%s)", name, scan.scan_id)
                response = _format_scan_progress(scan)
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
                response["llm_instructions"] = [
                    "Tell the user the scan has started.",
                    "To check recent progress, call the 'get move new downloads scan progress' tool with this scanId.",
                    "Keep using the progress tool until it returns status='completed' or status='failed'.",
                    "Only after status='completed', call the 'get move new downloads scan report' tool with this scanId to review planned moves/replaces/skips.",
                    "Do not call the confirm tool until the completed report has been reviewed and the user explicitly approves applying it.",
                ]
                response["next"] = "Use 'get move new downloads scan progress' for updates. Use 'get move new downloads scan report' only after progress status is completed."
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(response),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except HTTPException as exc:
                logger.warning("TOOL xxx %s (%s)", name, exc.detail)
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "confirm move new downloads scan":
            scan_id = arguments.get("scanId")
            if not scan_id:
                return _mcp_error_response(request_id, -32602, "scanId is required")

            item_ids = arguments.get("itemIds")
            source_paths = arguments.get("sourcePaths")
            source_prefixes = arguments.get("sourcePrefixes")

            try:
                scan = await manager.confirm_scan(scan_id, item_ids, source_paths, source_prefixes)
                logger.info("TOOL <<< %s (scan_id=%s)", name, scan_id)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(scan.model_dump(mode="json", by_alias=True)),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except HTTPException as exc:
                logger.warning("TOOL xxx %s (%s)", name, exc.detail)
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "get move new downloads scan progress":
            scan_id = arguments.get("scanId")
            try:
                if scan_id:
                    scan = manager.get_scan(scan_id)
                else:
                    scan = manager.get_current_scan()
                if not scan:
                    logger.info("TOOL <<< %s (no active scan)", name)
                    payload = {"hint": "No scan. Call 'move new downloads scan' to start."}
                else:
                    logger.info("TOOL <<< %s", name)
                    payload = _format_scan_progress(scan)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(payload),
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


@app.get("/scans/current/progress")
async def get_current_scan_progress():
    manager: ScanManager = app.state.scan_manager
    scan = manager.get_current_scan()
    if not scan:
        raise HTTPException(status_code=404, detail="No active scan. Run 'scan library' to create one.")
    return _format_scan_progress(scan)


@app.get("/scans/{scan_id}/progress")
async def get_scan_progress(scan_id: str):
    manager: ScanManager = app.state.scan_manager
    scan = manager.get_scan(scan_id)
    return _format_scan_progress(scan)


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
