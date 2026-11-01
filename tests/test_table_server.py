import unittest

from app_forge.table_server import (
    ServerPage, ServerSideTableModel, TableQuery,
)


class ServerSideTableTests(unittest.TestCase):
    def setUp(self):
        self.requests = []

        def query(request):
            self.requests.append(request)
            return ServerPage([{"id": request.page}], request.page,
                              request.page_size, 101)

        self.model = ServerSideTableModel(["id", "status", "name"], query, page_size=10)

    def test_passes_complete_query_state_to_callback(self):
        self.model.add_filter("status", "eq", "open")
        self.model.search_text = "alpha"
        self.model.set_filter_mode("or")
        self.model.set_sort(("name", True), ("id", False))
        page = self.model.page(3)
        request = self.requests[-1]
        self.assertEqual(page.page, 3)
        self.assertIsInstance(request, TableQuery)
        self.assertEqual(request.filters[0].value, "open")
        self.assertEqual(request.filter_mode, "or")
        self.assertEqual(request.search_text, "alpha")
        self.assertEqual(request.sort_keys, (("name", True), ("id", False)))
        self.assertEqual((request.page, request.page_size), (3, 10))

    def test_callback_controls_total_and_model_does_not_fetch_extra_rows(self):
        page = self.model.page()
        self.assertEqual((page.total, page.pages, len(page.rows)), (101, 11, 1))
        self.assertEqual(len(self.requests), 1)

    def test_refresh_reexecutes_callback(self):
        self.model.page()
        self.model.refresh()
        self.assertEqual(len(self.requests), 2)

    def test_invalid_columns_filters_sort_and_paging_rejected(self):
        with self.assertRaises(KeyError):
            self.model.add_filter("missing", "eq", 1)
        with self.assertRaises(ValueError):
            self.model.add_filter("id", "invalid", 1)
        with self.assertRaises(ValueError):
            self.model.set_sort(("missing", False))
        with self.assertRaises(ValueError):
            self.model.page(0)

    def test_callback_contract_is_validated(self):
        model = ServerSideTableModel(["id"], lambda q: [])
        with self.assertRaises(TypeError):
            model.page()
        model = ServerSideTableModel(["id"], lambda q: ServerPage([], 2, q.page_size, 0))
        with self.assertRaises(ValueError):
            model.page(1)

    def test_state_transitions(self):
        model = ServerSideTableModel(["id"], lambda q: ServerPage([], q.page, q.page_size, 0))
        self.assertEqual(model.state, "loading")
        model.page()
        self.assertEqual(model.state, "empty")


if __name__ == "__main__":
    unittest.main()
