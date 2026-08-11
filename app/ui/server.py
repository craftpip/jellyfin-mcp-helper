from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "index.html"
REACT_INDEX_HTML = HERE / "react-dist" / "index.html"
REACT_ASSETS_DIR = HERE / "react-dist" / "assets"

MCP_TARGET_URL: str = ""


def create_ui_app(mcp_target_url: str) -> FastAPI:
    global MCP_TARGET_URL
    MCP_TARGET_URL = mcp_target_url

    ui_app = FastAPI(title="JellySort UI")

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

    @ui_app.get("/react")
    async def react_redirect():
        return RedirectResponse(url="/", status_code=308)

    @ui_app.get("/react/")
    async def react_index():
        return RedirectResponse(url="/", status_code=308)

    @ui_app.get("/legacy")
    async def legacy_redirect():
        return RedirectResponse(url="/legacy/", status_code=308)

    @ui_app.get("/legacy/")
    async def legacy_index():
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
