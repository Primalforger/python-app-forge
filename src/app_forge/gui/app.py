"""GUI Shell (MOD-03): PySide6 desktop front end.

It calls ForgeServices only; it never mutates projects itself and never imports the CLI shell.
Apply and verification operations run in cancellable background workers.
Requires: pip install "python-app-forge[gui]"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QListWidgetItem,
                               QVBoxLayout, QWidget)

from app_forge import __version__
from app_forge.domain.errors import ForgeError, OperationCancelled
from app_forge.gui.theme import TOKENS, check_theme, stylesheet
from app_forge.services import CancellationToken, ForgeServices
from app_forge.settings import ForgeSettings

NAV = ["Dashboard", "Project Wizard", "Generation Review", "Component Catalog", "Component Manager",
       "Integration Workbench", "Design System", "Table Designer", "Architecture Explorer",
       "Quality and Compliance", "Extension Manager", "Configuration Center", "Diagnostics"]


def _title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("title")
    return lab


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSortingEnabled(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setAccessibleName("Results table")
    return t


def _fill(t: QTableWidget, rows: list[list[str]]) -> None:
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(str(v)))
    t.setSortingEnabled(True)


class OperationWorker(QObject):
    """Execute a service operation off the GUI thread and communicate only through signals."""

    progress = Signal(dict)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)
    finished = Signal()

    def __init__(self, operation, cancel_token: CancellationToken):
        super().__init__()
        self.operation = operation
        self.cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(cancel_token=self.cancel_token, progress=self.progress.emit)
            if isinstance(result, dict) and (result.get("cancelled") or result.get("overall") == "cancelled"):
                self.cancelled.emit(result)
            else:
                self.succeeded.emit(result)
        except OperationCancelled as exc:
            self.cancelled.emit({"message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - reported to the GUI boundary
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class CommandPaletteDialog(QDialog):
    """Keyboard-driven, searchable launcher for desktop screens and common actions."""

    def __init__(self, commands: list[tuple[str, str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setAccessibleName("Command palette")
        self.setModal(True)
        self.resize(560, 420)
        self._commands = commands
        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Type a command or screen name…")
        self.query.setAccessibleName("Search commands")
        self.results = QListWidget()
        self.results.setAccessibleName("Command results")
        layout.addWidget(self.query)
        layout.addWidget(self.results, 1)
        self.query.textChanged.connect(self._filter)
        self.results.itemActivated.connect(self._activate_item)
        self.query.returnPressed.connect(self._activate_current)
        self._filter("")

    def _filter(self, text: str) -> None:
        terms = text.casefold().split()
        self.results.clear()
        for label, keywords, callback in self._commands:
            haystack = f"{label} {keywords}".casefold()
            if all(term in haystack for term in terms):
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, callback)
                self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _activate_current(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self._activate_item(item)

    def _activate_item(self, item: QListWidgetItem) -> None:
        callback = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        callback()


class MainWindow(QMainWindow):
    def __init__(self, services: ForgeServices):
        super().__init__()
        self.s = services
        self.theme = "light"
        self.setWindowTitle(f"Python App Forge {__version__}")
        self.resize(1100, 700)
        root = QWidget()
        lay = QHBoxLayout(root)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setAccessibleName("Primary navigation")
        self.nav.addItems(NAV)
        self.nav.setFixedWidth(210)
        self.stack = QStackedWidget()
        self.status = QLabel("Ready")
        self.status.setAccessibleName("Operation status")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAccessibleName("Cancel background operation")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_background_operation)
        self._background_thread: QThread | None = None
        self._background_worker: OperationWorker | None = None
        self._active_cancel_token: CancellationToken | None = None
        self._background_label = ""
        self._background_on_success = None
        self._background_on_cancel = None
        self._closing_after_worker = False
        for build in (self._dashboard, self._templates, self._generation_review, self._catalog, self._components,
                      self._workbench, self._design_system, self._table_designer, self._architecture,
                      self._quality, self._extensions, self._settings, self._diagnostics):
            self.stack.addWidget(build())
        self.nav.currentRowChanged.connect(self._navigate)
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.command_palette_shortcut.activated.connect(self.open_command_palette)
        right = QVBoxLayout()
        right.addWidget(self.stack, 1)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.cancel_button)
        right.addLayout(status_row)
        lay.addWidget(self.nav)
        lay.addLayout(right, 1)
        self.setCentralWidget(root)
        self.nav.setCurrentRow(0)
        self.apply_theme()

    def _command_palette_commands(self) -> list[tuple[str, str, Any]]:
        commands = [
            (f"Go to {name}", f"open navigate screen {name}", lambda row=i: self.nav.setCurrentRow(row))
            for i, name in enumerate(NAV)
        ]
        commands.extend([
            ("Refresh dashboard", "reload recent operations history", self.refresh_dashboard),
            ("Run diagnostics", "doctor health environment", self.run_doctor),
            ("Toggle dark theme", "appearance light dark theme", lambda: self.set_theme(
                "light" if self.theme == "dark" else "dark")),
        ])
        return commands

    def open_command_palette(self) -> None:
        palette = CommandPaletteDialog(self._command_palette_commands(), self)
        palette.exec()

    # -- helpers --------------------------------------------------------------------------
    def apply_theme(self) -> None:
        self.setStyleSheet(stylesheet(self.theme))

    def _navigate(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        {"Dashboard": self.refresh_dashboard, "Component Catalog": self.search_catalog,
         "Design System": self.show_contrast, "Architecture Explorer": self.load_architecture,
         "Extension Manager": self.load_extensions, "Diagnostics": self.run_doctor}.get(NAV[row], lambda: None)()

    def _run(self, label: str, fn):
        self.status.setText(f"{label}...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = fn()
            self.status.setText(f"{label}: done")
            return result
        except ForgeError as exc:
            self.status.setText(f"{label}: failed ({exc.category})")
            QMessageBox.warning(self, "Operation failed",
                                "\n".join([exc.message, *exc.details, exc.hint or ""]).strip())
        except Exception as exc:  # noqa: BLE001 - last-resort UI boundary
            self.status.setText(f"{label}: internal error")
            QMessageBox.critical(self, "Internal error", f"{type(exc).__name__}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        return None

    def _start_background(self, label: str, operation, on_success=None, on_cancel=None) -> bool:
        if self._background_thread is not None:
            return False
        token = CancellationToken()
        thread = QThread(self)
        worker = OperationWorker(operation, token)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._background_progress_event)
        worker.succeeded.connect(self._background_succeeded_event)
        worker.failed.connect(self._background_failed_event)
        worker.cancelled.connect(self._background_cancelled_event)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._background_finished)
        self._background_thread = thread
        self._background_worker = worker
        self._active_cancel_token = token
        self._background_label = label
        self._background_on_success = on_success
        self._background_on_cancel = on_cancel
        self.nav.setEnabled(False)
        self.stack.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText(f"{label}: starting")
        thread.start()
        return True

    def _background_progress_event(self, event: dict) -> None:
        label = self._background_label
        message = str(event.get("message") or event.get("stage") or label)
        current, total = event.get("current"), event.get("total")
        suffix = f" ({current}/{total})" if current is not None and total is not None else ""
        self.status.setText(f"{label}: {message}{suffix}")

    def _background_succeeded_event(self, result: object) -> None:
        self.status.setText(f"{self._background_label}: done")
        callback = self._background_on_success
        self._background_on_success = None
        self._background_on_cancel = None
        if callback:
            callback(result)

    def _background_failed_event(self, exc: Exception) -> None:
        label = self._background_label
        if isinstance(exc, ForgeError):
            self.status.setText(f"{label}: failed ({exc.category})")
            QMessageBox.warning(self, "Operation failed",
                                "\n".join([exc.message, *exc.details, exc.hint or ""]).strip())
        else:
            self.status.setText(f"{label}: internal error")
            QMessageBox.critical(self, "Internal error", f"{type(exc).__name__}: {exc}")

    def _background_cancelled_event(self, result: object) -> None:
        label = self._background_label
        self.status.setText(f"{label}: cancelled")
        callback = self._background_on_cancel
        self._background_on_success = None
        self._background_on_cancel = None
        if callback:
            callback(result)
        elif isinstance(result, dict) and result.get("recovery"):
            QMessageBox.information(self, "Operation cancelled",
                                    "The operation was cancelled. Recovery result: " +
                                    str(result["recovery"].get("status", "unknown")))

    def _background_finished(self) -> None:
        self._background_thread = None
        self._background_worker = None
        self._active_cancel_token = None
        self.nav.setEnabled(True)
        self.stack.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def cancel_background_operation(self) -> None:
        if self._active_cancel_token is not None:
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancellation requested; finishing safe cleanup...")
            self._active_cancel_token.cancel()

    def closeEvent(self, event) -> None:
        thread = self._background_thread
        if thread is not None and thread.isRunning():
            event.ignore()
            if not self._closing_after_worker:
                self._closing_after_worker = True
                thread.finished.connect(self.close)
            self.cancel_background_operation()
            return
        event.accept()

    # -- UI-001 Dashboard -----------------------------------------------------------------
    def _dashboard(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Dashboard"))
        v.addWidget(QLabel("Recent operations (failures are shown with status 'failed')."))
        self.ops = _table(["Operation", "Kind", "Target", "Status", "Started"])
        self.ops.setAccessibleName("Recent operations table")
        v.addWidget(self.ops, 1)
        return w

    def refresh_dashboard(self) -> None:
        rows = self._run("Loading history", lambda: self.s.history(50)) or []
        _fill(self.ops, [[o["operation_id"], o["kind"], o["target"], o["status"], o["started"]] for o in rows])

    # -- UI-002..005 Template Studio ------------------------------------------------------
    def _templates(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Template Studio"))
        form = QFormLayout()
        self.t_arch = QComboBox()
        self.t_arch.setAccessibleName("Application archetype")
        self.t_arch.addItems(["desktop", "web", "cli", "service"])
        self.t_name = QLineEdit()
        self.t_name.setAccessibleName("Project name")
        self.t_out = QLineEdit()
        self.t_out.setAccessibleName("Output directory")
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self.t_out.setText(QFileDialog.getExistingDirectory(self, "Output") or self.t_out.text()))
        row = QHBoxLayout()
        row.addWidget(self.t_out, 1)
        row.addWidget(browse)
        self.t_comps = QLineEdit()
        self.t_comps.setAccessibleName("Components to include")
        self.t_comps.setPlaceholderText("component ids, comma separated (optional)")
        form.addRow("Archetype", self.t_arch)
        form.addRow("Project name", self.t_name)
        form.addRow("Output directory", row)
        form.addRow("Components", self.t_comps)
        v.addLayout(form)
        btns = QHBoxLayout()
        review = QPushButton("Open Generation Review")
        create = QPushButton("Create project")
        review.clicked.connect(lambda: self.nav.setCurrentRow(NAV.index("Generation Review")))
        create.clicked.connect(lambda: self.generate(False))
        btns.addWidget(review)
        btns.addWidget(create)
        v.addLayout(btns)
        self.t_out_box = QPlainTextEdit()
        self.t_out_box.setAccessibleName("Generation result")
        self.t_out_box.setReadOnly(True)
        v.addWidget(self.t_out_box, 1)
        return w

    def _generation_review(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Generation Review"))
        v.addWidget(QLabel("Build a dry-run plan from the Project Wizard settings. Review it here before creating files."))
        review = QPushButton("Build generation plan")
        review.setAccessibleName("Build generation plan")
        review.clicked.connect(self.review_generation)
        v.addWidget(review)
        self.gr_out = QPlainTextEdit()
        self.gr_out.setAccessibleName("Generation plan review")
        self.gr_out.setReadOnly(True)
        v.addWidget(self.gr_out, 1)
        return w

    def review_generation(self) -> None:
        comps = [c.strip() for c in self.t_comps.text().split(",") if c.strip()]
        out = self.t_out.text() or str(Path.home() / self.t_name.text().lower().replace(" ", "-"))
        res = self._run("Generation review", lambda: self.s.create_project(
            self.t_arch.currentText(), {"name": self.t_name.text()}, out, components=comps, dry_run=True))
        if res:
            self.gr_out.setPlainText(json.dumps(res, indent=2))

    def generate(self, dry: bool) -> None:
        comps = [c.strip() for c in self.t_comps.text().split(",") if c.strip()]
        out = self.t_out.text() or str(Path.home() / self.t_name.text().lower().replace(" ", "-"))
        res = self._run("Generation review" if dry else "Creating project", lambda: self.s.create_project(
            self.t_arch.currentText(), {"name": self.t_name.text()}, out, components=comps, dry_run=dry))
        if res:
            self.t_out_box.setPlainText(json.dumps(res, indent=2))

    # -- UI-006..008 Component Catalog ----------------------------------------------------
    def _catalog(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Component Catalog"))
        self.c_query = QLineEdit()
        self.c_query.setPlaceholderText("Search components")
        self.c_query.setAccessibleName("Search components")
        self.c_query.textChanged.connect(lambda _: self.search_catalog())
        v.addWidget(self.c_query)
        self.c_table = _table(["Id", "Version", "Category", "State", "Archetypes", "Summary"])
        self.c_table.setAccessibleName("Component catalog table")
        self.c_table.itemSelectionChanged.connect(self.show_component)
        v.addWidget(self.c_table, 2)
        self.c_detail = QPlainTextEdit()
        self.c_detail.setAccessibleName("Component manifest")
        self.c_detail.setReadOnly(True)
        v.addWidget(self.c_detail, 1)
        return w

    def search_catalog(self) -> None:
        rows = self._run("Searching catalog", lambda: self.s.search_components(self.c_query.text())) or []
        _fill(self.c_table, [[r["id"], r["version"], r["category"], r["state"], ", ".join(r["archetypes"]),
                              r["summary"]] for r in rows])

    def show_component(self) -> None:
        items = self.c_table.selectedItems()
        if items:
            cid = self.c_table.item(items[0].row(), 0).text()
            info = self._run("Loading component", lambda: self.s.inspect_component(cid))
            if info:
                self.c_detail.setPlainText(json.dumps(info["manifest"], indent=2, default=str))

    # -- UI-009..012 Integration Workbench ------------------------------------------------
    def _workbench(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Integration Workbench"))
        row = QHBoxLayout()
        self.w_path = QLineEdit()
        self.w_path.setAccessibleName("Project directory")
        pick = QPushButton("Browse...")
        pick.clicked.connect(lambda: self.w_path.setText(QFileDialog.getExistingDirectory(self, "Project") or self.w_path.text()))
        analyze = QPushButton("Analyze (read-only)")
        analyze.clicked.connect(self.analyze)
        row.addWidget(self.w_path, 1)
        row.addWidget(pick)
        row.addWidget(analyze)
        v.addLayout(row)
        row2 = QHBoxLayout()
        self.w_comp = QLineEdit()
        self.w_comp.setAccessibleName("Component id to add")
        self.w_comp.setPlaceholderText("component id to add, e.g. forge.forms-validation")
        plan = QPushButton("Create change plan")
        plan.clicked.connect(self.make_plan)
        self.w_apply = QPushButton("Approve and apply plan")
        self.w_apply.setEnabled(False)
        self.w_apply.clicked.connect(self.apply)
        self.w_recover = QPushButton("Recover last plan")
        self.w_recover.setEnabled(False)
        self.w_recover.clicked.connect(self.recover)
        for x in (self.w_comp, plan, self.w_apply, self.w_recover):
            row2.addWidget(x, 1 if x is self.w_comp else 0)
        v.addLayout(row2)
        self.w_out = QPlainTextEdit()
        self.w_out.setAccessibleName("Integration result")
        self.w_out.setReadOnly(True)
        v.addWidget(self.w_out, 1)
        self.plan_id: str | None = None
        return w

    def analyze(self) -> None:
        r = self._run("Analyzing", lambda: self.s.analyze_project(self.w_path.text()))
        if r:
            self.w_out.setPlainText(json.dumps(r, indent=2, default=str))

    def make_plan(self) -> None:
        r = self._run("Planning", lambda: self.s.plan_add(self.w_path.text(), {self.w_comp.text().strip(): "*"}))
        if r:
            self.plan_id = r["plan_id"]
            self.w_out.setPlainText(json.dumps(r, indent=2, default=str))
            self.w_apply.setEnabled(not r["conflicts"])

    def apply(self) -> None:
        if not self.plan_id:
            return
        self._approve_and_apply(
            self.plan_id,
            on_success=lambda result: (self.w_out.setPlainText(json.dumps(result, indent=2, default=str)),
                                       self.w_recover.setEnabled(True)),
            on_cancel=lambda result: (self.w_out.setPlainText(json.dumps(result, indent=2, default=str)),
                                      self.w_recover.setEnabled(True))
        )

    def recover(self) -> None:
        if self.plan_id:
            r = self._run("Recovering", lambda: self.s.recover_plan(self.plan_id))
            if r:
                self.w_out.setPlainText(json.dumps(r, indent=2, default=str))

    # -- shared: review a stored plan, ask for approval, apply ------------------------------
    def _approve_and_apply(self, plan_id: str, on_success=None, on_cancel=None):
        plan = self.s.preview_plan(plan_id)
        lines = [f"{c['action']:7} {c['path']}" for c in plan["changes"]]
        ok = QMessageBox.question(self, "Approve change plan",
                                  "This will modify the project:\n\n" + "\n".join(lines) +
                                  "\n\nA checkpoint is recorded so the change can be recovered. Approve and apply?")
        if ok != QMessageBox.StandardButton.Yes:
            return False
        approved = self._run("Approving", lambda: self.s.approve_plan(plan_id, "gui-user"))
        if not approved:
            return False
        return self._start_background("Applying",
                                      lambda *, cancel_token, progress: self.s.apply_plan(
                                          plan_id, cancel_token=cancel_token, progress=progress),
                                      on_success=on_success, on_cancel=on_cancel)

    # -- UI-008 Component Manager -----------------------------------------------------------
    def _components(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Component Manager"))
        row = QHBoxLayout()
        self.cm_path = QLineEdit()
        self.cm_path.setAccessibleName("Project directory")
        load = QPushButton("Load installed components")
        load.clicked.connect(self.load_components)
        row.addWidget(self.cm_path, 1)
        row.addWidget(load)
        v.addLayout(row)
        self.cm_table = _table(["Id", "Installed", "Newest usable", "Upgrade available", "Catalog state"])
        self.cm_table.setAccessibleName("Installed components table")
        v.addWidget(self.cm_table, 1)
        row2 = QHBoxLayout()
        up = QPushButton("Plan upgrade (selected)")
        rm = QPushButton("Plan removal (selected)")
        self.cm_apply = QPushButton("Approve and apply plan")
        self.cm_apply.setEnabled(False)
        up.clicked.connect(lambda: self.plan_selected("upgrade"))
        rm.clicked.connect(lambda: self.plan_selected("remove"))
        self.cm_apply.clicked.connect(self.apply_cm_plan)
        for b in (up, rm, self.cm_apply):
            row2.addWidget(b)
        v.addLayout(row2)
        self.cm_out = QPlainTextEdit()
        self.cm_out.setAccessibleName("Plan details")
        self.cm_out.setReadOnly(True)
        v.addWidget(self.cm_out, 1)
        self.cm_plan_id = None
        return w

    def load_components(self) -> None:
        rows = self._run("Loading components", lambda: self.s.project_components(self.cm_path.text())) or []
        _fill(self.cm_table, [[r["id"], r["installed"], r["newest"], "yes" if r["upgrade_available"] else "no",
                               r["state"]] for r in rows])

    def plan_selected(self, kind: str) -> None:
        items = self.cm_table.selectedItems()
        if not items:
            self.status.setText("Select a component first")
            return
        cid = self.cm_table.item(items[0].row(), 0).text()
        fn = self.s.plan_upgrade if kind == "upgrade" else self.s.plan_remove
        plan = self._run(f"Planning {kind}", lambda: fn(self.cm_path.text(), [cid]))
        if plan:
            self.cm_plan_id = plan["plan_id"]
            self.cm_out.setPlainText(json.dumps(plan, indent=2, default=str))
            self.cm_apply.setEnabled(not plan["conflicts"])

    def apply_cm_plan(self) -> None:
        if self.cm_plan_id:
            self._approve_and_apply(
                self.cm_plan_id,
                on_success=lambda result: (self.cm_out.setPlainText(json.dumps(result, indent=2, default=str)),
                                           self.load_components()),
                on_cancel=lambda result: self.cm_out.setPlainText(json.dumps(result, indent=2, default=str))
            )

    # -- UI-013 Design System ---------------------------------------------------------------
    def _design_system(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Design System"))
        self.ds_theme = QComboBox()
        self.ds_theme.addItems(sorted(TOKENS))
        self.ds_theme.setAccessibleName("Theme")
        self.ds_theme.currentTextChanged.connect(lambda _: self.show_contrast())
        use = QPushButton("Use this theme")
        use.clicked.connect(lambda: self.set_theme(self.ds_theme.currentText()))
        row = QHBoxLayout()
        row.addWidget(self.ds_theme)
        row.addWidget(use)
        v.addLayout(row)
        v.addWidget(QLabel("WCAG contrast of required colour pairs (minimum 4.5:1):"))
        self.ds_table = _table(["Foreground", "Background", "Ratio", "Meets 4.5:1"])
        self.ds_table.setAccessibleName("Contrast table")
        v.addWidget(self.ds_table, 1)
        return w

    def show_contrast(self) -> None:
        rows = check_theme(self.ds_theme.currentText())
        _fill(self.ds_table, [[r["foreground"], r["background"], r["ratio"], "yes" if r["ok"] else "NO"] for r in rows])

    def set_theme(self, name: str) -> None:
        self.theme = name
        self.apply_theme()

    # -- UI-014 Table Designer --------------------------------------------------------------
    SAMPLE_TABLE: dict[str, Any] = {"name": "Orders", "columns": [{"key": "id", "type": "number"}, {"key": "status", "type": "category"},
                                                  {"key": "placed", "type": "date"}],
                    "default_sort": [{"column": "placed", "descending": True}],
                    "filters": [{"column": "status", "op": "eq", "value": "open"}], "filter_mode": "and",
                    "page_size": 25, "export_formats": ["csv"]}

    def _table_designer(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Table Designer"))
        v.addWidget(QLabel("Define columns in the grid, then validate and generate the advanced-table model."))
        self.td_name = QLineEdit(self.SAMPLE_TABLE["name"])
        self.td_name.setAccessibleName("Table name")
        v.addWidget(self.td_name)
        self.td_columns = QTableWidget(0, 2)
        self.td_columns.setHorizontalHeaderLabels(["Column key", "Data type"])
        self.td_columns.setAccessibleName("Table columns grid")
        self.td_columns.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.td_columns.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.td_columns.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.td_columns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.td_columns, 2)
        controls = QHBoxLayout()
        add = QPushButton("Add column")
        add.setAccessibleName("Add table column")
        add.clicked.connect(self.add_table_column)
        remove = QPushButton("Remove selected")
        remove.setAccessibleName("Remove selected table column")
        remove.clicked.connect(self.remove_table_column)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        v.addLayout(controls)
        self.td_import = QLineEdit("my_app.table_model")
        self.td_import.setAccessibleName("Import path of the table component")
        go = QPushButton("Validate and generate")
        go.clicked.connect(self.design_table)
        row = QHBoxLayout()
        row.addWidget(self.td_import, 1)
        row.addWidget(go)
        v.addLayout(row)
        self.td_out = QPlainTextEdit()
        self.td_out.setAccessibleName("Generated code")
        self.td_out.setReadOnly(True)
        v.addWidget(self.td_out, 2)
        for column in self.SAMPLE_TABLE["columns"]:
            self._insert_table_column(column["key"], column["type"])
        return w

    def _insert_table_column(self, key: str, data_type: str) -> None:
        row = self.td_columns.rowCount()
        self.td_columns.insertRow(row)
        self.td_columns.setItem(row, 0, QTableWidgetItem(key))
        kind = QComboBox()
        kind.setAccessibleName(f"Data type for column {key or row + 1}")
        kind.addItems(["text", "number", "category", "date", "bool"])
        index = kind.findText(data_type)
        kind.setCurrentIndex(index if index >= 0 else 0)
        self.td_columns.setCellWidget(row, 1, kind)

    def add_table_column(self) -> None:
        self._insert_table_column(f"column_{self.td_columns.rowCount() + 1}", "text")
        self.td_columns.setCurrentCell(self.td_columns.rowCount() - 1, 0)
        self.td_columns.editItem(self.td_columns.item(self.td_columns.rowCount() - 1, 0))

    def remove_table_column(self) -> None:
        row = self.td_columns.currentRow()
        if row < 0:
            self.status.setText("Select a column to remove")
            return
        self.td_columns.removeRow(row)

    def design_table(self) -> None:
        columns = []
        for row in range(self.td_columns.rowCount()):
            key_item = self.td_columns.item(row, 0)
            kind = self.td_columns.cellWidget(row, 1)
            columns.append({"key": key_item.text().strip() if key_item else "",
                            "type": kind.currentText() if isinstance(kind, QComboBox) else "text"})
        definition = dict(self.SAMPLE_TABLE)
        definition["name"] = self.td_name.text().strip()
        definition["columns"] = columns
        r = self._run("Designing table", lambda: self.s.design_table(definition, self.td_import.text()))
        if r:
            self.td_out.setPlainText(r["python"])

    # -- UI-016 Architecture Explorer -------------------------------------------------------
    def _architecture(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Architecture Explorer"))
        self.ar_table = _table(["From", "To", "Imports"])
        self.ar_table.setAccessibleName("Dependency edges table")
        v.addWidget(self.ar_table, 2)
        self.ar_viol = QPlainTextEdit()
        self.ar_viol.setReadOnly(True)
        self.ar_viol.setAccessibleName("Rule violations")
        v.addWidget(QLabel("Dependency-direction violations:"))
        v.addWidget(self.ar_viol, 1)
        copy = QPushButton("Copy diagram as Mermaid")
        copy.clicked.connect(self.copy_mermaid)
        v.addWidget(copy)
        return w

    def load_architecture(self) -> None:
        g = self._run("Analysing architecture", self.s.architecture_graph)
        if g:
            _fill(self.ar_table, [[e["from"], e["to"], e["imports"]] for e in g["edges"]])
            self.ar_viol.setPlainText("\n".join(f"{x['file']}:{x['line']} {x['import']} - {x['rule']}"
                                                for x in g["violations"]) or "None: all rules satisfied.")

    def copy_mermaid(self) -> None:
        text = self._run("Rendering diagram", lambda: self.s.architecture_graph(None, "mermaid"))
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("Mermaid diagram copied to clipboard")

    # -- UI-019 Extension Manager -----------------------------------------------------------
    def _extensions(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Extension Manager"))
        v.addWidget(QLabel("Installed extensions are listed from package metadata without importing them. "
                           "Nothing runs until you trust and enable it."))
        self.ex_table = _table(["Name", "Target", "Trust", "Enabled"])
        self.ex_table.setAccessibleName("Extensions table")
        v.addWidget(self.ex_table, 1)
        row = QHBoxLayout()
        for label, fn in (("Trust...", self.trust_ext), ("Untrust", lambda: self.ext_action("untrust")),
                          ("Enable", lambda: self.ext_action("enable")), ("Disable", lambda: self.ext_action("disable"))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        return w

    def load_extensions(self) -> None:
        rows = self._run("Listing extensions", self.s.plugin_list) or []
        _fill(self.ex_table, [[r["name"], r["target"], r["trust"], "yes" if r["enabled"] else "no"] for r in rows])

    def _selected_ext(self):
        items = self.ex_table.selectedItems()
        return self.ex_table.item(items[0].row(), 0).text() if items else None

    def trust_ext(self) -> None:
        name = self._selected_ext()
        if name and QMessageBox.question(self, "Trust extension",
                                         f"Trust {name!r}? It will be able to run code inside App Forge.") == QMessageBox.StandardButton.Yes:
            self._run("Trusting", lambda: self.s.plugin_trust(name, "trusted"))
            self.load_extensions()

    def ext_action(self, action: str) -> None:
        name = self._selected_ext()
        if name:
            fn = {"untrust": lambda: self.s.plugin_trust(name, "untrusted"), "enable": lambda: self.s.plugin_enable(name),
                  "disable": lambda: self.s.plugin_disable(name)}[action]
            self._run(action.title(), fn)
            self.load_extensions()

    # -- UI-017/018 Quality and Compliance ------------------------------------------------
    def _quality(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Quality and Compliance"))
        row = QHBoxLayout()
        self.q_path = QLineEdit()
        self.q_path.setAccessibleName("Project directory to verify")
        run = QPushButton("Run verification")
        run.clicked.connect(self.verify)
        rep = QPushButton("Compliance report")
        rep.clicked.connect(self.report)
        for x in (self.q_path, run, rep):
            row.addWidget(x, 1 if x is self.q_path else 0)
        v.addLayout(row)
        self.q_out = QPlainTextEdit()
        self.q_out.setAccessibleName("Verification result")
        self.q_out.setReadOnly(True)
        v.addWidget(self.q_out, 1)
        return w

    def verify(self) -> None:
        path = self.q_path.text()
        self._start_background(
            "Verifying",
            lambda *, cancel_token, progress: self.s.verify_project(
                path, cancel_token=cancel_token, progress=progress),
            on_success=lambda result: self.q_out.setPlainText(json.dumps(
                {k: result[k] for k in ("overall", "passed", "failed", "not_run", "complete", "run_id")}, indent=2)),
            on_cancel=lambda result: self.q_out.setPlainText(json.dumps(
                {k: result[k] for k in ("overall", "passed", "failed", "not_run", "complete", "run_id")
                 if k in result}, indent=2))
        )

    def report(self) -> None:
        r = self._run("Building report", lambda: self.s.compliance_report(None, self.q_path.text()))
        if r:
            self.q_out.setPlainText(json.dumps({"summary": r["summary"], "gaps": r["gaps"],
                                                "disclaimer": r["disclaimer"]}, indent=2))

    # -- UI-021 Settings / UI-020 Diagnostics ---------------------------------------------
    def _settings(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Configuration Center"))
        dark = QCheckBox("Dark theme")
        dark.setAccessibleName("Dark theme")
        dark.toggled.connect(self.toggle_theme)
        v.addWidget(dark)
        box = QPlainTextEdit(json.dumps(self.s.show_config(), indent=2))
        box.setReadOnly(True)
        box.setAccessibleName("Current configuration")
        v.addWidget(box, 1)
        return w

    def toggle_theme(self, on: bool) -> None:
        self.set_theme("dark" if on else "light")

    def set_theme(self, theme: str) -> None:
        if theme not in ("light", "dark"):
            raise ValueError("theme must be 'light' or 'dark'")
        self.theme = theme
        self.apply_theme()

    def _diagnostics(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Diagnostics"))
        self.d_out = QPlainTextEdit()
        self.d_out.setAccessibleName("Diagnostics output")
        self.d_out.setReadOnly(True)
        v.addWidget(self.d_out, 1)
        return w

    def run_doctor(self) -> None:
        r = self._run("Running diagnostics", self.s.doctor)
        if r:
            self.d_out.setPlainText(json.dumps(r, indent=2))


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow(ForgeServices(ForgeSettings.load()))
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
