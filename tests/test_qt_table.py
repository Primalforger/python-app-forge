"""Real-Qt regression tests for the table model/view adapter."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableView

from app_forge.qt_table import QtTableModel, bind_table_view


class Column:
    def __init__(self, key, title="", visible=True):
        self.key, self.title, self.visible = key, title, visible


class Table:
    columns = [Column("name", "Name"), Column("hidden", "Hidden", False), Column("value", "Value")]

    def __init__(self):
        self._rows = [{"name": "Beta", "hidden": "x", "value": 2},
                      {"name": "Alpha", "hidden": "y", "value": 1}]
        self.sort_keys = []
        self.selection = set()

    def result_rows(self):
        indexed = list(enumerate(self._rows))
        for key, descending in reversed(self.sort_keys):
            indexed.sort(key=lambda pair: pair[1].get(key), reverse=descending)
        return [{**row, "_id": row_id} for row_id, row in indexed]

    def set_sort(self, *keys):
        self.sort_keys = list(keys)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_adapter_exposes_visible_columns_and_headers(app):
    source = Table()
    adapter = QtTableModel(source)
    assert adapter.rowCount() == 2
    assert adapter.columnCount() == 2
    assert adapter.headerData(0, Qt.Orientation.Horizontal) == "Name"
    assert adapter.headerData(1, Qt.Orientation.Horizontal) == "Value"
    assert adapter.data(adapter.index(0, 0)) == "Beta"
    assert adapter.data(adapter.index(0, 1), Qt.ItemDataRole.EditRole) == 2


def test_sort_delegates_to_source_model_and_resets_rows(app):
    source = Table()
    adapter = QtTableModel(source)
    adapter.sort(0, Qt.SortOrder.AscendingOrder)
    assert adapter.data(adapter.index(0, 0)) == "Alpha"
    assert source.sort_keys == [("name", False)]


def test_editing_is_opt_in_and_updates_source_data(app):
    source = Table()
    adapter = QtTableModel(source, editable_columns={"value"})
    name = adapter.index(0, 0)
    value = adapter.index(0, 1)
    assert not (adapter.flags(name) & Qt.ItemFlag.ItemIsEditable)
    assert adapter.flags(value) & Qt.ItemFlag.ItemIsEditable
    assert adapter.setData(value, 9)
    assert source._rows[0]["value"] == 9
    assert adapter.data(value, Qt.ItemDataRole.EditRole) == 9


def test_refresh_reloads_rows_and_visible_columns(app):
    source = Table()
    adapter = QtTableModel(source)
    source.columns[0].visible = False
    source._rows.pop()
    adapter.refresh()
    assert adapter.rowCount() == 1
    assert adapter.columnCount() == 1
    assert adapter.headerData(0, Qt.Orientation.Horizontal) == "Value"


def test_view_binding_syncs_stable_row_selection(app):
    source = Table()
    view = QTableView()
    adapter = bind_table_view(view, source)
    view.selectRow(1)
    app.processEvents()
    assert source.selection == {1}
    assert view.model() is adapter
