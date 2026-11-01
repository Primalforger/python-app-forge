import json
import tempfile
import unittest
from pathlib import Path

from app_forge.table_layout import ColumnWidthStore, MAX_WIDTH, MIN_WIDTH, normalize_widths


class ColumnWidthTests(unittest.TestCase):
    def test_normalize_sorts_keys_and_preserves_partial_widths(self):
        self.assertEqual(
            normalize_widths({"z": 180, "a": 90}, {"a", "z", "unused"}),
            {"a": 90, "z": 180},
        )

    def test_rejects_unknown_columns_and_invalid_widths(self):
        for value in (True, 0, MIN_WIDTH - 1, MAX_WIDTH + 1, 1.5, "120"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_widths({"name": value}, {"name"})
        with self.assertRaises(ValueError):
            normalize_widths({"other": 120}, {"name"})

    def test_store_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "widths.json"
            store = ColumnWidthStore(path, {"name", "status"})
            self.assertEqual(store.load(), {})
            store.save({"status": 210, "name": 140})
            self.assertEqual(store.load(), {"name": 140, "status": 210})
            self.assertTrue(store.clear())
            self.assertFalse(store.clear())
            self.assertEqual(store.load(), {})

    def test_corrupt_and_unsupported_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "widths.json"
            store = ColumnWidthStore(path, {"name"})
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()
            path.write_text(json.dumps({"schema": 99, "widths": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

    def test_saved_unknown_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "widths.json"
            path.write_text(json.dumps({"schema": 1, "widths": {"retired": 100}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                ColumnWidthStore(path, {"name"}).load()

    def test_column_key_set_is_validated(self):
        with self.assertRaises(ValueError):
            ColumnWidthStore("widths.json", set())


if __name__ == "__main__":
    unittest.main()
