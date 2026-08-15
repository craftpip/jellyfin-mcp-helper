from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, Request

from app.core.config import get_settings
from app.services.api_key_manager import ApiKeyManager


class MCPUnauthorizedError(Exception):
    """Raised when an MCP request is rejected: auth is required and the presented
    key is missing or invalid. Converted to HTTP 401 with a JSON-RPC error body
    by an exception handler on the MCP app."""


def _extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token and x_api_key:
        token = x_api_key.strip()
    return token or None


def require_mcp_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Gate /mcp requests.

    - MCP_ALLOW_UNAUTHENTICATED=true (default) -> pass, user is "anonymous".
    - Otherwise a valid API key from the key store or ADMIN_UI_TOKEN is required.
      Valid keys set request.state.mcp_user so the activity log can show "as <user>".
    """
    settings = get_settings()
    if settings.mcp_allow_unauthenticated:
        request.state.mcp_user = "anonymous"
        return

    raw_key = _extract_api_key(authorization, x_api_key)
    if not raw_key:
        request.state.mcp_user = None
        raise MCPUnauthorizedError()

    admin_token = settings.admin_ui_token
    if admin_token and hmac.compare_digest(raw_key, admin_token):
        request.state.mcp_user = "admin"
        return

    record = ApiKeyManager().authenticate(raw_key)
    if record is None:
        request.state.mcp_user = None
        raise MCPUnauthorizedError()

    request.state.mcp_user = record.get("user") or "default"
