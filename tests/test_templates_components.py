import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from app_forge.analyzer import snapshot_tree
from app_forge.cli.main import main as cli_main
from app_forge.domain.errors import ConflictFailure, ValidationFailure
from tests.helpers import ALL, ForgeTestCase


class TemplateTests(ForgeTestCase):
    def test_all_archetypes_generate_and_pass_smoke_tests(self):  # AT-001
        s = self.services()
        for a in ALL:
            out = self.tmp / a
            s.create_project(a, {"name": "Smoke App"}, out)
            rep = s.verify_project(out)
            self.assertEqual(rep["overall"], "passed", (a, rep["evidence"]))
            self.assertTrue(rep["complete"])

    def test_generation_is_reproducible(self):
        s = self.services()
        s.create_project("web", {"name": "Repro"}, self.tmp / "a", components=["forge.forms-validation"])
        s.create_project("web", {"name": "Repro"}, self.tmp / "b", components=["forge.forms-validation"])
        self.assertEqual(snapshot_tree(self.tmp / "a"), snapshot_tree(self.tmp / "b"))

    def test_bytecode_caches_in_template_tree_are_ignored(self):
        import shutil
        from app_forge.templates.engine import TEMPLATES_ROOT, TemplateEngine
        copy = self.tmp / "tpl"
        shutil.copytree(TEMPLATES_ROOT, copy)
        cache = copy / "cli" / "tree" / "src" / "__package__" / "__pycache__"
        cache.mkdir()
        (cache / "core.cpython-312.pyc").write_bytes(b"\xcb\x00binary")
        eng = TemplateEngine([copy])
        info = eng.get("cli")
        files = eng.render(info, eng.validate_inputs(info, {"name": "Cache Test"}))
        self.assertFalse([f for f in files if "pycache" in f or f.endswith(".pyc")])

    def test_dry_run_writes_nothing_and_lists_files(self):
        r = self.services().create_project("cli", {"name": "Dry"}, self.tmp / "d", dry_run=True)
        self.assertFalse((self.tmp / "d").exists())
        self.assertIn("forge.toml", [f["path"] for f in r["files"]])

    def test_input_validation_and_safe_target(self):
        s = self.services()
        for bad in ({"name": "1bad"}, {"name": "ok app", "description": 'x"y'}, {"name": "ok app", "python_version": "3.9"},
                    {"name": "ok app", "package": "class"}):
            with self.assertRaises(ValidationFailure):
                s.create_project("cli", bad, self.tmp / "x")
        (self.tmp / "full").mkdir()
        (self.tmp / "full" / "f.txt").write_text("x")
        with self.assertRaises(ConflictFailure):
            s.create_project("cli", {"name": "Ok App"}, self.tmp / "full")

    def test_failed_promotion_leaves_no_partial_project_or_stage(self):
        from unittest import mock
        s = self.services()
        out = self.tmp / "rollback"
        with mock.patch("app_forge.services.os.replace", side_effect=OSError("promotion failed")):
            with self.assertRaises(OSError):
                s.create_project("cli", {"name": "Rollback App"}, out)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.tmp.glob(".rollback.forge-create-*")), [])

    def test_adoption_rejects_invalid_or_undiscovered_package(self):
        root = self.tmp / "legacy"
        pkg = root / "src" / "legacy_pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (root / "pyproject.toml").write_text('[project]\nname = "legacy"\nversion = "1.0"\n',
                                             encoding="utf-8")
        s = self.services()
        with self.assertRaises(ValidationFailure):
            s.adopt_project(root, package="class", archetype="cli")
        with self.assertRaises(ValidationFailure):
            s.adopt_project(root, package="other_pkg", archetype="cli")
        preview = s.adopt_project(root, package="legacy_pkg", archetype="cli")
        self.assertTrue(preview["preview"])
        self.assertFalse((root / "forge.toml").exists())

    def test_adoption_uses_project_lock_and_commits_metadata(self):
        from app_forge.locks import project_lock
        root = self.tmp / "adoptable"
        pkg = root / "src" / "adoptable"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (root / "pyproject.toml").write_text('[project]\nname = "adoptable"\nversion = "1.0"\n',
                                             encoding="utf-8")
        s = self.services()
        with project_lock(s.settings.locks_dir, root, "another operation"):
            with self.assertRaises(ConflictFailure):
                s.adopt_project(root, package="adoptable", archetype="cli", confirm=True)
        result = s.adopt_project(root, package="adoptable", archetype="cli", confirm=True)
        self.assertFalse(result["preview"])
        self.assertEqual(s.analyzer.analyze(root)["package"], "adoptable")
        self.assertFalse(list(root.glob(".forge.toml.*.tmp")))

    def test_gui_and_cli_generate_identical_projects(self):  # AT-002
        # The GUI calls ForgeServices.create_project; the CLI must produce the same tree.
        self.services().create_project("desktop", {"name": "Parity App"}, self.tmp / "svc",
                                       components=["forge.themes"])
        buf = StringIO()
        with redirect_stdout(buf):
            code = cli_main(["--home", str(self.home), "--json", "init", "--archetype", "desktop", "--name",
                             "Parity App", "--out", str(self.tmp / "cli"), "--component", "forge.themes"])
        self.assertEqual(code, 0)
        self.assertEqual(snapshot_tree(self.tmp / "svc"), snapshot_tree(self.tmp / "cli"))
        from pathlib import Path
        import app_forge
        gui_src = (Path(app_forge.__file__).parent / "gui" / "app.py").read_text()
        self.assertIn("ForgeServices", gui_src)
        self.assertIn("self.s.create_project", gui_src)


class ComponentTests(ForgeTestCase):
    def test_every_builtin_component_passes_its_contract_tests(self):  # AT-005/AT-006
        s = self.services()
        for c in s.search_components():
            r = s.verify_component(c["id"])
            self.assertEqual(r["overall"], "passed", c["id"])
            self.assertTrue(r["complete"])

    def test_install_registers_component_and_tests_run(self):
        s = self.services()
        out = self.make_project(s, "desktop", components=["forge.advanced-table"])
        inv = s.project_inventory(out)
        self.assertEqual({c["id"] for c in inv["components"]}, {"forge.themes", "forge.advanced-table"})
        ev = {e["check_id"] for e in s.verify_project(out)["evidence"]}
        self.assertIn("tests/test_table_model.py::TableTests::test_multi_column_sort_is_deterministic_with_none_last", ev)

    def test_incompatible_archetype_rejected_at_creation(self):
        with self.assertRaises(ConflictFailure):
            self.services().create_project("cli", {"name": "No Table"}, self.tmp / "c", components=["forge.advanced-table"])

    def test_dependencies_added_for_generated_projects(self):
        self.custom_component("acme.rich", python_packages=("rich>=13",))
        s = self.services()
        out = self.make_project(s, "service", components=["acme.rich"])
        self.assertIn('"rich>=13"', (out / "pyproject.toml").read_text())


if __name__ == "__main__":
    unittest.main()
