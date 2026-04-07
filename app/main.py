from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from app.core.config import get_config
from app.models.schemas import ScanLogEntry, ScanPlan, ScanRequest
from app.services.scan_manager import ScanManager


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
            {"name": item.name, "reason": item.reason}
            for item in items_by_action["skip"]
        ]

    if scan.service_errors:
        report["service_errors"] = scan.service_errors

    report["next"] = f"To apply: call 'confirm scan' with scanId={scan.scan_id}. To re-scan: call 'scan media library'."
    return report


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.scan_manager = ScanManager(config)
    yield


app = FastAPI(title="Jellyfin Library Organizer", version="0.2.0", lifespan=lifespan)


def _mcp_tools() -> list[dict[str, object]]:
    return [
        {
            "name": "scan media library",
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
            "name": "confirm scan",
            "description": "Applies the scan plan: moves files, stops active downloads. Use after reviewing plan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "scan_id from scan media library"
                    }
                },
                "required": ["scanId"]
            },
        },
        {
            "name": "get scan report",
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
    ]


@app.post("/mcp")
async def mcp(request: dict) -> JSONResponse:
    method = request.get("method")
    request_id = request.get("id")

    if method == "notifications/initialized":
        return JSONResponse(status_code=204, content=None)

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

        manager: ScanManager = app.state.scan_manager

        if name == "scan media library":
            scan = await manager.create_scan(
                ScanRequest(
                    replaceExisting=arguments.get("replaceExisting", True),
                )
            )
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

        if name == "confirm scan":
            scan_id = arguments.get("scanId")
            if not scan_id:
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "scanId is required"}},
                    status_code=400,
                )

            try:
                scan = await manager.confirm_scan(scan_id)
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
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": exc.detail}},
                    status_code=exc.status_code,
                )

        if name == "get scan report":
            scan_id = arguments.get("scanId")
            try:
                if scan_id:
                    scan = manager.get_scan(scan_id)
                else:
                    scan = manager.get_current_scan()
                if not scan:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps({"hint": "No scan. Call 'scan media library' to start."}),
                                    }
                                ],
                                "isError": False,
                            },
                        }
                    )
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
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": exc.detail}},
                    status_code=exc.status_code,
                )

        return JSONResponse(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Tool not found"}},
            status_code=404,
        )

    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}},
        status_code=404,
    )


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
