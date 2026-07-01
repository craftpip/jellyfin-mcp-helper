from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from app.core.config import get_config
from app.core.logging import configure_logging
from app.core.version import VERSION
from app.models.schemas import ScanLogEntry, ScanPlan, ScanRequest, ScannedItem
from app.services.jellyfin import JellyfinClient
from app.services.release_tracker import ReleaseTracker
from app.services.scan_manager import ScanManager


logger = logging.getLogger(__name__)

_cached_library_list: str = ""

RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS = [
    "Release Tracker answers questions about what is stored, tracked, or saved locally for a series.",
    "If the user asks for the tracked/saved date or stored next release for a specific series, call the Release Tracker lookup tool before using Jellyfin or any external source.",
    "Only use Jellyfin or an external source when the user explicitly asks for live verification/current availability, or when no stored Release Tracker marker exists.",
    "When answering, clearly label whether the date came from Release Tracker local storage, Jellyfin library state, or an external source.",
]


def _mcp_request_body(request_body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(request_body or b"{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mcp_response_body(response_body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(response_body or b"{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mcp_line_details(method: object, arguments: dict[str, object]) -> str | None:
    if method != "tools/call":
        return None

    for key in ("libraryName", "source", "target"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            if key == "libraryName":
                return f"on {value}"
            return f"{key} {value}"

    return None


def _mcp_success_message(method: object, tool_name: object) -> str:
    if method == "tools/list":
        return "✅ 📋 Tools listed"
    if method == "prompts/list":
        return "✅ 📋 Prompts requested"
    if method == "tools/call" and isinstance(tool_name, str) and tool_name:
        return f"✅ 🔧 Ran “{tool_name}”"
    if isinstance(method, str) and method:
        return f"✅ {method} completed"
    return "✅ MCP request completed"


def _mcp_warning_message(method: object, error_message: str) -> str:
    if method == "prompts/list":
        return "⚠️ Prompts requested, but prompts/list is not supported"
    if isinstance(method, str) and method:
        return f"⚠️ {method} is not supported"
    return f"⚠️ MCP request warning: {error_message}"


def _mcp_error_message(method: object, tool_name: object) -> str:
    if method == "tools/call" and isinstance(tool_name, str) and tool_name:
        return f"❌ Failed to run “{tool_name}”"
    if isinstance(method, str) and method:
        return f"❌ {method} failed"
    return "❌ MCP request failed"


def _format_mcp_activity_line(
    request_body: bytes,
    response_body: bytes,
    duration_ms: int,
    status_code: int,
    client_host: str,
) -> str:
    request_payload = _mcp_request_body(request_body)
    response_payload = _mcp_response_body(response_body)
    method = request_payload.get("method")
    params = request_payload.get("params") if isinstance(request_payload.get("params"), dict) else {}
    tool_name = params.get("name") if isinstance(params, dict) else None
    arguments = params.get("arguments") if isinstance(params, dict) and isinstance(params.get("arguments"), dict) else {}
    error = response_payload.get("error") if isinstance(response_payload.get("error"), dict) else None
    timestamp = datetime.now().strftime("%H:%M:%S")

    if error:
        error_message = str(error.get("message") or "MCP error")
        error_code = error.get("code")
        if error_code == -32601 and method != "tools/call":
            message = _mcp_warning_message(method, error_message)
            reason = "MCP method not found" if error_message == "Method not found" else error_message
        else:
            message = _mcp_error_message(method, tool_name)
            reason = error_message
    else:
        message = _mcp_success_message(method, tool_name)
        reason = None

    details = _mcp_line_details(method, arguments)
    if details:
        message = f"{message} {details}"

    suffix_parts = []
    if reason:
        suffix_parts.append(reason)
    suffix_parts.append(f"{duration_ms}ms")
    suffix_parts.append(f"HTTP {status_code}")
    if client_host != "unknown":
        suffix_parts.append(f"from {client_host}")

    return f"[{timestamp}] {message} — {', '.join(suffix_parts)}"


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

    config = get_config()
    movie_roots_info = [
        {
            "path": path,
            "description": config.paths.movie_root_descriptions.get(key, ""),
        }
        for key, path in config.paths.movie_roots.items()
    ]
    series_roots_info = [
        {
            "path": path,
            "description": config.paths.series_root_descriptions.get(key, ""),
        }
        for key, path in config.paths.series_roots.items()
    ]

    summary = {
        "scan_id": scan.scan_id,
        "status": scan.status,
        "total": scan.counts.total,
        "movies": scan.counts.movies,
        "series": scan.counts.series,
        "skipped": scan.counts.skipped,
        "action_required": len(items_by_action["move"]) + len(items_by_action["replace"]),
    }

    if movie_roots_info:
        summary["movie_roots"] = movie_roots_info
    if series_roots_info:
        summary["series_roots"] = series_roots_info

    report = {
        "summary": summary,
        "report_md": _format_report_md(items_by_action, movie_roots_info, series_roots_info),
    }

    if scan.service_errors:
        report["service_errors"] = scan.service_errors

    report["llm_instructions"] = _report_llm_instructions(scan, movie_roots_info, series_roots_info)
    report["next"] = _report_next_step(scan)
    return report


EPISODE_TAG_RE = re.compile(r"S\d{2}E\d{2,3}", re.IGNORECASE)


def _format_report_md(
    items_by_action: dict[str, list[ScannedItem]],
    movie_roots_info: list[dict],
    series_roots_info: list[dict],
) -> str:
    lines = []
    movies = [i for i in items_by_action["move"] + items_by_action["replace"] if i.item_type == "movie"]
    series = [i for i in items_by_action["move"] + items_by_action["replace"] if i.item_type == "series"]

    if movies:
        lines.append("## Movies (%d)" % len(movies))
        lines.append("| cid | Title | Exists | Target |")
        lines.append("|-----|-------|--------|--------|")
        for item in movies:
            title = Path(item.target_path).parent.name
            exists = "yes" if item.folder_exists else "no"
            lines.append("| %s | %s | %s | `%s` |" % (item.confirm_id, title, exists, item.target_path))
        lines.append("")

    if series:
        lines.append("## Series (%d)" % len(series))
        lines.append("| cid | Show | Season | Ep | Exists | Target |")
        lines.append("|-----|------|--------|----|--------|--------|")
        for item in series:
            p = Path(item.target_path)
            show = p.parent.parent.name if p.parent.parent else p.parent.name
            season = p.parent.name
            tag_match = EPISODE_TAG_RE.search(p.name)
            ep = tag_match.group(0) if tag_match else p.stem
            exists = "yes" if item.folder_exists else "no"
            lines.append("| %s | %s | %s | %s | %s | `%s` |" % (item.confirm_id, show, season, ep, exists, item.target_path))
        lines.append("")

    if items_by_action["skip"]:
        by_reason: dict[str, list[str]] = {}
        for item in items_by_action["skip"]:
            key = item.reason[:120]
            by_reason.setdefault(key, []).append(item.source_path)

        lines.append("## Skipped (%d)" % len(items_by_action["skip"]))
        for reason, paths in by_reason.items():
            lines.append("- [%d] %s" % (len(paths), reason))
            for p in paths[:2]:
                lines.append("  - `%s`" % p)
            if len(paths) > 2:
                lines.append("  - ... and %d more" % (len(paths) - 2))
        lines.append("")

    return "\n".join(lines).strip()


def _report_llm_instructions(scan: ScanPlan, movie_roots_info: list[dict], series_roots_info: list[dict]) -> list[str]:
    unconfirmed = scan.counts.movies + scan.counts.series
    if unconfirmed == 0 or scan.status == "confirmed":
        return []

    roots = []
    for label, info in [("movies", movie_roots_info), ("series", series_roots_info)]:
        for r in info:
            roots.append(f"  {r['path']} → {r['description']}")

    instructions = [
        "You are curating the library, not just moving files.",
        "folderExists=true  → already on disk, keep it there",
        "folderExists=false → new item, can redirect",
    ]

    if roots:
        instructions.append("Available roots:\n" + "\n".join(roots))

    instructions.extend([
        "Path validation: compare each item's Source filename with its targetPath. "
        "If the show or movie folder names in targetPath look wrong or don't match "
        "the source, update them using the update tool below.",
        "Root curation: each root has a description. "
        "Check whether each item's content belongs in its assigned root based on the root descriptions. "
        "If another root is a better fit, redirect the item there.",
    ])

    instructions.append(
        "To redirect an item, call 'update move new downloads scan' "
        "with items=[{\"confirmId\": \"...\", \"targetPath\": \"<new full path>\"}]. "
        "Then fetch this report again, then confirm."
    )

    return instructions


def _report_next_step(scan: ScanPlan) -> str:
    unconfirmed = len([item for item in scan.items if not item.confirmed and item.action in ("move", "replace")])

    if unconfirmed == 0 or scan.status == "confirmed":
        parts = ["All items done. Run 'move new downloads scan' for a new scan."]
    else:
        parts = [
            f"{unconfirmed} items pending. Review each item below.",
            "Check that target paths are correct and roots match the content description before confirming.",
        ]

    next_step = " ".join(parts)
    if "Filesystem" in scan.service_errors:
        next_step += " Some paths could not be scanned; check skipped items."
    return next_step


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


def _format_confirm_progress(scan: ScanPlan) -> dict:
    now = datetime.now(UTC)
    started_at = scan.confirm_started_at or now
    elapsed_seconds = max((now - started_at).total_seconds(), 0.0)
    processed = scan.counts.moved + scan.counts.replaced + scan.counts.failed
    total = scan.confirm_total
    percent = round((processed / total) * 100, 1) if total else 0.0
    eta_seconds = None
    if scan.confirm_status == "running" and processed > 0 and total > processed:
        seconds_per_item = elapsed_seconds / processed
        eta_seconds = seconds_per_item * (total - processed)

    next_step = "Confirm finished. Call 'get move new downloads scan report' to see results."
    if scan.confirm_status == "running":
        next_step = "Confirm is running. Call 'get move new downloads confirm progress' again later."
    elif scan.confirm_status == "idle":
        next_step = "No confirm has been started. Use 'confirm move new downloads scan' first."

    return {
        "tool_purpose": "Reports progress for a running confirm operation. This tool is read-only and does not move files.",
        "scan_id": scan.scan_id,
        "status": scan.confirm_status,
        "processed": processed,
        "total": total,
        "percent": percent,
        "current_file": scan.confirm_current_item,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "elapsed": _format_duration(elapsed_seconds),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        "eta": _format_duration(eta_seconds),
        "counts": {
            "moved": scan.counts.moved,
            "replaced": scan.counts.replaced,
            "failed": scan.counts.failed,
        },
        "next": next_step,
    }


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
    app.state.release_tracker = ReleaseTracker()
    global _cached_library_list
    try:
        client = JellyfinClient.from_env()
        if client:
            libraries = await client.list_libraries()
            names = [lib["name"] for lib in libraries if lib.get("name")]
            if names:
                _cached_library_list = "Available: " + ", ".join(names) + "."
                logger.info("Cached Jellyfin library list: %s", _cached_library_list)
    except Exception:
        logger.warning("Failed to fetch Jellyfin library list at startup", exc_info=True)
    yield
    logger.info("Organizer service shutting down")


app = FastAPI(title="jellyfin-mcp-helper", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    request_id = uuid4().hex[:8]
    started = time.perf_counter()
    client_host = request.client.host if request.client else "unknown"
    request_body = await request.body() if request.url.path == "/mcp" else b""

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

    if request.url.path == "/mcp":
        response_body = b"".join([chunk async for chunk in response.body_iterator])
        logger.info(_format_mcp_activity_line(request_body, response_body, duration_ms, response.status_code, client_host))
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )

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


def _mcp_tools() -> list[dict[str, object]]:
    _lib_hint = _cached_library_list or ""
    return [
        {
            "name": "move new downloads scan",
            "description": "Start a new background organizer scan of the configured download folders. This tool is read-only: it classifies candidates and prepares a move plan, but it does not move files. After calling this tool, use the progress tool until the scan completes, then use the report tool to review planned actions before confirming.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "replaceExisting": {
                        "type": "boolean",
                        "default": True,
                        "description": "When true, the planned action may replace an existing target file. When false, items with an existing target are planned as skip instead of replace."
                    }
                }
            },
        },
        {
            "name": "confirm move new downloads scan",
            "description": "Apply a completed organizer scan plan. This tool performs write actions: it moves files and may stop active downloads before moving them. Use it only after the scan report has been reviewed and approved. If you need to redirect items to a different root, call 'update move new downloads scan' first, then fetch the report again, then confirm.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "The scan_id returned by 'move new downloads scan'."
                    },
                    "itemIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of compact confirmId values from the scan report. Use this to confirm only specific planned items. Omit to confirm all remaining items."
                    },
                    "sourcePaths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of exact sourcePath values from the scan report. Use this to confirm only matching planned items."
                    },
                    "sourcePrefixes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of source path prefixes to confirm selectively, such as the parent download folder for one release or batch."
                    }
                },
                "required": ["scanId"]
            },
        },
        {
            "name": "get move new downloads scan progress",
            "description": "Check progress for an organizer scan that is currently running or has already finished. Returns status, current file, processed and total counts, elapsed time, and ETA when available. Use this after starting a scan and before asking for the final report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Optional scan_id to check a specific scan. If omitted, the current active scan is used."
                    }
                }
            },
        },
        {
            "name": "get move new downloads confirm progress",
            "description": "Check progress for a confirm operation that is currently running or has already finished. Returns confirm status, current file, processed and total counts, elapsed time, and ETA when available. Use this after starting a confirm and before asking for the final report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Optional scan_id to check confirm progress for a specific scan. If omitted, the current active scan is used."
                    }
                }
            },
        },
        {
            "name": "get move new downloads scan report",
            "description": "Get the final organizer scan report after a scan completes. Returns planned items and actions such as move, replace, or skip. If the scan is still running, this tool returns compact progress guidance instead of a full report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Optional scan_id to fetch a specific scan report. If omitted, the current active scan is used."
                    }
                }
            },
        },
        {
            "name": "update move new downloads scan",
            "description": "Update planned target destinations for items in a completed scan report. Use this to redirect movie or series items to a different root before confirming. After updating, fetch the report again to verify, then confirm. This tool does not move files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "The scan_id returned by 'move new downloads scan'."
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "confirmId": {
                                    "type": "string",
                                    "description": "The confirmId from the scan report for the item to update."
                                },
                                "targetPath": {
                                    "type": "string",
                                    "description": "The new full destination path for this item. Must be under one of the configured movie or series roots."
                                }
                            },
                            "required": ["confirmId", "targetPath"]
                        },
                        "description": "List of item updates. Each update specifies a confirmId and the new targetPath."
                    }
                },
                "required": ["scanId", "items"]
            },
        },
        {
            "name": "trigger jellyfin library scan",
            "description": "Trigger a Jellyfin metadata refresh and library scan for a named library, such as Movies or Shows. By default refreshes the whole library. Use itemNames or itemIds to scan specific items only. Use refresh mode params to control whether metadata, images, or both are force-refreshed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "The Jellyfin library name to refresh, for example 'Movies' or 'Shows'."
                    },
                    "itemNames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of specific movie or series names to scan instead of the whole library."
                    },
                    "itemIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of Jellyfin item IDs to scan instead of the whole library."
                    },
                    "recursive": {
                        "type": "boolean",
                        "default": True,
                        "description": "When true, scan recursively including all children items."
                    },
                    "metadataRefreshMode": {
                        "type": "string",
                        "default": "Default",
                        "description": "Metadata refresh mode. Matches Jellyfin UI options: Default (scan for new/updated files), FullRefresh (search for missing metadata), ValidationOnly."
                    },
                    "imageRefreshMode": {
                        "type": "string",
                        "default": "Default",
                        "description": "Image refresh mode. Matches Jellyfin UI options: Default (scan for new/updated images), FullRefresh (replace existing images), ValidationOnly."
                    },
                    "replaceAllMetadata": {
                        "type": "boolean",
                        "default": False,
                        "description": "When true, replace all existing metadata instead of merging. Only applies when metadataRefreshMode is FullRefresh."
                    },
                    "replaceAllImages": {
                        "type": "boolean",
                        "default": False,
                        "description": "When true, replace all existing images instead of merging. Only applies when imageRefreshMode is FullRefresh."
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "get available jellyfin libraries list",
            "description": "List all Jellyfin libraries that are available to the configured Jellyfin user." + (f" {_lib_hint}" if _lib_hint else "") + " Use this when you need the exact library names before calling other Jellyfin tools.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "get jellyfin library items",
                        "description": "List compact Jellyfin library items for movies and series. This tool is for existence checks, lightweight library browsing, and LLM-friendly summaries. It supports optional fuzzy search (client-side token overlap and similarity scoring handles typos and partial name matches) and optional ongoing-series filtering. For series, it returns total season count, total episode count, and per-season episode counts instead of full episode listings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "The Jellyfin library name to search or browse, for example 'Movies' or 'Shows'."
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional search term for fuzzy matching by name (handles typos and partial matches client-side). Use this to check whether a movie or series already exists."
                    },
                    "ongoingOnly": {
                        "type": "boolean",
                        "default": False,
                        "description": "When true, return only ongoing series. Movies are excluded. This is useful when you want to inspect only currently active shows."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of items to return. Results are ordered by newest release year first, then by name."
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "get ongoing jellyfin series latest episodes",
            "description": "List only ongoing Jellyfin series and return the latest available episode for each series. This tool is useful for checking what the current latest released episode is for active shows. If search is omitted or set to 'all', it returns all ongoing series in the library.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "The Jellyfin series library name, for example 'Shows'."
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional search term used to filter ongoing series by name. Use 'all' or omit it to return all ongoing series in the library."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of ongoing series to return. Results are ordered by newest release year first, then by name."
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "store ongoing series next release",
            "description": "Release Tracker: store or update one locally tracked next-release marker for an ongoing Jellyfin series. Use this after an external source determines the next expected release date for the next episode that should appear in Jellyfin. Later, if the user asks what date is stored or tracked for that series, read Release Tracker first instead of using Jellyfin or the web.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Jellyfin library name for the series, for example 'Shows'."
                    },
                    "seriesName": {
                        "type": "string",
                        "description": "Series name as shown in Jellyfin. Required when storing or updating a marker."
                    },
                    "seriesId": {
                        "type": "string",
                        "description": "Optional Jellyfin series item id. Prefer this when available because series names can change. You can get it from 'get ongoing jellyfin series latest episodes'."
                    },
                    "nextReleaseDate": {
                        "type": "string",
                        "description": "Required next expected release time. Accepts either an ISO datetime like 2026-06-28T18:00:00+09:00 or a plain date like 2026-06-28. Plain dates are treated as due at the start of that date."
                    },
                    "nextSeason": {
                        "type": "integer",
                        "description": "Optional season number for the next expected episode."
                    },
                    "nextEpisode": {
                        "type": "integer",
                        "description": "Optional episode number for the next expected episode."
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Optional IANA timezone name such as Asia/Tokyo. Useful when nextReleaseDate is a plain date or a datetime without an offset."
                    },
                    "source": {
                        "type": "string",
                        "description": "Optional source label describing where the release estimate came from, for example 'llm', 'manual', or a website name."
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional free-text note about the release estimate or reasoning."
                    }
                },
                "required": ["libraryName", "seriesName", "nextReleaseDate"]
            },
        },
        {
            "name": "get ongoing series next release",
            "description": "Release Tracker: return the single locally stored next-release marker for one ongoing Jellyfin series. This is the local-memory lookup tool. Use it first when the user asks what date is stored, tracked, or saved for a specific series. Do not use Jellyfin or the web before this tool unless the user explicitly asks for live verification.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Jellyfin library name for the series, for example 'Shows'."
                    },
                    "seriesName": {
                        "type": "string",
                        "description": "Series name to look up in the local Release Tracker store. Required for direct lookup."
                    },
                    "seriesId": {
                        "type": "string",
                        "description": "Optional Jellyfin series item id. Prefer this when available because it is the most stable key."
                    }
                },
                "required": ["libraryName", "seriesName"]
            },
        },
        {
            "name": "get due ongoing series releases",
            "description": "Release Tracker: return locally tracked ongoing-series release markers whose nextReleaseDate is due now or overdue. Use this for cron-driven checks before re-checking Jellyfin for newly arrived episodes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Optional Jellyfin library name filter, for example 'Shows'. Omit it to check due markers across all tracked libraries."
                    },
                    "before": {
                        "type": "string",
                        "default": "now",
                        "description": "Optional due cutoff. Use 'now' or an ISO datetime. Returns markers whose nextReleaseDate is earlier than or equal to this time."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of due markers to return, sorted by nextReleaseDate ascending."
                    }
                }
            },
        },
        {
            "name": "get ongoing series next releases",
            "description": "Release Tracker: list all locally stored upcoming release markers for ongoing series. This is useful for planning, debugging, and confirming what is currently tracked before checking which ones are due. For a single-series stored-date question, prefer 'get ongoing series next release' first.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Optional Jellyfin library name filter, for example 'Shows'."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Maximum number of tracked markers to return, sorted by nextReleaseDate ascending."
                    }
                }
            },
        },
        {
            "name": "delete ongoing series next release",
            "description": "Release Tracker: delete one locally stored ongoing-series release marker when it is no longer needed. Prefer seriesId when available so the correct marker is removed even if the series name changes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Jellyfin library name for the series, for example 'Shows'."
                    },
                    "seriesName": {
                        "type": "string",
                        "description": "Series name for the marker to remove."
                    },
                    "seriesId": {
                        "type": "string",
                        "description": "Optional Jellyfin series item id. Prefer this when available because it is the most stable key."
                    }
                },
                "required": ["libraryName", "seriesName"]
            },
        },
    ]

@app.post("/mcp")
async def mcp(request: dict) -> JSONResponse:
    method = request.get("method")
    request_id = request.get("id")

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
                    "serverInfo": {"name": "jellyfin-mcp-helper", "version": VERSION},
                },
            }
        )

    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {}})

    if method == "tools/list":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": _mcp_tools(),
                    "llm_instructions": RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS,
                },
            }
        )

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}

        manager: ScanManager = app.state.scan_manager
        release_tracker: ReleaseTracker = app.state.release_tracker

        if name == "move new downloads scan":
            try:
                scan = await manager.create_scan(
                    ScanRequest(
                        replaceExisting=arguments.get("replaceExisting", True),
                    )
                )
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
                response = _format_confirm_progress(scan)
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
                response["llm_instructions"] = [
                    "Tell the user the confirm has started.",
                    "To check progress, call the 'get move new downloads confirm progress' tool with this scanId.",
                    "Keep using the confirm progress tool until it returns status='completed' or status='failed'.",
                    "After confirm is done, call 'get move new downloads scan report' to see the results.",
                ]
                response["next"] = "Use 'get move new downloads confirm progress' for updates. Use 'get move new downloads scan report' after confirm is complete to see results."
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
                    payload = {"hint": "No scan found. Ask the user if they want to start a new scan before doing anything."}
                else:
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
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "get move new downloads confirm progress":
            scan_id = arguments.get("scanId")
            try:
                if scan_id:
                    scan = manager.get_scan(scan_id)
                else:
                    scan = manager.get_current_scan()
                if not scan:
                    logger.info("TOOL <<< %s (no active scan)", name)
                    payload = {"hint": "No scan found. Ask the user if they want to start a new scan before doing anything."}
                else:
                    logger.info("TOOL <<< %s", name)
                    payload = _format_confirm_progress(scan)
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
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps({"hint": "No scan found. Ask the user if they want to start a new scan before doing anything."}),
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
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "update move new downloads scan":
            scan_id = arguments.get("scanId")
            items = arguments.get("items")
            if not scan_id:
                return _mcp_error_response(request_id, -32602, "scanId is required")
            if not items or not isinstance(items, list):
                return _mcp_error_response(request_id, -32602, "items is required and must be a list")

            try:
                updated_scan = manager.update_scan(scan_id, items)
                logger.info("TOOL <<< %s (scan_id=%s, updated=%d)", name, scan_id, len(items))
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(_format_scan_report(updated_scan)),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except HTTPException as exc:
                logger.warning("TOOL xxx %s (%s)", name, exc.detail)
                return _mcp_error_response(request_id, -32000, exc.detail)
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "trigger jellyfin library scan":
            library_name = arguments.get("libraryName")
            if not library_name:
                return _mcp_error_response(request_id, -32602, "libraryName is required")

            client = JellyfinClient.from_env()
            if not client:
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
                result = await client.scan_library(
                    library_name=library_name,
                    item_ids=arguments.get("itemIds"),
                    item_names=arguments.get("itemNames"),
                    recursive=arguments.get("recursive", True),
                    metadata_refresh_mode=arguments.get("metadataRefreshMode", "Default"),
                    image_refresh_mode=arguments.get("imageRefreshMode", "Default"),
                    replace_all_metadata=arguments.get("replaceAllMetadata", False),
                    replace_all_images=arguments.get("replaceAllImages", False),
                )
                logger.info("TOOL <<< %s (library=%s)", name, library_name)

                response_data: dict = {
                    "message": f"Triggered Jellyfin library scan for '{result['name']}'",
                    "library": result,
                }
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(response_data),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get available jellyfin libraries list":
            client = JellyfinClient.from_env()
            if not client:
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
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get jellyfin library items":
            library_name = arguments.get("libraryName")
            if not library_name:
                return _mcp_error_response(request_id, -32602, "libraryName is required")

            client = JellyfinClient.from_env()
            if not client:
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
                result = await client.list_library_items(
                    library_name=library_name,
                    search=arguments.get("search"),
                    limit=arguments.get("limit", 10),
                    ongoing_only=arguments.get("ongoingOnly", False),
                )
                result["next"] = "Search uses client-side fuzzy matching (token overlap + similarity scoring) so it handles typos and partial names. Use ongoingOnly to focus on currently ongoing series."
                logger.info("TOOL <<< %s (library=%s)", name, library_name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(result),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get ongoing jellyfin series latest episodes":
            library_name = arguments.get("libraryName")
            if not library_name:
                return _mcp_error_response(request_id, -32602, "libraryName is required")

            client = JellyfinClient.from_env()
            if not client:
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
                result = await client.list_ongoing_series_latest_episodes(
                    library_name=library_name,
                    search=arguments.get("search"),
                    limit=arguments.get("limit", 10),
                )
                result["next"] = "Use search to check a specific ongoing series. Omit search or use 'all' to list all ongoing series with their latest available episodes."
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(result),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "store ongoing series next release":
            try:
                record = release_tracker.upsert_release(arguments)
                payload = {
                    "message": f"Release Tracker stored the next release for '{record['seriesName']}' in '{record['libraryName']}'.",
                    "dataOrigin": "release_tracker",
                    "authorityScope": "stored_tracker_value",
                    "record": record,
                    "llm_instructions": RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS
                    + [
                        "Release Tracker stores one marker per ongoing series for the next expected episode release.",
                        "Prefer seriesId when available because it is more stable than the series name.",
                        "When the release becomes due, call 'get due ongoing series releases', then check Jellyfin latest episodes, then update this marker again with the following expected release.",
                    ],
                    "next": "When this Release Tracker marker becomes due, call 'get due ongoing series releases'. After Jellyfin has the new episode, calculate the following release and call this store tool again.",
                }
                logger.info("TOOL <<< %s (library=%s series=%s)", name, record["libraryName"], record["seriesName"])
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(payload)}],
                            "isError": False,
                        },
                    }
                )
            except ValueError as exc:
                logger.warning("TOOL xxx %s (%s)", name, str(exc))
                return _mcp_error_response(request_id, -32602, str(exc))
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get ongoing series next release":
            try:
                record = release_tracker.get_release(arguments)
                payload = {
                    "found": record is not None,
                    "dataOrigin": "release_tracker",
                    "authorityScope": "stored_tracker_value",
                    "record": record,
                    "message": (
                        f"Release Tracker returned the stored next release for '{record['seriesName']}' in '{record['libraryName']}'."
                        if record
                        else "No matching Release Tracker marker was found."
                    ),
                    "llm_instructions": RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS
                    + [
                        "Use this tool to answer questions about what date is stored, tracked, or saved for one series.",
                        "If found=false, say there is no stored Release Tracker marker yet before considering Jellyfin or any external source.",
                        "If the user wants the live current status instead of the stored value, then use Jellyfin or another explicitly requested source after stating that you are switching from stored tracker data to live verification.",
                    ],
                    "next": (
                        "If the user wants live verification, check Jellyfin latest episodes next. Otherwise answer from this stored Release Tracker value."
                        if record
                        else "If the user wants to save a tracker value, call 'store ongoing series next release'. If the user wants live verification instead, check Jellyfin latest episodes or another requested source."
                    ),
                }
                logger.info("TOOL <<< %s", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(payload)}],
                            "isError": False,
                        },
                    }
                )
            except ValueError as exc:
                logger.warning("TOOL xxx %s (%s)", name, str(exc))
                return _mcp_error_response(request_id, -32602, str(exc))
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get due ongoing series releases":
            try:
                payload = release_tracker.get_due_releases(
                    library_name=arguments.get("libraryName"),
                    before=arguments.get("before", "now"),
                    limit=arguments.get("limit", 50),
                )
                payload["dataOrigin"] = "release_tracker"
                payload["authorityScope"] = "stored_tracker_value"
                payload["llm_instructions"] = RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS + [
                    "Treat each returned item as a Release Tracker marker that should now be checked against Jellyfin.",
                    "For each due item, call 'get ongoing jellyfin series latest episodes' using the series name as search text and compare the returned latest episode to nextSeason and nextEpisode when those fields exist.",
                    "If the expected episode has arrived, calculate the following release and call 'store ongoing series next release' again.",
                    "If the expected episode has not arrived yet, leave the marker unchanged so it stays due for the next cron run.",
                ]
                payload["next"] = "For each due item, check Jellyfin latest episodes. If the tracked episode has arrived, calculate the following release date and call 'store ongoing series next release' again. If it has not arrived yet, leave the marker in place for the next cron run."
                logger.info("TOOL <<< %s", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(payload)}],
                            "isError": False,
                        },
                    }
                )
            except ValueError as exc:
                logger.warning("TOOL xxx %s (%s)", name, str(exc))
                return _mcp_error_response(request_id, -32602, str(exc))
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get ongoing series next releases":
            try:
                payload = release_tracker.list_releases(
                    library_name=arguments.get("libraryName"),
                    limit=arguments.get("limit", 100),
                )
                payload["dataOrigin"] = "release_tracker"
                payload["authorityScope"] = "stored_tracker_value"
                payload["llm_instructions"] = RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS + [
                    "Use this tool to inspect all stored Release Tracker markers, not just overdue ones.",
                    "Use 'get due ongoing series releases' when you want only the markers that should be checked now.",
                    "For a single-series stored lookup, prefer 'get ongoing series next release' because it avoids ambiguous list scanning.",
                ]
                payload["next"] = "Use this list to inspect tracked Release Tracker markers. Use 'get due ongoing series releases' to focus only on markers that should be checked now."
                logger.info("TOOL <<< %s", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(payload)}],
                            "isError": False,
                        },
                    }
                )
            except ValueError as exc:
                logger.warning("TOOL xxx %s (%s)", name, str(exc))
                return _mcp_error_response(request_id, -32602, str(exc))
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "delete ongoing series next release":
            try:
                deleted = release_tracker.delete_release(arguments)
                payload = {
                    "deleted": deleted is not None,
                    "dataOrigin": "release_tracker",
                    "authorityScope": "stored_tracker_value",
                    "record": deleted,
                    "message": "Release Tracker marker deleted." if deleted else "No matching Release Tracker marker was found.",
                    "llm_instructions": RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS
                    + [
                        "Prefer seriesId when available so the correct marker is deleted.",
                        "Use this only when a Release Tracker marker is wrong or no longer needed.",
                    ],
                }
                logger.info("TOOL <<< %s", name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(payload)}],
                            "isError": False,
                        },
                    }
                )
            except ValueError as exc:
                logger.warning("TOOL xxx %s (%s)", name, str(exc))
                return _mcp_error_response(request_id, -32602, str(exc))
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

        logger.warning("TOOL xxx %s (not found)", name)
        return _mcp_error_response(request_id, -32601, "Tool not found")

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
