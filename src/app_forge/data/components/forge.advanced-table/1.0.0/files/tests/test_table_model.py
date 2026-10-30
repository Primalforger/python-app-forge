import unittest

from {{package}}.table_model import TableModel

ROWS = [
    {"name": "bravo", "status": "open", "n": 3},
    {"name": "alpha", "status": "open", "n": 1},
    {"name": "charlie", "status": "closed", "n": 3},
    {"name": "delta", "status": "open", "n": None},
]


def model():
    return TableModel(["name", "status", "n"], ROWS)


class TableTests(unittest.TestCase):
    def test_multi_column_sort_is_deterministic_with_none_last(self):
        m = model()
        m.set_sort(("n", True), ("name", False))
        self.assertEqual([r["name"] for r in m.result_rows()], ["bravo", "charlie", "alpha", "delta"])

    def test_multiple_filters_and_semantics(self):
        m = model()
        m.add_filter("status", "eq", "open")
        m.add_filter("n", "gte", 3)
        self.assertEqual([r["name"] for r in m.result_rows()], ["bravo"])

    def test_multiple_filters_or_semantics(self):
        m = model()
        m.filter_mode = "or"
        m.add_filter("status", "eq", "closed")
        m.add_filter("n", "eq", 1)
        self.assertEqual({r["name"] for r in m.result_rows()}, {"charlie", "alpha"})

    def test_pagination_counts(self):
        m = model()
        m.page_size = 3
        p2 = m.page(2)
        self.assertEqual((p2.total, p2.pages, len(p2.rows)), (4, 2, 1))
        self.assertEqual(m.page(99).page, 2)  # out-of-range page is clamped

    def test_selection_survives_sorting(self):
        m = model()
        m.select(2)
        m.set_sort(("name", True))
        self.assertEqual([r["name"] for r in m.selected_rows()], ["charlie"])

    def test_states(self):
        self.assertEqual(TableModel(["a"], []).state, "empty")
        m = model()
        m.add_filter("name", "eq", "zzz")
        self.assertEqual(m.state, "no_results")
        self.assertEqual(TableModel(["a"], [], state="error", error="boom").state, "error")

    def test_csv_export_respects_filters_and_hidden_columns(self):
        m = model()
        m.add_filter("status", "eq", "closed")
        m.set_visible("status", False)
        self.assertEqual(m.export_csv(), "Name,N\ncharlie,3\n")
