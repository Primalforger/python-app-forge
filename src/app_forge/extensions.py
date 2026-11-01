"""Extension discovery, trust decisions and isolated invocation (MOD-15/G-16)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Callable

from app_forge.domain.errors import SecurityBlock, ValidationFailure
from app_forge.security import TrustPolicy, safe_environ

GROUP = "app_forge.plugins"
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576


class ExtensionHost:
    def __init__(self, store, entry_points: Callable[[], list] | None = None, *, timeout: float = 10.0):
        self._store = store
        self._trust = TrustPolicy(store)
        self._eps = entry_points or (lambda: list(metadata.entry_points(group=GROUP)))
        self._timeout = timeout

    def _find(self, name: str):
        for ep in self._eps():
            if ep.name == name:
                return ep
        raise ValidationFailure(f"No extension named {name!r} is installed",
                                hint=f"Extensions advertise themselves via the '{GROUP}' entry-point group.")

    def discover(self) -> list[dict]:
        """List installed extensions from package metadata. Does NOT import their code."""
        enabled = self._store.enabled_plugins()
        return [{"name": ep.name, "target": ep.value, "trust": self._trust.level(ep.name),
                 "enabled": ep.name in enabled} for ep in self._eps()]

    def inspect(self, name: str) -> dict:
        ep = self._find(name)
        return {"name": ep.name, "target": ep.value, "group": GROUP, "trust": self._trust.level(name),
                "enabled": name in self._store.enabled_plugins(),
                "isolation": "separate worker process; no OS sandbox (trusted extensions only)"}

    def trust(self, name: str, level: str = "trusted") -> dict:
        self._find(name)
        if level not in ("trusted", "untrusted"):
            raise ValidationFailure("Trust level must be 'trusted' or 'untrusted'")
        self._store.set_trust(name, level)
        if level == "untrusted":
            self._store.set_enabled_plugin(name, False)
        return self.inspect(name)

    def enable(self, name: str) -> dict:
        self._find(name)
        self._trust.require_trusted(name)
        self._store.set_enabled_plugin(name, True)
        return self.inspect(name)

    def disable(self, name: str) -> dict:
        self._find(name)
        self._store.set_enabled_plugin(name, False)
        return self.inspect(name)

    def invoke(self, name: str, method: str, *args, **kwargs):
        """Invoke a public extension method in a child process using JSON-only IPC.

        Process separation limits host-process failure propagation. It is NOT a
        sandbox: trusted extension code still has the OS permissions of this user.
        """
        self._find(name)
        self._trust.require_trusted(name)
        if name not in self._store.enabled_plugins():
            raise SecurityBlock(f"Extension {name!r} is not enabled", hint=f"forge plugin enable {name}")
        if not isinstance(method, str) or not method or method.startswith("_"):
            raise ValidationFailure("Extension method must be a public method name")
        request = {"version": PROTOCOL_VERSION, "plugin": name, "method": method,
                   "args": list(args), "kwargs": kwargs}
        try:
            encoded = json.dumps(request, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as exc:
            raise ValidationFailure(f"Extension IPC arguments must be JSON data: {exc}") from None
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ValidationFailure("Extension IPC request exceeds the 1 MiB limit")
        package_root = str(Path(__file__).resolve().parent.parent)
        env = safe_environ()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH", ""))))
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "app_forge.extension_worker"],
                input=encoded, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=tempfile.gettempdir(), env=env, timeout=self._timeout,
                shell=False, check=False,
            )
        except subprocess.TimeoutExpired:
            raise SecurityBlock(f"Extension {name!r} exceeded the {self._timeout:g}s execution timeout") from None
        if len(completed.stdout) > MAX_MESSAGE_BYTES:
            raise SecurityBlock(f"Extension {name!r} returned an oversized IPC response")
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SecurityBlock(f"Extension {name!r} worker exited without a valid IPC response") from None
        if (not isinstance(response, dict) or response.get("version") != PROTOCOL_VERSION
                or not isinstance(response.get("ok"), bool)):
            raise SecurityBlock(f"Extension {name!r} returned an invalid IPC frame")
        if not response["ok"]:
            raise SecurityBlock(f"Extension {name!r} failed: {response.get('message', response.get('error', 'worker error'))}")
        if completed.returncode != 0:
            raise SecurityBlock(f"Extension {name!r} worker exited unexpectedly ({completed.returncode})")
        return response.get("result")
