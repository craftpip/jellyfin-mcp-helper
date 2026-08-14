from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import get_settings

_sessions: set[str] = set()


def password_required() -> bool:
    return bool(get_settings().ui_panel_password)


def login(password: str) -> dict:
    stored = get_settings().ui_panel_password
    if not stored:
        return {"token": "", "directLogin": True}
    if not isinstance(password, str) or not hmac.compare_digest(password, stored):
        raise HTTPException(status_code=401, detail="invalid password")
    token = secrets.token_hex(16)
    _sessions.add(token)
    return {"token": token}


def logout(token: str | None = None) -> None:
    if token:
        _sessions.discard(token)


def require_panel_auth(
    authorization: Annotated[str | None, Header()] = None,
    x_panel_token: Annotated[str | None, Header()] = None,
) -> None:
    if not password_required():
        return
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token and x_panel_token:
        token = x_panel_token.strip()
    if token and token in _sessions:
        return
    raise HTTPException(status_code=401, detail="not authenticated")
