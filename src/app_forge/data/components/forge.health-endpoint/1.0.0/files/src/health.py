"""Health payload shared by the HTTP endpoint and its tests (framework independent)."""
from __future__ import annotations

import time

_STARTED = time.monotonic()


def health_payload(checks: dict[str, bool] | None = None) -> dict:
    """Overall status is 'ok' only if every named check is exactly True."""
    checks = dict(checks or {})
    ok = all(v is True for v in checks.values())
    return {"status": "ok" if ok else "degraded", "uptime_s": round(time.monotonic() - _STARTED, 1), "checks": checks}
