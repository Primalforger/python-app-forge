"""Persistence Adapters (MOD-14): SQLite metadata store behind a replaceable interface."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from typing import Protocol

from app_forge.observability import utcnow


class MetadataStore(Protocol):
    def set_disabled(self, component_id: str, disabled: bool) -> None: ...
    def disabled_components(self) -> set[str]: ...
    def record_operation(self, op: dict) -> None: ...
    def list_operations(self, limit: int = 50) -> list[dict]: ...
    def get_operation(self, operation_id: str) -> dict | None: ...
    def add_evidence(self, rows: list[dict]) -> None: ...
    def list_evidence(self, subject: str, run_id: str | None = None) -> list[dict]: ...
    def list_runs(self, subject: str, limit: int = 20) -> list[dict]: ...
    def set_trust(self, plugin_id: str, level: str) -> None: ...
    def get_trust(self, plugin_id: str) -> str | None: ...
    def set_enabled_plugin(self, plugin_id: str, enabled: bool) -> None: ...
    def enabled_plugins(self) -> set[str]: ...
    def replace_index(self, rows: list[dict]) -> None: ...
    def read_index(self) -> list[dict]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS disabled(component_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS operations(operation_id TEXT PRIMARY KEY, kind TEXT, target TEXT, status TEXT,
    started TEXT, finished TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, subject TEXT,
    check_id TEXT, status TEXT, detail TEXT, duration_s REAL, recorded_at TEXT);
CREATE INDEX IF NOT EXISTS ev_subject ON evidence(subject, run_id);
CREATE TABLE IF NOT EXISTS trust(plugin_id TEXT PRIMARY KEY, level TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS plugins_enabled(plugin_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS catalog_index(component_id TEXT, version TEXT, category TEXT, summary TEXT,
    state TEXT, source TEXT, digest TEXT, PRIMARY KEY(component_id, version, source));
"""


class SqliteStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """One short-lived connection per operation: commit on success, roll back on error, ALWAYS close.

        (`with sqlite3.connect(...)` alone only commits; the open handle would block deleting forge.db on Windows.)
        """
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def set_disabled(self, component_id, disabled):
        with self._conn() as c:
            if disabled:
                c.execute("INSERT OR IGNORE INTO disabled VALUES (?)", (component_id,))
            else:
                c.execute("DELETE FROM disabled WHERE component_id=?", (component_id,))

    def disabled_components(self):
        with self._conn() as c:
            return {r[0] for r in c.execute("SELECT component_id FROM disabled")}

    def record_operation(self, op):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO operations VALUES (?,?,?,?,?,?,?)",
                      (op["operation_id"], op["kind"], op["target"], op["status"], op["started"],
                       op.get("finished"), json.dumps(op.get("summary", {}), sort_keys=True)))

    def list_operations(self, limit=50):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM operations ORDER BY started DESC, rowid DESC LIMIT ?", (limit,))
            return [{**dict(r), "summary": json.loads(r["summary"] or "{}")} for r in rows]

    def get_operation(self, operation_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            return None if r is None else {**dict(r), "summary": json.loads(r["summary"] or "{}")}

    def add_evidence(self, rows):
        with self._conn() as c:
            c.executemany("INSERT INTO evidence(run_id,subject,check_id,status,detail,duration_s,recorded_at)"
                          " VALUES (:run_id,:subject,:check_id,:status,:detail,:duration_s,:recorded_at)", rows)

    def list_evidence(self, subject, run_id=None):
        with self._conn() as c:
            if run_id is None:
                r = c.execute("SELECT run_id FROM evidence WHERE subject=? ORDER BY id DESC LIMIT 1",
                              (subject,)).fetchone()
                if r is None:
                    return []
                run_id = r[0]
            return [dict(x) for x in c.execute(
                "SELECT run_id,subject,check_id,status,detail,duration_s,recorded_at FROM evidence "
                "WHERE subject=? AND run_id=? ORDER BY id", (subject, run_id))]

    def list_runs(self, subject, limit=20):
        with self._conn() as c:
            rows = c.execute(
                "SELECT run_id, MIN(recorded_at) AS recorded_at, COUNT(*) AS records, "
                "SUM(status='failed') AS failed, SUM(status='not_run') AS not_run FROM evidence "
                "WHERE subject=? GROUP BY run_id ORDER BY MAX(id) DESC LIMIT ?", (subject, limit))
            return [dict(r) for r in rows]

    def set_trust(self, plugin_id, level):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO trust VALUES (?,?,?)", (plugin_id, level, utcnow()))

    def get_trust(self, plugin_id):
        with self._conn() as c:
            r = c.execute("SELECT level FROM trust WHERE plugin_id=?", (plugin_id,)).fetchone()
            return r[0] if r else None

    def set_enabled_plugin(self, plugin_id, enabled):
        with self._conn() as c:
            if enabled:
                c.execute("INSERT OR IGNORE INTO plugins_enabled VALUES (?)", (plugin_id,))
            else:
                c.execute("DELETE FROM plugins_enabled WHERE plugin_id=?", (plugin_id,))

    def enabled_plugins(self):
        with self._conn() as c:
            return {r[0] for r in c.execute("SELECT plugin_id FROM plugins_enabled")}

    def replace_index(self, rows):
        with self._conn() as c:  # one transaction: catalog updates are transactional
            c.execute("DELETE FROM catalog_index")
            c.executemany("INSERT INTO catalog_index VALUES (:component_id,:version,:category,:summary,"
                          ":state,:source,:digest)", rows)

    def read_index(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM catalog_index ORDER BY component_id, version")]
