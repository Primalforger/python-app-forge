import ast
import importlib
import inspect
import json
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import app_forge
from app_forge.cli.main import main
from app_forge.domain.errors import ConflictFailure, ValidationFailure
from app_forge.gui import theme
from app_forge.services import ForgeServices
from app_forge.table_designer import normalize_definition, to_python
from tests import qt_stub
from tests.helpers import ForgeTestCase

PKG = Path(app_forge.__file__).resolve().parent
TABLE_DEF = {"name": "Orders", "columns": [{"key": "id", "type": "number"}, {"key": "status", "type": "category"},
                                           {"key": "total", "type": "number"}],
             "default_sort": [{"column": "total", "descending": True}],
             "filters": [{"column": "status", "op": "eq", "value": "open"}], "page_size": 2}


class UpgradeTests(ForgeTestCase):
    def setUp(self):
        super().setUp()
        self.custom_component("acme.lib", "1.0.0", files={"src/lib_mod.py": "V = 1\n", "src/old_mod.py": "B = 1\n"})
        self.custom_component("acme.lib", "2.0.0", files={"src/lib_mod.py": "V = 2\n", "src/new_mod.py": "C = 1\n"},
                              python_packages=("attrs>=23",))
        self.s = self.services()
        self.proj = self.make_project(self.s, "cli", "Up App")
        p = self.s.plan_add(self.proj, {"acme.lib": "^1.0"})
        self.s.approve_plan(p["plan_id"], "t")
        self.assertEqual(self.s.apply_plan(p["plan_id"])["status"], "applied")
        self.pkg = self.proj / "src" / "up_app"

    def installed(self):
        return {c["id"]: c["version"] for c in self.s.analyze_project(self.proj)["installed_components"]}

    def test_upgrade_plan_contents(self):
        self.assertTrue(self.s.project_components(self.proj)[0]["upgrade_available"])
        p = self.s.plan_upgrade(self.proj, ["acme.lib"])
        self.assertEqual(p["conflicts"], [])
        self.assertEqual({(c["action"], c["path"]) for c in p["changes"]},
                         {("modify", "src/up_app/lib_mod.py"), ("delete", "src/up_app/old_mod.py"),
                          ("create", "src/up_app/new_mod.py"), ("modify", "pyproject.toml"),
                          ("modify", ".forge/components.toml")})
        self.assertTrue(any("major upgrade" in w for w in p["warnings"]))
        self.assertEqual(self.pkg.joinpath("lib_mod.py").read_text(), "V = 1\n")  # planning changed nothing

    def test_apply_then_recover(self):
        p = self.s.plan_upgrade(self.proj, ["acme.lib"])
        self.s.approve_plan(p["plan_id"], "t")
        r = self.s.apply_plan(p["plan_id"])
        self.assertEqual(r["status"], "applied")
        self.assertEqual(self.pkg.joinpath("lib_mod.py").read_text(), "V = 2\n")
        self.assertFalse(self.pkg.joinpath("old_mod.py").exists())
        self.assertIn('"attrs>=23"', (self.proj / "pyproject.toml").read_text())
        self.assertEqual(self.installed(), {"acme.lib": "2.0.0"})
        self.assertFalse(self.s.project_components(self.proj)[0]["upgrade_available"])
        self.assertEqual(self.s.recover_plan(p["plan_id"])["status"], "rolled_back")
        self.assertEqual(self.pkg.joinpath("lib_mod.py").read_text(), "V = 1\n")
        self.assertTrue(self.pkg.joinpath("old_mod.py").exists())
        self.assertNotIn("attrs", (self.proj / "pyproject.toml").read_text())
        self.assertEqual(self.installed(), {"acme.lib": "1.0.0"})

    def test_user_edits_are_never_overwritten_or_deleted(self):
        self.pkg.joinpath("lib_mod.py").write_text("V = 1  # tuned by me\n")
        self.pkg.joinpath("old_mod.py").write_text("B = 99\n")
        p = self.s.plan_upgrade(self.proj, ["acme.lib"])
        self.assertEqual(sorted(c["path"] for c in p["conflicts"]),
                         ["src/up_app/lib_mod.py", "src/up_app/old_mod.py"])
        with self.assertRaises(ConflictFailure):
            self.s.approve_plan(p["plan_id"], "t")

    def test_up_to_date_is_a_noop(self):
        p = self.s.plan_upgrade(self.proj, ["acme.lib"])
        self.s.approve_plan(p["plan_id"], "t")
        self.s.apply_plan(p["plan_id"])
        again = self.s.plan_upgrade(self.proj, ["acme.lib"])
        self.assertEqual(again["changes"], [])
        self.assertTrue(any("newest usable" in w for w in again["warnings"]))

    def test_not_installed_and_dependents(self):
        with self.assertRaises(ValidationFailure):
            self.s.plan_upgrade(self.proj, ["forge.themes"])
        self.custom_component("acme.app", requires={"acme.lib": "^1.0"})
        s2 = self.services()
        p = s2.plan_add(self.proj, {"acme.app": "*"})
        s2.approve_plan(p["plan_id"], "t")
        s2.apply_plan(p["plan_id"])
        up = s2.plan_upgrade(self.proj, ["acme.lib"])
        self.assertEqual(up["conflicts"][0]["code"], "breaks-dependent")

    def test_upgrade_pulls_in_new_transitive_dependency(self):
        self.custom_component("acme.core", "1.0.0", files={"src/core_mod.py": "X = 1\n"})
        self.custom_component("acme.core", "1.1.0", files={"src/core_mod.py": "X = 2\n"}, requires={"acme.helper": "^1.0"})
        self.custom_component("acme.helper", files={"src/helper_mod.py": "H = 1\n"})
        s2 = self.services()
        p = s2.plan_add(self.proj, {"acme.core": "==1.0.0"})
        s2.approve_plan(p["plan_id"], "t")
        s2.apply_plan(p["plan_id"])
        up = s2.plan_upgrade(self.proj, ["acme.core"])
        self.assertIn(("create", "src/up_app/helper_mod.py"), {(c["action"], c["path"]) for c in up["changes"]})
        s2.approve_plan(up["plan_id"], "t")
        self.assertEqual(s2.apply_plan(up["plan_id"])["status"], "applied")
        self.assertEqual(self.installed()["acme.helper"], "1.0.0")


class CliNewCommandTests(ForgeTestCase):
    def run_cli(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), "--non-interactive", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_component_upgrade_through_cli(self):
        self.custom_component("acme.lib", "1.0.0")
        self.custom_component("acme.lib", "1.1.0", files={"src/lib.py": "VALUE = 2\n"})
        proj = str(self.tmp / "p")
        self.run_cli("init", "--archetype", "cli", "--name", "Cli Up", "--out", proj)
        self.run_cli("component", "add", proj, "acme.lib@==1.0.0", "--apply", "--by", "ci", "--yes")
        code, out, _ = self.run_cli("--json", "component", "outdated", proj)
        self.assertEqual(json.loads(out)["result"][0]["newest"], "1.1.0")
        code, out, _ = self.run_cli("--json", "component", "upgrade", proj, "acme.lib", "--apply", "--by", "ci", "--yes")
        self.assertEqual((code, json.loads(out)["result"]["status"]), (0, "applied"))
        self.assertEqual(self.run_cli("--json", "integrate", "plan", proj, "--upgrade", "acme.lib")[0], 0)

    def test_architecture_diagram_formats(self):
        code, out, _ = self.run_cli("architecture", "diagram", "--format", "mermaid")
        self.assertTrue(out.startswith("graph LR") and "app_forge_services" in out)
        code, out, _ = self.run_cli("--json", "architecture", "diagram", "--format", "json")
        g = json.loads(out)["result"]
        self.assertEqual(g["violations"], [])
        edges = {(e["from"], e["to"]) for e in g["edges"]}
        self.assertNotIn(("app_forge.cli", "app_forge.gui"), edges)
        self.assertNotIn(("app_forge.domain", "app_forge.security"), edges)

    def test_test_compare_flags_regressions_with_exit_code(self):
        proj = self.tmp / "p"
        self.run_cli("init", "--archetype", "cli", "--name", "Cmp App", "--out", str(proj))
        self.assertEqual(self.run_cli("test", "compare", str(proj))[0], 2)  # no runs yet
        self.run_cli("test", "run", str(proj))
        self.run_cli("test", "run", str(proj))
        code, out, _ = self.run_cli("--json", "test", "compare", str(proj))
        self.assertEqual((code, json.loads(out)["result"]["verdict"]), (0, "no-regression"))
        (proj / "tests" / "test_core.py").write_text(
            "import unittest\nclass GreetTests(unittest.TestCase):\n    def test_greet(self):\n        self.fail('x')\n")
        self.run_cli("test", "run", str(proj))
        code, out, _ = self.run_cli("--json", "test", "compare", str(proj))
        r = json.loads(out)["result"]
        self.assertEqual(code, 6)
        self.assertIn("tests/test_core.py::GreetTests::test_greet", r["regressions"])
        self.assertTrue(any(item.startswith("tests:") for item in r["regressions"]))  # aggregate runner regression
        self.assertTrue(r["removed"])  # the other test no longer exists
        self.assertEqual(len(json.loads(self.run_cli("--json", "test", "runs", str(proj))[1])["result"]), 3)

    def test_history_compare(self):
        self.run_cli("doctor")
        self.run_cli("init", "--archetype", "cli", "--name", "1bad", "--out", str(self.tmp / "x"))
        ops = json.loads(self.run_cli("--json", "history", "list")[1])["result"]
        code, out, _ = self.run_cli("--json", "history", "compare", ops[0]["operation_id"], ops[1]["operation_id"]) \
            if len(ops) > 1 else (0, "{}", "")
        self.assertEqual(code, 0)
        self.assertEqual(self.run_cli("history", "compare", "only-one")[0], 2)

    def test_template_export_import_roundtrip(self):
        exp = self.tmp / "exp"
        self.assertEqual(self.run_cli("template", "export", "cli", "--out", str(exp))[0], 0)
        self.assertEqual(self.run_cli("template", "import", str(exp))[0], 3)  # same id as built-in: refused
        toml = (exp / "template.toml").read_text().replace('id = "cli-typer"', 'id = "my-cli"')
        (exp / "template.toml").write_text(toml)
        self.assertEqual(self.run_cli("template", "import", str(exp))[0], 0)
        out = self.tmp / "gen"
        self.assertEqual(self.run_cli("init", "--template", "my-cli", "--name", "From Custom", "--out", str(out))[0], 0)
        self.assertEqual(self.run_cli("test", "run", str(out))[0], 0)

    def test_import_rejects_symlinks_and_non_templates(self):
        self.assertEqual(self.run_cli("template", "import", str(self.tmp))[0], 2)
        exp = self.tmp / "exp"
        self.run_cli("template", "export", "cli", "--out", str(exp))
        try:
            (exp / "tree" / "evil").symlink_to("/etc")
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertEqual(self.run_cli("template", "import", str(exp))[0], 4)

    def test_table_design_command(self):
        f = self.tmp / "t.json"
        f.write_text(json.dumps(TABLE_DEF))
        code, out, _ = self.run_cli("table", "design", str(f), "--import-path", "x.table_model", "--python-only")
        self.assertEqual(code, 0)
        compile(out, "gen", "exec")
        f.write_text(json.dumps({**TABLE_DEF, "page_size": 0, "export_formats": ["xlsx"]}))
        code, out, err = self.run_cli("table", "design", str(f))
        self.assertEqual(code, 2)
        self.assertIn("page_size", err)


class TableDesignerTests(unittest.TestCase):
    def test_validation_messages(self):
        bad = {"name": "x y", "columns": [{"key": "A b", "type": "weird"}, {"key": "id"}, {"key": "id"}],
               "default_sort": [{"column": "nope"}], "filters": [{"column": "id", "op": "contains", "value": 1}],
               "filter_mode": "xor", "page_size": True}
        with self.assertRaises(ValidationFailure) as cm:
            normalize_definition(bad)
        self.assertGreaterEqual(len(cm.exception.details), 7)

    def test_generated_code_drives_the_real_component(self):
        import sys
        from app_forge.catalog.registry import BUILTIN_COMPONENTS
        src = str(BUILTIN_COMPONENTS / "forge.advanced-table/1.0.0/files/src")
        sys.path.insert(0, src)
        self.addCleanup(sys.path.remove, src)
        self.addCleanup(sys.modules.pop, "table_model", None)
        ns: dict = {}
        exec(compile(to_python(TABLE_DEF, "table_model"), "gen", "exec"), ns)  # noqa: S102 - our own generated code
        rows = [{"id": 1, "status": "open", "total": 5}, {"id": 2, "status": "closed", "total": 9},
                {"id": 3, "status": "open", "total": 7}, {"id": 4, "status": "open", "total": 1}]
        m = ns["build_orders"](rows)
        self.assertEqual([r["id"] for r in m.page(1).rows], [3, 1])  # filtered, sorted desc, page size 2
        self.assertEqual(m.page(1).total, 3)

    def test_injection_in_values_is_inert(self):
        d = {**TABLE_DEF, "filters": [{"column": "status", "op": "eq", "value": "x'); __import__('os').system('echo pwn"}]}
        code = to_python(d, "table_model")
        ast.parse(code)
        self.assertNotIn("\n    __import__", code)


class StoreConnectionTests(ForgeTestCase):
    def test_every_connection_is_closed_so_forge_db_can_be_deleted_on_windows(self):
        import sqlite3
        from unittest import mock
        opened = []
        real = sqlite3.connect

        def tracking(*a, **k):
            c = real(*a, **k)
            opened.append(c)
            return c
        with mock.patch("app_forge.persistence.sqlite3.connect", tracking):
            s = self.services()
            self.make_project(s, "cli", "Closer")
            s.history()
            s.search_components("x")
            s.rebuild_catalog_index()
            with self.assertRaises(Exception):  # an error inside an operation must also release the handle
                s.store.get_operation(None.__class__)  # type: ignore[arg-type]
        self.assertGreater(len(opened), 5)
        for c in opened:
            with self.assertRaises(sqlite3.ProgrammingError):  # "Cannot operate on a closed database"
                c.execute("select 1")
        (self.home / "forge.db").unlink()  # the operation that failed on Windows


class ThemeTests(unittest.TestCase):
    def test_gui_themes_meet_contrast(self):
        for name in theme.TOKENS:
            bad = [r for r in theme.check_theme(name) if not r["ok"]]
            self.assertEqual(bad, [], name)


class GuiStubTests(ForgeTestCase):
    """Executes gui/app.py against a Qt stand-in. Proves our logic runs; says nothing about real Qt behaviour."""

    def setUp(self):
        super().setUp()
        qt_stub.install()
        self.addCleanup(qt_stub.uninstall)
        self.gui = importlib.import_module("app_forge.gui.app")
        self.s = self.services()
        self.win = self.gui.MainWindow(self.s)

    def test_every_service_call_in_gui_exists_with_valid_arity(self):
        tree = ast.parse((PKG / "gui" / "app.py").read_text())
        checked = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "s" and isinstance(node.value.value, ast.Name) and node.value.value.id == "self"):
                self.assertTrue(hasattr(ForgeServices, node.attr), f"GUI uses missing service method {node.attr}")
                checked += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Attribute) \
                    and node.func.value.attr == "s":
                sig = inspect.signature(getattr(ForgeServices, node.func.attr))
                sig.bind(None, *[None] * len(node.args), **{k.arg: None for k in node.keywords if k.arg})
        self.assertGreater(checked, 15)

    def test_all_screens_build_and_load_without_errors(self):
        self.assertEqual(len(self.gui.NAV), 13)
        for row in range(len(self.gui.NAV)):
            self.win._navigate(row)
        self.assertEqual(qt_stub.ERRORS, [])
        self.assertTrue(self.win.ar_table._items)       # architecture edges loaded
        self.assertEqual(self.win.ar_viol.toPlainText(), "None: all rules satisfied.")
        self.assertEqual(self.win.ds_table.item(0, 3).text(), "yes")
        self.assertTrue(json.loads(self.win.d_out.toPlainText())["checks"])

    def test_every_input_widget_has_an_accessible_name(self):
        # audits every widget ever constructed (not only window attributes: a local `box` once slipped through)
        inputs = {"QLineEdit", "QComboBox", "QPlainTextEdit", "QTableWidget", "QListWidget", "QCheckBox"}
        seen = [w for w in qt_stub.INSTANCES if type(w).__name__ in inputs]
        self.assertGreater(len(seen), 20)
        missing = [type(w).__name__ for w in seen
                   if not (w.accessibleName() or (type(w).__name__ == "QCheckBox" and w.text()))]
        self.assertEqual(missing, [], "widgets without an accessible name (screen readers cannot announce them)")

    def test_project_wizard_and_generation_review_are_separate(self):
        self.assertEqual(self.gui.NAV[1:3], ["Project Wizard", "Generation Review"])
        self.win.t_name.setText("Review App")
        self.win.t_out.setText(str(self.tmp / "review-app"))
        self.win.nav.setCurrentRow(self.gui.NAV.index("Project Wizard"))
        self.win.nav.setCurrentRow(self.gui.NAV.index("Generation Review"))
        self.win.review_generation()
        self.assertIn("Review App", self.win.gr_out.toPlainText())
        self.assertFalse((self.tmp / "review-app").exists())
        self.assertEqual(self.gui.NAV[-2:], ["Configuration Center", "Diagnostics"])

    def test_table_designer_screen(self):
        self.win.td_import.setText("app.table_model")
        self.win.td_columns.item(0, 0).setText("order_id")
        self.win.td_columns.cellWidget(0, 1).setCurrentText("number")
        self.win.add_table_column()
        self.assertEqual(self.win.td_columns.rowCount(), 4)
        self.win.td_columns.setCurrentCell(3, 0)
        self.win.remove_table_column()
        self.assertEqual(self.win.td_columns.rowCount(), 3)
        self.win.design_table()
        self.assertIn("def build_orders", self.win.td_out.toPlainText())
        self.assertIn("order_id", self.win.td_out.toPlainText())
        self.win.td_columns.item(1, 0).setText("order_id")
        self.win.design_table()
        self.assertTrue(qt_stub.ERRORS and "duplicated" in qt_stub.ERRORS[0])

    def test_component_manager_upgrade_flow(self):
        self.custom_component("acme.lib", "1.0.0")
        self.custom_component("acme.lib", "1.1.0", files={"src/lib.py": "VALUE = 2\n"})
        s = self.services()
        proj = self.make_project(s, "cli", "Gui Up")
        p = s.plan_add(proj, {"acme.lib": "==1.0.0"})
        s.approve_plan(p["plan_id"], "t")
        s.apply_plan(p["plan_id"])
        win = self.gui.MainWindow(s)
        win.cm_path.setText(str(proj))
        win.load_components()
        self.assertEqual(win.cm_table.item(0, 3).text(), "yes")
        win.cm_table._selected = [SimpleNamespace(row=lambda: 0)]
        win.plan_selected("upgrade")
        self.assertIn('"kind": "upgrade"', win.cm_out.toPlainText())
        def run_inline(label, operation, on_success=None, on_cancel=None):
            from app_forge.cancellation import CancellationToken
            result = operation(cancel_token=CancellationToken(), progress=lambda event: None)
            if on_success:
                on_success(result)
            return True

        with mock.patch.object(win, "_start_background", side_effect=run_inline):
            win.apply_cm_plan()
        self.assertEqual(qt_stub.ERRORS, [])
        self.assertEqual((proj / "src/gui_up/lib.py").read_text(), "VALUE = 2\n")

    def test_extension_manager_never_runs_untrusted(self):
        class EP:
            name, value = "acme-ext", "acme.ext:Plugin"
            def load(self): raise AssertionError("must not load")
        from app_forge.extensions import ExtensionHost
        self.s.extensions = ExtensionHost(self.s.store, lambda: [EP()])
        self.win.load_extensions()
        self.assertEqual(self.win.ex_table.item(0, 2).text(), "untrusted")
        self.win.ex_table._selected = [SimpleNamespace(row=lambda: 0)]
        self.win.ext_action("enable")  # must be refused, surfaced to the user
        self.assertTrue(any("not trusted" in e for e in qt_stub.ERRORS))
        self.win.trust_ext()
        self.win.ext_action("enable")
        self.assertEqual(self.win.ex_table.item(0, 3).text(), "yes")


if __name__ == "__main__":
    unittest.main()
