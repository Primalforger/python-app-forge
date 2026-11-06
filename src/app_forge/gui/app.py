"""GUI Shell (MOD-03): PySide6 desktop front end.

It calls ForgeServices only; it never mutates projects itself and never imports the CLI shell.
Apply and verification operations run in cancellable background workers.
Requires: pip install "python-app-forge[gui]"
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QListWidgetItem, QVBoxLayout, QWidget)

from app_forge import __version__
from app_forge.domain.errors import ForgeError, OperationCancelled
from app_forge.observability import CrashReporter
from app_forge.gui.theme import TOKENS, check_theme, stylesheet
from app_forge.services import CancellationToken, ForgeServices
from app_forge.settings import ForgeSettings

NAV = ["Dashboard", "Project Workspace", "Project Wizard", "Generation Review", "Component Catalog", "Component Manager",
       "Integration Workbench", "Design System", "Table Designer", "Architecture Explorer",
       "Quality and Compliance", "Extension Manager", "Configuration Center", "Diagnostics"]

NAV_DESCRIPTIONS = [
    "Workspace activity, recent operations, and history",
    "Open a recent project or continue working in an existing workspace",
    "Create a project from a guided setup",
    "Review generated project files before writing them",
    "Find reusable components and templates",
    "Inspect and manage installed components",
    "Analyze projects, apply integrations, and recover changes",
    "Review theme tokens and accessibility contrast",
    "Design database tables and column definitions",
    "Explore project structure and architecture",
    "Run verification and review quality evidence",
    "Manage extensions and available capabilities",
    "Configure application preferences and behavior",
    "Inspect environment health and diagnostic reports",
]


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



class GlobalSearchDialog(QDialog):
    """Search across Forge screens, components, extensions, projects, and activity."""

    def __init__(self, search_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Everything")
        self.setAccessibleName("Global search")
        self.setModal(True)
        self.resize(680, 500)
        self._search_callback = search_callback
        layout = QVBoxLayout(self)
        heading = QLabel("Search your Forge workspace")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search projects, components, extensions, operations, or screens…")
        self.query.setAccessibleName("Search everything")
        layout.addWidget(self.query)
        self.results = QListWidget()
        self.results.setAccessibleName("Global search results")
        layout.addWidget(self.results, 1)
        self.summary = QLabel("Start typing to search across your workspace.")
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        self.query.textChanged.connect(self._filter)
        self.results.itemActivated.connect(self._activate_item)
        self.query.returnPressed.connect(self._activate_current)
        self.query.setFocus()

    def _filter(self, text: str) -> None:
        self.results.clear()
        query = text.strip()
        if not query:
            self.summary.setText("Search projects, components, extensions, operations, and screens.")
            return
        matches = self._search_callback(query)
        for result in matches:
            item = QListWidgetItem(f'{result["title"]}   ·   {result["category"]}')
            item.setToolTip(result.get("description", ""))
            item.setData(Qt.ItemDataRole.UserRole, result["callback"])
            self.results.addItem(item)
        self.summary.setText(
            f"{len(matches)} result{'s' if len(matches) != 1 else ''} · "
            "Press Enter to open the selected result"
            if matches else "No matching results. Try a shorter or different search."
        )
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



class NotificationCenterDialog(QDialog):
    """Persistent, user-managed notification history."""

    def __init__(self, notifications: list[dict], on_action, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Notification Center")
        self.setAccessibleName("Notification center")
        self.resize(640, 460)
        self._notifications = notifications
        self._on_action = on_action
        layout = QVBoxLayout(self)
        layout.addWidget(_title("Notification Center"))
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        self.items = QListWidget()
        self.items.setAccessibleName("Notifications")
        layout.addWidget(self.items, 2)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName("Notification details")
        self.detail.setMaximumHeight(120)
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        self.read_button = QPushButton("Mark as read")
        self.read_button.clicked.connect(lambda: self._act("read"))
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.clicked.connect(lambda: self._act("dismiss"))
        self.open_button = QPushButton("Open activity")
        self.open_button.clicked.connect(lambda: self._act("open"))
        self.clear_button = QPushButton("Clear all")
        self.clear_button.clicked.connect(lambda: self._act("clear"))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (self.read_button, self.dismiss_button, self.open_button, self.clear_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.items.currentRowChanged.connect(self._selection_changed)
        self.refresh()

    def refresh(self) -> None:
        self.items.clear()
        unread = sum(not item.get("read", False) for item in self._notifications)
        self.summary.setText(
            f"{len(self._notifications)} notifications · {unread} unread"
            if self._notifications else "You're all caught up. New operation updates will appear here."
        )
        for notification in self._notifications:
            state = "READ" if notification.get("read") else "NEW"
            self.items.addItem(
                f'{state}  ·  {notification.get("title", "Forge update")}  ·  '
                f'{notification.get("created_at", "")}'
            )
        if self.items.count():
            self.items.setCurrentRow(0)
        else:
            self.detail.setPlainText("No notifications.")

    def _selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._notifications):
            self.detail.clear()
            self.read_button.setEnabled(False)
            self.dismiss_button.setEnabled(False)
            self.open_button.setEnabled(False)
            return
        item = self._notifications[row]
        self.detail.setPlainText(
            f'{item.get("title", "Forge update")}\n'
            f'{item.get("message", "")}\n\n'
            f'Severity: {item.get("severity", "info")}\n'
            f'Time: {item.get("created_at", "")}'
        )
        self.read_button.setEnabled(not item.get("read", False))
        self.dismiss_button.setEnabled(True)
        self.open_button.setEnabled(bool(item.get("open_activity", True)))

    def _act(self, action: str) -> None:
        row = self.items.currentRow()
        notification = self._notifications[row] if 0 <= row < len(self._notifications) else None
        if action in ("read", "dismiss", "open") and notification is None:
            return
        updated = self._on_action(action, notification)
        if isinstance(updated, list):
            self._notifications = updated
        if action == "open":
            self.accept()
        else:
            self.refresh()


class MainWindow(QMainWindow):
    def __init__(self, services: ForgeServices):
        super().__init__()
        self.s = services
        self.crash_reporter = CrashReporter(services.settings.home / "crashes")
        try:
            self._saved_session = services.load_desktop_session()
        except ValueError as exc:
            self._saved_session = {}
            self._record_crash(exc, "Loading desktop session")
        saved_theme = self._saved_session.get("theme")
        self.theme = saved_theme if saved_theme in {"light", "dark"} else "light"
        self.accent = self._saved_session.get("accent", "blue")
        if self.accent not in {"blue", "green", "purple"}:
            self.accent = "blue"
        self.compact_density = bool(self._saved_session.get("compact_density", False))
        self.mascots_enabled = self._saved_session.get("mascots_enabled", True) is not False
        saved_notifications = self._saved_session.get("notifications", [])
        self._notifications = [item for item in saved_notifications if isinstance(item, dict)][-100:] \
            if isinstance(saved_notifications, list) else []
        self.setWindowTitle(f"Python App Forge {__version__}")
        self.resize(1100, 700)
        root = QWidget()
        lay = QHBoxLayout(root)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(238)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 14)
        sidebar_layout.setSpacing(10)

        brand = QLabel("PYTHON APP FORGE")
        brand.setObjectName("sidebarBrand")
        brand.setAccessibleName("Python App Forge")
        tagline = QLabel("Cultivate. Create. Forge.")
        tagline.setObjectName("sidebarTagline")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(tagline)
        self.global_search_button = QPushButton("Search everything…  Ctrl+Shift+F")
        self.global_search_button.setObjectName("secondaryAction")
        self.global_search_button.setAccessibleName("Search everything")
        self.global_search_button.clicked.connect(self.open_global_search)
        sidebar_layout.addWidget(self.global_search_button)
        self.notification_button = QPushButton("Notifications")
        self.notification_button.setObjectName("secondaryAction")
        self.notification_button.setAccessibleName("Open notification center")
        self.notification_button.clicked.connect(self.open_notification_center)
        sidebar_layout.addWidget(self.notification_button)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setAccessibleName("Primary navigation")
        for label, description in zip(NAV, NAV_DESCRIPTIONS):
            item = QListWidgetItem(label)
            item.setToolTip(description)
            item.setStatusTip(description)
            self.nav.addItem(item)
        sidebar_layout.addWidget(self.nav, 1)

        nav_hint = QLabel("CTRL + K   COMMAND PALETTE")
        nav_hint.setObjectName("sidebarHint")
        nav_hint.setAccessibleName("Press Control K to open the command palette")
        sidebar_layout.addWidget(nav_hint)
        self.stack = QStackedWidget()
        self.status = QLabel("Ready")
        self.status.setAccessibleName("Operation status")
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName("Background operation progress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
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
        for build in (self._dashboard, self._project_workspace, self._templates, self._generation_review, self._catalog, self._components,
                      self._workbench, self._design_system, self._table_designer, self._architecture,
                      self._quality, self._extensions, self._settings, self._diagnostics):
            self.stack.addWidget(build())
        self.nav.currentRowChanged.connect(self._navigate)
        self._recent_projects_menu = self.menuBar().addMenu("Recent Projects")
        self._refresh_recent_projects_menu()
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.command_palette_shortcut.activated.connect(self.open_command_palette)
        self.global_search_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self.global_search_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.global_search_shortcut.activated.connect(self.open_global_search)
        right = QVBoxLayout()
        right.addWidget(self.stack, 1)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.progress_bar, 1)
        status_row.addWidget(self.cancel_button)
        right.addLayout(status_row)
        lay.addWidget(self.sidebar)
        lay.addLayout(right, 1)
        self.setCentralWidget(root)
        geometry = self._saved_session.get("geometry")
        if isinstance(geometry, str) and geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii")))
            except ValueError:
                self._record_crash(ValueError("saved window geometry is invalid"), "Restoring desktop session")
        saved_screen = self._saved_session.get("screen", 0)
        if isinstance(saved_screen, int) and not isinstance(saved_screen, bool) and 0 <= saved_screen < len(NAV):
            self.nav.setCurrentRow(saved_screen)
        else:
            self.nav.setCurrentRow(0)
        self.apply_theme()
        self._refresh_notification_button()
        if self._saved_session.get("maximized") is True:
            self.showMaximized()

    def dismiss_welcome(self) -> None:
        self._saved_session["welcome_seen"] = True
        if hasattr(self, "welcome_panel"):
            self.welcome_panel.hide()
        self._save_session()

    def _refresh_recent_projects_menu(self) -> None:
        self._recent_projects_menu.clear()
        try:
            projects = self.s.list_recent_projects(existing_only=True)
        except ValueError as exc:
            projects = []
            self._record_crash(exc, "Loading recent projects")
        if not projects:
            action = self._recent_projects_menu.addAction("No recent projects")
            action.setEnabled(False)
        for path in projects:
            action = self._recent_projects_menu.addAction(path)
            action.triggered.connect(lambda checked=False, selected=path: self._open_recent_project(selected))
        self._recent_projects_menu.addSeparator()
        clear = self._recent_projects_menu.addAction("Clear recent projects")
        clear.triggered.connect(self._clear_recent_projects)

    def _remember_project(self, path: str) -> None:
        candidate = Path(path).expanduser()
        if not path.strip() or not candidate.is_dir():
            return
        try:
            self.s.add_recent_project(candidate)
            self._refresh_recent_projects_menu()
        except (OSError, ValueError) as exc:
            self._record_crash(exc, "Saving recent project")

    def _open_recent_project(self, path: str) -> None:
        self.w_path.setText(path)
        self.q_path.setText(path)
        self.nav.setCurrentRow(NAV.index("Integration Workbench"))
        self.status.setText(f"Recent project selected: {path}")

    def _clear_recent_projects(self) -> None:
        try:
            self.s.clear_recent_projects()
        except OSError as exc:
            self._record_crash(exc, "Clearing recent projects")
        self._refresh_recent_projects_menu()

    def _save_session(self) -> None:
        state = {
            "theme": self.theme,
            "screen": self.nav.currentRow(),
            "geometry": bytes(self.saveGeometry().toHex()).decode("ascii"),
            "maximized": self.isMaximized(),
            "accent": self.accent,
            "compact_density": self.compact_density,
            "mascots_enabled": self.mascots_enabled,
            "welcome_seen": self._saved_session.get("welcome_seen", False),
            "notifications": self._notifications[-100:],
        }
        try:
            self.s.save_desktop_session(state)
        except (OSError, ValueError) as exc:
            self._record_crash(exc, "Saving desktop session")

    def _command_palette_commands(self) -> list[tuple[str, str, Any]]:
        commands: list[tuple[str, str, Any]] = [
            (f"Go to {name}", f"open navigate screen {name}", lambda i=i: self.nav.setCurrentRow(i))
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

    def _add_notification(self, severity: str, title: str, message: str) -> None:
        notification = {
            "id": uuid.uuid4().hex,
            "severity": severity if severity in {"success", "warning", "error", "info"} else "info",
            "title": str(title)[:180],
            "message": str(message)[:2000],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "read": False,
            "open_activity": True,
        }
        self._notifications.append(notification)
        self._notifications = self._notifications[-100:]
        self._refresh_notification_button()
        self._save_session()

    def _refresh_notification_button(self) -> None:
        unread = sum(not item.get("read", False) for item in self._notifications)
        self.notification_button.setText(f"Notifications  ·  {unread} new" if unread else "Notifications")
        self.notification_button.setToolTip(f"{unread} unread notification(s)")

    def _notification_action(self, action: str, notification: dict | None) -> None:
        if action == "clear":
            self._notifications.clear()
        elif notification is not None:
            identifier = notification.get("id")
            if action == "read":
                for item in self._notifications:
                    if item.get("id") == identifier:
                        item["read"] = True
                        break
            elif action == "dismiss":
                self._notifications = [item for item in self._notifications if item.get("id") != identifier]
            elif action == "open":
                notification["read"] = True
                self.nav.setCurrentRow(NAV.index("Dashboard"))
                self.activity_search.clear()
                self.refresh_dashboard()
        self._refresh_notification_button()
        self._save_session()
        return self._notifications

    def open_notification_center(self) -> None:
        dialog = NotificationCenterDialog(self._notifications, self._notification_action, self)
        dialog.exec()

    def _global_search_items(self, query: str) -> list[dict[str, Any]]:
        """Collect searchable metadata only; opening a result is an explicit user action."""
        q = query.casefold().strip()
        if not q:
            return []
        results: list[dict[str, Any]] = []

        def add(title: str, category: str, description: str, callback) -> None:
            haystack = f"{title} {category} {description}".casefold()
            if all(term in haystack for term in q.split()):
                results.append({"title": title, "category": category,
                                "description": description, "callback": callback})

        for index, name in enumerate(NAV):
            add(name, "Screen", NAV_DESCRIPTIONS[index],
                lambda i=index: self.nav.setCurrentRow(i))

        try:
            for component in self.s.search_components(query):
                cid = str(component.get("id", ""))
                title = str(component.get("name") or cid)
                description = str(component.get("summary", ""))
                add(title, "Component", f"{cid} · {description}",
                    lambda value=cid: self._open_component_search_result(value))
        except Exception as exc:
            self._record_crash(exc, "Searching component catalog")

        try:
            for extension in self.s.plugin_list():
                name = str(extension.get("name", ""))
                description = f'{extension.get("target", "")} · {extension.get("trust", "")} trust'
                add(name, "Extension", description,
                    lambda value=name: self._open_extension_search_result(value))
        except Exception as exc:
            self._record_crash(exc, "Searching installed extensions")

        try:
            for project in self.s.list_recent_projects(existing_only=True):
                path = str(project)
                add(Path(path).name or path, "Recent project", path,
                    lambda value=path: self._open_recent_project(value))
        except (OSError, ValueError) as exc:
            self._record_crash(exc, "Searching recent projects")

        try:
            for operation in self.s.history(200):
                op_id = str(operation.get("operation_id", ""))
                kind = str(operation.get("kind", "operation"))
                target = str(operation.get("target", ""))
                status = str(operation.get("status", ""))
                description = f"{kind} · {status} · {target} · {op_id}"
                add(f"{kind} — {target or op_id}", "Operation", description,
                    lambda value=kind: self._open_operation_search_result(value))
        except Exception as exc:
            self._record_crash(exc, "Searching operation history")

        return results[:100]

    def _open_component_search_result(self, component_id: str) -> None:
        self.nav.setCurrentRow(NAV.index("Component Catalog"))
        self.c_query.setText(component_id)
        for row in range(self.c_table.rowCount()):
            if self.c_table.item(row, 0) and self.c_table.item(row, 0).text() == component_id:
                self.c_table.selectRow(row)
                break

    def _open_extension_search_result(self, name: str) -> None:
        self.nav.setCurrentRow(NAV.index("Extension Manager"))
        for row in range(self.ex_table.rowCount()):
            if self.ex_table.item(row, 0) and self.ex_table.item(row, 0).text() == name:
                self.ex_table.selectRow(row)
                break

    def _open_operation_search_result(self, kind: str) -> None:
        self.nav.setCurrentRow(NAV.index("Dashboard"))
        self.activity_search.setText(kind)

    def open_global_search(self) -> None:
        dialog = GlobalSearchDialog(self._global_search_items, self)
        dialog.exec()

    # -- helpers --------------------------------------------------------------------------
    def apply_theme(self) -> None:
        sheet = stylesheet(self.theme)
        accents = {"blue": "#2563EB" if self.theme == "light" else "#3989E8",
                   "green": "#087A55" if self.theme == "light" else "#45C99A",
                   "purple": "#6D42C7" if self.theme == "light" else "#A88AEF"}
        from app_forge.gui.theme import TOKENS
        sheet = sheet.replace(TOKENS[self.theme]["primary"], accents[self.accent])
        if self.compact_density:
            sheet = sheet.replace("padding: 10px 12px", "padding: 6px 9px")
        self.setStyleSheet(sheet)

    def _navigate(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        {"Dashboard": self.refresh_dashboard, "Project Workspace": self.refresh_project_workspace,
         "Component Catalog": self.search_catalog,
         "Design System": self.show_contrast, "Architecture Explorer": self.load_architecture,
         "Extension Manager": self.load_extensions, "Diagnostics": self.run_doctor}.get(NAV[row], lambda: None)()

    def _record_crash(self, exc: BaseException, context: str) -> None:
        try:
            self.crash_reporter.capture_exception(exc, context=context)
        except Exception:  # noqa: BLE001 - reporting must never mask the original failure
            pass

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
            self._record_crash(exc, label)
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
        # Queue the Python slot onto the worker's event loop instead of invoking it
        # directly from Qt's native thread-start signal. This is more reliable on
        # Windows, where direct startup-slot execution can destabilize PySide teardown.
        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(self._background_progress_event)
        worker.succeeded.connect(self._background_succeeded_event)
        worker.failed.connect(self._background_failed_event)
        worker.cancelled.connect(self._background_cancelled_event)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
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
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.status.setText(f"{label}: starting")
        thread.start()
        return True

    def _background_progress_event(self, event: dict) -> None:
        label = self._background_label
        message = str(event.get("message") or event.get("stage") or label)
        current, total = event.get("current"), event.get("total")
        suffix = f" ({current}/{total})" if current is not None and total is not None else ""
        if current is not None and total is not None and total > 0:
            self.progress_bar.setRange(0, int(total))
            self.progress_bar.setValue(max(0, min(int(current), int(total))))
        else:
            self.progress_bar.setRange(0, 0)
        self.status.setText(f"{label}: {message}{suffix}")

    def _background_succeeded_event(self, result: object) -> None:
        self.status.setText(f"{self._background_label}: done")
        self._add_notification("success", f"{self._background_label} completed",
                               "The background operation finished successfully.")
        callback = self._background_on_success
        self._background_on_success = None
        self._background_on_cancel = None
        if callback:
            callback(result)

    def _background_failed_event(self, exc: Exception) -> None:
        label = self._background_label
        message = exc.message if isinstance(exc, ForgeError) else f"{type(exc).__name__}: {exc}"
        self._add_notification("error", f"{label} failed", message)
        if isinstance(exc, ForgeError):
            self.status.setText(f"{label}: failed ({exc.category})")
            QMessageBox.warning(self, "Operation failed",
                                "\n".join([exc.message, *exc.details, exc.hint or ""]).strip())
        else:
            self._record_crash(exc, label)
            self.status.setText(f"{label}: internal error")
            QMessageBox.critical(self, "Internal error", f"{type(exc).__name__}: {exc}")

    def _background_cancelled_event(self, result: object) -> None:
        label = self._background_label
        message = str(result.get("message", "The operation was cancelled.")) if isinstance(result, dict) else "The operation was cancelled."
        self._add_notification("warning", f"{label} cancelled", message)
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
        # QThread.finished is emitted as the native thread is exiting. Wait for
        # its final cleanup before scheduling QObject destruction; this avoids
        # a Windows Qt teardown race when the window/test fixture is closed.
        thread = self._background_thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self._background_thread = None
        self._background_worker = None
        self._active_cancel_token = None
        self.nav.setEnabled(True)
        self.stack.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

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
        self._save_session()
        event.accept()

    # -- UI-001 Dashboard -----------------------------------------------------------------
    def _dashboard(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)

        heading = QHBoxLayout()
        title_column = QVBoxLayout()
        eyebrow = QLabel("WORKSPACE OVERVIEW")
        eyebrow.setObjectName("eyebrow")
        title_column.addWidget(eyebrow)
        title_column.addWidget(_title("Recent Forge Activity"))
        self.activity_description = QLabel(
            "A clear view of actions performed by Python App Forge—not a list of installed apps or projects. "
            "Review recent operations, inspect results, and keep your workspace history tidy."
        )
        self.activity_description.setObjectName("muted")
        self.activity_description.setWordWrap(True)
        title_column.addWidget(self.activity_description)
        heading.addLayout(title_column, 1)
        refresh = QPushButton("Refresh activity")
        refresh.setObjectName("secondaryAction")
        refresh.clicked.connect(self.refresh_dashboard)
        heading.addWidget(refresh, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(heading)

        if not self._saved_session.get("welcome_seen", False):
            self.welcome_panel = QWidget()
            self.welcome_panel.setObjectName("welcomePanel")
            welcome_layout = QVBoxLayout(self.welcome_panel)
            welcome_layout.setContentsMargins(16, 12, 16, 12)
            welcome_title = QLabel("Welcome to Forge Universe" + ("  ✦" if self.mascots_enabled else ""))
            welcome_title.setObjectName("title")
            welcome_layout.addWidget(welcome_title)
            welcome_copy = QLabel("Your workshop for creating, extending, and verifying Python applications. Start with a guided project, explore reusable components, or personalize your workspace.")
            welcome_copy.setWordWrap(True)
            welcome_layout.addWidget(welcome_copy)
            welcome_actions = QHBoxLayout()
            start = QPushButton("Create your first project")
            start.clicked.connect(lambda: self.nav.setCurrentRow(NAV.index("Project Wizard")))
            welcome_actions.addWidget(start)
            personalize = QPushButton("Personalize Forge")
            personalize.setObjectName("secondaryAction")
            personalize.clicked.connect(lambda: self.nav.setCurrentRow(NAV.index("Configuration Center")))
            welcome_actions.addWidget(personalize)
            dismiss = QPushButton("Dismiss")
            dismiss.setObjectName("secondaryAction")
            dismiss.clicked.connect(self.dismiss_welcome)
            welcome_actions.addWidget(dismiss)
            welcome_actions.addStretch(1)
            welcome_layout.addLayout(welcome_actions)
            v.addWidget(self.welcome_panel)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.metric_total = QLabel("<b>—</b><br>Total operations")
        self.metric_succeeded = QLabel("<b>—</b><br>Succeeded")
        self.metric_failed = QLabel("<b>—</b><br>Failed")
        self.metric_running = QLabel("<b>—</b><br>Running")
        self.metric_retention = QLabel("<b>—</b><br>Retention")
        for name, label in (
            ("total", self.metric_total), ("succeeded", self.metric_succeeded),
            ("failed", self.metric_failed), ("running", self.metric_running),
            ("retention", self.metric_retention),
        ):
            label.setObjectName("metricCard")
            label.setAccessibleName(f"{name.title()} dashboard metric")
            label.setMinimumHeight(58)
            metrics.addWidget(label, 1)
        v.addLayout(metrics)

        self.ops_summary = QLabel("Loading activity…")
        self.ops_summary.setObjectName("muted")
        self.ops_summary.setAccessibleName("Activity summary")
        v.addWidget(self.ops_summary)

        filters = QHBoxLayout()
        self.activity_search = QLineEdit()
        self.activity_search.setAccessibleName("Search activity")
        self.activity_search.setPlaceholderText("Search operation, kind, target, or summary…")
        self.activity_search.textChanged.connect(self._filter_dashboard_activity)
        self.activity_status_filter = QComboBox()
        self.activity_status_filter.setAccessibleName("Filter activity by status")
        self.activity_status_filter.addItems(["All statuses", "running", "succeeded", "failed", "cancelled"])
        self.activity_status_filter.currentTextChanged.connect(self._filter_dashboard_activity)
        self.activity_kind_filter = QComboBox()
        self.activity_kind_filter.setAccessibleName("Filter activity by kind")
        self.activity_kind_filter.addItem("All kinds")
        self.activity_kind_filter.currentTextChanged.connect(self._filter_dashboard_activity)
        filters.addWidget(self.activity_search, 2)
        filters.addWidget(self.activity_status_filter)
        filters.addWidget(self.activity_kind_filter)
        v.addLayout(filters)

        self.ops = _table(["Operation", "Kind", "Target", "Status", "Started"])
        self.ops.setObjectName("activityTable")
        self.ops.setAccessibleName("Recent operations table")
        self.ops.currentCellChanged.connect(self._show_dashboard_activity_detail)
        v.addWidget(self.ops, 2)
        self.activity_detail = QPlainTextEdit()
        self.activity_detail.setAccessibleName("Selected activity details")
        self.activity_detail.setReadOnly(True)
        self.activity_detail.setPlaceholderText("Select an activity record to inspect its details.")
        self.activity_detail.setMaximumHeight(170)
        v.addWidget(self.activity_detail)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.clear_history_button = QPushButton("Clear activity history…")
        self.clear_history_button.setAccessibleName("Clear activity history")
        self.clear_history_button.clicked.connect(self.clear_dashboard_history)
        actions.addWidget(self.clear_history_button)
        v.addLayout(actions)
        self._activity_rows: list[dict] = []
        self._visible_activity_rows: list[dict] = []
        return w

    def refresh_dashboard(self) -> None:
        rows = self._run("Loading activity", lambda: self.s.history(200)) or []
        self._activity_rows = list(rows)
        kinds = sorted({str(o.get("kind", "")) for o in rows if o.get("kind")})
        current_kind = self.activity_kind_filter.currentText()
        self.activity_kind_filter.blockSignals(True)
        self.activity_kind_filter.clear()
        self.activity_kind_filter.addItem("All kinds")
        self.activity_kind_filter.addItems(kinds)
        self.activity_kind_filter.setCurrentText(current_kind if current_kind in kinds else "All kinds")
        self.activity_kind_filter.blockSignals(False)
        counts = {status: sum(o.get("status") == status for o in rows)
                  for status in ("succeeded", "failed", "cancelled", "running")}
        retention_days = getattr(self.s, "settings").operation_retention_days
        self.metric_total.setText(f"<b>{len(rows)}</b><br>Total operations")
        self.metric_succeeded.setText(f"<b>{counts['succeeded']}</b><br>Succeeded")
        self.metric_failed.setText(f"<b>{counts['failed']}</b><br>Failed")
        self.metric_running.setText(f"<b>{counts['running']}</b><br>Running")
        self.metric_retention.setText(f"<b>{retention_days} days</b><br>Retention")
        self.ops_summary.setText(
            f"Showing {len(rows)} recent operations · "
            f"{counts['succeeded']} succeeded · {counts['failed']} failed · "
            f"{counts['cancelled']} cancelled · {counts['running']} running"
        )
        self._filter_dashboard_activity()

    def _filter_dashboard_activity(self, *_args) -> None:
        query = self.activity_search.text().strip().casefold()
        status = self.activity_status_filter.currentText()
        kind = self.activity_kind_filter.currentText()
        visible = []
        for operation in self._activity_rows:
            if status != "All statuses" and operation.get("status") != status:
                continue
            if kind != "All kinds" and operation.get("kind") != kind:
                continue
            searchable = " ".join(str(operation.get(key, "")) for key in
                                  ("operation_id", "kind", "target", "status", "started", "finished", "summary"))
            if query and query not in searchable.casefold():
                continue
            visible.append(operation)
        self._visible_activity_rows = visible
        _fill(self.ops, [[o.get("operation_id", ""), o.get("kind", ""), o.get("target", ""),
                          o.get("status", ""), o.get("started", "")] for o in visible])
        self.activity_detail.clear()
        if visible:
            self.ops.selectRow(0)
            self._show_dashboard_activity_detail(0, 0, -1, -1)
        else:
            self.activity_detail.setPlainText("No activity records match the current search and filters.")

    def _show_dashboard_activity_detail(self, row: int, _column: int, _previous_row: int, _previous_column: int) -> None:
        if row < 0 or row >= len(self._visible_activity_rows):
            self.activity_detail.clear()
            return
        operation_id = str(self._visible_activity_rows[row].get("operation_id", ""))
        operation = self._run("Loading activity details", lambda: self.s.history_item(operation_id))
        if operation is not None:
            self.activity_detail.setPlainText(json.dumps(operation, indent=2, sort_keys=True, default=str))

    def clear_dashboard_history(self) -> None:
        count = self._run("Counting activity history", self.s.history_count)
        if count is None:
            return
        if count == 0:
            QMessageBox.information(self, "Activity history is empty", "There are no activity records to clear.")
            return
        answer = QMessageBox.question(
            self, "Clear activity history",
            f"Permanently delete {count} Forge activity record(s)?\n\n"
            "This only removes the dashboard operation history. Projects, plans, checkpoints, "
            "verification evidence, and recent-project shortcuts will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self._run("Clearing activity history", self.s.clear_history)
        if removed is not None:
            self.refresh_dashboard()
            self.status.setText(f"Activity history cleared ({removed} records)")

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
        self._selected_component_ids: list[str] = []
        self.t_comps = QLineEdit()
        self.t_comps.setObjectName("selectedComponents")
        self.t_comps.setAccessibleName("Selected components")
        self.t_comps.setPlaceholderText("No components selected (optional)")
        self.t_comps.setReadOnly(True)
        choose_components = QPushButton("Choose components...")
        choose_components.setAccessibleName("Choose project components")
        choose_components.clicked.connect(self.choose_project_components)
        component_row = QHBoxLayout()
        component_row.addWidget(self.t_comps, 1)
        component_row.addWidget(choose_components)
        form.addRow("Archetype", self.t_arch)
        form.addRow("Project name", self.t_name)
        form.addRow("Output directory", row)
        form.addRow("Components", component_row)
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

    def _component_picker_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose project components")
        dialog.setAccessibleName("Project component picker")
        dialog.resize(620, 520)
        layout = QVBoxLayout(dialog)
        intro = QLabel("Search the catalog and select any components to include in your project.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        search = QLineEdit()
        search.setPlaceholderText("Search by component ID, category, or description...")
        search.setAccessibleName("Search project components")
        layout.addWidget(search)
        items = QListWidget()
        items.setAccessibleName("Available project components")
        dialog.component_items = items
        rows = self._run("Loading component choices", lambda: self.s.search_components("")) or []
        for component in rows:
            component_id = str(component["id"])
            description = str(component.get("summary") or component.get("category") or "Reusable project component")
            item = QListWidgetItem(f"{component_id} — {description}")
            item.setData(Qt.ItemDataRole.UserRole, component_id)
            item.setToolTip(description)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if component_id in self._selected_component_ids else Qt.CheckState.Unchecked)
            items.addItem(item)
        layout.addWidget(items, 1)

        def filter_items(query: str) -> None:
            terms = query.casefold().split()
            for index in range(items.count()):
                item = items.item(index)
                haystack = item.text().casefold()
                item.setHidden(not all(term in haystack for term in terms))

        search.textChanged.connect(filter_items)
        footer = QHBoxLayout()
        select_visible = QPushButton("Select visible")
        clear = QPushButton("Clear selection")
        done = QPushButton("Apply selection")
        done.setDefault(True)
        select_visible.clicked.connect(lambda: [items.item(i).setCheckState(Qt.CheckState.Checked)
                                                 for i in range(items.count()) if not items.item(i).isHidden()])
        clear.clicked.connect(lambda: [items.item(i).setCheckState(Qt.CheckState.Unchecked)
                                       for i in range(items.count())])
        done.clicked.connect(dialog.accept)
        footer.addWidget(select_visible)
        footer.addWidget(clear)
        footer.addStretch(1)
        footer.addWidget(done)
        layout.addLayout(footer)
        return dialog

    def choose_project_components(self) -> None:
        dialog = self._component_picker_dialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._selected_component_ids = [
            str(dialog.component_items.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(dialog.component_items.count())
            if dialog.component_items.item(i).checkState() == Qt.CheckState.Checked
        ]
        self.t_comps.setText(", ".join(self._selected_component_ids))

    def review_generation(self) -> None:
        comps = list(self._selected_component_ids)
        out = self.t_out.text() or str(Path.home() / self.t_name.text().lower().replace(" ", "-"))
        template = self.t_arch.currentText()
        options = {"name": self.t_name.text()}
        self.gr_out.setPlainText("Preparing generation preview…")
        self._start_background(
            "Generation review",
            lambda *, cancel_token, progress: self.s.create_project(
                template, options, out, components=comps, dry_run=True,
                cancel_token=cancel_token, progress=progress),
            on_success=lambda result: self.gr_out.setPlainText(json.dumps(result, indent=2, default=str)),
            on_cancel=lambda result: self.gr_out.setPlainText(
                "Generation preview cancelled. No project files were written.\n" +
                (str(result.get("message", "")) if isinstance(result, dict) else "")
            ),
        )

    def generate(self, dry: bool) -> None:
        comps = list(self._selected_component_ids)
        out = self.t_out.text() or str(Path.home() / self.t_name.text().lower().replace(" ", "-"))
        template = self.t_arch.currentText()
        options = {"name": self.t_name.text()}
        if dry:
            self.review_generation()
            return
        self.t_out_box.setPlainText("Preparing project generation…")

        def generation_succeeded(result: object) -> None:
            self.t_out_box.setPlainText(json.dumps(result, indent=2, default=str))
            self._remember_project(out)

        self._start_background(
            "Creating project",
            lambda *, cancel_token, progress: self.s.create_project(
                template, options, out, components=comps, dry_run=False,
                cancel_token=cancel_token, progress=progress),
            on_success=generation_succeeded,
            on_cancel=lambda result: self.t_out_box.setPlainText(
                "Project generation cancelled. The incomplete staging directory was cleaned up; "
                "no partial project was promoted.\n" +
                (str(result.get("message", "")) if isinstance(result, dict) else "")
            ),
        )

    # -- Project Workspace ----------------------------------------------------------------
    def _project_workspace(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("Project Workspace"))
        intro = QLabel("Pick up where you left off. Your recent projects are stored locally; this view only lists folders that still exist.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        v.addWidget(intro)

        actions = QHBoxLayout()
        refresh = QPushButton("Refresh projects")
        refresh.setAccessibleName("Refresh recent projects")
        refresh.clicked.connect(self.refresh_project_workspace)
        new_project = QPushButton("Create a project")
        new_project.setAccessibleName("Create a new project")
        new_project.clicked.connect(lambda: self.nav.setCurrentRow(NAV.index("Project Wizard")))
        open_project = QPushButton("Open in Workbench")
        open_project.setAccessibleName("Open selected project in Integration Workbench")
        open_project.clicked.connect(self.open_project_workspace_selection)
        actions.addWidget(refresh)
        actions.addStretch(1)
        actions.addWidget(new_project)
        actions.addWidget(open_project)
        v.addLayout(actions)

        self.workspace_projects = QListWidget()
        self.workspace_projects.setObjectName("workspaceProjects")
        self.workspace_projects.setAccessibleName("Recent projects")
        self.workspace_projects.setToolTip("Select a project to see its location and open it in the Integration Workbench.")
        self.workspace_projects.currentItemChanged.connect(self.show_project_workspace_selection)
        v.addWidget(self.workspace_projects, 2)

        self.workspace_detail = QPlainTextEdit()
        self.workspace_detail.setObjectName("workspaceDetail")
        self.workspace_detail.setAccessibleName("Selected project details")
        self.workspace_detail.setReadOnly(True)
        self.workspace_detail.setMaximumHeight(130)
        v.addWidget(self.workspace_detail)
        self.refresh_project_workspace()
        return w

    def refresh_project_workspace(self) -> None:
        selected = self.workspace_projects.currentItem().data(Qt.ItemDataRole.UserRole) if self.workspace_projects.currentItem() else None
        projects = self._run("Loading recent projects", lambda: self.s.list_recent_projects(existing_only=True)) or []
        self.workspace_projects.clear()
        for project in projects:
            path = Path(project)
            item = QListWidgetItem(path.name or str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.workspace_projects.addItem(item)
            if str(path) == selected:
                self.workspace_projects.setCurrentItem(item)
        if self.workspace_projects.count() and self.workspace_projects.currentRow() < 0:
            self.workspace_projects.setCurrentRow(0)
        if not projects:
            self.workspace_detail.setPlainText("No recent projects yet. Create a project or open one in the Integration Workbench to get started.")

    def show_project_workspace_selection(self, current, _previous=None) -> None:
        if current is None:
            return
        path = Path(str(current.data(Qt.ItemDataRole.UserRole)))
        self.workspace_detail.setPlainText(
            f"Project: {path.name or path}\nLocation: {path}\nStatus: Folder available")

    def open_project_workspace_selection(self) -> None:
        item = self.workspace_projects.currentItem()
        if item is None:
            self.status.setText("Select a project first")
            return
        path = str(item.data(Qt.ItemDataRole.UserRole))
        self.w_path.setText(path)
        self.q_path.setText(path)
        self.nav.setCurrentRow(NAV.index("Integration Workbench"))
        self.status.setText(f"Project opened in Integration Workbench: {path}")

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
        self._remember_project(self.w_path.text())
        r = self._run("Analyzing", lambda: self.s.analyze_project(self.w_path.text()))
        if r:
            self.w_out.setPlainText(json.dumps(r, indent=2, default=str))

    def make_plan(self) -> None:
        self._remember_project(self.w_path.text())
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
    def _confirm_plan(self, lines: list[str]) -> bool:
        message = ("This will modify the project:\n\n" + "\n".join(lines) +
                   "\n\nA checkpoint is recorded so the change can be recovered. Approve and apply?")
        return QMessageBox.question(
            self, "Approve change plan", message
        ) == QMessageBox.StandardButton.Yes

    def _approve_and_apply(self, plan_id: str, on_success=None, on_cancel=None):
        plan = self.s.preview_plan(plan_id)
        lines = [f"{c['action']:7} {c['path']}" for c in plan["changes"]]
        if not self._confirm_plan(lines):
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
        v.addWidget(_title("Extension & Tool Discovery"))
        v.addWidget(QLabel(
            "Discover installed capabilities, review their package entry points, and manage trust. "
            "Discovery reads metadata only: extension code is not imported or executed."
        ))
        self.ex_security_note = QLabel(
            "SECURITY BOUNDARY  •  Trust and enablement are separate decisions. "
            "Invocation is sandboxed on supported Linux hosts; unsupported platforms fail closed."
        )
        self.ex_security_note.setWordWrap(True)
        self.ex_security_note.setObjectName("muted")
        v.addWidget(self.ex_security_note)
        self.ex_table = _table(["Extension", "Entry point", "Trust", "Enabled"])
        self.ex_table.setAccessibleName("Extensions table")
        self.ex_table.setToolTip("Installed extensions discovered from package metadata; selecting a row shows details.")
        v.addWidget(self.ex_table, 2)
        self.ex_detail = QPlainTextEdit()
        self.ex_detail.setReadOnly(True)
        self.ex_detail.setAccessibleName("Selected extension details")
        self.ex_detail.setPlaceholderText("Select an extension to inspect its metadata and security status.")
        self.ex_detail.setMaximumHeight(150)
        v.addWidget(self.ex_detail, 1)
        row = QHBoxLayout()
        self.ex_refresh_button = QPushButton("Refresh discovery")
        self.ex_refresh_button.clicked.connect(self.load_extensions)
        row.addWidget(self.ex_refresh_button)
        self.ex_inspect_button = QPushButton("Inspect")
        self.ex_inspect_button.clicked.connect(self.inspect_ext)
        row.addWidget(self.ex_inspect_button)
        self.ex_trust_button = QPushButton("Trust...")
        self.ex_trust_button.clicked.connect(self.trust_ext)
        row.addWidget(self.ex_trust_button)
        self.ex_untrust_button = QPushButton("Untrust")
        self.ex_untrust_button.clicked.connect(lambda: self.ext_action("untrust"))
        row.addWidget(self.ex_untrust_button)
        self.ex_enable_button = QPushButton("Enable")
        self.ex_enable_button.clicked.connect(lambda: self.ext_action("enable"))
        row.addWidget(self.ex_enable_button)
        self.ex_disable_button = QPushButton("Disable")
        self.ex_disable_button.clicked.connect(lambda: self.ext_action("disable"))
        row.addWidget(self.ex_disable_button)
        v.addLayout(row)
        self.ex_table.itemSelectionChanged.connect(self._show_selected_extension)
        self._set_extension_actions(False)
        return w

    def _set_extension_actions(self, selected: bool) -> None:
        for button in (self.ex_inspect_button, self.ex_trust_button, self.ex_untrust_button,
                       self.ex_enable_button, self.ex_disable_button):
            button.setEnabled(selected)

    def load_extensions(self) -> None:
        rows = self._run("Discovering extensions", self.s.plugin_list) or []
        self.ex_table.setSortingEnabled(False)
        _fill(self.ex_table, [[r["name"], r["target"], r["trust"], "yes" if r["enabled"] else "no"]
                              for r in rows])
        self.ex_table.setSortingEnabled(True)
        self.ex_table.clearSelection()
        self._set_extension_actions(False)
        if not rows:
            self.ex_detail.setPlainText(
                "No extensions are currently installed.\n\n"
                "Extensions are discovered from Python package entry points in the "
                "'app_forge.plugins' group. Install an extension package, then refresh discovery. "
                "No network request or code execution is performed by this screen."
            )
        else:
            self.ex_detail.setPlainText(
                f"{len(rows)} installed extension{'s' if len(rows) != 1 else ''} discovered. "
                "Select one to review its trust, enablement, and execution boundary."
            )

    def _selected_ext(self):
        items = self.ex_table.selectedItems()
        return self.ex_table.item(items[0].row(), 0).text() if items else None

    def _show_selected_extension(self) -> None:
        name = self._selected_ext()
        self._set_extension_actions(bool(name))
        if name:
            row = self.ex_table.currentRow()
            target = self.ex_table.item(row, 1).text()
            trust = self.ex_table.item(row, 2).text()
            enabled = self.ex_table.item(row, 3).text()
            self.ex_detail.setPlainText(
                f"{name}\n"
                f"Entry point: {target}\n"
                f"Trust: {trust}\n"
                f"Enabled: {enabled}\n\n"
                "Select Inspect for the full extension metadata and isolation details. "
                "Selecting an extension never imports or executes its code."
            )

    def inspect_ext(self) -> None:
        name = self._selected_ext()
        if not name:
            return
        details = self._run("Inspecting extension", lambda: self.s.plugin_inspect(name))
        if details:
            self.ex_detail.setPlainText(
                f"{details.get('name', name)}\n"
                f"Entry point: {details.get('target', 'unknown')}\n"
                f"Entry-point group: {details.get('group', 'app_forge.plugins')}\n"
                f"Trust: {details.get('trust', 'unknown')}\n"
                f"Enabled: {'yes' if details.get('enabled') else 'no'}\n"
                f"Execution boundary: {details.get('isolation', 'not reported')}\n\n"
                "Security note: trust approval is explicit. Enablement is separate, and "
                "extension invocation is refused when the required OS sandbox is unavailable."
            )

    def trust_ext(self) -> None:
        name = self._selected_ext()
        if name and QMessageBox.question(
            self, "Trust extension",
            f"Trust {name!r}? Trusting permits it to be enabled and invoked subject to the OS sandbox. "
            "Only trust extensions from sources you have reviewed."
        ) == QMessageBox.StandardButton.Yes:
            self._run("Trusting", lambda: self.s.plugin_trust(name, "trusted"))
            self.load_extensions()

    def ext_action(self, action: str) -> None:
        name = self._selected_ext()
        if name:
            fn = {"untrust": lambda: self.s.plugin_trust(name, "untrusted"),
                  "enable": lambda: self.s.plugin_enable(name),
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
        self._remember_project(path)
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
        self._remember_project(self.q_path.text())
        r = self._run("Building report", lambda: self.s.compliance_report(None, self.q_path.text()))
        if r:
            self.q_out.setPlainText(json.dumps({"summary": r["summary"], "gaps": r["gaps"],
                                                "disclaimer": r["disclaimer"]}, indent=2))

    # -- UI-021 Settings / UI-020 Diagnostics ---------------------------------------------
    def _settings(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)
        v.addWidget(_title("Settings & Personalization"))
        intro = QLabel("Make Forge feel right for your workflow. Preferences are stored locally on this device.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        v.addWidget(intro)
        appearance = QFormLayout()
        self.preference_theme = QComboBox()
        self.preference_theme.setAccessibleName("Application theme")
        self.preference_theme.addItem("Light", "light")
        self.preference_theme.addItem("Dark", "dark")
        self.preference_theme.setCurrentIndex(0 if self.theme == "light" else 1)
        appearance.addRow("Theme", self.preference_theme)
        self.preference_accent = QComboBox()
        self.preference_accent.setAccessibleName("Accent color")
        for label, value in (("Electric blue", "blue"), ("Emerald green", "green"), ("Cosmic purple", "purple")):
            self.preference_accent.addItem(label, value)
        self.preference_accent.setCurrentIndex(["blue", "green", "purple"].index(self.accent))
        appearance.addRow("Accent color", self.preference_accent)
        self.preference_compact = QCheckBox("Use compact spacing")
        self.preference_compact.setAccessibleName("Use compact spacing")
        self.preference_compact.setChecked(self.compact_density)
        appearance.addRow("Layout density", self.preference_compact)
        self.preference_mascots = QCheckBox("Show Aura Guild touches in welcome and empty states")
        self.preference_mascots.setAccessibleName("Show Aura Guild touches")
        self.preference_mascots.setChecked(self.mascots_enabled)
        appearance.addRow("Brand details", self.preference_mascots)
        v.addLayout(appearance)
        actions = QHBoxLayout()
        save = QPushButton("Save preferences")
        save.clicked.connect(self.save_personalization)
        actions.addWidget(save)
        reset = QPushButton("Reset to defaults")
        reset.setObjectName("secondaryAction")
        reset.clicked.connect(self.reset_personalization)
        actions.addWidget(reset)
        actions.addStretch(1)
        v.addLayout(actions)
        self.preference_status = QLabel("Changes are applied when you save.")
        self.preference_status.setObjectName("muted")
        v.addWidget(self.preference_status)
        v.addWidget(_title("Forge configuration"))
        box = QPlainTextEdit(json.dumps(self.s.show_config(), indent=2))
        box.setReadOnly(True)
        box.setAccessibleName("Current configuration")
        v.addWidget(box, 1)
        return w

    def save_personalization(self) -> None:
        self.theme = str(self.preference_theme.currentData())
        self.accent = str(self.preference_accent.currentData())
        self.compact_density = self.preference_compact.isChecked()
        self.mascots_enabled = self.preference_mascots.isChecked()
        self.apply_theme()
        self._save_session()
        self.preference_status.setText("Preferences saved on this device.")

    def reset_personalization(self) -> None:
        self.preference_theme.setCurrentIndex(0)
        self.preference_accent.setCurrentIndex(0)
        self.preference_compact.setChecked(False)
        self.preference_mascots.setChecked(True)
        self.save_personalization()

    def toggle_theme(self, on: bool) -> None:
        self.set_theme("dark" if on else "light")

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
