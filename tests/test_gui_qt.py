"""Real PySide6 tests, run headless (QT_QPA_PLATFORM=offscreen). Skipped automatically when PySide6 is absent.

These are the tests that can actually show whether the GUI works in Qt. They have NOT been executed in the
environment where this project was written (PySide6 could not be installed there). Run them with:

    pip install -e ".[gui]" && python scripts/verify_gui.py
"""
import json
import os
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QListWidget, QMessageBox,
                                   QPlainTextEdit, QPushButton, QScrollArea, QTableWidget)
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


    def test_responsive_shell_keeps_pages_scrollable_and_navigation_compact(self):
        from app_forge.gui.app import _scrollable_page
        self.assertIsInstance(self.win.stack.currentWidget(), QScrollArea)
        self.assertTrue(self.win.stack.currentWidget().widgetResizable())
        self.assertIsNotNone(self.win.stack.currentWidget().widget())

        self.win.resize(820, 620)
        self.app.processEvents()
        self.assertEqual(self.win.sidebar.width(), 184)
        self.assertGreaterEqual(self.win.width(), 760)

        self.win.resize(1200, 760)
        self.app.processEvents()
        self.assertEqual(self.win.sidebar.width(), 238)
        self.assertTrue(all(isinstance(self.win.stack.widget(i), QScrollArea)
                            for i in range(self.win.stack.count())))

    def test_dashboard_and_sidebar_layout_remain_readable_at_compact_sizes(self):
        self.assertEqual(self.win.global_search_button.text(), "Search everything")
        self.assertEqual(self.win.global_search_button.accessibleName(), "Search everything")
        self.assertTrue(self.win.nav.wordWrap())
        self.assertTrue(self.win.metric_total.wordWrap())
        self.assertTrue(self.win.metric_succeeded.wordWrap())
        self.assertTrue(self.win.metric_failed.wordWrap())
        self.assertEqual(self.win.findChild(QLabel, "eyebrow").text(), "OPERATIONS OVERVIEW")

        self.win.resize(760, 560)
        self.app.processEvents()
        self.assertEqual(self.win.sidebar.width(), 184)
        self.assertGreaterEqual(self.win.global_search_button.width(), 140)
        self.assertLessEqual(
            self.win.global_search_button.fontMetrics().horizontalAdvance(
                self.win.global_search_button.text()
            ) + 14,
            self.win.global_search_button.width(),
        )
        self.assertGreaterEqual(self.win.metric_total.height(), 72)

        self.win.resize(1200, 760)
        self.app.processEvents()
        self.assertEqual(self.win.sidebar.width(), 238)
        self.assertGreaterEqual(self.win.global_search_button.width(), 190)

    def test_command_palette_filters_and_navigates(self):
        self.win.nav.setCurrentRow(0)
        palette = self.gui.CommandPaletteDialog(self.win._command_palette_commands(), self.win)
        palette.query.setText("table designer")
        self.assertEqual(palette.results.count(), 1)
        self.assertEqual(palette.results.item(0).text(), "Go to Table Designer")
        QTest.keyClick(palette.query, Qt.Key.Key_Return)
        self.assertEqual(self.win.nav.currentRow(), self.gui.NAV.index("Table Designer"))

    def test_command_palette_shortcut_and_empty_search(self):
        self.assertEqual(self.win.command_palette_shortcut.key().toString(), "Ctrl+K")
        palette = self.gui.CommandPaletteDialog(self.win._command_palette_commands(), self.win)
        self.assertGreaterEqual(palette.results.count(), len(self.gui.NAV))
        palette.query.setText("no matching command")
        self.assertEqual(palette.results.count(), 0)

    def test_desktop_session_restores_theme_and_active_screen(self):
        self.win.set_theme("dark")
        print("QTDIAG: before navigation", flush=True)
        self.win.nav.setCurrentRow(self.gui.NAV.index("Integration Workbench"))
        print("QTDIAG: after navigation", flush=True)
        self.win.close()
        saved = self.s.load_desktop_session()
        self.assertEqual(saved["theme"], "dark")
        self.assertEqual(saved["screen"], self.gui.NAV.index("Integration Workbench"))
        self.assertIn("geometry", saved)
        restored = self.gui.MainWindow(self.services())
        self.addCleanup(restored.close)
        self.assertEqual(restored.theme, "dark")
        self.assertEqual(restored.nav.currentRow(), self.gui.NAV.index("Integration Workbench"))

    def test_recent_projects_menu_remembers_opens_and_clears(self):
        project = self.tmp / "recent-project"
        project.mkdir()
        expected = str(project.resolve())
        self.win._remember_project(str(project))
        self.assertEqual(self.win.s.list_recent_projects(existing_only=True), [expected])
        actions = self.win._recent_projects_menu.actions()
        recent_action = next(action for action in actions if action.text() == expected)
        recent_action.trigger()
        self.assertEqual(self.win.w_path.text(), expected)
        self.assertEqual(self.win.q_path.text(), expected)
        self.assertEqual(self.win.nav.currentRow(), self.gui.NAV.index("Integration Workbench"))
        self.win._clear_recent_projects()
        self.assertEqual(self.win.s.list_recent_projects(), [])

    def test_dashboard_explains_activity_and_clears_only_operation_history(self):
        project = self.tmp / "dashboard-preservation"
        project.mkdir()
        self.s.add_recent_project(project)
        self.s.store.add_evidence([{
            "run_id": "keep-run", "subject": str(project), "check_id": "unit",
            "status": "passed", "detail": "preserve me", "duration_s": 0.1,
            "recorded_at": "2026-11-03T12:00:00+00:00",
        }])
        with self.s.operation("dashboard_test", project):
            pass
        self.win.refresh_dashboard()
        self.assertEqual(self.win.activity_description.text(), "Your latest Forge activity, outcomes, and operation history.")
        self.assertEqual(self.win.metric_total.text(), "<b>1</b><br>Total operations")
        self.assertEqual(self.win.metric_succeeded.text(), "<b>1</b><br>Succeeded")
        self.assertEqual(self.win.metric_failed.text(), "<b>0</b><br>Needs attention")
        self.assertFalse(hasattr(self.win, "metric_retention"))
        self.assertFalse(hasattr(self.win, "metric_running"))
        self.assertEqual(self.win.activity_technical_button.text(), "Show technical details")
        self.assertEqual(self.win.ops.objectName(), "activityTable")
        self.assertEqual(self.s.history_count(), 1)
        self.assertEqual(self.s.clear_history(), 1)
        self.assertEqual(self.s.history_count(), 0)
        self.assertEqual(self.s.store.list_evidence(str(project))[0]["detail"], "preserve me")
        self.assertEqual(self.s.list_recent_projects(), [str(project.resolve())])

    def test_dashboard_action_center_surfaces_and_filters_failed_operations(self):
        with self.assertRaisesRegex(RuntimeError, "expected test failure"):
            with self.s.operation("dashboard_failure", self.tmp / "failed-target"):
                raise RuntimeError("expected test failure")
        self.win.refresh_dashboard()
        self.assertTrue(self.win.review_failed_button.isEnabled())
        self.assertFalse(self.win.review_failed_button.isHidden())
        self.assertIn("1 failed operation", self.win.review_failed_button.text())
        self.win.review_failed_activity()
        self.assertEqual(self.win.activity_status_filter.currentText(), "failed")
        self.assertEqual(self.win.ops.rowCount(), 1)
        self.assertEqual(self.win.ops.item(0, 1).text(), "dashboard_failure")

    def test_dashboard_activity_search_filters_and_details(self):
        first_target = self.tmp / "activity-alpha"
        second_target = self.tmp / "activity-beta"
        with self.s.operation("dashboard_alpha", first_target):
            pass
        with self.s.operation("dashboard_beta", second_target):
            pass

        self.win.refresh_dashboard()
        self.assertEqual(self.win.ops.rowCount(), 2)
        self.win.activity_kind_filter.setCurrentText("dashboard_alpha")
        self.assertEqual(self.win.ops.rowCount(), 1)
        self.assertEqual(self.win.ops.item(0, 1).text(), "dashboard_alpha")
        self.assertIn("dashboard_alpha", self.win.activity_detail.toPlainText())
        self.assertIn("Status: Succeeded", self.win.activity_detail.toPlainText())
        self.assertNotIn('"operation_id"', self.win.activity_detail.toPlainText())
        self.assertTrue(self.win.activity_technical_button.isEnabled())
        self.win.activity_technical_button.setChecked(True)
        self.assertIn('"operation_id"', self.win.activity_detail.toPlainText())
        self.win.activity_technical_button.setChecked(False)
        self.assertNotIn('"operation_id"', self.win.activity_detail.toPlainText())

        self.win.activity_kind_filter.setCurrentText("All kinds")
        self.win.activity_search.setText("activity-beta")
        self.assertEqual(self.win.ops.rowCount(), 1)
        self.assertEqual(self.win.ops.item(0, 2).text(), str(second_target))
        self.assertIn("activity-beta", self.win.activity_detail.toPlainText())

        self.win.activity_search.setText("no-such-operation")
        self.assertEqual(self.win.ops.rowCount(), 0)
        self.assertIn("No activity records match", self.win.activity_detail.toPlainText())
        self.assertFalse(self.win.activity_technical_button.isEnabled())

    def test_activity_center_summarizes_selection_and_copies_operation_id(self):
        target = self.tmp / "copy-operation-id"
        with self.s.operation("copyable_operation", target) as operation:
            pass
        self.win.refresh_dashboard()
        self.assertIn("SUCCEEDED", self.win.activity_detail_summary.text())
        self.assertIn("copyable_operation", self.win.activity_detail_summary.text())
        self.assertTrue(self.win.copy_activity_id_button.isEnabled())
        operation_id = self.win._visible_activity_rows[0]["operation_id"]
        self.win.copy_selected_activity_id()
        self.assertEqual(self.gui.QApplication.clipboard().text(), operation_id)
        self.win.activity_search.setText("not-a-real-operation")
        self.assertFalse(self.win.copy_activity_id_button.isEnabled())

    def test_invalid_saved_geometry_recovers_to_available_screen(self):
        self.s.save_desktop_session({"geometry": "not-hex"})
        restored = self.gui.MainWindow(self.s)
        self.addCleanup(restored.close)
        self.assertGreaterEqual(restored.width(), 760)
        self.assertGreaterEqual(restored.height(), 520)
        screen = restored.screen() or self.app.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.assertTrue(available.intersects(restored.frameGeometry()))

    def test_window_structure(self):
        self.assertEqual(self.win.nav.count(), len(self.gui.NAV))
        self.assertEqual(self.win.stack.count(), len(self.gui.NAV))

    def test_every_screen_loads_renders_and_reports_no_errors(self):
        for row in range(len(self.gui.NAV)):
            self.win.nav.setCurrentRow(row)
            self.assertEqual(self.win.stack.currentIndex(), row, self.gui.NAV[row])
            self.assertFalse(self.win.grab().isNull(), f"{self.gui.NAV[row]} failed to render")
        self.assertEqual(self.errors, [])

    def test_project_workspace_lists_recent_projects_and_opens_selection(self):
        project = self.tmp / "workspace-project"
        project.mkdir()
        self.s.add_recent_project(project)
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Workspace"))
        self.assertEqual(self.win.workspace_projects.count(), 1)
        self.assertEqual(self.win.workspace_summary.text(), "1 recent project available")
        item = self.win.workspace_projects.item(0)
        self.assertEqual(item.text(), "workspace-project")
        self.assertIn(str(project.resolve()), self.win.workspace_detail.toPlainText())
        self.win.open_project_workspace_selection()
        self.assertEqual(self.win.nav.currentRow(), self.gui.NAV.index("Integration Workbench"))
        self.assertEqual(self.win.w_path.text(), str(project.resolve()))
        self.assertEqual(self.win.q_path.text(), str(project.resolve()))

    def test_project_workspace_can_add_an_existing_folder(self):
        project = self.tmp / "existing-workspace-project"
        project.mkdir()
        marker = project / "keep-me.txt"
        marker.write_text("untouched", encoding="utf-8")
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Workspace"))
        with mock.patch.object(self.gui.QFileDialog, "getExistingDirectory", return_value=str(project)):
            self.win.add_existing_workspace_project()
        self.assertIn(str(project.resolve()), self.s.list_recent_projects(existing_only=True))
        self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
        self.assertEqual(self.win.workspace_projects.count(), 1)
        self.assertEqual(self.win.workspace_projects.item(0).text(), project.name)

    def test_project_workspace_empty_state_is_helpful(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Workspace"))
        self.assertEqual(self.win.workspace_projects.count(), 0)
        self.assertEqual(self.win.workspace_summary.text(), "No projects in your recent workspace yet")
        self.assertIn("No recent projects yet", self.win.workspace_detail.toPlainText())

    def test_sidebar_branding_descriptions_and_navigation_layout(self):
        self.assertEqual(self.win.sidebar.objectName(), "sidebar")
        self.assertEqual(self.win.nav.count(), len(self.gui.NAV))
        self.assertEqual(len(self.gui.NAV_DESCRIPTIONS), len(self.gui.NAV))
        self.assertEqual(self.win.nav.item(0).toolTip(), self.gui.NAV_DESCRIPTIONS[0])
        self.assertEqual(self.win.nav.item(5).statusTip(), self.gui.NAV_DESCRIPTIONS[5])
        self.assertTrue(self.win.findChild(type(self.win.status), "sidebarBrand"))
        self.assertTrue(self.win.findChild(type(self.win.status), "sidebarTagline"))
        self.assertTrue(self.win.findChild(type(self.win.status), "sidebarHint"))

    def test_keyboard_navigation_changes_screen(self):
        self.win.nav.setFocus()
        self.win.nav.setCurrentRow(0)
        QTest.keyClick(self.win.nav, Qt.Key.Key_Down)
        self.assertEqual((self.win.nav.currentRow(), self.win.stack.currentIndex()), (1, 1))
        QTest.keyClick(self.win.nav, Qt.Key.Key_Up)
        self.assertEqual(self.win.stack.currentIndex(), 0)

    def test_project_component_picker_searches_and_preserves_multi_selection(self):
        dialog = self.win._component_picker_dialog()
        self.assertGreater(dialog.component_items.count(), 0)
        ids = [str(dialog.component_items.item(i).data(Qt.ItemDataRole.UserRole))
               for i in range(dialog.component_items.count())]
        self.assertEqual(len(ids), len(set(ids)))
        first = dialog.component_items.item(0)
        first.setCheckState(Qt.CheckState.Checked)
        self.assertIn("1 selected", dialog.findChild(QLabel, "selectionSummary").text())
        category = str(first.data(Qt.ItemDataRole.UserRole + 1))
        self.assertIn(category, first.text())
        self.assertIn(ids[0], dialog.findChild(QLabel, "selectionSummary").text())
        dialog.findChild(QLineEdit).setText(category)
        self.assertFalse(first.isHidden())
        dialog.findChild(QLineEdit).clear()
        dialog.findChild(QLineEdit).setText(ids[0])
        self.assertTrue(first.isHidden() is False)
        self.assertTrue(any(dialog.component_items.item(i).isHidden()
                            for i in range(dialog.component_items.count())))
        dialog.accept()
        self.win._selected_component_ids = [ids[0], ids[-1]]
        reopened = self.win._component_picker_dialog()
        checked = [str(reopened.component_items.item(i).data(Qt.ItemDataRole.UserRole))
                   for i in range(reopened.component_items.count())
                   if reopened.component_items.item(i).checkState() == Qt.CheckState.Checked]
        self.assertEqual(checked, [ids[0], ids[-1]])

    def test_project_component_picker_selection_flows_into_generation_review(self):
        captured = {}
        self.win._selected_component_ids = ["forge.forms-validation"]
        self.win.t_name.setText("Component Picker App")
        def create_project(archetype, config, output, *, components, dry_run, cancel_token, progress):
            captured.update(components=components, dry_run=dry_run, cancel_token=cancel_token)
            progress({"stage": "compose", "message": "Assembling project files"})
            return {"plan": "ready"}
        with mock.patch.object(self.s, "create_project", side_effect=create_project):
            self.win.review_generation()
            self._wait_for_background()
        self.assertEqual(captured["components"], ["forge.forms-validation"])
        self.assertTrue(captured["dry_run"])
        self.assertIsNotNone(captured["cancel_token"])
        self.assertIn("ready", self.win.gr_out.toPlainText())

    def test_project_wizard_lists_real_templates_and_explains_selection(self):
        template_ids = {
            str(self.win.t_arch.itemData(index))
            for index in range(self.win.t_arch.count())
        }
        expected = {item["id"] for item in self.s.list_templates()}
        self.assertEqual(template_ids, expected)
        self.assertIn("desktop-pyside6", template_ids)
        self.assertIn("PySide6 desktop shell", self.win.template_summary.text())
        web_index = next(
            index for index in range(self.win.t_arch.count())
            if self.win.t_arch.itemData(index) == "web-fastapi"
        )
        self.win.t_arch.setCurrentIndex(web_index)
        self.assertIn("FastAPI", self.win.template_summary.text())
        self.assertIn("web", self.win.template_summary.text())

    def test_project_wizard_opens_dedicated_generation_review(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Wizard"))
        self.win.t_name.setText("Reviewed Qt App")
        self.win.nav.setCurrentRow(self.gui.NAV.index("Generation Review"))
        self.win.review_generation()
        self._wait_for_background()
        self.assertIn("Reviewed Qt App", self.win.gr_out.toPlainText())
        self.assertFalse((self.tmp / "reviewed-qt-app").exists())

    def test_generation_review_summarizes_plan_and_lists_generated_files(self):
        result = {
            "operation_id": "preview-123", "dry_run": True, "path": str(self.tmp / "reviewed-app"),
            "template": "desktop@1.0", "components": ["forge.forms-validation"],
            "added_dependencies": ["requests>=2"], "patches": ["forge.forms-validation:forms -> src/app.py"],
            "files": [{"path": "pyproject.toml", "bytes": 240}, {"path": "src/app.py", "bytes": 512}],
            "configuration": {"name": "Reviewed App", "package": "reviewed_app"},
        }
        self.win._render_generation_review(result)
        self.assertIn("Reviewed App", self.win.gr_summary.text())
        self.assertIn("2 files", self.win.gr_summary.text())
        self.assertIn("forge.forms-validation", self.win.gr_dependencies.text())
        self.assertIn("requests>=2", self.win.gr_dependencies.text())
        self.assertEqual(self.win.gr_files.rowCount(), 2)
        displayed_paths = {self.win.gr_files.item(row, 0).text() for row in range(self.win.gr_files.rowCount())}
        self.assertEqual(displayed_paths, {"pyproject.toml", "src/app.py"})
        self.assertTrue(self.win.gr_copy_button.isEnabled())
        self.win.copy_generation_review()
        self.assertIn("preview-123", self.gui.QApplication.clipboard().text())

    def test_project_generation_runs_in_background_with_progress_and_remembers_project(self):
        output = self.tmp / "background-generated"
        started = threading.Event()
        release = threading.Event()

        def create_project(_template, _options, _output, *, components, dry_run, cancel_token, progress):
            progress({"stage": "write", "message": "Writing sample.py", "current": 1, "total": 2})
            started.set()
            release.wait(3)
            output.mkdir()
            return {"path": str(output), "dry_run": False, "files": [{"path": "sample.py"}]}

        self.win.t_name.setText("Background Generated")
        self.win.t_out.setText(str(output))
        with mock.patch.object(self.s, "create_project", side_effect=create_project):
            self.win.generate(False)
            self.assertTrue(started.wait(2))
            self.app.processEvents()
            self.assertTrue(self.win.progress_bar.isVisible())
            self.assertTrue(self.win.cancel_button.isEnabled())
            self.assertEqual(self.win.progress_bar.maximum(), 2)
            release.set()
            self._wait_for_background()

        self.assertFalse(self.win.progress_bar.isVisible())
        self.assertFalse(self.win.cancel_button.isEnabled())
        self.assertIn("sample.py", self.win.t_out_box.toPlainText())
        self.assertEqual(self.s.list_recent_projects(existing_only=True), [str(output.resolve())])

    def test_catalog_search_filters(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Component Catalog"))
        self.assertGreater(self.win.c_table.rowCount(), 3)
        self.win.c_query.setText("pagination")
        self.assertEqual(self.win.c_table.rowCount(), 1)

    def test_catalog_empty_state_explains_no_matches(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Component Catalog"))
        self.win.c_query.setText("component-that-does-not-exist")
        self.assertEqual(self.win.c_table.rowCount(), 0)
        self.assertTrue(self.win.catalog_empty.isVisible())
        self.assertIn("clear the search", self.win.catalog_empty.text())

    def test_project_wizard_explains_preview_before_creation(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Wizard"))
        self.assertIn("preview the generated files", self.win.wizard_intro.text().lower())
        self.assertEqual(self.win.t_review_button.text(), "Preview project plan")
        with mock.patch.object(self.win, "review_generation") as preview:
            self.win.open_generation_review_from_wizard()
        self.assertEqual(self.win.nav.currentRow(), self.gui.NAV.index("Generation Review"))
        preview.assert_called_once_with()

    def test_theme_switch_applies_tokens_and_focus_style(self):
        from app_forge.gui.theme import TOKENS
        for name in TOKENS:
            self.win.set_theme(name)
            sheet = self.win.styleSheet()
            self.assertIn(TOKENS[name]["background"], sheet)
            self.assertIn(":focus", sheet)  # focus must stay visible in both themes
            for control in ("QCheckBox:focus", "QRadioButton:focus", "QSpinBox:focus", "QDateEdit:focus", "QSlider:focus"):
                self.assertIn(control, sheet)
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
        print("QTDIAG: test entered", flush=True)
        proj = self.make_project(self.s, "cli", "Qt Flow")
        print("QTDIAG: project created", flush=True)
        self.win.nav.setCurrentRow(self.gui.NAV.index("Integration Workbench"))
        self.win.w_path.setText(str(proj))
        self.win.analyze()
        print("QTDIAG: analyzed", flush=True)
        self.assertIn('"level": 1', self.win.w_out.toPlainText())
        self.win.w_comp.setText("forge.forms-validation")
        self.win.make_plan()
        print("QTDIAG: plan created", flush=True)
        self.assertTrue(self.win.w_apply.isEnabled())
        # This GUI test exercises the workbench's apply/recovery lifecycle. Keep
        # project test execution out of this UI test: VerificationEngine has its
        # own subprocess and cancellation coverage, and running an arbitrary
        # generated project's test runner here makes the Qt suite nondeterministic.
        verification = {
            "run_id": "run-gui-integration", "overall": "passed", "passed": 1,
            "failed": 0, "not_run": [], "complete": True, "evidence": [],
        }
        with (mock.patch.object(self.s.integration._verifier, "run", return_value=verification),
              mock.patch.object(self.win, "_confirm_plan", return_value=True)):
            self.win.apply()
            self._wait_for_background()
            print("QTDIAG: worker finished", flush=True)
        self.assertTrue((proj / "src/qt_flow/forms.py").is_file())
        print("QTDIAG: file exists", flush=True)
        self.assertTrue(self.win.w_recover.isEnabled())
        print("QTDIAG: before recover", flush=True)
        self.win.recover()
        print("QTDIAG: recover returned", flush=True)
        self.assertFalse((proj / "src/qt_flow/forms.py").exists())
        self.assertEqual(self.errors, [])

    def test_conflicts_disable_apply(self):
        proj = self.make_project(self.s, "cli", "Qt Conflict")
        (proj / "src/qt_conflict/forms.py").write_text("# mine\n")
        self.win.w_path.setText(str(proj))
        self.win.w_comp.setText("forge.forms-validation")
        self.win.make_plan()
        self.assertFalse(self.win.w_apply.isEnabled())

    def test_table_designer_exposes_column_metadata_and_generation_options(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Table Designer"))
        self.assertEqual(self.win.td_columns.rowCount(), 3)
        self.assertEqual(self.win.td_columns.columnCount(), 4)
        self.win.td_columns.item(0, 0).setText("order_id")
        self.win.td_columns.item(0, 1).setText("Order ID")
        self.win.td_columns.cellWidget(0, 2).setCurrentText("number")
        self.win.td_columns.cellWidget(0, 3).setCurrentText("Hidden")
        self.win.td_page_size.setValue(50)
        self.win.td_filter_mode.setCurrentText("or")
        self.win.add_table_column()
        self.assertEqual(self.win.td_columns.rowCount(), 4)
        self.win.td_columns.setCurrentCell(3, 0)
        self.win.remove_table_column()
        self.assertEqual(self.win.td_columns.rowCount(), 3)
        self.win.design_table()
        generated = self.win.td_out.toPlainText()
        self.assertIn("order_id", generated)
        self.assertTrue(generated)
        definition = self.s.design_table({
            "name": "Orders",
            "columns": [{"key": "order_id", "title": "Order ID", "type": "number", "visible": False}],
            "page_size": 50, "filter_mode": "or",
        })["definition"]
        self.assertEqual(definition["columns"][0]["title"], "Order ID")
        self.assertFalse(definition["columns"][0]["visible"])
        self.assertEqual(definition["page_size"], 50)
        self.assertEqual(definition["filter_mode"], "or")

    def test_project_health_assessment_summarizes_read_only_project_signals(self):
        project = self.make_project(self.s, "cli", "Health Sample")
        self.win.nav.setCurrentRow(self.gui.NAV.index("Quality and Compliance"))
        self.win.q_path.setText(str(project))
        self.win.assess_project_health()
        self.assertEqual(self.win.health_table.rowCount(), 7)
        self.assertIn("Health Sample", self.win.health_summary.text())
        self.assertIn("Read-only project assessment", self.win.q_out.toPlainText())
        self.assertIn("Tests", [self.win.health_table.item(row, 0).text()
                                for row in range(self.win.health_table.rowCount())])

    def test_verification_history_displays_runs_and_comparison(self):
        project = self.make_project(self.s, "cli", "Evidence Sample")
        subject = str(project.resolve())
        self.s.store.add_evidence([
            {"run_id": "run-new", "subject": subject, "check_id": "syntax", "status": "passed",
             "detail": "compiled", "duration_s": 0.1, "recorded_at": "2026-11-07T12:00:00+00:00"},
            {"run_id": "run-old", "subject": subject, "check_id": "tests", "status": "failed",
             "detail": "one failed", "duration_s": 0.2, "recorded_at": "2026-11-06T12:00:00+00:00"},
        ])
        self.win.nav.setCurrentRow(self.gui.NAV.index("Quality and Compliance"))
        self.win.q_path.setText(str(project))
        self.win.load_evidence_history()
        self.assertEqual(self.win.evidence_table.rowCount(), 2)
        self.assertTrue(self.win.evidence_compare_button.isEnabled())
        new_run_row = next(row for row in range(self.win.evidence_table.rowCount())
                           if self.win.evidence_table.item(row, 0).text() == "run-new")
        self.win.evidence_table.selectRow(new_run_row)
        self.assertIn("run-new", self.win.evidence_detail.text())
        self.assertIn("syntax: passed", self.win.evidence_detail.text())
        with mock.patch.object(self.s, "compare_runs", return_value={"regressions": [], "improvements": []}) as compare:
            self.win.compare_latest_runs()
        compare.assert_called_once_with(str(project))
        self.assertIn("regressions", self.win.q_out.toPlainText())

    def test_health_assessment_shows_prioritized_recommendations(self):
        project = self.make_project(self.s, "cli", "Recommendation Sample")
        self.win.nav.setCurrentRow(self.gui.NAV.index("Quality and Compliance"))
        self.win.q_path.setText(str(project))
        self.win.assess_project_health()
        self.assertIn("Prioritized recommendations", self.win.health_recommendations.text())
        self.assertTrue(self.win.health_recommendations.text().strip())

    def test_unexpected_ui_error_is_saved_as_local_crash_report(self):
        with mock.patch.object(self.s, "doctor", side_effect=RuntimeError("token=private-value")):
            self.win.run_doctor()
        reports = list((self.s.settings.home / "crashes").glob("crash-*.json"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text(encoding="utf-8")
        self.assertIn('"exception_type": "RuntimeError"', report)
        self.assertNotIn("private-value", report)
        self.assertIn("[REDACTED]", report)

    def test_validation_errors_are_shown_not_raised(self):
        self.win.t_name.setText("1 bad name")
        self.win.generate(True)
        self._wait_for_background()
        self.assertTrue(self.errors and self.errors[0][0] == "warning")


    def test_extension_manager_explains_empty_discovery_state(self):
        with mock.patch.object(self.s, "plugin_list", return_value=[]):
            self.win.nav.setCurrentRow(self.gui.NAV.index("Extension Manager"))
        self.assertEqual(self.win.ex_table.rowCount(), 0)
        self.assertIn("No extensions are currently installed", self.win.ex_detail.toPlainText())
        self.assertIn("app_forge.plugins", self.win.ex_detail.toPlainText())
        self.assertFalse(self.win.ex_inspect_button.isEnabled())

    def test_extension_manager_inspects_metadata_without_execution(self):
        extension = {
            "name": "sample-extension", "target": "sample_package:Extension",
            "trust": "untrusted", "enabled": False,
        }
        details = {
            **extension, "group": "app_forge.plugins",
            "isolation": "bubblewrap Linux namespaces; network disabled; only explicit directories writable",
        }
        with (mock.patch.object(self.s, "plugin_list", return_value=[extension]),
              mock.patch.object(self.s, "plugin_inspect", return_value=details) as inspect):
            self.win.nav.setCurrentRow(self.gui.NAV.index("Extension Manager"))
            self.assertEqual(self.win.ex_table.rowCount(), 1)
            self.win.ex_table.selectRow(0)
            self.assertIn("sample-extension", self.win.ex_detail.toPlainText())
            self.assertTrue(self.win.ex_inspect_button.isEnabled())
            self.win.inspect_ext()
        inspect.assert_called_once_with("sample-extension")
        self.assertIn("Entry-point group: app_forge.plugins", self.win.ex_detail.toPlainText())
        self.assertIn("Trust: untrusted", self.win.ex_detail.toPlainText())
        self.assertIn("bubblewrap Linux namespaces", self.win.ex_detail.toPlainText())
        self.assertIn("refused when the required OS sandbox is unavailable", self.win.ex_detail.toPlainText())

    def test_extension_trust_requires_confirmation_and_is_separate_from_enablement(self):
        extension = {
            "name": "review-me", "target": "review_package:Extension",
            "trust": "untrusted", "enabled": False,
        }
        with (mock.patch.object(self.s, "plugin_list", return_value=[extension]),
              mock.patch.object(self.s, "plugin_trust") as trust,
              mock.patch.object(self.s, "plugin_enable") as enable,
              mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No)):
            self.win.nav.setCurrentRow(self.gui.NAV.index("Extension Manager"))
            self.win.ex_table.selectRow(0)
            self.win.trust_ext()
            trust.assert_not_called()
            enable.assert_not_called()


    def test_personalization_settings_apply_and_persist(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Configuration Center"))
        self.win.preference_theme.setCurrentIndex(1)
        self.win.preference_accent.setCurrentIndex(2)
        self.win.preference_compact.setChecked(True)
        self.win.preference_mascots.setChecked(False)
        self.win.save_personalization()
        self.assertEqual(self.win.theme, "dark")
        self.assertEqual(self.win.accent, "purple")
        self.assertTrue(self.win.compact_density)
        self.assertFalse(self.win.mascots_enabled)
        saved = self.s.load_desktop_session()
        self.assertEqual(saved["theme"], "dark")
        self.assertEqual(saved["accent"], "purple")
        self.assertTrue(saved["compact_density"])
        self.assertFalse(saved["mascots_enabled"])
        self.assertIn("Preferences saved", self.win.preference_status.text())

    def test_preference_backup_round_trip_restores_only_personalization(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Configuration Center"))
        self.win.preference_theme.setCurrentIndex(1)
        self.win.preference_accent.setCurrentIndex(2)
        self.win.preference_compact.setChecked(True)
        self.win.preference_mascots.setChecked(False)
        backup = self.tmp / "preferences.json"
        self.win.export_preferences(backup)
        payload = json.loads(backup.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(set(payload), {
            "schema_version", "theme", "accent", "compact_density", "mascots_enabled",
        })

        self.win.preference_theme.setCurrentIndex(0)
        self.win.preference_accent.setCurrentIndex(0)
        self.win.preference_compact.setChecked(False)
        self.win.preference_mascots.setChecked(True)
        self.win.import_preferences(backup)
        self.assertEqual(self.win.theme, "dark")
        self.assertEqual(self.win.accent, "purple")
        self.assertTrue(self.win.compact_density)
        self.assertFalse(self.win.mascots_enabled)
        self.assertIn("restored successfully", self.win.preference_status.text())

    def test_invalid_preference_backup_does_not_change_current_preferences(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Configuration Center"))
        self.win.preference_theme.setCurrentIndex(1)
        self.win.save_personalization()
        backup = self.tmp / "invalid-preferences.json"
        backup.write_text(json.dumps({
            "schema_version": 1, "theme": "dark", "accent": "not-a-color",
            "compact_density": False, "mascots_enabled": True,
        }), encoding="utf-8")
        self.win.import_preferences(backup)
        self.assertEqual(self.win.theme, "dark")
        self.assertIn("Backup not restored", self.win.preference_status.text())

    def test_personalization_reset_restores_product_defaults(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Configuration Center"))
        self.win.preference_theme.setCurrentIndex(1)
        self.win.preference_accent.setCurrentIndex(1)
        self.win.preference_compact.setChecked(True)
        self.win.preference_mascots.setChecked(False)
        self.win.reset_personalization()
        self.assertEqual(self.win.theme, "light")
        self.assertEqual(self.win.accent, "blue")
        self.assertFalse(self.win.compact_density)
        self.assertTrue(self.win.mascots_enabled)

    def test_first_run_welcome_can_be_dismissed_and_remains_dismissed(self):
        self.assertTrue(hasattr(self.win, "welcome_panel"))
        self.win.dismiss_welcome()
        self.assertFalse(self.win.welcome_panel.isVisible())
        self.assertTrue(self.s.load_desktop_session()["welcome_seen"])
        restored = self.gui.MainWindow(self.services())
        self.addCleanup(restored.close)
        self.assertFalse(hasattr(restored, "welcome_panel"))



    def test_global_search_collects_results_across_workspace_categories(self):
        project = self.tmp / "widget-project"
        project.mkdir()
        self.s.search_components = mock.Mock(return_value=[{
            "id": "ui.widget", "name": "Widget Component", "summary": "Reusable widget",
        }])
        self.s.plugin_list = mock.Mock(return_value=[{
            "name": "widget-tools", "target": "widget_tools:main", "trust": "trusted", "enabled": True,
        }])
        self.s.list_recent_projects = mock.Mock(return_value=[str(project)])
        self.s.history = mock.Mock(return_value=[{
            "operation_id": "op-widget-1", "kind": "build_widget",
            "target": "widget-project", "status": "succeeded",
        }])
        results = self.win._global_search_items("widget")
        categories = {item["category"] for item in results}
        self.assertTrue({"Component", "Extension", "Recent project", "Operation"}.issubset(categories))
        self.assertTrue(all(callable(item["callback"]) for item in results))

    def test_global_search_dialog_filters_and_activates_selected_result(self):
        activated = []
        from app_forge.gui.app import GlobalSearchDialog
        dialog = GlobalSearchDialog(lambda query: [{
            "title": "Widget Component", "category": "Component",
            "description": "ui.widget reusable", "callback": lambda: activated.append("ui.widget"),
        }] if "widget" in query.casefold() else [], self.win)
        dialog.query.setText("wid")
        self.assertEqual(dialog.results.count(), 0)
        self.assertEqual(dialog.summary.text(), "Searching your workspace…")
        dialog.query.setText("widget")
        QTest.qWait(500)
        self.assertEqual(dialog.results.count(), 1)
        QTest.keyClick(dialog.query, Qt.Key.Key_Return)
        self.assertEqual(activated, ["ui.widget"])
        self.assertFalse(dialog.isVisible())

    def test_global_search_enter_flushes_pending_debounce(self):
        activated = []
        from app_forge.gui.app import GlobalSearchDialog
        dialog = GlobalSearchDialog(lambda query: [{
            "title": "Widget Component", "category": "Component",
            "description": "ui.widget", "callback": lambda: activated.append(query),
        }], self.win)
        dialog.query.setText("widget")
        QTest.keyClick(dialog.query, Qt.Key.Key_Return)
        self.assertEqual(activated, ["widget"])

    def test_global_search_operation_result_targets_exact_operation_id(self):
        self.win.activity_search.setText("")
        self.win._open_operation_search_result("op-widget-42")
        self.assertEqual(self.win.nav.currentRow(), self.gui.NAV.index("Dashboard"))
        self.assertEqual(self.win.activity_search.text(), "op-widget-42")
        self.assertEqual(self.win.ops.rowCount(), 0)

    def test_global_search_shortcut_and_sidebar_action(self):
        self.assertEqual(self.win.global_search_shortcut.key().toString(), "Ctrl+Shift+F")
        self.assertEqual(self.win.global_search_button.accessibleName(), "Search everything")
        self.assertEqual(self.win.global_search_button.text(), "Search")
        self.assertEqual(self.win.global_search_button.toolTip(), "Search everything (Ctrl+Shift+F)")
        self.assertLessEqual(self.win.global_search_button.sizeHint().width(), self.win.global_search_button.width())



    def test_background_operation_notifications_persist_and_update_unread_count(self):
        self.win._background_label = "Project verification"
        self.win._background_succeeded_event({"ok": True})
        self.win._background_failed_event(RuntimeError("Compiler unavailable"))
        self.win._background_cancelled_event({"message": "Cancelled by user"})
        self.assertEqual(len(self.win._notifications), 3)
        self.assertEqual(self.win.notification_button.text(), "Notifications  ·  3 new")
        saved = self.s.load_desktop_session()
        self.assertEqual(len(saved["notifications"]), 3)
        self.assertEqual([item["severity"] for item in self.win._notifications],
                         ["success", "error", "warning"])
        first = self.win._notifications[0]
        self.win._notification_action("read", first)
        self.assertEqual(self.win.notification_button.text(), "Notifications  ·  2 new")
        restored = self.gui.MainWindow(self.services())
        self.addCleanup(restored.close)
        self.assertEqual(len(restored._notifications), 3)
        self.assertEqual(sum(not item["read"] for item in restored._notifications), 2)

    def test_notification_center_mark_read_dismiss_and_clear_actions(self):
        from app_forge.gui.app import NotificationCenterDialog
        notifications = [{
            "id": "notice-1", "title": "Build completed", "message": "All checks passed",
            "severity": "success", "created_at": "2026-11-06T12:00:00+00:00",
            "read": False, "open_activity": True,
        }]
        actions = []
        dialog = NotificationCenterDialog(
            notifications,
            lambda action, item: actions.append((action, item.get("id") if item else None)),
            self.win,
        )
        dialog.items.setCurrentRow(0)
        expected_names = {
            dialog.read_button: "Mark selected notification as read",
            dialog.dismiss_button: "Dismiss selected notification",
            dialog.open_button: "Open activity for selected notification",
            dialog.clear_button: "Clear all notifications",
        }
        for button, name in expected_names.items():
            self.assertEqual(button.accessibleName(), name)
        self.assertTrue(dialog.read_button.isEnabled())
        dialog.read_button.click()
        self.assertEqual(actions[-1], ("read", "notice-1"))
        dialog.dismiss_button.click()
        self.assertEqual(actions[-1], ("dismiss", "notice-1"))
        dialog.clear_button.click()
        self.assertEqual(actions[-1], ("clear", None))

    def test_notification_center_button_is_accessible(self):
        self.assertEqual(self.win.notification_button.accessibleName(), "Open notification center")
        self.assertEqual(self.win.notification_button.text(), "Notifications")
        self.win._add_notification("info", "Workspace ready", "Forge is ready to use.")
        self.assertIn("1 new", self.win.notification_button.text())
        self.assertIn("unread notification", self.win.notification_button.toolTip().lower())


if __name__ == "__main__":
    unittest.main()
