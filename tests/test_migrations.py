"""Safety and journal tests for the optional Alembic migration runner."""
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
import sys

from app_forge.migrations import MigrationError, MigrationRunner


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Engine:
    def connect(self):
        return _Connection()

    def dispose(self):
        pass


class MigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config_path = root / "alembic.ini"
        self.config_path.write_text("[alembic]\n", encoding="utf-8")
        (root / "migrations").mkdir()
        self.runner = MigrationRunner(self.config_path, root / "journal")
        self.command = SimpleNamespace(upgrade=Mock())
        self.config = SimpleNamespace(
            get_main_option=lambda key: {
                "script_location": "migrations",
                "sqlalchemy.url": "sqlite:///example.db",
            }.get(key)
        )
        self.scripts = SimpleNamespace(
            get_heads=lambda: ["rev2"],
            get_revision=lambda _revision: object(),
        )
        self.engine = _Engine()
        self.runner._dependencies = lambda: (
            self.command,
            lambda _path: self.config,
            (SimpleNamespace(from_config=lambda _config: self.scripts),
             lambda _url, **_kwargs: self.engine),
        )

    def test_plan_is_read_only_and_reports_current_and_head(self):
        runtime = ModuleType("alembic.runtime.migration")
        runtime.MigrationContext = SimpleNamespace(
            configure=lambda _connection: SimpleNamespace(get_current_revision=lambda: "rev1")
        )
        runtime_package = ModuleType("alembic.runtime")
        runtime_package.__path__ = []
        alembic_package = ModuleType("alembic")
        alembic_package.__path__ = []
        alembic_package.runtime = runtime_package
        with patch.dict(sys.modules, {
            "alembic": alembic_package,
            "alembic.runtime": runtime_package,
            "alembic.runtime.migration": runtime,
        }):
            plan = self.runner.plan()
        self.assertEqual((plan.current_revision, plan.heads, plan.target_revision),
                         ("rev1", ("rev2",), "head"))
        self.command.upgrade.assert_not_called()

    def test_upgrade_requires_explicit_irreversible_consent(self):
        with self.assertRaisesRegex(MigrationError, "confirm_irreversible"):
            self.runner.upgrade()
        self.command.upgrade.assert_not_called()

    def test_upgrade_journals_success_without_database_url(self):
        runtime = ModuleType("alembic.runtime.migration")
        runtime.MigrationContext = SimpleNamespace(
            configure=lambda _connection: SimpleNamespace(get_current_revision=lambda: "rev1")
        )
        runtime_package = ModuleType("alembic.runtime")
        runtime_package.__path__ = []
        with patch.dict(sys.modules, {
            "alembic": ModuleType("alembic"),
            "alembic.runtime": runtime_package,
            "alembic.runtime.migration": runtime,
        }):
            result = self.runner.upgrade(confirm_irreversible=True)
        self.assertEqual(result.status, "succeeded")
        record = json.loads(result.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "succeeded")
        self.assertNotIn("sqlalchemy.url", json.dumps(record))
        self.command.upgrade.assert_called_once_with(self.config, "head")
        self.assertFalse((self.runner.journal_dir / ".migration.lock").exists())

    def test_failed_upgrade_is_journaled_and_never_downgraded(self):
        self.command.upgrade.side_effect = RuntimeError("migration failed")
        runtime = ModuleType("alembic.runtime.migration")
        runtime.MigrationContext = SimpleNamespace(
            configure=lambda _connection: SimpleNamespace(get_current_revision=lambda: "rev1")
        )
        runtime_package = ModuleType("alembic.runtime")
        runtime_package.__path__ = []
        with patch.dict(sys.modules, {
            "alembic": ModuleType("alembic"),
            "alembic.runtime": runtime_package,
            "alembic.runtime.migration": runtime,
        }):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                self.runner.upgrade(confirm_irreversible=True)
        records = list(self.runner.journal_dir.glob("*.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"], "migration failed")
        self.assertFalse(hasattr(self.command, "downgrade"))


if __name__ == "__main__":
    unittest.main()
