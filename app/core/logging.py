from __future__ import annotations

import contextvars
import logging

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def set_request_id(value: str | None) -> None:
    _request_id_var.set(value)


def get_request_id() -> str | None:
    return _request_id_var.get()


def configure_logging() -> None:
    import json
    import os

    log_format = os.getenv("LOG_FORMAT", "").strip().lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

    # Add request_id to every record via filter — works for both json and plain
    class RequestIdFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            rid = get_request_id()
            if rid and not hasattr(record, "request_id"):
                record.request_id = rid
            elif not hasattr(record, "request_id"):
                record.request_id = ""
            return True

    req_filter = RequestIdFilter()

    if log_format == "json":
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                req_id = getattr(record, "request_id", "") or get_request_id()
                if req_id:
                    payload["request_id"] = req_id
                if record.exc_info and record.exc_info[0] is not None:
                    payload["exc"] = self.formatException(record.exc_info)
                return json.dumps(payload, ensure_ascii=False)

        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.addFilter(req_filter)
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(getattr(logging, log_level, logging.INFO))
        # also attach filter to already-created handlers for propagation
        for h in logging.getLogger().handlers:
            h.addFilter(req_filter)
    else:
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(message)s",
            force=True,
        )
        # attach filter after basicConfig (for JSON request_id propagation, plain keeps simple format)
        for h in logging.getLogger().handlers:
            h.addFilter(req_filter)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Reduce noise from guessit internals
    logging.getLogger("guessit").setLevel(logging.WARNING)
