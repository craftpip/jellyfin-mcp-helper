from __future__ import annotations

import os

from app.ui.server import create_ui_app


app = create_ui_app(os.getenv("MCP_TARGET_URL", "http://jellysort:18327/mcp"))
