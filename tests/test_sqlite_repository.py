"""Tests for the optional SQLAlchemy SQLite repository adapter."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app_forge.sqlite_repository import RecordNotFound, SqliteDatabase, SqliteRepository


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    books: Mapped[list["Book"]] = relationship(back_populates="author", cascade="all, delete-orphan")


class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[int] = mapped_column(ForeignKey("authors.id"), nullable=False)
    author: Mapped[Author] = relationship(back_populates="books")


class SqliteRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = SqliteDatabase(Path(self.tmp.name) / "app.db")
        self.addCleanup(self.database.dispose)
        self.database.create_schema(Base)
        self.authors = SqliteRepository(self.database, Author)
        self.books = SqliteRepository(self.database, Book)

    def test_crud_round_trip_and_persist_across_instances(self):
        author = self.authors.add(name="Ada")
        book = self.books.add(title="Notes", author_id=author.id)
        self.assertEqual(self.books.require(book.id).title, "Notes")
        updated = self.books.update(book.id, title="Revised")
        self.assertEqual(updated.title, "Revised")
        self.assertTrue(self.books.delete(book.id))
        self.assertFalse(self.books.delete(book.id))
        reopened = SqliteDatabase(Path(self.tmp.name) / "app.db")
        try:
            self.assertEqual(SqliteRepository(reopened, Author).require(author.id).name, "Ada")
        finally:
            reopened.dispose()

    def test_filter_order_pagination_and_count(self):
        self.authors.add(name="Grace")
        self.authors.add(name="Ada")
        self.authors.add(name="Linus")
        self.assertEqual(self.authors.count(), 3)
        self.assertEqual(
            [row.name for row in self.authors.list(order_by="name", filters={}, limit=2)],
            ["Ada", "Grace"],
        )
        self.assertEqual(
            [row.name for row in self.authors.list(order_by="name", offset=1, limit=1)],
            ["Grace"],
        )
        self.assertEqual(self.authors.count(filters={"name": "Ada"}), 1)

    def test_missing_record_and_invalid_fields_fail_clearly(self):
        with self.assertRaises(RecordNotFound):
            self.authors.require(999)
        with self.assertRaises(RecordNotFound):
            self.authors.update(999, name="missing")
        with self.assertRaises(ValueError):
            self.authors.list(order_by="not_a_column")
        with self.assertRaises(ValueError):
            self.authors.list(filters={"not_a_column": "x"})
        with self.assertRaises(ValueError):
            self.authors.update(1, unknown="x")
        with self.assertRaises(ValueError):
            self.authors.update(1, id=2)

    def test_foreign_keys_are_enabled(self):
        with self.assertRaises(Exception):
            self.books.add(title="Orphan", author_id=999)

    def test_transaction_rolls_back_all_changes(self):
        with self.assertRaises(RuntimeError):
            with self.database.transaction() as session:
                session.add(Author(name="temporary"))
                raise RuntimeError("abort")
        self.assertEqual(self.authors.count(), 0)

    def test_in_memory_database_shares_schema_between_sessions(self):
        database = SqliteDatabase(":memory:")
        try:
            database.create_schema(Base)
            repository = SqliteRepository(database, Author)
            repository.add(name="Memory")
            self.assertEqual(repository.count(), 1)
        finally:
            database.dispose()

    def test_validation(self):
        with self.assertRaises(ValueError):
            SqliteDatabase(Path(self.tmp.name) / "bad.db", timeout=0)
        with self.assertRaises(ValueError):
            self.authors.list(limit=0)
        with self.assertRaises(ValueError):
            self.authors.list(offset=-1)


if __name__ == "__main__":
    unittest.main()
