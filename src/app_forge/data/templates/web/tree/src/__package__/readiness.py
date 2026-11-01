"""Liveness and readiness state with explicit dependency checks."""
from __future__ import annotations
from collections.abc import Callable
_checks: dict[str, Callable[[], bool]] = {}

def register_readiness_check(name: str, check: Callable[[], bool]) -> None:
    if not isinstance(name, str) or not name or name in _checks:
        raise ValueError("readiness check name must be unique and non-empty")
    if not callable(check):
        raise TypeError("readiness check must be callable")
    _checks[name] = check

def clear_readiness_checks() -> None:
    _checks.clear()

def liveness_payload() -> dict:
    return {"status": "ok"}

def readiness_payload() -> tuple[dict, int]:
    results: dict[str, bool] = {}
    for name, check in _checks.items():
        try:
            results[name] = check() is True
        except Exception:
            results[name] = False
    ready = all(results.values())
    return {"status": "ready" if ready else "not_ready", "checks": results}, 200 if ready else 503
