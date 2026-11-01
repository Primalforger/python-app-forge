import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import app_forge
from app_forge.architecture import check_rules
from app_forge.cli.main import main
from tests.helpers import ForgeTestCase

PKG = Path(app_forge.__file__).resolve().parent


class CliTests(ForgeTestCase):
    def run_cli(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), "--non-interactive", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_json_envelope_and_exit_codes(self):
        code, out, _ = self.run_cli("--json", "component", "search", "--query", "forms")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])
        code, out, _ = self.run_cli("--json", "init", "--archetype", "cli", "--name", "1bad", "--out", str(self.tmp / "x"))
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])
        code, _, err = self.run_cli("component", "inspect", "nope.nothing")
        self.assertEqual(code, 2)
        self.assertIn("error [validation]", err)

    def test_positional_search_query_filters(self):
        code, out, _ = self.run_cli("--json", "component", "search", "pagination")
        self.assertEqual([r["id"] for r in json.loads(out)["result"]], ["forge.advanced-table"])

    def test_full_workflow_via_cli(self):
        proj = str(self.tmp / "p")
        self.assertEqual(self.run_cli("init", "--archetype", "service", "--name", "Cli Flow", "--out", proj)[0], 0)
        code, out, _ = self.run_cli("--json", "integrate", "plan", proj, "--component", "forge.config-profiles")
        self.assertEqual(code, 0)
        plan_id = json.loads(out)["result"]["plan_id"]
        code, _, err = self.run_cli("integrate", "apply", plan_id)
        self.assertEqual(code, 4)  # security block: not approved
        self.assertEqual(self.run_cli("integrate", "approve", plan_id, "--by", "ci")[0], 0)
        code, out, _ = self.run_cli("--json", "integrate", "apply", plan_id)
        self.assertEqual((code, json.loads(out)["result"]["status"]), (0, "applied"))
        self.assertEqual(self.run_cli("integrate", "recover", plan_id)[0], 0)
        code, _, _ = self.run_cli("test", "run", proj)
        self.assertEqual(code, 0)

    def test_conflict_exit_code_and_verification_exit_code(self):
        proj = self.tmp / "p"
        self.run_cli("init", "--archetype", "cli", "--name", "Conf", "--out", str(proj))
        (proj / "src/conf/forms.py").write_text("# mine\n")
        code, out, _ = self.run_cli("--json", "integrate", "plan", str(proj), "--component", "forge.forms-validation")
        self.assertEqual(code, 3)
        (proj / "tests/test_core.py").write_text("import unittest\nclass T(unittest.TestCase):\n"
                                                 "    def test_a(self):\n        self.fail('x')\n")
        self.assertEqual(self.run_cli("test", "run", str(proj))[0], 6)

    def test_confirmation_required_noninteractively(self):
        code, _, err = self.run_cli("plugin", "trust", "x")
        self.assertEqual(code, 2)
        self.assertIn("Confirmation required", err)

    def test_misc_commands(self):
        for argv in (["doctor"], ["catalog", "validate"], ["catalog", "list"], ["config", "show"], ["template", "list"],
                     ["history", "list"], ["gc"], ["architecture", "check-rules"], ["plugin", "list"],
                     ["dependency", "resolve", "forge.advanced-table", "--archetype", "desktop"],
                     ["dependency", "explain", "forge.advanced-table"]):
            self.assertEqual(self.run_cli(*argv)[0], 0, argv)
        self.assertEqual(self.run_cli("dependency", "resolve", "forge.advanced-table", "--archetype", "cli")[0], 3)

    def test_hash_chained_audit_cli(self):
        path = self.tmp / "audit.jsonl"
        code, out, _ = self.run_cli("--json", "audit", "append", str(path), "--actor", "test-user",
                                    "--event", '{"action":"created"}')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["result"]["appended"])
        code, out, _ = self.run_cli("--json", "audit", "verify", str(path))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["result"]["ok"])
        path.write_text(path.read_text(encoding="utf-8").replace("created", "tampered"),
                        encoding="utf-8")
        code, out, _ = self.run_cli("--json", "audit", "verify", str(path))
        self.assertEqual(code, 6)
        self.assertFalse(json.loads(out)["result"]["ok"])

    def test_operation_history_records_failures(self):
        self.run_cli("init", "--archetype", "cli", "--name", "1bad", "--out", str(self.tmp / "x"))
        code, out, _ = self.run_cli("--json", "history", "list")
        ops = json.loads(out)["result"]
        self.assertEqual((ops[0]["kind"], ops[0]["status"]), ("create_project", "failed"))



    def test_output_formats_yaml_and_table(self):
        code, out, _ = self.run_cli("--output", "yaml", "component", "search", "--query", "pagination")
        self.assertEqual(code, 0)
        import yaml
        rows = yaml.safe_load(out)
        self.assertEqual(rows[0]["id"], "forge.advanced-table")

        code, out, _ = self.run_cli("--output", "table", "component", "search", "--query", "pagination")
        self.assertEqual(code, 0)
        self.assertIn("forge.advanced-table", out)
        self.assertIn("id", out)

    def test_shell_completion_scripts(self):
        for shell, expected in (("bash", "complete -F"), ("zsh", "compdef"), ("fish", "complete -c")):
            code, out, _ = self.run_cli("completion", shell)
            self.assertEqual(code, 0)
            self.assertIn(expected, out)
            self.assertIn("component", out)

    def test_progress_is_consistent_and_stderr_only(self):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), "--progress", "always", "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("forge: running doctor", err.getvalue())
        self.assertIn("forge: completed", err.getvalue())
        self.assertNotIn("forge: running", out.getvalue())

class ArchitectureTests(unittest.TestCase):
    def test_platform_obeys_dependency_rules(self):  # Gate 1
        self.assertEqual(check_rules(PKG), [])

    def test_detects_violations(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "app_forge"
            for d in ("domain", "gui", "cli"):
                (pkg / d).mkdir(parents=True)
                (pkg / d / "__init__.py").write_text("")
            (pkg / "__init__.py").write_text("")
            (pkg / "domain" / "bad.py").write_text("import sqlite3\nfrom PySide6 import QtCore\n")
            (pkg / "gui" / "bad.py").write_text("from app_forge.cli import main\n")
            (pkg / "cli" / "bad.py").write_text("from app_forge.integration import IntegrationEngine\n")
            found = {(v["file"], v["rule"].split(" ")[0]) for v in check_rules(pkg)}
            self.assertIn(("app_forge/domain/bad.py", "Domain"), found)
            self.assertIn(("app_forge/gui/bad.py", "GUI"), found)
            self.assertIn(("app_forge/cli/bad.py", "Shells"), found)
            (pkg / "cli" / "bad.py").write_text("from app_forge.compliance import to_markdown\n")
            self.assertTrue([v for v in check_rules(pkg) if v["file"].endswith("cli/bad.py")])

    def test_gui_module_is_syntactically_valid(self):
        import py_compile
        py_compile.compile(str(PKG / "gui" / "app.py"), doraise=True)


if __name__ == "__main__":
    unittest.main()
