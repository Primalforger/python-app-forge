"""Real PySide6 tests, run headless (QT_QPA_PLATFORM=offscreen). Skipped automatically when PySide6 is absent.

These are the tests that can actually show whether the GUI works in Qt. They have NOT been executed in the
environment where this project was written (PySide6 could not be installed there). Run them with:

    pip install -e ".[gui]" && python scripts/verify_gui.py
"""
import os
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLineEdit, QListWidget, QMessageBox,
                                   QPlainTextEdit, QPushButton, QTableWidget)
    HAVE_QT = True
    QT_IMPORT_ERROR = ""
except ImportError as exc:
    HAVE_QT = False
    QT_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

from tests.helpers import ForgeTestCase


@unittest.skipUnless(HAVE_QT, f"PySide6 Qt test imports failed: {QT_IMPORT_ERROR or 'PySide6 is not installed'}")
class RealQtTests(ForgeTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app_forge.gui import app as gui
        self.gui = gui
        self.errors = []
        for name in ("warning", "critical"):  # modal dialogs would block a headless run: record instead
            p = mock.patch.object(QMessageBox, name, side_effect=lambda *a, _n=name: self.errors.append((_n, a[1:3])))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
        p.start()
        self.addCleanup(p.stop)
        self.s = self.services()
        self.win = gui.MainWindow(self.s)
        self.addCleanup(self.win.close)
        self.win.show()

    def test_window_structure(self):
        self.assertEqual(self.win.nav.count(), len(self.gui.NAV))
        self.assertEqual(self.win.stack.count(), len(self.gui.NAV))

    def test_every_screen_loads_renders_and_reports_no_errors(self):
        for row in range(len(self.gui.NAV)):
            self.win.nav.setCurrentRow(row)
            self.assertEqual(self.win.stack.currentIndex(), row, self.gui.NAV[row])
            self.assertFalse(self.win.grab().isNull(), f"{self.gui.NAV[row]} failed to render")
        self.assertEqual(self.errors, [])

    def test_keyboard_navigation_changes_screen(self):
        self.win.nav.setFocus()
        self.win.nav.setCurrentRow(0)
        QTest.keyClick(self.win.nav, Qt.Key.Key_Down)
        self.assertEqual((self.win.nav.currentRow(), self.win.stack.currentIndex()), (1, 1))
        QTest.keyClick(self.win.nav, Qt.Key.Key_Up)
        self.assertEqual(self.win.stack.currentIndex(), 0)

    def test_catalog_search_filters(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Component Catalog"))
        self.assertGreater(self.win.c_table.rowCount(), 3)
        self.win.c_query.setText("pagination")
        self.assertEqual(self.win.c_table.rowCount(), 1)

    def test_theme_switch_applies_tokens_and_focus_style(self):
        from app_forge.gui.theme import TOKENS
        for name in TOKENS:
            self.win.set_theme(name)
            sheet = self.win.styleSheet()
            self.assertIn(TOKENS[name]["background"], sheet)
            self.assertIn(":focus", sheet)  # focus must stay visible in both themes
            self.assertFalse(self.win.grab().isNull())

    def test_accessibility_audit(self):
        inputs = (QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget)
        for cls in inputs:
            for w in self.win.findChildren(cls):
                self.assertTrue(w.accessibleName(), f"{cls.__name__} without accessible name: {w.objectName()!r}")
                self.assertNotEqual(w.focusPolicy(), Qt.FocusPolicy.NoFocus, f"{cls.__name__} cannot take focus")
        for w in self.win.findChildren(QCheckBox) + self.win.findChildren(QPushButton):
            self.assertTrue(w.text().strip(), "button without a label")

    def _wait_for_background(self, timeout=10):
        deadline = time.monotonic() + timeout
        while self.win._background_thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.app.processEvents()
        self.assertIsNone(self.win._background_thread, "background worker did not finish before timeout")

    def test_verification_runs_in_background_and_can_cancel(self):
        started = threading.Event()

        def slow_verify(path, *, cancel_token=None, progress=None):
            started.set()
            if progress:
                progress({"stage": "tests", "message": "Waiting in test runner"})
            cancel_token.wait(5)
            return {"overall": "cancelled", "passed": 0, "failed": 0, "not_run": [],
                    "complete": False, "run_id": "run-cancelled"}

        with mock.patch.object(self.s, "verify_project", side_effect=slow_verify):
            self.win.nav.setCurrentRow(self.gui.NAV.index("Quality and Compliance"))
            self.win.verify()
            self.assertTrue(started.wait(2))
            self.app.processEvents()
            self.assertTrue(self.win.cancel_button.isEnabled())
            self.assertIn("Waiting in test runner", self.win.status.text())
            self.win.cancel_button.click()
            self._wait_for_background()
        self.assertFalse(self.win.cancel_button.isEnabled())
        self.assertIn('"overall": "cancelled"', self.win.q_out.toPlainText())

    def test_integration_workbench_end_to_end(self):
        proj = self.make_project(self.s, "cli", "Qt Flow")
        self.win.nav.setCurrentRow(self.gui.NAV.index("Integration Workbench"))
        self.win.w_path.setText(str(proj))
        self.win.analyze()
        self.assertIn('"level": 1', self.win.w_out.toPlainText())
        self.win.w_comp.setText("forge.forms-validation")
        self.win.make_plan()
        self.assertTrue(self.win.w_apply.isEnabled())
        # This GUI test exercises the workbench's apply/recovery lifecycle. Keep
        # project test execution out of this UI test: VerificationEngine has its
        # own subprocess and cancellation coverage, and running an arbitrary
        # generated project's test runner here makes the Qt suite nondeterministic.
        verification = {
            "run_id": "run-gui-integration", "overall": "passed", "passed": 1,
            "failed": 0, "not_run": [], "complete": True, "evidence": [],
        }
        with mock.patch.object(self.s.integration._verifier, "run", return_value=verification):
            self.win.apply()
            self._wait_for_background()
        self.assertTrue((proj / "src/qt_flow/forms.py").is_file())
        self.assertTrue(self.win.w_recover.isEnabled())
        self.win.recover()
        self.assertFalse((proj / "src/qt_flow/forms.py").exists())
        self.assertEqual(self.errors, [])

    def test_conflicts_disable_apply(self):
        proj = self.make_project(self.s, "cli", "Qt Conflict")
        (proj / "src/qt_conflict/forms.py").write_text("# mine\n")
        self.win.w_path.setText(str(proj))
        self.win.w_comp.setText("forge.forms-validation")
        self.win.make_plan()
        self.assertFalse(self.win.w_apply.isEnabled())

    def test_table_designer_uses_column_grid(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Table Designer"))
        self.assertEqual(self.win.td_columns.rowCount(), 3)
        self.win.td_columns.item(0, 0).setText("order_id")
        self.win.td_columns.cellWidget(0, 1).setCurrentText("number")
        self.win.add_table_column()
        self.assertEqual(self.win.td_columns.rowCount(), 4)
        self.win.td_columns.setCurrentCell(3, 0)
        self.win.remove_table_column()
        self.assertEqual(self.win.td_columns.rowCount(), 3)
        self.win.design_table()
        self.assertIn("order_id", self.win.td_out.toPlainText())
        self.assertTrue(self.win.td_out.toPlainText())

    def test_validation_errors_are_shown_not_raised(self):
        self.win.t_name.setText("1 bad name")
        self.win.generate(True)
        self.assertTrue(self.errors and self.errors[0][0] == "warning")


if __name__ == "__main__":
    unittest.main()
