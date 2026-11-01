"""Tests for saved table views."""
import json
import tempfile
import unittest
from pathlib import Path

from app_forge.data.components import __name__ as _components_package  # noqa: F401
from app_forge.table_views import TableViewStore, apply_view, normalize_view


class _Column:
    def __init__(self, key):
        self.key = key


class _Model:
    def __init__(self):
        self.columns = [_Column("name"), _Column("status"), _Column("amount")]
        self.filters = []
        self.sort_keys = []
        self.filter_mode = "and"
        self.search_text = ""
        self.page_size = 25

    def move_column(self, key, index):
        column = next(c for c in self.columns if c.key == key)
        self.columns.remove(column)
        self.columns.insert(index, column)

    def set_visible(self, key, visible):
        pass

    def set_sort(self, *keys):
        self.sort_keys = list(keys)

    def clear_filters(self):
        self.filters.clear()

    def add_filter(self, column, op, value):
        self.filters.append((column, op, value))


class TableViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "views.json"
        self.store = TableViewStore(self.path)
        self.keys = {"name", "status", "amount"}
        self.state = {"columns": ["status", "name", "amount"],
                      "sort": [{"column": "amount", "descending": True}],
                      "filters": [{"column": "status", "op": "eq", "value": "open"}],
                      "filter_mode": "or", "search_text": "alpha", "page_size": 50}

    def test_round_trip_and_sorted_names(self):
        self.store.save("Open items", self.state, self.keys)
        self.store.save("All items", {"columns": list(self.keys)}, self.keys)
        self.assertEqual(self.store.names(), ["All items", "Open items"])
        self.assertEqual(self.store.get("Open items", self.keys), normalize_view(self.state, self.keys))

    def test_delete_is_idempotent(self):
        self.store.save("Open items", self.state, self.keys)
        self.assertTrue(self.store.delete("Open items"))
        self.assertFalse(self.store.delete("Open items"))

    def test_rejects_invalid_names_and_unknown_columns(self):
        with self.assertRaises(ValueError):
            self.store.save("../escape", self.state, self.keys)
        with self.assertRaises(ValueError):
            normalize_view({"columns": ["name", "unknown", "amount"]}, self.keys)

    def test_rejects_invalid_filters_and_non_json_values(self):
        with self.assertRaises(ValueError):
            normalize_view({"columns": list(self.keys),
                            "filters": [{"column": "status", "op": "exec", "value": "x"}]}, self.keys)
        with self.assertRaises(ValueError):
            normalize_view({"columns": list(self.keys), "search_text": float("nan")}, self.keys)

    def test_applies_order_sort_filters_and_search(self):
        model = _Model()
        apply_view(model, self.state)
        self.assertEqual([c.key for c in model.columns], self.state["columns"])
        self.assertEqual(model.sort_keys, [("amount", True)])
        self.assertEqual(model.filters, [("status", "eq", "open")])
        self.assertEqual((model.filter_mode, model.search_text, model.page_size), ("or", "alpha", 50))

    def test_corrupt_store_fails_closed(self):
        self.path.write_text(json.dumps({"schema": 99, "views": {}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.names()
