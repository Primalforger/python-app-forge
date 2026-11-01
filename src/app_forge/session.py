"""Portable persistence for recent files and desktop session state.

The stores contain JSON data only; they never deserialize executable objects.
Writes use atomic replacement so interrupted saves do not leave partial state.
"""
from __future__ import annotations

import builtins
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_SCHEMA = 1
_MAX_SESSION_BYTES = 1_048_576


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != _SCHEMA:
        raise ValueError(f"{label} has an unsupported or invalid format")
    return raw


def _normalize_path(value: str | Path) -> str:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("file path must be a non-empty string or Path")
    return str(Path(value).expanduser().resolve(strict=False))


class RecentFilesStore:
    """Maintain a bounded, newest-first list of recently opened file paths."""

    def __init__(self, path: str | Path, max_items: int = 10):
        if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 100:
            raise ValueError("max_items must be an integer from 1 to 100")
        self.path = Path(path)
        self.max_items = max_items

    def list(self, *, existing_only: bool = False) -> builtins.list[str]:
        raw = _read_json(self.path, "recent files")
        entries = raw.get("files", [])
        if not isinstance(entries, list) or any(not isinstance(item, str) or not item for item in entries):
            raise ValueError("recent files data is malformed")
        seen: set[str] = set()
        result = []
        for item in entries:
            normalized = _normalize_path(item)
            key = os.path.normcase(normalized).casefold()
            if key in seen:
                continue
            seen.add(key)
            if existing_only and not Path(normalized).is_file():
                continue
            result.append(normalized)
        return result[: self.max_items]

    def add(self, path: str | Path) -> builtins.list[str]:
        normalized = _normalize_path(path)
        key = os.path.normcase(normalized).casefold()
        entries = [normalized] + [item for item in self.list() if os.path.normcase(item).casefold() != key]
        entries = entries[: self.max_items]
        _atomic_json(self.path, {"schema": _SCHEMA, "files": entries})
        return entries.copy()

    def remove(self, path: str | Path) -> bool:
        normalized = _normalize_path(path)
        key = os.path.normcase(normalized).casefold()
        entries = self.list()
        remaining = [item for item in entries if os.path.normcase(item).casefold() != key]
        if len(remaining) == len(entries):
            return False
        _atomic_json(self.path, {"schema": _SCHEMA, "files": remaining})
        return True

    def clear(self) -> None:
        _atomic_json(self.path, {"schema": _SCHEMA, "files": []})


class SessionStateStore:
    """Persist a bounded JSON object containing desktop window/session metadata."""

    def __init__(self, path: str | Path, *, max_bytes: int = _MAX_SESSION_BYTES):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 16_777_216:
            raise ValueError("max_bytes must be an integer from 1 to 16777216")
        self.path = Path(path)
        self.max_bytes = max_bytes

    def load(self) -> dict[str, Any]:
        raw = _read_json(self.path, "session state")
        state = raw.get("state", {})
        if not isinstance(state, dict):
            raise ValueError("session state must be a JSON object")
        self._validate(state)
        return state

    def save(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict):
            raise ValueError("session state must be a JSON object")
        self._validate(state)
        payload = {"schema": _SCHEMA, "state": state}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError(f"session state exceeds the {self.max_bytes}-byte limit")
        _atomic_json(self.path, payload)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _validate(self, state: dict[str, Any]) -> None:
        try:
            encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("session state must contain finite JSON-compatible values") from exc
        if len(encoded) > self.max_bytes:
            raise ValueError(f"session state exceeds the {self.max_bytes}-byte limit")
