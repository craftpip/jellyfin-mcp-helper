from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, Request

from app.core.config import get_settings


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

    - JELLYSORT_MCP_TOKEN empty -> pass, user is "anonymous".
    - Otherwise the presented Bearer/X-API-Key must equal the token.
      Valid token sets request.state.mcp_user to "admin" for logging.
    """
    settings = get_settings()
    token = settings.mcp_token
    if not token:
        request.state.mcp_user = "anonymous"
        return

    raw_key = _extract_api_key(authorization, x_api_key)
    if not raw_key:
        request.state.mcp_user = None
        raise MCPUnauthorizedError()

    if hmac.compare_digest(raw_key, token):
        request.state.mcp_user = "admin"
        return

    request.state.mcp_user = None
    raise MCPUnauthorizedError()
