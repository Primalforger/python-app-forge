"""A tiny stand-in for PySide6 so the GUI module can be *executed* (not just compiled) without Qt.

It verifies our own logic (screens build, navigation works, handlers call services correctly). It cannot
verify real Qt behaviour: layout, rendering, keyboard focus or signal semantics.
"""
import sys
import types

ERRORS: list[str] = []
INSTANCES: list = []  # every widget created, including locals that never become attributes


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub()


class _Stub(metaclass=_Meta):
    def __init__(self, *a, **k):
        self._text = a[0] if a and isinstance(a[0], str) else ""
        self._items, self._selected, self._accessible = {}, [], ""
        self._combo_items = []
        self._cell_widgets, self._rows, self._current_row = {}, 0, -1
        INSTANCES.append(self)

    def __call__(self, *a, **k):
        return _Stub()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub()

    # state we want to observe
    def setAccessibleName(self, n): self._accessible = n
    def accessibleName(self): return self._accessible
    def text(self): return self._text
    def setText(self, t): self._text = str(t)
    def toPlainText(self): return self._text
    def setPlainText(self, t): self._text = str(t)
    def currentText(self): return self._text
    def addItems(self, items):  # like QComboBox, the first item becomes current
        self._combo_items = list(items)
        self._text = self._combo_items[0] if self._combo_items else ""
    def findText(self, value):
        try:
            return self._combo_items.index(value)
        except ValueError:
            return -1
    def setCurrentIndex(self, index):
        if 0 <= index < len(self._combo_items):
            self._text = self._combo_items[index]
    def setItem(self, r, c, item): self._items[(r, c)] = item
    def item(self, r, c): return self._items.get((r, c))
    def rowCount(self): return self._rows
    def insertRow(self, row): self._rows += 1
    def removeRow(self, row):
        self._rows -= 1
        self._items = {(r - (r > row), c): v for (r, c), v in self._items.items() if r != row}
        self._cell_widgets = {(r - (r > row), c): v for (r, c), v in self._cell_widgets.items() if r != row}
    def setCellWidget(self, r, c, widget): self._cell_widgets[(r, c)] = widget
    def cellWidget(self, r, c): return self._cell_widgets.get((r, c))
    def setCurrentCell(self, row, col): self._current_row = row
    def currentRow(self): return self._current_row
    def editItem(self, item): return None
    def setCurrentText(self, value): self._text = str(value)
    def selectedItems(self): return list(self._selected)


class _MessageBox(_Stub):
    StandardButton = types.SimpleNamespace(Yes=object(), No=object())

    @classmethod
    def question(cls, *a, **k): return cls.StandardButton.Yes

    @classmethod
    def warning(cls, parent, title, text, *a): ERRORS.append(f"warning:{title}:{text}")

    @classmethod
    def critical(cls, parent, title, text, *a): ERRORS.append(f"critical:{title}:{text}")


_cache: dict[str, type] = {}


def _getattr(name):
    if name == "QMessageBox":
        return _MessageBox
    if name.startswith("__"):
        raise AttributeError(name)
    return _cache.setdefault(name, type(name, (_Stub,), {}))


_NAMES = ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "app_forge.gui.app")
_saved: dict = {}


def install():
    ERRORS.clear()
    INSTANCES.clear()
    _saved.update({n: sys.modules[n] for n in _NAMES if n in sys.modules})  # keep real Qt if it was imported
    mods = {}
    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
        m = types.ModuleType(name)
        m.__getattr__ = _getattr
        mods[name] = m
        sys.modules[name] = m
    sys.modules["PySide6"].QtCore, sys.modules["PySide6"].QtGui, sys.modules["PySide6"].QtWidgets = (\n        mods["PySide6.QtCore"], mods["PySide6.QtGui"], mods["PySide6.QtWidgets"]\n    )
    sys.modules.pop("app_forge.gui.app", None)


def uninstall():
    for name in _NAMES:
        sys.modules.pop(name, None)
    sys.modules.update(_saved)
    _saved.clear()
