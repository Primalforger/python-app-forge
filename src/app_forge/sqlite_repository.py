"""SQLAlchemy-backed SQLite database and generic repository primitives.

The adapter is optional: importing this module does not require SQLAlchemy.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generic, Iterator, TypeVar

try:
    from sqlalchemy import Engine, create_engine, event, func, select
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
    from sqlalchemy.pool import StaticPool
except ImportError as exc:  # pragma: no cover - exercised in dependency-isolation tests
    raise ImportError(
        "SQLite repository support requires the optional 'sqlite' extra "
        "(SQLAlchemy >= 2.0)."
    ) from exc


ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class RepositoryError(RuntimeError):
    """Base error for repository operations."""


class RecordNotFound(RepositoryError, LookupError):
    """Raised when an update or delete targets a missing row."""


class SqliteDatabase:
    """Own a SQLite SQLAlchemy engine and short-lived ORM sessions.

    Schema creation is always explicit via :meth:`create_schema`. File-backed
    databases enable foreign keys, a bounded busy timeout and WAL mode. In-memory
    databases use one shared connection so sessions see the same schema/data.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 5.0,
        echo: bool = False,
    ) -> None:
        import math

        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        raw = str(path)
        self.path = raw
        if raw != ":memory:" and not raw.startswith("file:"):
            database_path = Path(raw).expanduser()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{database_path.resolve().as_posix()}"
            connect_args: dict[str, Any] = {"timeout": float(timeout), "check_same_thread": False}
            poolclass = None
        elif raw == ":memory:":
            url = "sqlite://"
            connect_args = {"timeout": float(timeout), "check_same_thread": False}
            poolclass = StaticPool
        else:
            url = f"sqlite:///{raw}"
            connect_args = {"timeout": float(timeout), "check_same_thread": False, "uri": True}
            poolclass = None

        options: dict[str, Any] = {"echo": bool(echo), "connect_args": connect_args}
        if poolclass is not None:
            options["poolclass"] = poolclass
        self.engine: Engine = create_engine(url, **options)

        @event.listens_for(self.engine, "connect")
        def _configure_sqlite(connection: Any, _record: Any) -> None:
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={int(float(timeout) * 1000)}")
                if raw != ":memory:":
                    cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

        self._sessions = sessionmaker(
            bind=self.engine, class_=Session, expire_on_commit=False, autoflush=True
        )

    def create_schema(self, base: type[DeclarativeBase]) -> None:
        """Create missing tables for a declarative base; never called implicitly."""
        base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session and close it on every path; caller controls transactions."""
        session = self._sessions()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Run a unit of work atomically and roll it back if any error escapes."""
        with self.session() as session:
            with session.begin():
                yield session

    def dispose(self) -> None:
        """Close pooled connections."""
        self.engine.dispose()

    def __enter__(self) -> "SqliteDatabase":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.dispose()


class SqliteRepository(Generic[ModelT]):
    """CRUD repository for one SQLAlchemy declarative model."""

    def __init__(self, database: SqliteDatabase, model: type[ModelT]) -> None:
        if not hasattr(model, "__table__"):
            raise TypeError("model must be a SQLAlchemy declarative model")
        self.database = database
        self.model = model
        primary_keys = tuple(model.__mapper__.primary_key)
        if len(primary_keys) != 1:
            raise ValueError("repository models must have exactly one primary-key column")
        self._primary_key = primary_keys[0].key

    def add(self, **values: Any) -> ModelT:
        with self.database.transaction() as session:
            record = self.model(**values)
            session.add(record)
            session.flush()
            session.refresh(record)
            return record

    def get(self, identity: Any) -> ModelT | None:
        with self.database.session() as session:
            return session.get(self.model, identity)

    def require(self, identity: Any) -> ModelT:
        record = self.get(identity)
        if record is None:
            raise RecordNotFound(f"{self.model.__name__} {identity!r} was not found")
        return record

    def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelT]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        statement = select(self.model)
        for name, value in (filters or {}).items():
            column = getattr(self.model, name, None)
            if column is None or name.startswith("_"):
                raise ValueError(f"unknown filter field: {name!r}")
            statement = statement.where(column == value)
        sort_name = order_by or self._primary_key
        sort_column = getattr(self.model, sort_name, None)
        if sort_column is None or sort_name.startswith("_"):
            raise ValueError(f"unknown order field: {sort_name!r}")
        statement = statement.order_by(sort_column.desc() if descending else sort_column.asc())
        statement = statement.limit(limit).offset(offset)
        with self.database.session() as session:
            return list(session.scalars(statement).all())

    def count(self, *, filters: dict[str, Any] | None = None) -> int:
        statement = select(func.count()).select_from(self.model)
        for name, value in (filters or {}).items():
            column = getattr(self.model, name, None)
            if column is None or name.startswith("_"):
                raise ValueError(f"unknown filter field: {name!r}")
            statement = statement.where(column == value)
        with self.database.session() as session:
            return int(session.scalar(statement) or 0)

    def update(self, identity: Any, **changes: Any) -> ModelT:
        if self._primary_key in changes:
            raise ValueError("primary-key updates are not supported")
        with self.database.transaction() as session:
            record = session.get(self.model, identity)
            if record is None:
                raise RecordNotFound(f"{self.model.__name__} {identity!r} was not found")
            for name, value in changes.items():
                if name.startswith("_") or not hasattr(type(record), name):
                    raise ValueError(f"unknown update field: {name!r}")
                setattr(record, name, value)
            session.flush()
            session.refresh(record)
            return record

    def delete(self, identity: Any) -> bool:
        with self.database.transaction() as session:
            record = session.get(self.model, identity)
            if record is None:
                return False
            session.delete(record)
            return True
