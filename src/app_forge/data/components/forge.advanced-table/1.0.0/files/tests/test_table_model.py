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


    def test_group_by_preserves_first_seen_order_and_calculates_aggregates(self):
        rows = [
            {"team": "red", "score": 3, "cost": 4},
            {"team": "blue", "score": 5, "cost": None},
            {"team": "red", "score": 7, "cost": 2},
            {"team": "blue", "score": None, "cost": 8},
        ]
        groups = TableModel(["team", "score", "cost"], rows).group_by(
            "team", {
                "score_total": ("sum", "score"),
                "score_average": ("avg", "score"),
                "score_count": ("count", "score"),
                "row_count": ("count", "*"),
                "lowest_cost": ("min", "cost"),
                "highest_cost": ("max", "cost"),
            }
        )
        self.assertEqual([group["key"] for group in groups], ["red", "blue"])
        self.assertEqual(groups[0]["aggregates"], {
            "score_total": 10, "score_average": 5.0, "score_count": 2,
            "row_count": 2, "lowest_cost": 2, "highest_cost": 4,
        })
        self.assertEqual(groups[1]["aggregates"]["score_total"], 5)
        self.assertEqual(groups[1]["aggregates"]["score_count"], 1)

    def test_group_by_respects_filters_and_search_but_not_pagination(self):
        m = TableModel(
            ["team", "name", "score"],
            [{"team": "red", "name": "alpha", "score": 1},
             {"team": "red", "name": "beta", "score": 2},
             {"team": "blue", "name": "alphabet", "score": 3}],
        )
        m.add_filter("score", "gte", 1)
        m.search_text = "alpha"
        m.page_size = 1
        groups = m.group_by("team", {"total": ("sum", "score")})
        self.assertEqual([g["key"] for g in groups], ["red", "blue"])
        self.assertEqual([len(g["rows"]) for g in groups], [1, 1])

    def test_group_by_empty_values_and_null_group_keys(self):
        m = TableModel(["team", "score"], [{"team": None, "score": None}])
        group = m.group_by("team", {"total": ("sum", "score")})[0]
        self.assertIsNone(group["key"])
        self.assertIsNone(group["aggregates"]["total"])

    def test_group_by_rejects_invalid_specs_and_non_numeric_values(self):
        m = TableModel(["team", "score"], [{"team": "red", "score": "high"}])
        with self.assertRaises(KeyError):
            m.group_by("missing")
        with self.assertRaises(ValueError):
            m.group_by("team", {"bad": ("median", "score")})
        with self.assertRaises(ValueError):
            m.group_by("team", {"total": ("sum", "score")})

    def test_csv_export_respects_filters_and_hidden_columns(self):
        m = model()
        m.add_filter("status", "eq", "closed")
        m.set_visible("status", False)
        self.assertEqual(m.export_csv(), "Name,N\ncharlie,3\n")
