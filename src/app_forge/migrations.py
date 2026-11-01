"""Explicit Alembic migration execution with a durable, fail-closed journal.

Database migrations are not Forge file patches: a successful or partially
successful migration is never automatically downgraded by Forge.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MigrationError(RuntimeError):
    """Raised when migration configuration or execution is unsafe."""


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Read-only snapshot of the database and Alembic revision graph."""

    current_revision: str | None
    heads: tuple[str, ...]
    target_revision: str
    requires_confirmation: bool = True


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Recorded result of one explicitly approved migration attempt."""

    operation_id: str
    status: str
    current_revision: str | None
    target_revision: str
    journal_path: Path


class MigrationRunner:
    """Plan and explicitly execute Alembic upgrades without implicit rollback.

    config_path must be an existing alembic.ini and journal_dir should be on
    durable local storage. Journal records never contain the database URL.
    A journal left in running state after a crash is intentionally not retried
    automatically: inspect the database revision before taking action.
    """

    def __init__(self, config_path: str | Path, journal_dir: str | Path) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        self.journal_dir = Path(journal_dir).expanduser().resolve()
        if not self.config_path.is_file():
            raise MigrationError(f"Alembic config does not exist: {self.config_path}")
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def _dependencies(self) -> tuple[Any, Any, Any]:
        try:
            from alembic import command
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            from sqlalchemy import create_engine
        except ImportError as exc:
            raise MigrationError(
                "Migration support requires the optional migrations extra "
                "(SQLAlchemy and Alembic)."
            ) from exc
        return command, Config, (ScriptDirectory, create_engine)

    def _config_and_engine(self) -> tuple[Any, Any, Any, Any]:
        command, Config, (ScriptDirectory, create_engine) = self._dependencies()
        config = Config(str(self.config_path))
        script_location = config.get_main_option("script_location")
        if not script_location:
            raise MigrationError("Alembic config must define script_location")
        script_path = Path(script_location)
        if not script_path.is_absolute():
            script_path = (self.config_path.parent / script_path).resolve()
        if not script_path.is_dir():
            raise MigrationError("Alembic script_location is not an existing directory")
        url = config.get_main_option("sqlalchemy.url")
        if not url:
            raise MigrationError("Alembic config must define sqlalchemy.url")
        engine = create_engine(url, future=True)
        return command, config, ScriptDirectory.from_config(config), engine

    def plan(self, target_revision: str = "head") -> MigrationPlan:
        """Inspect revisions without changing the database."""
        if not isinstance(target_revision, str) or not target_revision.strip():
            raise ValueError("target_revision must be a non-empty string")
        command, config, scripts, engine = self._config_and_engine()
        del command, config
        try:
            from alembic.runtime.migration import MigrationContext
            with engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_revision()
            heads = tuple(sorted(scripts.get_heads()))
            if len(heads) > 1 and target_revision == "head":
                raise MigrationError(
                    "Alembic has multiple heads; merge them or select an explicit revision"
                )
            scripts.get_revision(target_revision)
            return MigrationPlan(current, heads, target_revision)
        finally:
            engine.dispose()

    def upgrade(
        self, target_revision: str = "head", *, confirm_irreversible: bool = False
    ) -> MigrationResult:
        """Run an Alembic upgrade only after explicit irreversible-side-effect consent.

        This method never invokes downgrade, even when an upgrade raises. A
        failed or interrupted attempt is journaled for operator reconciliation.
        """
        if confirm_irreversible is not True:
            raise MigrationError(
                "Database upgrades require confirm_irreversible=True; "
                "Forge cannot promise automatic rollback."
            )
        plan = self.plan(target_revision)
        operation_id = uuid.uuid4().hex
        journal_path = self.journal_dir / f"{operation_id}.json"
        lock_path = self.journal_dir / ".migration.lock"
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise MigrationError("Another migration operation holds the migration lock") from exc
        os.close(lock_fd)

        record = {
            "operation_id": operation_id,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "current_revision": plan.current_revision,
            "target_revision": plan.target_revision,
            "heads": list(plan.heads),
            "config_path": str(self.config_path),
            "warning": "No automatic downgrade is attempted; inspect database state after failure.",
        }
        try:
            self._write_record(journal_path, record)
            command, config, _scripts, engine = self._config_and_engine()
            try:
                command.upgrade(config, target_revision)
            finally:
                engine.dispose()
            record["status"] = "succeeded"
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._write_record(journal_path, record)
            return MigrationResult(
                operation_id, "succeeded", plan.current_revision, target_revision, journal_path
            )
        except BaseException as exc:
            record["status"] = "failed"
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            record["error_type"] = type(exc).__name__
            record["error"] = str(exc)[:2000]
            self._write_record(journal_path, record)
            raise
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _write_record(path: Path, record: dict[str, Any]) -> None:
        """Atomically replace a private JSON journal record."""
        fd, temporary = tempfile.mkstemp(prefix=".migration-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(record, stream, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
