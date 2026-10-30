"""Structured JSON logging with secret redaction and per-operation correlation IDs."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timezone

operation_id: contextvars.ContextVar[str] = contextvars.ContextVar("operation_id", default="-")
_SECRET = re.compile(r"(?i)\b(password|secret|token|api[_-]?key|authorization)\b(\s*[:=]\s*)(\S+)")


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname, "logger": record.name,
            "operation_id": operation_id.get(), "message": redact(record.getMessage()),
        }, sort_keys=True)


def new_operation() -> str:
    op = "op-" + uuid.uuid4().hex[:12]
    operation_id.set(op)
    return op


def configure(level: int = logging.INFO, stream=None) -> logging.Logger:
    logger = logging.getLogger()
    for h in list(logger.handlers):
        if getattr(h, "_structured", False):
            logger.removeHandler(h)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler._structured = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger
