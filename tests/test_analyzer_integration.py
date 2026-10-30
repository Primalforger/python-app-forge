import shutil
import unittest
from pathlib import Path

from app_forge.analyzer import snapshot_tree
from app_forge.domain.errors import ConflictFailure, SecurityBlock
from tests.helpers import ForgeTestCase


class AnalyzerTests(ForgeTestCase):
    def test_analysis_is_read_only_and_executes_nothing(self):  # AT-007
        root = self.tmp / "evil"
        (root / "pkg").mkdir(parents=True)
        marker = self.tmp / "EXECUTED"
        (root / "pkg" / "__init__.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
        (root / "setup.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
        (root / "pyproject.toml").write_text('[project]\nname = "evil"\nversion = "1"\n')
        before = snapshot_tree(root)
        a = self.services().analyze_project(root)
        self.assertEqual(snapshot_tree(root), before)
        self.assertFalse(marker.exists())
        self.assertEqual(a["level"], 3)

    def test_levels(self):
        s = self.services()
        gen = self.make_project(s, "web")
        a = s.analyze_project(gen)
        self.assertEqual((a["level"], a["archetype_indicators"], a["tests"]["present"]), (1, ["web"], True))
        self.assertIn("fastapi", a["frameworks"])
        l2 = self.tmp / "l2"
        (l2 / "src" / "lib").mkdir(parents=True)
        (l2 / "src" / "lib" / "__init__.py").write_text("")
        (l2 / "tests").mkdir()
        (l2 / "tests" / "test_x.py").write_text("")
        (l2 / "pyproject.toml").write_text('[project]\nname="lib"\nversion="1"\ndependencies=["typer"]\n')
        self.assertEqual(s.analyze_project(l2)["level"], 2)
        l4 = self.tmp / "l4"
        l4.mkdir()
        (l4 / "notes.txt").write_text("hi")
        a4 = s.analyze_project(l4)
        self.assertEqual(a4["level"], 4)
        self.assertEqual(a4["supported_operations"], ["analyze"])

    def test_git_dirty_detection(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        out = self.make_project()
        self.git_init(out)
        self.assertEqual(self.services().analyze_project(out)["git"]["state"], "clean")
        (out / "README.md").write_text("changed")
        g = self.services().analyze_project(out)["git"]
        self.assertEqual((g["state"], g["dirty_paths"]), ("dirty", ["README.md"]))


class IntegrationTests(ForgeTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.services()
        self.proj = self.make_project(self.s, "cli", "Target App")

    def plan(self, ids=("forge.forms-validation",), proj=None):
        return self.s.plan_add(proj or self.proj, {i: "*" for i in ids})

    def approved(self, **kw):
        p = self.plan(**kw)
        self.s.approve_plan(p["plan_id"], "tester")
        return p

    def test_plan_is_accurate_and_mutates_nothing(self):  # AT-008
        before = snapshot_tree(self.proj)
        p = self.plan()
        self.assertEqual(snapshot_tree(self.proj), before)
        self.assertEqual({(c["action"], c["path"]) for c in p["changes"]},
                         {("create", "src/target_app/forms.py"), ("create", "tests/test_forms.py"),
                          ("create", ".forge/components.toml")})
        self.assertEqual(p["conflicts"], [])

    def test_apply_requires_approval(self):
        p = self.plan()
        with self.assertRaises(SecurityBlock):
            self.s.apply_plan(p["plan_id"])
        self.assertFalse((self.proj / "src/target_app/forms.py").exists())

    def test_cannot_approve_conflicted_plan(self):
        (self.proj / "src/target_app/forms.py").write_text("# mine\n")
        p = self.plan()
        self.assertEqual(p["conflicts"][0]["code"], "would-overwrite")
        with self.assertRaises(ConflictFailure):
            self.s.approve_plan(p["plan_id"], "tester")

    def test_apply_verifies_and_registers(self):
        p = self.approved()
        r = self.s.apply_plan(p["plan_id"])
        self.assertEqual((r["status"], r["ok"], r["exit_code"]), ("applied", True, 0))
        self.assertTrue(r["verification"]["complete"])
        self.assertIn("forge.forms-validation", [c["id"] for c in self.s.analyze_project(self.proj)["installed_components"]])

    def test_fault_injection_rolls_back_and_preserves_state(self):  # AT-009
        before = snapshot_tree(self.proj)
        p = self.approved()

        def boom(path, i):
            if i == 1:
                raise OSError("disk full (injected)")
        rep = self.s.integration.apply(p["plan_id"], fault=boom)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "rolled_back")
        self.assertEqual(snapshot_tree(self.proj), before)

    def test_recovery_preserves_user_edits_and_reports_remaining(self):
        p = self.approved()
        self.s.apply_plan(p["plan_id"])
        (self.proj / "src/target_app/forms.py").write_text("# user rewrote this\n")
        rec = self.s.recover_plan(p["plan_id"])
        self.assertEqual(rec["status"], "partially_recovered")
        self.assertEqual(rec["preserved_user_changes"], ["src/target_app/forms.py"])
        self.assertEqual((self.proj / "src/target_app/forms.py").read_text(), "# user rewrote this\n")
        self.assertFalse((self.proj / "tests/test_forms.py").exists())

    def test_failed_verification_is_explicit_and_recoverable(self):
        self.custom_component("acme.bad", files={"tests/test_bad.py": "import unittest\nclass T(unittest.TestCase):\n"
                                                 "    def test_x(self):\n        self.fail('nope')\n"})
        s = self.services()
        p = s.plan_add(self.proj, {"acme.bad": "*"})
        s.approve_plan(p["plan_id"], "t")
        r = s.apply_plan(p["plan_id"])
        self.assertEqual((r["status"], r["ok"], r["exit_code"]), ("applied_verification_failed", False, 6))
        self.assertEqual(s.recover_plan(p["plan_id"])["status"], "rolled_back")
        self.assertFalse((self.proj / "tests/test_bad.py").exists())

    def test_auto_recover_on_failed_verification(self):
        self.custom_component("acme.bad", files={"tests/test_bad.py": "import unittest\nclass T(unittest.TestCase):\n"
                                                 "    def test_x(self):\n        self.fail('nope')\n"})
        s = self.services()
        p = s.plan_add(self.proj, {"acme.bad": "*"})
        s.approve_plan(p["plan_id"], "t")
        r = s.apply_plan(p["plan_id"], auto_recover=True)
        self.assertEqual((r["status"], r["exit_code"]), ("rolled_back", 6))

    def test_drift_after_planning_blocks_apply(self):
        p = self.approved()
        (self.proj / ".forge").mkdir()
        (self.proj / ".forge" / "components.toml").write_text("schema_version = 1\n# edited\n")
        with self.assertRaises(ConflictFailure):
            self.s.apply_plan(p["plan_id"])

    def test_tampered_plan_is_rejected(self):
        import json
        p = self.approved()
        f = self.s.settings.plans_dir / f"{p['plan_id']}.json"
        d = json.loads(f.read_text())
        d["changes"][0]["path"] = "src/target_app/__init__.py"
        f.write_text(json.dumps(d))
        with self.assertRaises(SecurityBlock):
            self.s.apply_plan(p["plan_id"])

    def test_dirty_git_overlap_is_a_conflict(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        self.git_init(self.proj)
        (self.proj / ".forge").mkdir()
        (self.proj / ".forge" / "components.toml").write_text("schema_version = 1\n")
        p = self.plan()
        self.assertIn("dirty-overlap", {c["code"] for c in p["conflicts"]})

    def test_remove_flow_and_protection_of_edits(self):
        p = self.approved()
        self.s.apply_plan(p["plan_id"])
        (self.proj / "tests/test_forms.py").write_text("# edited\n")
        rp = self.s.plan_remove(self.proj, ["forge.forms-validation"])
        self.assertEqual(rp["conflicts"][0]["code"], "modified-since-install")
        (self.proj / "tests/test_forms.py").write_bytes(  # bytes: write_text would convert to CRLF on Windows
            (self.s.registry.get("forge.forms-validation").files_dir / "tests/test_forms.py").read_text()
            .replace("{{package}}", "target_app").encode("utf-8"))
        rp = self.s.plan_remove(self.proj, ["forge.forms-validation"])
        self.assertEqual(rp["conflicts"], [])
        self.s.approve_plan(rp["plan_id"], "t")
        self.assertEqual(self.s.apply_plan(rp["plan_id"])["status"], "applied")
        self.assertFalse((self.proj / "src/target_app/forms.py").exists())
        self.assertEqual(self.s.analyze_project(self.proj)["installed_components"], [])

    def test_remove_blocked_by_dependents(self):
        proj = self.make_project(self.s, "desktop", where=self.tmp / "d", components=["forge.advanced-table"])
        rp = self.s.plan_remove(proj, ["forge.themes"])
        self.assertEqual(rp["conflicts"][0]["code"], "has-dependents")

    def test_level4_project_is_read_only(self):
        l4 = self.tmp / "l4"
        l4.mkdir()
        (l4 / "a.txt").write_text("x")
        with self.assertRaises(ConflictFailure):
            self.s.plan_add(l4, {"forge.forms-validation": "*"})

    def test_third_party_project_gets_files_but_manual_dependencies(self):
        self.custom_component("acme.rich", python_packages=("rich>=13",))
        s = self.services()
        root = self.tmp / "legacy"
        (root / "legacy").mkdir(parents=True)
        (root / "legacy" / "__init__.py").write_text("")
        (root / "pyproject.toml").write_text('[project]\nname="legacy"\nversion="1"\n')
        before_pp = (root / "pyproject.toml").read_text()
        p = s.plan_add(root, {"acme.rich": "*"})
        self.assertEqual(p["level"], 3)
        self.assertIn(("create", "legacy/rich.py"), {(c["action"], c["path"]) for c in p["changes"]})
        self.assertEqual([d["mode"] for d in p["dependency_changes"]], ["manual"])
        s.approve_plan(p["plan_id"], "t")
        r = s.apply_plan(p["plan_id"])
        self.assertEqual(r["status"], "applied")
        self.assertEqual((root / "pyproject.toml").read_text(), before_pp)  # never edited automatically

    def test_apply_does_not_follow_planted_predictable_temp_symlink(self):
        outside = self.tmp / "outside.txt"
        outside.write_text("must remain untouched", encoding="utf-8")
        target = self.proj / "src" / "target_app" / "forms.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        planted = target.with_name(target.name + ".forge-tmp")
        try:
            planted.symlink_to(outside)
        except OSError:
            self.skipTest("file symlinks unavailable")
        p = self.s.plan_add(self.proj, {"forge.forms-validation": "*"})
        self.s.approve_plan(p["plan_id"], "tester")
        result = self.s.apply_plan(p["plan_id"], verify=False)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(outside.read_text(encoding="utf-8"), "must remain untouched")
        self.assertTrue(planted.is_symlink())
        self.assertTrue(target.is_file())

    def test_apply_detects_file_changed_after_preflight_before_write(self):
        p = self.approved()
        victim = self.proj / "src" / "target_app" / "forms.py"

        def edit_before_write(path, index):
            if index == 0:
                victim.parent.mkdir(parents=True, exist_ok=True)
                victim.write_text("# user change\n", encoding="utf-8")

        result = self.s.integration.apply(p["plan_id"], verify=False, fault=edit_before_write)
        self.assertFalse(result["ok"])
        self.assertIn("changed while the plan was being applied", result["error"])
        self.assertEqual(victim.read_text(encoding="utf-8"), "# user change\n")

    def test_path_traversal_component_is_blocked(self):
        v = self.custom_component("acme.slip")
        t = (v / "component.toml").read_text().replace('dest = "src/{{package}}/slip.py"', 'dest = "src/{{package}}/../../../escape.py"')
        (v / "component.toml").write_text(t)
        s = self.services()
        self.assertEqual(s.validate_catalog()["ok"], False)  # manifest validation rejects '..'

    def test_symlink_escape_is_blocked(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        link = self.proj / "scripts"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.custom_component("acme.sneaky", files={"scripts/x.py": "x=1\n"})
        with self.assertRaises(SecurityBlock):
            self.services().plan_add(self.proj, {"acme.sneaky": "*"})
        self.assertFalse((outside / "x.py").exists())


if __name__ == "__main__":
    unittest.main()
