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
        self.assertIn("not a list of installed apps", self.win.activity_description.text())
        self.assertIn("<b>1</b>", self.win.metric_total.text())
        self.assertIn("<b>1</b>", self.win.metric_succeeded.text())
        for metric in (self.win.metric_total, self.win.metric_succeeded, self.win.metric_failed,
                       self.win.metric_running, self.win.metric_retention):
            self.assertIn("<br>", metric.text())
            self.assertNotIn(r"\n", metric.text())
        self.assertIn("Retention", self.win.metric_retention.text())
        self.assertEqual(self.win.ops.objectName(), "activityTable")
        self.assertEqual(self.s.history_count(), 1)
        self.assertEqual(self.s.clear_history(), 1)
        self.assertEqual(self.s.history_count(), 0)
        self.assertEqual(self.s.store.list_evidence(str(project))[0]["detail"], "preserve me")
        self.assertEqual(self.s.list_recent_projects(), [str(project.resolve())])

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

        self.win.activity_kind_filter.setCurrentText("All kinds")
        self.win.activity_search.setText("activity-beta")
        self.assertEqual(self.win.ops.rowCount(), 1)
        self.assertEqual(self.win.ops.item(0, 2).text(), str(second_target))
        self.assertIn("activity-beta", self.win.activity_detail.toPlainText())

        self.win.activity_search.setText("no-such-operation")
        self.assertEqual(self.win.ops.rowCount(), 0)
        self.assertIn("No activity records match", self.win.activity_detail.toPlainText())

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
        item = self.win.workspace_projects.item(0)
        self.assertEqual(item.text(), "workspace-project")
        self.assertIn(str(project.resolve()), self.win.workspace_detail.toPlainText())
        self.win.open_project_workspace_selection()
        self.assertEqual(self.win.nav.currentRow(), self.gui.NAV.index("Integration Workbench"))
        self.assertEqual(self.win.w_path.text(), str(project.resolve()))
        self.assertEqual(self.win.q_path.text(), str(project.resolve()))

    def test_project_workspace_empty_state_is_helpful(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Workspace"))
        self.assertEqual(self.win.workspace_projects.count(), 0)
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

    def test_project_wizard_opens_dedicated_generation_review(self):
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Wizard"))
        self.win.t_name.setText("Reviewed Qt App")
        self.win.nav.setCurrentRow(self.gui.NAV.index("Generation Review"))
        self.win.review_generation()
        self._wait_for_background()
        self.assertIn("Reviewed Qt App", self.win.gr_out.toPlainText())
        self.assertFalse((self.tmp / "reviewed-qt-app").exists())

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
        dialog.query.setText("widget")
        self.assertEqual(dialog.results.count(), 1)
        QTest.keyClick(dialog.query, Qt.Key.Key_Return)
        self.assertEqual(activated, ["ui.widget"])
        self.assertFalse(dialog.isVisible())

    def test_global_search_shortcut_and_sidebar_action(self):
        self.assertEqual(self.win.global_search_shortcut.key().toString(), "Ctrl+Shift+F")
        self.assertEqual(self.win.global_search_button.accessibleName(), "Search everything")
        self.assertIn("Ctrl+Shift+F", self.win.global_search_button.text())


if __name__ == "__main__":
    unittest.main()
