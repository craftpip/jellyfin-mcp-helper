from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import _extract_api_key, require_mcp_auth
from app.main import app


def _post_mcp(client: TestClient, headers: dict | None = None) -> object:
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers,
    )
    return resp


class TestExtractApiKey:
    def test_bearer_header(self):
        assert _extract_api_key("Bearer abc123", None) == "abc123"

    def test_x_api_key_fallback(self):
        assert _extract_api_key(None, "xyz") == "xyz"

    def test_bearer_wins_over_x_api_key(self):
        assert _extract_api_key("Bearer abc", "xyz") == "abc"

    def test_case_insensitive_bearer(self):
        assert _extract_api_key("bearer abc", None) == "abc"

    def test_empty(self):
        assert _extract_api_key(None, None) is None
        assert _extract_api_key("Basic abc", None) is None


class TestMcpAuthEnabled:
    def test_unauthenticated_requires_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JELLYSORT_MCP_TOKEN", "secret123")
        monkeypatch.delenv("MCP_DEFAULT_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_UI_TOKEN", raising=False)

        from app.core.config import reset_settings

        reset_settings()
        try:
            with TestClient(app) as client:
                resp = _post_mcp(client)
                assert resp.status_code == 401
                body = resp.json()
                assert body["error"]["code"] == -32001
                assert body["error"]["message"] == "unauthorized"
        finally:
            reset_settings()

    def test_valid_token_passes_bearer(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JELLYSORT_MCP_TOKEN", "secret123")
        monkeypatch.delenv("MCP_DEFAULT_TOKEN", raising=False)

        from app.core.config import reset_settings

        reset_settings()
        try:
            with TestClient(app) as client:
                resp = _post_mcp(client, {"Authorization": "Bearer secret123"})
                assert resp.status_code == 200
                assert "result" in resp.json()
        finally:
            reset_settings()

    def test_x_api_key_header_passes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JELLYSORT_MCP_TOKEN", "secret123")

        from app.core.config import reset_settings

        reset_settings()
        try:
            with TestClient(app) as client:
                resp = _post_mcp(client, {"X-API-Key": "secret123"})
                assert resp.status_code == 200
        finally:
            reset_settings()

    def test_deprecated_mcp_default_token_accepted(self, monkeypatch, tmp_path):
        monkeypatch.delenv("JELLYSORT_MCP_TOKEN", raising=False)
        monkeypatch.setenv("MCP_DEFAULT_TOKEN", "super-secret-token")

        from app.core.config import reset_settings

        reset_settings()
        try:
            with TestClient(app) as client:
                resp = _post_mcp(client, {"Authorization": "Bearer super-secret-token"})
                assert resp.status_code == 200
                assert resp.json()["result"]["tools"]
        finally:
            reset_settings()

    def test_wrong_token_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JELLYSORT_MCP_TOKEN", "secret123")

        from app.core.config import reset_settings

        reset_settings()
        try:
            with TestClient(app) as client:
                resp = _post_mcp(client, {"Authorization": "Bearer wrong"})
                assert resp.status_code == 401
        finally:
            reset_settings()


class TestMcpAuthDisabledByDefault:
    def test_anonymous_passes_by_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("JELLYSORT_MCP_TOKEN", raising=False)
        monkeypatch.delenv("MCP_DEFAULT_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_UI_TOKEN", raising=False)

        from app.core.config import reset_settings

        reset_settings()
        try:
            with TestClient(app) as client:
                resp = _post_mcp(client)
                assert resp.status_code == 200
        finally:
            reset_settings()


class TestRequireMcpAuthUser:
    def test_anonymous_user_when_open(self, monkeypatch, tmp_path):
        class FakeRequest:
            state = type("State", (), {})()

        monkeypatch.delenv("JELLYSORT_MCP_TOKEN", raising=False)
        monkeypatch.delenv("MCP_DEFAULT_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_UI_TOKEN", raising=False)

        from app.core.config import reset_settings

        reset_settings()
        try:
            from fastapi import Header

            require_mcp_auth(FakeRequest(), Header())
        finally:
            reset_settings()
        assert FakeRequest.state.mcp_user == "anonymous"

    def test_admin_user_from_token(self, monkeypatch, tmp_path):
        class FakeRequest:
            state = type("State", (), {})()

        monkeypatch.setenv("JELLYSORT_MCP_TOKEN", "tok")
        monkeypatch.delenv("MCP_DEFAULT_TOKEN", raising=False)

        from app.core.config import reset_settings

        reset_settings()
        try:
            require_mcp_auth(FakeRequest(), "Bearer tok")
        finally:
            reset_settings()
        assert FakeRequest.state.mcp_user == "admin"
