"""PySide6 model/view adapter for the framework-independent advanced TableModel.

The adapter is duck-typed so generated components need not be imported into
the Forge runtime package.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class QtTableModel(QAbstractTableModel):
    """Expose a Forge TableModel through Qt's model/view API.

    editable_columns opts individual keys into editing. Changes are written
    back to the source model's stable row storage and signalled to Qt.
    """

    def __init__(self, table_model: Any, parent=None, *, editable_columns=()):
        super().__init__(parent)
        self.table_model = table_model
        self.editable_columns = frozenset(editable_columns)
        self._rows: list[dict] = []
        self._columns: list[Any] = []
        self.refresh()

    def _visible_columns(self) -> list[Any]:
        return [column for column in self.table_model.columns if column.visible]

    def refresh(self) -> None:
        self.beginResetModel()
        self._columns = self._visible_columns()
        self._rows = list(self.table_model.result_rows())
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._columns):
            column = self._columns[section]
            return column.title or column.key
        if orientation == Qt.Orientation.Vertical and 0 <= section < len(self._rows):
            return section + 1
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        if not (0 <= index.column() < len(self._columns)):
            return None
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        value = self._rows[index.row()].get(self._columns[index.column()].key)
        if value is None:
            return ""
        return str(value) if role == Qt.ItemDataRole.DisplayRole else value

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = super().flags(index)
        if self._columns[index.column()].key in self.editable_columns:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value: Any, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if not (0 <= index.row() < len(self._rows) and 0 <= index.column() < len(self._columns)):
            return False
        column = self._columns[index.column()]
        if column.key not in self.editable_columns:
            return False
        row = self._rows[index.row()]
        row_id = row.get("_id")
        if not isinstance(row_id, int) or not (0 <= row_id < len(self.table_model._rows)):
            return False
        self.table_model._rows[row_id][column.key] = value
        row[column.key] = value
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        return True

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        if not 0 <= column < len(self._columns):
            return
        key = self._columns[column].key
        descending = order == Qt.SortOrder.DescendingOrder
        self.beginResetModel()
        self.table_model.set_sort((key, descending))
        self._rows = list(self.table_model.result_rows())
        self.endResetModel()

    def sync_selection(self, selected_row_indexes) -> None:
        self.table_model.selection.clear()
        for row_index in selected_row_indexes:
            if 0 <= row_index < len(self._rows):
                row_id = self._rows[row_index].get("_id")
                if isinstance(row_id, int):
                    self.table_model.selection.add(row_id)


def bind_table_view(view, table_model: Any, *, editable_columns=()) -> QtTableModel:
    """Attach the adapter to a QTableView and sync selection to stable row IDs."""
    adapter = QtTableModel(table_model, view, editable_columns=editable_columns)
    view.setModel(adapter)
    view.setSelectionBehavior(view.SelectionBehavior.SelectRows)
    view.setSelectionMode(view.SelectionMode.ExtendedSelection)

    def update_selection(*_):
        indexes = view.selectionModel().selectedRows()
        adapter.sync_selection(index.row() for index in indexes)

    view.selectionModel().selectionChanged.connect(update_selection)
    return adapter
