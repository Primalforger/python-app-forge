"""Observability (MOD-16): operation IDs and structured logs shared by CLI/GUI/services."""
from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone

from app_forge.security import redact
from app_forge.crash_reporter import CrashReporter


def new_operation_id() -> str:
    return "op-" + uuid.uuid4().hex[:12]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": utcnow(), "level": record.levelname, "logger": record.name,
                   "message": redact(record.getMessage())}
        for key in ("operation_id", "operation", "target", "outcome"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, sort_keys=True)


def get_logger(verbosity: int = 0) -> logging.Logger:
    logger = logging.getLogger("app_forge")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel({0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG))
    return logger
