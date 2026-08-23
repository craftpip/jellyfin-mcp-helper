"""Shared pytest fixtures.

The real /app/.env (bind-mounted production config) must never leak into the
test suite: get_settings() feeds parsed .env entries as init kwargs with
highest precedence, which would override monkeypatch.setenv values. Pointing
DOTENV_PATH at a nonexistent file restores pure-os.environ semantics for every
test; env-manager tests opt back in by re-pointing it at their tmp .env.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_dotenv(monkeypatch, tmp_path):
    from app.core.config import reset_settings

    monkeypatch.setattr("app.core.config.DOTENV_PATH", tmp_path / "does-not-exist.env")
    reset_settings()
    yield
    reset_settings()
