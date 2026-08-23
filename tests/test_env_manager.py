from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.env_manager import (
    ENV_FILE,
    ENV_SPEC,
    ENV_SPEC_KEYS,
    _field_for_key,
    _format_value,
    _parse_env_file,
    _rewrite_env,
    list_env,
    reload_settings,
    update_env,
)


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.env_manager.ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr("app.services.env_manager.ENV_SPEC_KEYS", {item["key"] for item in ENV_SPEC})
    yield
    from app.core.config import reset_settings

    reset_settings()


class TestParseEnvFile:
    def test_parses_key_values(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\nFOO=bar\n# another\nBAZ = \"quoted value\"\n", encoding="utf-8")
        result = _parse_env_file(env)
        assert result == {"FOO": "bar", "BAZ": "quoted value"}

    def test_missing_file_returns_empty(self, tmp_path):
        assert _parse_env_file(tmp_path / "nope.env") == {}

    def test_strips_quotes_and_comments(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text('A="x y z"\nB=# leading hash\n', encoding="utf-8")
        result = _parse_env_file(env)
        assert result == {"A": "x y z", "B": "# leading hash"}


class TestFormatValue:
    def test_plain(self):
        assert _format_value("ollama") == "ollama"

    def test_quotes_when_contains_hash_or_edges(self):
        assert _format_value("#hash") == '"#hash"'
        assert _format_value("  spaced  ") == '"  spaced  "'

    def test_escapes_embedded_quotes(self, tmp_path):
        # Bare values with embedded quotes round-trip through the parser.
        env = tmp_path / ".env"
        env.write_text(f"K={_format_value('a\"b')}\n", encoding="utf-8")
        assert _parse_env_file(env)["K"] == 'a"b'

    def test_multiline(self):
        assert _format_value("line1\nline2") == '"line1\\nline2"'


class TestRewriteEnv:
    def test_updates_in_place_preserving_comments(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# header\nMOVIE_ROOTS=/media1/movies\n# section\nUI_PANEL_PASSWORD=oldpass\n", encoding="utf-8")
        _rewrite_env({"MOVIE_ROOTS": "/media2/movies", "UI_PANEL_PASSWORD": "newpass"})
        text = env.read_text(encoding="utf-8")
        assert "# header" in text
        assert "# section" in text
        assert "MOVIE_ROOTS=/media2/movies" in text
        assert "UI_PANEL_PASSWORD=newpass" in text
        assert "oldpass" not in text

    def test_appends_new_keys(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("MOVIE_ROOTS=/media1/movies\n", encoding="utf-8")
        _rewrite_env({"MCP_DEFAULT_TOKEN": "secret"})
        text = env.read_text(encoding="utf-8")
        assert "MCP_DEFAULT_TOKEN=secret" in text
        assert "MOVIE_ROOTS=/media1/movies" in text

    def test_atomic_write_leaves_no_tmp(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("MOVIE_ROOTS=/media1/movies\n", encoding="utf-8")
        _rewrite_env({"MOVIE_ROOTS": "/media2/movies"})
        assert not list(tmp_path.glob("*.tmp"))


class TestFieldForKey:
    def test_maps_alias(self):
        assert _field_for_key("MOVIE_ROOTS") == "movie_roots"
        assert _field_for_key("MCP_ALLOW_UNAUTHENTICATED") == "mcp_allow_unauthenticated"

    def test_unknown_key(self):
        assert _field_for_key("NOPE") is None


class TestListEnv:
    def test_returns_spec_with_saved_and_effective(self, tmp_path, monkeypatch):
        for key in os.environ:
            if key in ENV_SPEC_KEYS or key in (item["key"] for item in ENV_SPEC):
                monkeypatch.delenv(key, raising=False)
        os.environ["MOVIE_ROOTS"] = "/media1/movies"
        (tmp_path / ".env").write_text("MOVIE_ROOTS=/media1/movies\n", encoding="utf-8")

        from app.core.config import reset_settings

        reset_settings()
        try:
            result = list_env()
        finally:
            reset_settings()

        assert "MOVIE_ROOTS" not in result["pending"]
        providers = [e for e in result["spec"] if e["key"] == "MOVIE_ROOTS"]
        assert providers
        assert providers[0]["saved"] == "/media1/movies"
        assert providers[0]["effective"] == "/media1/movies"
        assert providers[0]["apply"] == "restart"

    def test_secrets_masked(self, tmp_path, monkeypatch):
        for key in list(os.environ):
            if key in ENV_SPEC_KEYS:
                monkeypatch.delenv(key, raising=False)
        os.environ["MCP_DEFAULT_TOKEN"] = "super-secret"
        (tmp_path / ".env").write_text("MCP_DEFAULT_TOKEN=super-secret\n", encoding="utf-8")

        from app.core.config import reset_settings

        reset_settings()
        try:
            result = list_env()
        finally:
            reset_settings()

        entry = [e for e in result["spec"] if e["key"] == "MCP_DEFAULT_TOKEN"][0]
        assert entry["saved"] == "********"
        assert entry["effective"] == "********"
        assert "super-secret" not in str(result)

    def test_pending_detected(self, tmp_path, monkeypatch):
        for key in list(os.environ):
            if key in ENV_SPEC_KEYS:
                monkeypatch.delenv(key, raising=False)
        os.environ["MOVIE_ROOTS"] = "/media2/movies"
        (tmp_path / ".env").write_text("MOVIE_ROOTS=/media1/movies\n", encoding="utf-8")

        from app.core.config import reset_settings

        reset_settings()
        try:
            result = list_env()
        finally:
            reset_settings()

        assert "MOVIE_ROOTS" in result["pending"]


class TestUpdateEnv:
    def test_rejects_unknown_keys(self, tmp_path):
        with pytest.raises(ValueError, match="unknown setting"):
            update_env({"NOPE": "x"})

    def test_rejects_non_dict(self, tmp_path):
        with pytest.raises(ValueError):
            update_env(["not", "a", "dict"])

    def test_blank_secret_keeps_unchanged(self, tmp_path):
        (tmp_path / ".env").write_text("JELLYFIN_API_KEY=real\n", encoding="utf-8")
        result = update_env({"JELLYFIN_API_KEY": ""})
        assert result == {"appliedLive": [], "needsRecreate": []}
        assert _parse_env_file()[ "JELLYFIN_API_KEY"] == "real"

    def test_live_change_returns_applied_live(self, tmp_path):
        (tmp_path / ".env").write_text("MCP_ALLOW_UNAUTHENTICATED=true\n", encoding="utf-8")
        result = update_env({"MCP_ALLOW_UNAUTHENTICATED": "false"})
        assert result["appliedLive"] == ["MCP_ALLOW_UNAUTHENTICATED"]
        assert _parse_env_file()["MCP_ALLOW_UNAUTHENTICATED"] == "false"

    def test_restart_change_returns_needs_recreate(self, tmp_path):
        (tmp_path / ".env").write_text("MOVIE_ROOTS=/media1/movies\n", encoding="utf-8")
        result = update_env({"MOVIE_ROOTS": "/media2/movies"})
        assert result["needsRecreate"] == ["MOVIE_ROOTS"]
        assert result["appliedLive"] == []

    def test_invalid_value_rejected(self, tmp_path):
        (tmp_path / ".env").write_text("MODEL_CLASSIFY_CONFIDENCE_THRESHOLD=0.65\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid setting"):
            update_env({"MODEL_CLASSIFY_CONFIDENCE_THRESHOLD": "not-a-float"})

    def test_no_changes_returns_empty(self, tmp_path):
        (tmp_path / ".env").write_text("MOVIE_ROOTS=/media1/movies\n", encoding="utf-8")
        assert update_env({}) == {"appliedLive": [], "needsRecreate": []}


class TestReloadSettings:
    def test_saved_env_becomes_effective_without_restart(self, tmp_path, monkeypatch):
        # .env is authoritative: a saved value wins over an older inherited
        # env var as soon as the cache is reset — no os.environ patching.
        monkeypatch.setenv("JELLYFIN_BASE_URL", "http://old:8096")
        monkeypatch.setattr("app.core.config.DOTENV_PATH", tmp_path / ".env")
        (tmp_path / ".env").write_text("JELLYFIN_BASE_URL=http://jellyfin.local:8096\n", encoding="utf-8")
        reload_settings()
        assert get_settings().jellyfin_base_url == "http://jellyfin.local:8096"
        assert os.environ.get("JELLYFIN_BASE_URL") == "http://old:8096"

    def test_env_var_falls_back_when_key_missing_from_dotenv(self, tmp_path, monkeypatch):
        # A key absent from .env falls back to the inherited process env.
        monkeypatch.setenv("MOVIE_ROOTS", "/media1/movies")
        monkeypatch.setattr("app.core.config.DOTENV_PATH", tmp_path / ".env")
        (tmp_path / ".env").write_text("", encoding="utf-8")
        reload_settings()
        assert get_settings().movie_roots == "/media1/movies"
