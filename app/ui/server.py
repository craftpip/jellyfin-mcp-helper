from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "index.html"

MCP_TARGET_URL: str = ""


def create_ui_app(mcp_port: int) -> FastAPI:
    global MCP_TARGET_URL
    MCP_TARGET_URL = f"http://localhost:{mcp_port}/mcp"

    ui_app = FastAPI(title="jellyfin-mcp-helper UI")

    @ui_app.get("/")
    async def index():
        html = INDEX_HTML.read_text(encoding="utf-8")
        return HTMLResponse(html)

    @ui_app.api_route("/mcp", methods=["GET", "POST", "OPTIONS"])
    async def proxy_mcp(request: Request):
        if request.method == "OPTIONS":
            return JSONResponse(content={})

        body = await request.body()
        headers = {
            "Content-Type": request.headers.get("Content-Type", "application/json"),
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                resp = await client.post(
                    MCP_TARGET_URL,
                    content=body,
                    headers=headers,
                )
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
            except httpx.ConnectError:
                logger.warning("UI proxy: MCP server not reachable at %s", MCP_TARGET_URL)
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32000,
                            "message": f"MCP server not reachable at {MCP_TARGET_URL}",
                        },
                    },
                    status_code=502,
                )

    return ui_app
