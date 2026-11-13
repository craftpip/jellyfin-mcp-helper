from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.auth import MCPUnauthorizedError, require_mcp_auth
from app.core.config import get_config
from app.core.logging import configure_logging, set_request_id
from app.core.version import VERSION
from app.models.schemas import ScanPlan, ScanRequest, SortHint
from app.services.jellyfin import JellyfinClient
from app.services.presenters import (
    format_confirm_progress,
    format_duration,
    format_path_exists,
    format_report_items,
    format_report_md,
    format_scan_progress,
    format_scan_report,
    format_transfer_speed,
    is_cross_drive_transfer,
    report_llm_instructions,
    report_next_step,
)
from app.services.release_tracker import ReleaseTracker
from app.services.scan_manager import ScanManager
from app.ui.server import create_ui_app

# Backward-compat aliases for the former private formatter names (used by tests).
_format_scan_report = format_scan_report
_format_scan_progress = format_scan_progress
_format_confirm_progress = format_confirm_progress
_format_report_items = format_report_items
_format_report_md = format_report_md
_format_path_exists = format_path_exists
_format_duration = format_duration
_format_transfer_speed = format_transfer_speed
_report_llm_instructions = report_llm_instructions
_report_next_step = report_next_step
_is_cross_drive_transfer = is_cross_drive_transfer

logger = logging.getLogger(__name__)


def _parse_sort_hints(raw_hints: object) -> list[SortHint]:
    """Validate MCP/REST hint payloads into SortHint models (400 on bad input)."""
    if not raw_hints:
        return []
    if not isinstance(raw_hints, list):
        raise HTTPException(status_code=400, detail="hints must be an array of {sourcePrefix, title, kind, ...} objects.")
    try:
        return [SortHint(**h) if isinstance(h, dict) else SortHint.model_validate(h) for h in raw_hints]
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid hints: {exc.errors(include_url=False)}") from exc

_cached_library_list: str = ""

RELEASE_TRACKER_LOCAL_FIRST_INSTRUCTIONS = [
    "Release Tracker answers questions about what is stored, tracked, or saved locally for a series.",
    "If the user asks for the tracked/saved date or stored next release for a specific series, call the Release Tracker lookup tool before using Jellyfin or any external source.",
    "Only use Jellyfin or an external source when the user explicitly asks for live verification/current availability, or when no stored Release Tracker marker exists.",
    "When answering, clearly label whether the date came from Release Tracker local storage, Jellyfin library state, or an external source.",
]


MCP_SERVER_INSTRUCTIONS = """JellySort moves finished downloads into the Jellyfin library.

Work autonomously. When the user asks to scan, sort, organize, or move downloads into the library, that request is
the approval for the whole workflow. Run every step back-to-back without asking "want me to check progress?",
"should I confirm?", or announcing what you are about to do. Report once, at the end.

Workflow:
1. 'downloads_scan_start' - starts a background scan and returns immediately.
2. 'downloads_scan_progress' - this call waits server-side (waitSeconds, default 30) until the scan
   finishes. If status is still 'running', call it again immediately. Repeat until 'completed'. Never ask the user
   whether to keep checking. (If your client times out on long tool calls, pass a smaller waitSeconds and sleep
   ~30 seconds between calls yourself.)
3. 'downloads_scan_report' with search=<show or release name> to get only the items the user asked
   about (the full report can be large). Check targetPath/root for obvious mistakes; fix with
   'downloads_scan_update' if needed.
4. 'downloads_scan_confirm' with itemIds = the matching confirmId values (or sourcePrefixes = the release folder) so only
   the requested release moves. Omit filters only when the user asked to move everything.
5. 'downloads_confirm_progress' - waits like step 2; repeat until confirm_status is not 'running'.
   Jellyfin library scans are triggered automatically after the move; you do not need to trigger one.
6. Tell the user what moved where, plus any skipped or failed items.

Only stop to ask the user when something is genuinely ambiguous (e.g. a suspect item with no fitting
candidateTargets, or the requested release is not in the report even after a rescan) or before destructive
deletes ('downloads_scan_delete_items')."""

MCP_PROGRESS_MAX_WAIT_SECONDS = 55
MCP_PROGRESS_DEFAULT_WAIT_SECONDS = 30


def _progress_wait_seconds(arguments: dict) -> float:
    """Clamp the optional waitSeconds argument for progress tools."""
    raw = arguments.get("waitSeconds", MCP_PROGRESS_DEFAULT_WAIT_SECONDS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = MCP_PROGRESS_DEFAULT_WAIT_SECONDS
    return max(0.0, min(value, MCP_PROGRESS_MAX_WAIT_SECONDS))


async def _wait_while_running(get_scan, is_running, wait_seconds: float, interval: float = 1.0):
    """Poll ``get_scan()`` until ``is_running(scan)`` is false or ``wait_seconds`` elapse.

    Lets the agent do a single "wait ~30s and check" call instead of needing its own sleep tool.
    """
    scan = get_scan()
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while scan is not None and is_running(scan):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(interval, remaining))
        scan = get_scan()
    return scan


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


def _tool_error_text(result: dict) -> str:
    """Error message from an isError tool result (content[0].text JSON or plain text)."""
    content = result.get("content") if isinstance(result.get("content"), list) else []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text or "Tool failed"
    if isinstance(parsed, dict):
        return str(parsed.get("error") or parsed.get("message") or "Tool failed")
    return text or "Tool failed"


def _format_mcp_activity_line(
    request_body: bytes,
    response_body: bytes,
    duration_ms: int,
    status_code: int,
    client_host: str,
    user: str | None = None,
) -> str:
    request_payload = _mcp_request_body(request_body)
    response_payload = _mcp_response_body(response_body)
    method = request_payload.get("method")
    params = request_payload.get("params") if isinstance(request_payload.get("params"), dict) else {}
    tool_name = params.get("name") if isinstance(params, dict) else None
    arguments = params.get("arguments") if isinstance(params, dict) and isinstance(params.get("arguments"), dict) else {}
    error = response_payload.get("error") if isinstance(response_payload.get("error"), dict) else None
    result = response_payload.get("result") if isinstance(response_payload.get("result"), dict) else {}
    if error is None and result.get("isError"):
        error = {"message": _tool_error_text(result)}
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
    if user:
        suffix_parts.append(f"as {user}")

    return f"[{timestamp}] {message} — {', '.join(suffix_parts)}"


def _mcp_error_response(request_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _build_recent_file_items(files: list, series_title_aliases: dict[str, str]) -> list[dict]:
    """Shape recent download files like 'jellyfin_library_items' entries."""
    from app.models.schemas import CandidateItem
    from app.services.classifier import classify_candidate

    items = []
    for f in files:
        candidate = CandidateItem(
            source_root_key="download",
            source_root=f.source_root,
            source_path=f.source_path,
            name=f.name,
            extension=f.extension,
            container_path=f.container_path,
            relative_path=f.name,
            file_size=f.file_size,
        )
        cls = classify_candidate(candidate, series_title_aliases)
        if cls.kind == "series":
            items.append(
                {
                    "name": cls.title or f.name,
                    "type": "series",
                    "ongoing": False,
                    "path": f.source_path,
                    "season_count": 1 if cls.season else 0,
                    "episode_count": 1 if cls.episode else 0,
                }
            )
        elif cls.kind == "movie":
            items.append(
                {
                    "name": cls.title or f.name,
                    "type": "movie",
                    "year": cls.year,
                    "path": f.source_path,
                }
            )
        else:
            items.append(
                {
                    "name": cls.title or f.name,
                    "type": "skip",
                    "path": f.source_path,
                }
            )
    return items


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Organizer service starting up")
    config = get_config()
    app.state.scan_manager = ScanManager(config)
    app.state.release_tracker = ReleaseTracker()
    global _cached_library_list

    ui_app = create_ui_app(app.state.scan_manager, app.state.release_tracker)
    ui_app.state.scan_manager = app.state.scan_manager
    ui_app.state.release_tracker = app.state.release_tracker
    app.state.ui_app = ui_app
    app.mount("/", ui_app)
    logger.info("Web UI mounted at / on the MCP app (single port, shares ScanManager/ReleaseTracker)")

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


app = FastAPI(title="JellySort", version=VERSION, lifespan=lifespan)


@app.exception_handler(MCPUnauthorizedError)
async def mcp_unauthorized_handler(request: Request, exc: MCPUnauthorizedError) -> JSONResponse:
    request_id = _mcp_request_body(await request.body()).get("id")
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "unauthorized"}},
        status_code=401,
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    # Honor a client-supplied X-Request-ID (plan 0.3) so callers can correlate logs;
    # fall back to a generated id. Cap length to keep log lines sane.
    request_id = (request.headers.get("X-Request-ID") or "").strip()[:64] or uuid4().hex[:8]
    set_request_id(request_id)
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
        mcp_user = getattr(request.state, "mcp_user", None)
        logger.info(_format_mcp_activity_line(request_body, response_body, duration_ms, response.status_code, client_host, mcp_user))
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )

    timestamp = datetime.now().strftime("%H:%M:%S")
    logger.info(
        "[%s] ✅ %s %s completed — %sms, HTTP %s, from %s [rid:%s]",
        timestamp,
        request.method,
        request.url.path,
        duration_ms,
        response.status_code,
        client_host,
        request_id,
    )
    return response


def _mcp_tools() -> list[dict[str, object]]:
    _lib_hint = _cached_library_list or ""
    return [
        {
            "name": "downloads_scan_start",
            "title": "Start downloads scan",
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
            "description": "Start a background scan of the download folders that classifies files and builds a move plan (move/replace/skip). Does not move files. Incremental by default: keeps the existing report and its edits, adds only new files. Then, without asking the user, call 'downloads_scan_progress' until completed, 'downloads_scan_report' (with search) and confirm the requested items.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "replaceExisting": {
                        "type": "boolean",
                        "default": True,
                        "description": "Allow replacing an existing target file; false plans those items as skip."
                    },
                    "fullRescan": {
                        "type": "boolean",
                        "default": False,
                        "description": "Rescan everything and overwrite the report, discarding edits. Default false: only add new files."
                    },
                    "hints": {
                        "type": "array",
                        "default": [],
                        "description": "Authoritative per-folder metadata (e.g. from the downloader). A hint classifies the files of one download folder instead of guessing; other folders classify as usual.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sourcePrefix": {
                                    "type": "string",
                                    "description": "Download folder basename (case-insensitive)."
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Canonical title."
                                },
                                "kind": {
                                    "type": "string",
                                    "enum": ["movie", "series"],
                                    "description": "Media kind."
                                },
                                "year": {
                                    "type": "integer",
                                    "description": "Year, if known."
                                },
                                "season": {
                                    "type": "integer",
                                    "description": "Pack season, used when a file has no SxxEyy tag; a conflicting tag flags the item suspect."
                                },
                                "strict": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": "false ignores the hint."
                                }
                            },
                            "required": ["sourcePrefix", "title", "kind"]
                        }
                    },
                    "hintScope": {
                        "type": "string",
                        "enum": ["additive", "only"],
                        "default": "additive",
                        "description": "Only 'additive' is supported."
                    }
                }
            },
        },
        {
            "name": "downloads_recent_files",
            "title": "Recent download files",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "List video files in the download folders (filesystem, not Jellyfin) added or modified in the last N hours, newest first, with a quick classification. Read-only; useful to see what is new before scanning.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "number",
                        "default": 24,
                        "description": "Look-back window in hours."
                    }
                }
            },
        },
        {
            "name": "jellyfin_recently_added",
            "title": "Recently added in Jellyfin",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "List individual episodes and movies most recently added to a Jellyfin library (DateCreated descending, default last 72 hours), each with its file path; movies include year and audio/subtitle languages.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library name, e.g. 'Movies' or 'Shows'."
                    },
                    "hours": {
                        "type": "number",
                        "default": 72,
                        "description": "Look-back window in hours."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum items to return."
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "downloads_scan_confirm",
            "title": "Move scanned items into library",
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
            "description": "Move the planned items of a completed scan into the library. A user request to move/organize downloads is the approval: call this right after checking the report, without asking again. Limit it with itemIds (confirmId) or sourcePrefixes; fix targets first with 'downloads_scan_update'. Then poll 'downloads_confirm_progress'; Jellyfin scans run automatically.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Defaults to the current scan."
                    },
                    "itemIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "confirmId values from the report to move. Omit all filters to move every remaining item."
                    },
                    "sourcePaths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact sourcePath values from the report to move."
                    },
                    "sourcePrefixes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source path prefixes to move, e.g. one release's download folder."
                    }
                },
                "required": []
            },
        },
        {
            "name": "downloads_scan_progress",
            "title": "Scan progress",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Scan status, current file, processed/total, elapsed and ETA. Waits up to waitSeconds for the scan to finish; while status is 'running' call it again immediately - do not ask the user. When completed, fetch the report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Defaults to the current scan."
                    },
                    "waitSeconds": {
                        "type": "number",
                        "description": "Wait server-side up to this long (0-55, default 30); returns as soon as it is done. Lower it only if your client times out."
                    }
                }
            },
        },
        {
            "name": "downloads_confirm_progress",
            "title": "Move progress",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Move status, current file, processed/total, elapsed and ETA. Waits up to waitSeconds for the move to finish; while confirm_status is 'running' call it again immediately - do not ask the user.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Defaults to the current scan."
                    },
                    "waitSeconds": {
                        "type": "number",
                        "description": "Wait server-side up to this long (0-55, default 30); returns as soon as it is done. Lower it only if your client times out."
                    }
                }
            },
        },
        {
            "name": "downloads_scan_report",
            "title": "Scan report",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Planned items of a scan with their action (move/replace/skip) and target. Pass search with the show/release name - the full report can be very large. While the scan runs it returns progress guidance instead.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "Defaults to the current scan."
                    },
                    "search": {
                        "type": "string",
                        "description": "Only items whose name/source/target contain every word (case- and punctuation-insensitive), e.g. 'show name s01'."
                    },
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "json"],
                        "default": "markdown",
                        "description": "markdown: report_md + flat items; json: groups by sourceFolder."
                    },
                    "groupBy": {
                        "type": "string",
                        "enum": ["sourceFolder"],
                        "default": "sourceFolder",
                        "description": "Grouping for format=json."
                    }
                }
            },
        },
        {
            "name": "downloads_scan_delete_items",
            "title": "Delete download files",
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
            "description": "Permanently delete the source download files of planned items and drop them from the plan. Destructive and irreversible - ask the user first.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "scan_id from 'downloads_scan_start'."
                    },
                    "itemIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "confirmId values whose source files to delete."
                    }
                },
                "required": ["scanId", "itemIds"]
            },
        },
        {
            "name": "downloads_scan_update",
            "title": "Change planned targets",
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Change planned target paths of report items (e.g. a different root) before confirming. Does not move files; re-check the report, then confirm.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scanId": {
                        "type": "string",
                        "description": "scan_id from 'downloads_scan_start'."
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "confirmId": {
                                    "type": "string",
                                    "description": "confirmId from the report."
                                },
                                "targetPath": {
                                    "type": "string",
                                    "description": "New full destination path under a configured movie or series root."
                                }
                            },
                            "required": ["confirmId", "targetPath"]
                        },
                        "description": "Updates, each a confirmId and new targetPath."
                    }
                },
                "required": ["scanId", "items"]
            },
        },
        {
            "name": "jellyfin_library_scan",
            "title": "Refresh Jellyfin library",
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Refresh a Jellyfin library (or only itemNames/itemIds in it) to pick up new or changed files and metadata. Not needed after 'downloads_scan_confirm', which triggers it automatically.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library name, e.g. 'Movies' or 'Shows'."
                    },
                    "itemNames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Scan only these movie/series names."
                    },
                    "itemIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Scan only these Jellyfin item IDs."
                    },
                    "recursive": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include child items."
                    },
                    "metadataRefreshMode": {
                        "type": "string",
                        "default": "Default",
                        "description": "Default (new/updated files), FullRefresh (search missing metadata) or ValidationOnly."
                    },
                    "imageRefreshMode": {
                        "type": "string",
                        "default": "Default",
                        "description": "Default (new/updated images), FullRefresh (replace images) or ValidationOnly."
                    },
                    "replaceAllMetadata": {
                        "type": "boolean",
                        "default": False,
                        "description": "Replace instead of merge (FullRefresh only)."
                    },
                    "replaceAllImages": {
                        "type": "boolean",
                        "default": False,
                        "description": "Replace instead of merge (FullRefresh only)."
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "jellyfin_libraries",
            "title": "Jellyfin libraries",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "List all Jellyfin libraries that are available to the configured Jellyfin user." + (f" {_lib_hint}" if _lib_hint else "") + " Use this when you need the exact library names before calling other Jellyfin tools.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "jellyfin_library_items",
            "title": "Jellyfin library items",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Compact list of a library's movies and series, most recently added first, with optional fuzzy search; use it to check whether something exists. Movies: name, year, path. Series: name, path, ongoing, season_count, episode_count. For one item's episodes per season, missing episodes, files or audio/subtitle languages, call 'jellyfin_item_details'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library name, e.g. 'Movies' or 'Shows'."
                    },
                    "search": {
                        "type": "string",
                        "description": "Fuzzy name search (typos and partial names OK)."
                    },
                    "ongoingOnly": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only ongoing series (excludes movies)."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum items: the most recent without search, the best matches with it."
                    },
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "jellyfin_item_details",
            "title": "Jellyfin item details",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Detail for ONE movie or series (fuzzy name match). Series, per season: episode_numbers as ranges ('1-12, 14'), missing_episodes (gaps), aired_not_downloaded and upcoming (when Jellyfin has that metadata), audio/subtitle languages and language_groups when episodes differ; pass season for a per-episode list. Season 0 is specials. Movie: year, runtime and each file's size, container, resolution, codec, audio tracks and subtitles.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library name, e.g. 'Movies' or 'Shows'."
                    },
                    "name": {
                        "type": "string",
                        "description": "Movie or series name (fuzzy matched)."
                    },
                    "season": {
                        "type": "integer",
                        "description": "Series only: return just this season with a per-episode list."
                    },
                },
                "required": ["libraryName", "name"]
            },
        },
        {
            "name": "jellyfin_ongoing_latest_episodes",
            "title": "Ongoing series latest episodes",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "List ongoing series in a library with the latest episode Jellyfin has for each.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Series library name, e.g. 'Shows'."
                    },
                    "search": {
                        "type": "string",
                        "description": "Filter by series name; omit or 'all' for every ongoing series."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum series, newest release year first."
                    }
                },
                "required": ["libraryName"]
            },
        },
        {
            "name": "release_tracker_lookup",
            "title": "Release Tracker lookup",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            "description": "Release Tracker (local store, not Jellyfin or the web): stored next-release markers for ongoing series. seriesName: that series' marker - use this first when asked what date is stored/tracked; only go live (Jellyfin/web) if the user asks. dueOnly=true: markers due now, for cron checks. Neither: all markers, soonest first.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library name, e.g. 'Shows'. Required with seriesName, else a filter."
                    },
                    "seriesName": {
                        "type": "string",
                        "description": "Return this one series' marker."
                    },
                    "seriesId": {
                        "type": "string",
                        "description": "Jellyfin series id; most stable key."
                    },
                    "dueOnly": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only markers due by 'before'."
                    },
                    "before": {
                        "type": "string",
                        "default": "now",
                        "description": "'now' or an ISO datetime."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum markers (default 100 list, 50 due), soonest first."
                    }
                }
            },
        },
        {
            "name": "release_tracker_update",
            "title": "Release Tracker store/delete",
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
            "description": "Release Tracker (local store): action=store (default) saves or updates the next expected release of one ongoing series, e.g. after looking it up externally; action=delete removes a wrong or unneeded marker.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["store", "delete"],
                        "default": "store",
                        "description": "store creates/updates, delete removes."
                    },
                    "libraryName": {
                        "type": "string",
                        "description": "Library name, e.g. 'Shows'."
                    },
                    "seriesName": {
                        "type": "string",
                        "description": "Series name as in Jellyfin."
                    },
                    "seriesId": {
                        "type": "string",
                        "description": "Jellyfin series id; preferred, names can change."
                    },
                    "nextReleaseDate": {
                        "type": "string",
                        "description": "Required for store: ISO datetime (2026-06-28T18:00:00+09:00) or date (2026-06-28, due at its start)."
                    },
                    "nextSeason": {
                        "type": "integer",
                        "description": "Season of the next episode."
                    },
                    "nextEpisode": {
                        "type": "integer",
                        "description": "Number of the next episode."
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone for dates without an offset."
                    },
                    "source": {
                        "type": "string",
                        "description": "Where the estimate came from, e.g. 'llm', 'manual', a site."
                    },
                    "notes": {
                        "type": "string",
                        "description": "Free-text note."
                    }
                },
                "required": ["libraryName", "seriesName"]
            },
        },
    ]

# Advertised snake_case names (MCP spec: ^[a-zA-Z0-9_-]{1,64}$) -> internal
# handler key. Internal keys are the legacy spaced names, which stay callable
# as aliases so older clients and saved prompts keep working.
MCP_TOOL_ALIASES: dict[str, str] = {
    "downloads_scan_start": "move new downloads scan",
    "downloads_recent_files": "get recently added download files",
    "downloads_scan_progress": "get move new downloads scan progress",
    "downloads_scan_report": "get move new downloads scan report",
    "downloads_scan_update": "update move new downloads scan",
    "downloads_scan_confirm": "confirm move new downloads scan",
    "downloads_confirm_progress": "get move new downloads confirm progress",
    "downloads_scan_delete_items": "delete move new downloads scan items",
    "jellyfin_recently_added": "get recently added in library",
    "jellyfin_library_scan": "trigger jellyfin library scan",
    "jellyfin_libraries": "get available jellyfin libraries list",
    "jellyfin_library_items": "get jellyfin library items",
    "jellyfin_item_details": "get jellyfin series details",
    "jellyfin_ongoing_latest_episodes": "get ongoing jellyfin series latest episodes",
}

MCP_SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _negotiate_protocol_version(request: dict) -> str:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    requested = params.get("protocolVersion")
    return requested if requested in MCP_SUPPORTED_PROTOCOL_VERSIONS else MCP_SUPPORTED_PROTOCOL_VERSIONS[-1]


def _resolve_tool_name(name: object, arguments: dict) -> object:
    """Map an advertised (or legacy) tool name to its internal handler key."""
    if name == "release_tracker_lookup":
        if arguments.get("seriesName") or arguments.get("seriesId"):
            return "get ongoing series next release"
        if arguments.get("dueOnly"):
            return "get due ongoing series releases"
        return "get ongoing series next releases"
    if name == "release_tracker_update":
        action = str(arguments.get("action") or "store").lower()
        if action == "delete":
            return "delete ongoing series next release"
        if action != "store":
            return "release_tracker_update:invalid"
        return "store ongoing series next release"
    return MCP_TOOL_ALIASES.get(name, name) if isinstance(name, str) else name


def _tool_error_result(request_id: object, message: str) -> JSONResponse:
    """Tool execution failure as a normal result with isError=true.

    MCP clients hand result content to the model, so it can read the message
    and retry with fixed arguments; JSON-RPC errors are often swallowed.
    """
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps({"error": message})}],
                "isError": True,
            },
        }
    )


@app.post("/mcp", dependencies=[Depends(require_mcp_auth)])
async def mcp(request: dict) -> Response:
    response = await _mcp_dispatch(request)
    if request.get("method") != "tools/call" or not isinstance(response, JSONResponse):
        return response
    try:
        body = json.loads(response.body)
    except (TypeError, ValueError):
        return response
    error = body.get("error") if isinstance(body, dict) else None
    # Unknown tool stays a protocol error; every other tool failure becomes isError.
    if isinstance(error, dict) and error.get("code") != -32601:
        return _tool_error_result(body.get("id"), str(error.get("message") or "Tool failed"))
    return response


async def _mcp_dispatch(request: dict) -> Response:
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
                    "protocolVersion": _negotiate_protocol_version(request),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "JellySort", "version": VERSION},
                    "instructions": MCP_SERVER_INSTRUCTIONS,
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
        arguments = params.get("arguments") or {}
        name = _resolve_tool_name(params.get("name"), arguments)

        manager: ScanManager = app.state.scan_manager
        release_tracker: ReleaseTracker = app.state.release_tracker

        if name == "move new downloads scan":
            try:
                scan = await manager.create_scan(
                    ScanRequest(
                        replaceExisting=arguments.get("replaceExisting", True),
                        fullRescan=bool(arguments.get("fullRescan", False)),
                        hints=_parse_sort_hints(arguments.get("hints")),
                        hintScope=arguments.get("hintScope", "additive"),
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
                instructions = [
                    "Do not stop to ask the user anything. Continue the workflow yourself.",
                    "Call 'downloads_scan_progress' with this scanId now. It waits up to 30s server-side; if status is still 'running', call it again immediately. Repeat until 'completed'.",
                    "Then call 'downloads_scan_report' with search=<the show/release the user asked about>.",
                    "Then confirm the matching items (the user's request to move them is the approval) and poll 'downloads_confirm_progress' until done.",
                    "Do not call the confirm tool before the scan has completed.",
                ]
                if _is_cross_drive_transfer():
                    instructions.insert(0, "This is a cross-drive transfer (downloads and media folders are on different drives). Moving files will take longer; keep polling progress, and mention it in your final summary.")
                response["llm_instructions"] = instructions
                response["next"] = "Do not ask the user. Call 'downloads_scan_progress' now and keep calling it until the scan completes."
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

        if name == "get recently added download files":
            from datetime import datetime as _datetime

            from app.services.scanner import ScanPathError, recent_video_files

            try:
                raw_hours = arguments.get("hours", 24) or 24
                hours = float(raw_hours)
            except (TypeError, ValueError):
                hours = 24.0
            hours = min(max(hours, 0.5), 24 * 30)
            config = get_config()
            errors: list[ScanPathError] = []
            files = recent_video_files(config.paths, hours, errors)
            cutoff = _datetime.now().timestamp() - hours * 3600
            items = _build_recent_file_items(files, config.series_title_aliases)
            response = {
                "tool": "downloads_recent_files",
                "query": {"hours": hours, "cutoffUtc": _datetime.fromtimestamp(cutoff).isoformat()},
                "count": len(items),
                "rootsChecked": list(config.paths.download_roots),
                "items": items,
            }
            if errors:
                response["errors"] = [
                    {"path": e.path, "error": e.error} for e in errors
                ]
            response["message"] = (
                f"Found {len(items)} video file(s) added or modified in the last {hours:g} hour(s). "
                "Each item follows the same shape as 'jellyfin_library_items'. "
                "This list is informational only — nothing was moved or classified."
            )
            response["next"] = "Ask the user if they want to run 'downloads_scan_start' to organize these files."
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

        if name == "confirm move new downloads scan":
            scan_id = arguments.get("scanId")
            if not scan_id:
                current = manager.get_current_scan()
                if current:
                    scan_id = current.scan_id
                else:
                    return _mcp_error_response(request_id, -32000, "No active scan — scanId is required when no current scan exists. Run 'downloads_scan_start' first.")

            item_ids = arguments.get("itemIds")
            source_paths = arguments.get("sourcePaths")
            source_prefixes = arguments.get("sourcePrefixes")

            try:
                scan = await manager.confirm_scan(scan_id, item_ids, source_paths, source_prefixes)
                logger.info("TOOL <<< %s (scan_id=%s)", name, scan_id)
                response = _format_confirm_progress(scan)
                queued = response.get("queue_length", 0) > 0
                if queued:
                    response["message"] = (
                        f"A move is already running. This confirm was added to the queue "
                        f"({response.get('queue_items', 0)} item(s) behind the current move) and will "
                        "start automatically when the current move finishes."
                    )
                    response["tool_purpose"] = "Apply a completed organizer scan plan. This tool performs write actions: it moves files. A move was already running, so this confirm was queued and will start automatically when the current move finishes."
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
                        "The confirm was queued behind the running move and will start automatically when it finishes.",
                        "The user does not need to do anything else — do not call the confirm tool again.",
                        "Call 'downloads_confirm_progress' with this scanId now and keep calling it until confirm_status is not 'running'. Do not ask the user.",
                        "Then tell the user what was moved.",
                    ]
                    if _is_cross_drive_transfer():
                        instructions.insert(0, "This is a cross-drive transfer (downloads and media folders are on different drives). Moving files will take longer; keep polling progress, and mention it in your final summary.")
                    response["llm_instructions"] = instructions
                    response["next"] = "Confirm was queued and will start automatically. Keep calling 'downloads_confirm_progress' until it is done; do not ask the user."
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
                response["message"] = "Confirm started in the background. This tool returns immediately. No files were moved yet."
                response["tool_purpose"] = "Apply a completed organizer scan plan. This tool performs write actions: it moves files and returns immediately and processes in the background. Use the confirm progress tool to track progress."
                response["what_happens_now"] = [
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
                    "Do not stop to ask the user anything.",
                    "Call 'downloads_confirm_progress' with this scanId now. It waits up to 30s server-side; if confirm_status is still 'running', call it again immediately. Repeat until done.",
                    "Jellyfin library scans are triggered automatically after the move. When done, tell the user what moved where and any failures.",
                ]
                if _is_cross_drive_transfer():
                    instructions.insert(0, "This is a cross-drive transfer (downloads and media folders are on different drives). Moving files will take longer; keep polling progress, and mention it in your final summary.")
                response["llm_instructions"] = instructions
                response["next"] = "Do not ask the user. Call 'downloads_confirm_progress' now and keep calling it until the move finishes."
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
                scan = await _wait_while_running(
                    (lambda: manager.get_scan(scan_id)) if scan_id else manager.get_current_scan,
                    lambda sc: sc.status == "running",
                    _progress_wait_seconds(arguments),
                )
                if not scan:
                    logger.info("TOOL <<< %s (no active scan)", name)
                    payload = {"hint": "No scan found. If the user asked to scan or move downloads, call 'downloads_scan_start' now; otherwise ask what they want."}
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
                scan = await _wait_while_running(
                    (lambda: manager.get_scan(scan_id)) if scan_id else manager.get_current_scan,
                    lambda sc: sc.confirm_status == "running",
                    _progress_wait_seconds(arguments),
                )
                if not scan:
                    logger.info("TOOL <<< %s (no active scan)", name)
                    payload = {"hint": "No scan found. If the user asked to scan or move downloads, call 'downloads_scan_start' now; otherwise ask what they want."}
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
            fmt = str(arguments.get("format") or "markdown").lower()
            if fmt not in ("markdown", "json"):
                fmt = "markdown"
            group_by = str(arguments.get("groupBy") or "sourceFolder")
            search = arguments.get("search")
            search = str(search) if isinstance(search, str) else None
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
                                        "text": json.dumps({"hint": "No scan found. If the user asked to scan or move downloads, call 'downloads_scan_start' now; otherwise ask what they want."}),
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
                                    "text": json.dumps(_format_scan_report(scan, format=fmt, group_by=group_by, search=search)),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except HTTPException as exc:
                return _mcp_error_response(request_id, -32000, exc.detail)

        if name == "delete move new downloads scan items":
            scan_id = arguments.get("scanId")
            item_ids = arguments.get("itemIds")
            if not scan_id:
                return _mcp_error_response(request_id, -32602, "scanId is required")
            if not item_ids or not isinstance(item_ids, list):
                return _mcp_error_response(request_id, -32602, "itemIds is required and must be a list")

            try:
                scan = await manager.delete_items(scan_id, item_ids)
                logger.info("TOOL <<< %s (scan_id=%s, deleted=%d)", name, scan_id, len(item_ids))
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
            except Exception as exc:
                logger.error("TOOL xxx %s (%s)", name, str(exc), exc_info=True)
                return _mcp_error_response(request_id, -32000, str(exc))

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
                            "isError": True,
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
                            "isError": True,
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
                            "isError": True,
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
                result["next"] = "Items are sorted by most recently added first. Search uses client-side fuzzy matching (token overlap + similarity scoring) so it handles typos and partial names. Use ongoingOnly to focus on currently ongoing series."
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

        if name == "get jellyfin series details":
            library_name = arguments.get("libraryName")
            item_name = arguments.get("name") or arguments.get("seriesName")
            if not library_name or not item_name:
                return _mcp_error_response(request_id, -32602, "libraryName and name are required")
            season = arguments.get("season")
            if season is not None:
                try:
                    season = int(season)
                except (TypeError, ValueError):
                    return _mcp_error_response(request_id, -32602, "season must be an integer")

            client = JellyfinClient.from_env()
            if not client:
                return _mcp_error_response(
                    request_id,
                    -32000,
                    "Jellyfin integration is not configured. Set ENABLE_JELLYFIN_INTEGRATION=true and JELLYFIN_API_KEY in .env",
                )
            try:
                result = await client.get_item_details(
                    library_name=library_name,
                    name=item_name,
                    season=season,
                )
                if season is None and result.get("type") == "series":
                    result["next"] = "Pass 'season' to get a per-episode list (title + audio/subtitle languages) for one season."
                logger.info("TOOL <<< %s (library=%s, item=%s)", name, library_name, item_name)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result)}],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                return _mcp_error_response(request_id, -32000, str(exc))

        if name == "get recently added in library":
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
                            "isError": True,
                        },
                    }
                )

            try:
                hours = arguments.get("hours", 72) or 72
                try:
                    hours = float(hours)
                except (TypeError, ValueError):
                    hours = 72.0
                result = await client.recently_added_items(
                    library_name=library_name,
                    limit=arguments.get("limit", 10),
                    hours=hours,
                )
                result["next"] = "These are the individual episodes and movies most recently added in Jellyfin (DateCreated descending). For recently added download files on disk, use 'downloads_recent_files'."
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
                            "isError": True,
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
                        "When the release becomes due, call 'release_tracker_lookup' with dueOnly=true, then check Jellyfin latest episodes, then update this marker again with the following expected release.",
                    ],
                    "next": "When this Release Tracker marker becomes due, call 'release_tracker_lookup' with dueOnly=true. After Jellyfin has the new episode, calculate the following release and call this store tool again.",
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
                        else "If the user wants to save a tracker value, call 'release_tracker_update'. If the user wants live verification instead, check Jellyfin latest episodes or another requested source."
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
                    "For each due item, call 'jellyfin_ongoing_latest_episodes' using the series name as search text and compare the returned latest episode to nextSeason and nextEpisode when those fields exist.",
                    "If the expected episode has arrived, calculate the following release and call 'release_tracker_update' again.",
                    "If the expected episode has not arrived yet, leave the marker unchanged so it stays due for the next cron run.",
                ]
                payload["next"] = "For each due item, check Jellyfin latest episodes. If the tracked episode has arrived, calculate the following release date and call 'release_tracker_update' again. If it has not arrived yet, leave the marker in place for the next cron run."
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
                    "Use 'release_tracker_lookup' with dueOnly=true when you want only the markers that should be checked now.",
                    "For a single-series stored lookup, prefer 'release_tracker_lookup' with seriesName because it avoids ambiguous list scanning.",
                ]
                payload["next"] = "Use this list to inspect tracked Release Tracker markers. Use 'release_tracker_lookup' with dueOnly=true to focus only on markers that should be checked now."
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

        if name == "release_tracker_update:invalid":
            return _mcp_error_response(request_id, -32602, "action must be 'store' or 'delete'")

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
