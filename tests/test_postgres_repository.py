"""Tests for the optional PostgreSQL repository adapter."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import String, create_engine as sqlalchemy_create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app_forge.postgres_repository import (
    PostgresDatabase,
    PostgresRepository,
    RecordNotFound,
)


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class PostgresRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_engine = sqlalchemy_create_engine("sqlite://")
        self.addCleanup(self.test_engine.dispose)
        self.engine_factory = patch(
            "app_forge.postgres_repository.create_engine",
            return_value=self.test_engine,
        )
        self.create_engine = self.engine_factory.start()
        self.addCleanup(self.engine_factory.stop)
        self.database = PostgresDatabase(
            "postgresql+psycopg://forge:secret@localhost/forge_test",
            pool_size=3,
            max_overflow=2,
        )
        self.addCleanup(self.database.dispose)
        self.database.create_schema(Base)
        self.widgets = PostgresRepository(self.database, Widget)

    def test_postgresql_url_and_resilient_pool_configuration(self) -> None:
        args, kwargs = self.create_engine.call_args
        self.assertEqual(args[0].get_backend_name(), "postgresql")
        self.assertTrue(kwargs["pool_pre_ping"])
        self.assertEqual(kwargs["pool_size"], 3)
        self.assertEqual(kwargs["max_overflow"], 2)
        self.assertNotIn("secret", repr(self.database.url))

    def test_crud_filter_order_pagination_and_count(self) -> None:
        self.widgets.add(name="Zeta")
        self.widgets.add(name="Alpha")
        self.widgets.add(name="Gamma")
        self.assertEqual(self.widgets.count(), 3)
        self.assertEqual(
            [item.name for item in self.widgets.list(order_by="name", limit=2)],
            ["Alpha", "Gamma"],
        )
        self.assertEqual(
            [item.name for item in self.widgets.list(order_by="name", offset=1, limit=1)],
            ["Gamma"],
        )
        self.assertEqual(self.widgets.count(filters={"name": "Alpha"}), 1)
        item = self.widgets.require(1)
        self.assertEqual(self.widgets.update(item.id, name="Renamed").name, "Renamed")
        self.assertTrue(self.widgets.delete(item.id))
        self.assertFalse(self.widgets.delete(item.id))

    def test_missing_records_and_invalid_fields(self) -> None:
        with self.assertRaises(RecordNotFound):
            self.widgets.require(404)
        with self.assertRaises(RecordNotFound):
            self.widgets.update(404, name="missing")
        item = self.widgets.add(name="Existing")
        with self.assertRaises(ValueError):
            self.widgets.list(order_by="missing")
        with self.assertRaises(ValueError):
            self.widgets.list(filters={"missing": "value"})
        with self.assertRaises(ValueError):
            self.widgets.update(item.id, unknown="value")
        with self.assertRaises(ValueError):
            self.widgets.update(item.id, id=9)

    def test_transaction_rolls_back(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.database.transaction() as session:
                session.add(Widget(name="temporary"))
                raise RuntimeError("rollback")
        self.assertEqual(self.widgets.count(), 0)

    def test_validation_rejects_non_postgres_urls_and_bad_pool_settings(self) -> None:
        with self.assertRaises(ValueError):
            PostgresDatabase("sqlite:///not-postgres.db")
        with self.assertRaises(ValueError):
            PostgresDatabase("postgresql://localhost")
        with self.assertRaises(ValueError):
            PostgresDatabase(
                "postgresql://localhost/forge",
                pool_size=0,
            )
        with self.assertRaises(ValueError):
            PostgresDatabase(
                "postgresql://localhost/forge",
                max_overflow=-1,
            )
        with self.assertRaises(ValueError):
            PostgresDatabase(
                "postgresql://localhost/forge",
                pool_timeout=float("inf"),
            )

    def test_repository_rejects_non_declarative_models(self) -> None:
        with self.assertRaises(TypeError):
            PostgresRepository(self.database, object)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
