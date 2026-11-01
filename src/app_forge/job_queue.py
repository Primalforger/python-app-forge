"""Persistent SQLite-backed job queue with retries and dead-letter handling.

Jobs contain finite JSON objects only. Claims and state transitions use short
SQLite write transactions so multiple worker processes can safely share a queue.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = 1
_MAX_PAYLOAD_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class Job:
    """Immutable snapshot of a persisted job."""

    id: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    available_at: float
    created_at: float
    updated_at: float
    last_error: str | None
    worker_id: str | None
    lease_until: float | None


class JobQueue:
    """A durable queue with atomic claims, retry scheduling and dead letters."""

    def __init__(self, path: str | Path, *, timeout: float = 5.0,
                 max_payload_bytes: int = _MAX_PAYLOAD_BYTES) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        if isinstance(max_payload_bytes, bool) or not isinstance(max_payload_bytes, int) or not 1 <= max_payload_bytes <= 16_777_216:
            raise ValueError("max_payload_bytes must be an integer from 1 to 16777216")
        self.path = Path(path)
        self.timeout = float(timeout)
        self.max_payload_bytes = max_payload_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','dead')),
                    attempts INTEGER NOT NULL CHECK (attempts >= 0),
                    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
                    available_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT,
                    worker_id TEXT,
                    lease_until REAL,
                    CHECK ((status = 'running' AND worker_id IS NOT NULL AND lease_until IS NOT NULL)
                        OR (status != 'running' AND worker_id IS NULL AND lease_until IS NULL))
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status, available_at, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_lease ON jobs(status, lease_until)")
            connection.execute("PRAGMA user_version = 1")

    def enqueue(self, payload: dict[str, Any], *, max_attempts: int = 3,
                delay: float = 0.0, job_id: str | None = None,
                now: float | None = None) -> Job:
        """Persist a new JSON job; duplicate explicit IDs are rejected."""
        if not isinstance(payload, dict):
            raise ValueError("job payload must be a JSON object")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        delay = self._duration(delay, "delay", allow_zero=True)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("job payload must contain finite JSON-compatible values") from exc
        if len(encoded.encode("utf-8")) > self.max_payload_bytes:
            raise ValueError(f"job payload exceeds the {self.max_payload_bytes}-byte limit")
        identifier = job_id or uuid.uuid4().hex
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 128:
            raise ValueError("job_id must be a non-empty string of at most 128 characters")
        timestamp = self._timestamp(now)
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO jobs
                (id,payload,status,attempts,max_attempts,available_at,created_at,updated_at,last_error,worker_id,lease_until)
                VALUES (?,?, 'pending',0,?,?,?,?,NULL,NULL,NULL)""",
                (identifier, encoded, max_attempts, timestamp + delay, timestamp, timestamp),
            )
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        return self._job(row)

    def claim(self, worker_id: str, *, lease_seconds: float = 60.0,
              now: float | None = None) -> Job | None:
        """Atomically claim the oldest ready job, reclaiming expired worker leases."""
        self._worker(worker_id)
        lease = self._duration(lease_seconds, "lease_seconds")
        timestamp = self._timestamp(now)
        with self._transaction() as connection:
            expired = connection.execute(
                "SELECT id, attempts, max_attempts FROM jobs WHERE status='running' AND lease_until <= ?",
                (timestamp,),
            ).fetchall()
            for row in expired:
                status = "dead" if row["attempts"] >= row["max_attempts"] else "pending"
                connection.execute(
                    """UPDATE jobs SET status=?, worker_id=NULL, lease_until=NULL,
                    available_at=?, updated_at=? WHERE id=? AND status='running'""",
                    (status, timestamp, timestamp, row["id"]),
                )
            row = connection.execute(
                """SELECT * FROM jobs WHERE status='pending' AND available_at <= ?
                ORDER BY available_at, created_at, id LIMIT 1""", (timestamp,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE jobs SET status='running', attempts=attempts+1, worker_id=?,
                lease_until=?, updated_at=? WHERE id=? AND status='pending'""",
                (worker_id, timestamp + lease, timestamp, row["id"]),
            )
            claimed = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        return self._job(claimed)

    def complete(self, job_id: str, worker_id: str, *, now: float | None = None) -> Job:
        """Mark a currently leased job successful; stale workers cannot complete it."""
        timestamp = self._timestamp(now)
        with self._transaction() as connection:
            self._owned_running(connection, job_id, worker_id)
            connection.execute(
                """UPDATE jobs SET status='succeeded', worker_id=NULL, lease_until=NULL,
                updated_at=?, last_error=NULL WHERE id=?""", (timestamp, job_id)
            )
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row)

    def fail(self, job_id: str, worker_id: str, error: str, *, retry_delay: float = 0.0,
             now: float | None = None) -> Job:
        """Schedule a retry or move an exhausted job to the dead-letter state."""
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error must be a non-empty string")
        delay = self._duration(retry_delay, "retry_delay", allow_zero=True)
        timestamp = self._timestamp(now)
        with self._transaction() as connection:
            current = self._owned_running(connection, job_id, worker_id)
            status = "pending" if current["attempts"] < current["max_attempts"] else "dead"
            connection.execute(
                """UPDATE jobs SET status=?, available_at=?, updated_at=?, last_error=?,
                worker_id=NULL, lease_until=NULL WHERE id=?""",
                (status, timestamp + delay, timestamp, error[:4096], job_id),
            )
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row)

    def retry_dead(self, job_id: str, *, delay: float = 0.0,
                   now: float | None = None) -> Job:
        """Explicitly requeue a dead-letter job and reset its attempt counter."""
        wait = self._duration(delay, "delay", allow_zero=True)
        timestamp = self._timestamp(now)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown job {job_id!r}")
            if row["status"] != "dead":
                raise ValueError("only dead-letter jobs can be manually retried")
            connection.execute(
                """UPDATE jobs SET status='pending', attempts=0, available_at=?, updated_at=?,
                last_error=NULL WHERE id=?""", (timestamp + wait, timestamp, job_id)
            )
            updated = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(updated)

    def get(self, job_id: str) -> Job:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown job {job_id!r}")
        return self._job(row)

    def list(self, *, status: str | None = None, limit: int = 100) -> list[Job]:
        if status is not None and status not in {"pending", "running", "succeeded", "dead"}:
            raise ValueError("status must be pending, running, succeeded or dead")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        with self._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM jobs ORDER BY created_at, id LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE status=? ORDER BY created_at, id LIMIT ?",
                    (status, limit),
                ).fetchall()
        return [self._job(row) for row in rows]

    def dead_letters(self, *, limit: int = 100) -> list[Job]:
        """Return dead-letter jobs in creation order."""
        return self.list(status="dead", limit=limit)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        return connection

    class _Transaction:
        def __init__(self, queue: "JobQueue") -> None:
            self.queue = queue
            self.connection: sqlite3.Connection | None = None

        def __enter__(self) -> sqlite3.Connection:
            self.connection = self.queue._connect()
            self.connection.execute("BEGIN IMMEDIATE")
            return self.connection

        def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
            assert self.connection is not None
            try:
                self.connection.execute("ROLLBACK" if exc_type else "COMMIT")
            finally:
                self.connection.close()

    def _transaction(self) -> "JobQueue._Transaction":
        return self._Transaction(self)

    def _owned_running(self, connection: sqlite3.Connection, job_id: str, worker_id: str) -> sqlite3.Row:
        self._worker(worker_id)
        row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown job {job_id!r}")
        if row["status"] != "running" or row["worker_id"] != worker_id:
            raise ValueError("job is not leased by this worker")
        return row

    @staticmethod
    def _worker(worker_id: str) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must be a non-empty string of at most 128 characters")

    @staticmethod
    def _duration(value: float, name: str, *, allow_zero: bool = False) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        if value < 0 or (value == 0 and not allow_zero):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValueError(f"{name} must be {qualifier}")
        return float(value)

    @staticmethod
    def _timestamp(value: float | None) -> float:
        result = time.time() if value is None else value
        if isinstance(result, bool) or not isinstance(result, (int, float)) or not math.isfinite(result):
            raise ValueError("now must be a finite timestamp")
        return float(result)

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"], payload=json.loads(row["payload"]), status=row["status"],
            attempts=row["attempts"], max_attempts=row["max_attempts"],
            available_at=row["available_at"], created_at=row["created_at"],
            updated_at=row["updated_at"], last_error=row["last_error"],
            worker_id=row["worker_id"], lease_until=row["lease_until"],
        )
