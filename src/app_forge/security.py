"""Security Services (MOD-13): safe paths, secret redaction, safe subprocesses, trust policy."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from app_forge.domain.errors import SecurityBlock

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b(\s*[:=]\s*)(\S+)"),
    re.compile(r"\b(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
]


def redact(text: str) -> str:
    """Remove likely secrets from text destined for logs, reports or history."""
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return _SECRET_PATTERNS[1].sub("[REDACTED]", text)


def safe_join(root: Path, relative: str) -> Path:
    """Resolve `relative` under `root`, rejecting traversal, absolute paths and symlink escapes."""
    if not relative or relative.strip() != relative:
        raise SecurityBlock(f"Unsafe path {relative!r}")
    norm = relative.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in norm.split("/"):
        raise SecurityBlock(f"Path {relative!r} escapes the project root",
                            hint="Component destinations must be relative paths inside the project.")
    root_resolved = Path(root).resolve()
    candidate = root_resolved.joinpath(*norm.split("/"))
    # Resolve through any existing symlinks to catch escapes.
    probe = candidate
    while not probe.exists() and probe != root_resolved:
        probe = probe.parent
    real = probe.resolve()
    if real != root_resolved and root_resolved not in real.parents:
        raise SecurityBlock(f"Path {relative!r} resolves outside the project root via a symlink")
    return candidate


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
                 "HOME", "USERPROFILE", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "VIRTUAL_ENV")


def safe_environ(passthrough: tuple[str, ...] = ()) -> dict[str, str]:
    """A minimal environment for running untrusted project code: no tokens, keys or other secrets by default."""
    keep = set(SAFE_ENV_KEYS) | set(passthrough)
    return {k: v for k, v in os.environ.items() if k in keep}


def run_command(args: list[str], *, cwd: Path, timeout: float = 600, env: dict | None = None,
                inherit_env: bool = True) -> subprocess.CompletedProcess:
    """Run an executable with an explicit argument list. Never uses a shell.

    With inherit_env=False only `env` is passed (use safe_environ() as a base for untrusted code).
    """
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise SecurityBlock("Commands must be explicit argument lists")
    full_env = {**(os.environ if inherit_env else {}), **(env or {})}
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                          env=full_env, shell=False)


class TrustPolicy:
    """Presence in a catalog or in the entry-point list never authorises execution."""

    def __init__(self, store):
        self._store = store

    def level(self, plugin_id: str) -> str:
        return self._store.get_trust(plugin_id) or "untrusted"

    def require_trusted(self, plugin_id: str) -> None:
        if self.level(plugin_id) not in ("trusted", "builtin"):
            raise SecurityBlock(
                f"Extension {plugin_id!r} is not trusted and will not be executed",
                hint=f"Review it, then run: forge plugin trust {plugin_id}")
