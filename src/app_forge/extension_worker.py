"""Child-process entry point for the versioned extension IPC protocol.

This is process separation, not an OS sandbox. Callers must not treat it as a
security boundary against a malicious extension.
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import json
import sys

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576


def _emit(payload: dict) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC response exceeds the size limit")
    output = sys.__stdout__
    if output is None:
        raise RuntimeError("worker stdout is unavailable")
    output.write(encoded + "\n")
    output.flush()


def main() -> int:
    raw = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
    if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
        _emit({"version": PROTOCOL_VERSION, "ok": False, "error": "invalid_request"})
        return 2
    try:
        request = json.loads(raw)
        if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
            raise ValueError("unsupported protocol")
        name, method = request.get("plugin"), request.get("method")
        args, kwargs = request.get("args", []), request.get("kwargs", {})
        if (not isinstance(name, str) or not name or not isinstance(method, str)
                or not method or method.startswith("_") or not isinstance(args, list)
                or not isinstance(kwargs, dict)):
            raise ValueError("invalid request fields")
        # stdout is reserved for IPC; extension output cannot corrupt the frame.
        with contextlib.redirect_stdout(sys.stderr):
            matches = [ep for ep in importlib.metadata.entry_points(group="app_forge.plugins")
                       if ep.name == name]
            if len(matches) != 1:
                raise LookupError("extension entry point is missing or ambiguous")
            plugin = matches[0].load()
            if isinstance(plugin, type):
                plugin = plugin()
            target = getattr(plugin, method, None)
            if not callable(target):
                raise AttributeError("extension method is not callable")
            result = target(*args, **kwargs)
        # JSON round-trip enforces the data-only IPC contract.
        result = json.loads(json.dumps(result, allow_nan=False))
        _emit({"version": PROTOCOL_VERSION, "ok": True, "result": result})
        return 0
    except Exception as exc:
        _emit({"version": PROTOCOL_VERSION, "ok": False,
               "error": "extension_error", "message": f"{type(exc).__name__}: {exc}"[:2000]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
