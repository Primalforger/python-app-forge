"""Tests for recent-file and desktop session persistence."""
import json
import tempfile
import unittest
from pathlib import Path

from app_forge.session import RecentFilesStore, SessionStateStore


class RecentFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = RecentFilesStore(self.root / "recent.json", max_items=2)

    def test_newest_first_deduplicated_and_bounded(self):
        a, b, c = (self.root / name for name in ("a.py", "b.py", "c.py"))
        self.store.add(a)
        self.store.add(b)
        self.store.add(a)
        self.assertEqual(self.store.list(), [str(a.resolve()), str(b.resolve())])
        self.store.add(c)
        self.assertEqual(self.store.list(), [str(c.resolve()), str(a.resolve())])

    def test_existing_only_and_remove(self):
        present = self.root / "present.py"
        present.write_text("pass", encoding="utf-8")
        missing = self.root / "missing.py"
        self.store.add(present)
        self.store.add(missing)
        self.assertEqual(self.store.list(existing_only=True), [str(present.resolve())])
        self.assertTrue(self.store.remove(missing))
        self.assertFalse(self.store.remove(missing))

    def test_clear_and_missing_file(self):
        self.assertEqual(self.store.list(), [])
        self.store.add(self.root / "a.py")
        self.store.clear()
        self.assertEqual(self.store.list(), [])

    def test_rejects_invalid_limit_and_corrupt_data(self):
        with self.assertRaises(ValueError):
            RecentFilesStore(self.root / "x", max_items=0)
        self.store.path.write_text('{"schema":1,"files":[3]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.list()


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "session.json"
        self.store = SessionStateStore(self.path)

    def test_round_trip_nested_json_state(self):
        state = {"window": {"width": 1200, "height": 800, "maximized": True},
                 "workspace": "/tmp/project", "open_tabs": ["a.py", "b.py"]}
        self.store.save(state)
        self.assertEqual(self.store.load(), state)

    def test_missing_state_is_empty_and_clear_is_idempotent(self):
        self.assertEqual(self.store.load(), {})
        self.store.save({"active_tab": "main.py"})
        self.store.clear()
        self.store.clear()
        self.assertEqual(self.store.load(), {})

    def test_rejects_non_json_non_finite_and_oversized_state(self):
        with self.assertRaises(ValueError):
            self.store.save({"callback": object()})
        with self.assertRaises(ValueError):
            self.store.save({"ratio": float("nan")})
        tiny = SessionStateStore(self.root_path(), max_bytes=20)
        with self.assertRaises(ValueError):
            tiny.save({"long": "a value that is too large"})

    def root_path(self):
        return self.path.parent / "tiny.json"

    def test_corrupt_or_unsupported_state_fails_closed(self):
        self.path.write_text(json.dumps({"schema": 2, "state": {}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()
        self.path.write_text(json.dumps({"schema": 1, "state": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()
