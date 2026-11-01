"""Security Services (MOD-13): safe paths, secret redaction, safe subprocesses, trust policy."""
from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from app_forge.domain.errors import OperationCancelled, SecurityBlock

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


def _stop_process(proc: subprocess.Popen, *, process_group: bool, grace: float = 1.0) -> tuple[str, str]:
    """Terminate a child (and its POSIX descendants), escalating to kill and always reaping it."""
    if process_group and os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif proc.poll() is None:
        proc.terminate()
    try:
        return proc.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            if process_group and os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            elif proc.poll() is None:
                proc.kill()
        except ProcessLookupError:
            pass
        return proc.communicate()


def run_command(args: list[str], *, cwd: Path, timeout: float = 600, env: dict | None = None,
                inherit_env: bool = True, cancel_token=None, poll_interval: float = 0.1) -> subprocess.CompletedProcess:
    """Run an explicit command, optionally stopping it promptly when a cancellation token is set.

    POSIX commands run in a new session so cancellation also terminates their child processes.
    Existing timeout, environment, capture and no-shell behavior is preserved.
    """
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise SecurityBlock("Commands must be explicit argument lists")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    full_env = {**(os.environ if inherit_env else {}), **(env or {})}
    kwargs = {"cwd": str(cwd), "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
              "text": True, "env": full_env, "shell": False}
    process_group = os.name == "posix"
    if process_group:
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(args, **kwargs)
    started = time.monotonic()
    try:
        while True:
            if cancel_token is not None and cancel_token.cancelled:
                _stop_process(proc, process_group=process_group)
                raise OperationCancelled("Operation cancelled by user")
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                stdout, stderr = _stop_process(proc, process_group=process_group)
                raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
            try:
                stdout, stderr = proc.communicate(timeout=min(poll_interval, remaining))
                return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        if proc.poll() is None:
            _stop_process(proc, process_group=process_group)
        raise


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
