"""Qt entry point. Qt is imported lazily so importing this module never requires a display."""
from __future__ import annotations

import sys

from {{package}}.core import AppState, greeting


def main() -> int:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

    state = AppState()
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle(state.title)
    layout = QVBoxLayout(window)
    label = QLabel(greeting("world"))
    button = QPushButton("Count")
    button.clicked.connect(lambda: label.setText(f"Clicked {state.increment()} times"))
    layout.addWidget(label)
    layout.addWidget(button)
    # forge:anchor widgets
    window.resize(360, 160)
    window.show()
    return app.exec()
