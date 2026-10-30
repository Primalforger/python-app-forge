"""Project locks: one mutating Forge operation per project at a time (G-05).

Locks live in the platform home (never inside the project, so they cannot dirty a repository).
A lock whose owning process on this host has died is detected as stale and taken over.
"""
from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app_forge.domain.errors import ConflictFailure
from app_forge.security import sha256_text


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) is not a safe probe on Windows
        import ctypes
        from ctypes import wintypes
        k32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return getattr(ctypes, "get_last_error")() == 5  # ACCESS_DENIED: it exists, we may not inspect it
        try:
            code = wintypes.DWORD()
            # An exited process can still be opened while anyone holds a handle: check it is really running.
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path(locks_dir: Path, project: Path) -> Path:
    return locks_dir / (sha256_text(str(Path(project).resolve()))[:24] + ".lock")


def read_lock(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@contextmanager
def project_lock(locks_dir: Path, project: Path, operation: str) -> Iterator[Path]:
    locks_dir.mkdir(parents=True, exist_ok=True)
    path = lock_path(locks_dir, project)
    info = {"pid": os.getpid(), "host": socket.gethostname(), "operation": operation,
            "project": str(Path(project).resolve()), "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = read_lock(path)
            if held and held.get("host") == info["host"] and not pid_alive(int(held.get("pid", 0))):
                try:
                    path.unlink()  # stale: its owner is gone
                except FileNotFoundError:
                    pass
                continue
            who = held or {}
            raise ConflictFailure(
                f"Project is locked by another Forge operation ({who.get('operation', '?')}, pid {who.get('pid', '?')} "
                f"on {who.get('host', '?')}, since {who.get('since', '?')})",
                hint="Wait for it to finish. If you are sure it is dead: forge project unlock PATH --yes")
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(info, fh)
            break
    else:
        raise ConflictFailure("Could not acquire the project lock")
    try:
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
