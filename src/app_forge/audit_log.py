"""Append-only JSONL audit log with a verifiable SHA-256 hash chain."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_GENESIS = "0" * 64
_FIELDS = {"sequence", "timestamp", "actor", "event", "previous_hash", "hash"}
_LOCK = threading.RLock()


class AuditLogError(ValueError):
    """An audit log is malformed, inaccessible, or has a broken hash chain."""


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def _lock_file(stream) -> None:
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        if stream.read(1) == "":
            stream.write(" ")
            stream.flush()
        stream.seek(0)
        getattr(msvcrt, "locking")(stream.fileno(), getattr(msvcrt, "LK_LOCK"), 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _unlock_file(stream) -> None:
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        getattr(msvcrt, "locking")(stream.fileno(), getattr(msvcrt, "LK_UNLCK"), 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class HashChainedAuditLog:
    """Append audit events and verify sequence, previous-hash and content integrity.

    Each line is canonical JSON. Appends are serialized across threads and
    processes using an OS file lock. The log is tamper-evident, not tamper-proof:
    an attacker able to rewrite the entire file can recompute the chain.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any], *, actor: str, timestamp: str | None = None) -> dict[str, Any]:
        if not isinstance(event, dict) or not event:
            raise ValueError("event must be a non-empty JSON object")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 256:
            raise ValueError("actor must be a non-empty string of at most 256 characters")
        try:
            encoded_event = json.loads(_canonical(event).decode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("event must contain finite JSON-compatible values") from exc
        moment = timestamp or datetime.now(timezone.utc).isoformat(timespec="microseconds")
        if not isinstance(moment, str) or not moment:
            raise ValueError("timestamp must be a non-empty ISO-8601 string")
        try:
            datetime.fromisoformat(moment.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601") from exc

        lock_path = self.path.with_name(self.path.name + ".lock")
        with _LOCK, lock_path.open("a+", encoding="utf-8") as lock_stream:
            _lock_file(lock_stream)
            try:
                with self.path.open("a+", encoding="utf-8", newline="\n") as stream:
                    stream.seek(0)
                    records, valid = self._read_stream(stream)
                    if not valid["ok"]:
                        raise AuditLogError("cannot append to an invalid audit log")
                    record: dict[str, Any] = {
                        "sequence": len(records) + 1,
                        "timestamp": moment,
                        "actor": actor,
                        "event": encoded_event,
                        "previous_hash": records[-1]["hash"] if records else _GENESIS,
                    }
                    record["hash"] = _digest(record)
                    stream.seek(0, os.SEEK_END)
                    stream.write(_canonical(record).decode("utf-8") + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                    return record.copy()
            finally:
                _unlock_file(lock_stream)

    def verify(self) -> dict[str, Any]:
        """Return a stable report; malformed lines are reported, never repaired."""
        if not self.path.exists():
            return {"ok": True, "records": 0, "head": _GENESIS, "error": None}
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                records, report = self._read_stream(stream)
            return {**report, "records": len(records),
                    "head": records[-1]["hash"] if records else _GENESIS}
        except (OSError, UnicodeDecodeError) as exc:
            return {"ok": False, "records": 0, "head": _GENESIS,
                    "error": f"audit log is unreadable: {type(exc).__name__}"}

    @staticmethod
    def _read_stream(stream) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        previous = _GENESIS
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or set(record) != _FIELDS:
                    raise ValueError("unexpected record fields")
                if record["sequence"] != line_number:
                    raise ValueError("sequence mismatch")
                if record["previous_hash"] != previous:
                    raise ValueError("previous hash mismatch")
                if not isinstance(record["actor"], str) or not record["actor"]:
                    raise ValueError("invalid actor")
                if not isinstance(record["event"], dict) or not isinstance(record["timestamp"], str):
                    raise ValueError("invalid event or timestamp")
                datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
                if not isinstance(record["hash"], str) or record["hash"] != _digest(record):
                    raise ValueError("record hash mismatch")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return records, {"ok": False, "error": f"line {line_number}: {exc}"}
            records.append(record)
            previous = record["hash"]
        return records, {"ok": True, "error": None}
