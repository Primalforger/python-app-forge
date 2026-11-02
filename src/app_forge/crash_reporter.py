"""Local-only, privacy-conscious desktop crash reports.

Reports contain exception type, a redacted message and traceback text. Local variables,
environment variables and process memory are never collected; this module performs no
network I/O.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app_forge.security import redact


_SENSITIVE = re.compile(
    r"(?i)(bearer\\s+)[A-Za-z0-9._~+/-]+=*|"
    r"((?:https?://)[^:/\\s]+:)[^@/\\s]+@|"
    r"([?&](?:token|key|secret|password)=)[^&\\s]+"
)


def _clean(value: str, home: Path) -> str:
    value = redact(value)
    value = _SENSITIVE.sub(lambda m: (m.group(1) or "") + "[REDACTED]", value)
    value = value.replace(str(home), "~")
    return value[:32_000]


class CrashReporter:
    """Write bounded JSON reports beneath a caller-selected local directory."""

    def __init__(self, directory: Path, *, max_reports: int = 20):
        if isinstance(max_reports, bool) or not isinstance(max_reports, int) or not 1 <= max_reports <= 500:
            raise ValueError("max_reports must be between 1 and 500")
        self.directory = Path(directory)
        self.max_reports = max_reports
        self.home = Path.home()

    def capture_exception(self, exc: BaseException, *, context: str = "desktop") -> Path:
        if not isinstance(exc, BaseException):
            raise TypeError("exc must be an exception")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)
        trace = "".join(traceback.TracebackException.from_exception(exc, capture_locals=False).format())
        payload = {
            "schema": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context": _clean(str(context), self.home)[:120],
            "exception_type": type(exc).__name__[:200],
            "message": _clean(str(exc), self.home)[:4000],
            "traceback": _clean(trace, self.home),
            "network_upload": False,
        }
        name = f"crash-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:12]}.json"
        fd, temp_name = tempfile.mkstemp(prefix=".crash-", suffix=".tmp", dir=self.directory)
        temp = Path(temp_name)
        target = self.directory / name
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        self._prune()
        return target

    def _prune(self) -> None:
        reports = sorted(self.directory.glob("crash-*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
        for old in reports[self.max_reports:]:
            old.unlink(missing_ok=True)
