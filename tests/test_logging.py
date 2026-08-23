from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import configure_logging, get_request_id, set_request_id


@pytest.fixture(autouse=True)
def _restore_logging():
    yield
    configure_logging()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "INFO")


def test_json_format_includes_request_id(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    set_request_id("abc123")

    logging.getLogger("app.test").info("hello resolver")

    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "hello resolver"
    assert payload["request_id"] == "abc123"
    assert payload["level"] == "INFO"


def test_json_format_omits_request_id_when_unset(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    set_request_id(None)

    logging.getLogger("app.test").info("no rid")

    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "request_id" not in payload


def test_plain_mode_attaches_request_id_attribute():
    configure_logging()
    set_request_id("rid42")

    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    # configure_logging replaces root handlers, so attach AFTER it runs
    logging.getLogger().addHandler(Capture(level=logging.INFO))
    try:
        logging.getLogger("app.test").info("plain line")
    finally:
        root = logging.getLogger()
        root.handlers = [h for h in root.handlers if not isinstance(h, Capture)]

    assert getattr(records[-1], "request_id", "") == "rid42"
    set_request_id(None)
