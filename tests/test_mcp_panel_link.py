"""'jellysort_panel_link' — LAN URL of the web panel."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import _panel_link, app


def _settings(**overrides):
    base = dict(
        panel_public_url="",
        panel_port=18328,
        jellyfin_base_url="http://192.168.50.7:8096",
        ui_panel_password="",
        web_ui_enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _request(host: str | None, proto: str | None = None):
    headers = {}
    if host:
        headers["host"] = host
    if proto:
        headers["x-forwarded-proto"] = proto
    return SimpleNamespace(headers=headers, url=SimpleNamespace(scheme="http"))


def test_explicit_panel_public_url_wins() -> None:
    result = _panel_link(_request("192.168.50.9:18328"), _settings(panel_public_url="http://panel.lan:9000/"))
    assert result["url"] == "http://panel.lan:9000/"
    assert result["pages"] == {
        "scan": "http://panel.lan:9000/",
        "history": "http://panel.lan:9000/history",
        "settings": "http://panel.lan:9000/settings",
    }
    assert result["source"] == "PANEL_PUBLIC_URL"
    assert "note" not in result


def test_explicit_url_without_scheme_gets_http() -> None:
    assert _panel_link(None, _settings(panel_public_url="192.168.50.9:18328"))["url"] == "http://192.168.50.9:18328/"


def test_lan_host_header_is_used_exactly() -> None:
    result = _panel_link(_request("192.168.50.9:18328", proto="https"), _settings())
    assert result["url"] == "https://192.168.50.9:18328/"
    assert result["source"] == "MCP request Host header"


@pytest.mark.parametrize("host", ["127.0.0.1:18327", "localhost:18328", "172.17.0.2:18327", "[::1]:18328"])
def test_loopback_or_container_port_falls_back_to_jellyfin_host(host: str) -> None:
    result = _panel_link(_request(host), _settings())
    assert result["url"] == "http://192.168.50.7:18328/"
    assert result["source"] == "JELLYFIN_BASE_URL host + PANEL_PORT"
    assert "PANEL_PUBLIC_URL" in result["note"]


def test_fallback_uses_panel_port() -> None:
    assert _panel_link(None, _settings(panel_port=8080))["url"] == "http://192.168.50.7:8080/"


def test_no_usable_address_raises_with_fix() -> None:
    with pytest.raises(ValueError, match="PANEL_PUBLIC_URL"):
        _panel_link(_request("127.0.0.1:18327"), _settings(jellyfin_base_url="http://localhost:8096"))


def test_login_and_disabled_ui_are_reported() -> None:
    result = _panel_link(None, _settings(ui_panel_password="x", web_ui_enabled=False))
    assert result["login_required"] is True
    assert "password" in result["next"]
    assert "WEB_UI_ENABLED" in result["warning"]


def test_mcp_tool_uses_request_host(monkeypatch) -> None:
    monkeypatch.setattr("app.main.get_settings", lambda: _settings())
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            headers={"host": "192.168.50.9:18328"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "jellysort_panel_link", "arguments": {}}},
        )
    result = resp.json()["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["url"] == "http://192.168.50.9:18328/"
    assert payload["pages"]["history"] == "http://192.168.50.9:18328/history"
