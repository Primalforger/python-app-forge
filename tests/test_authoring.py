import json
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from app_forge.cli.main import main
from tests.helpers import ForgeTestCase


class AuthoringTests(ForgeTestCase):
    def cli(self, *argv, home=None):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(home or self.home), "--non-interactive", *argv])
        return code, out.getvalue(), err.getvalue()

    def scaffold(self, cid="acme.widget", **extra):
        code, out, err = self.cli("--json", "component", "new", cid, "--out", str(self.tmp / "src"), *extra.get("args", []))
        self.assertEqual(code, 0, err)
        return self.tmp / "src" / cid / "1.0.0"

    def test_cli_only_workflow_scaffold_validate_add_install_verify(self):
        v = self.scaffold(args=["--archetype", "cli,service", "--category", "tooling", "--summary", "A widget"])
        self.assertEqual(self.cli("component", "validate", str(v))[0], 0)
        code, out, _ = self.cli("--json", "catalog", "add", str(v))
        self.assertEqual((code, json.loads(out)["result"]["added"]), (0, "acme.widget@1.0.0"))
        self.assertEqual(self.cli("component", "verify", "acme.widget")[0], 0)
        proj = self.tmp / "proj"
        self.assertEqual(self.cli("init", "--archetype", "cli", "--name", "Uses Widget", "--out", str(proj),
                                  "--component", "acme.widget")[0], 0)
        self.assertEqual(self.cli("test", "run", str(proj))[0], 0)
        self.assertEqual(self.cli("catalog", "add", str(v))[0], 3)  # versions are immutable

    def test_interface_contract_tests_are_validated_and_reported(self):
        v = self.scaffold()
        manifest = (v / "component.toml").read_text().replace(
            "provides = []", 'provides = ["ui.widget@1.0"]'
        ).replace(
            'tests = ["tests/test_widget.py"]',
            'tests = ["tests/test_widget.py", "tests/test_widget.py"]'
        )
        manifest += '\n[[interfaces.contract_tests]]\ninterface = "ui.widget@1.0"\ntests = ["tests/test_widget.py"]\n'
        (v / "component.toml").write_text(manifest)
        self.assertEqual(self.cli("component", "seal", str(v))[0], 0)
        self.assertEqual(self.cli("component", "validate", str(v))[0], 0)
        self.assertEqual(self.cli("catalog", "add", str(v))[0], 0)
        code, out, err = self.cli("--json", "component", "verify", "acme.widget")
        self.assertEqual(code, 0, err)
        contract = json.loads(out)["result"]["interface_contracts"][0]
        self.assertEqual(contract["interface"], "ui.widget@1.0")
        self.assertEqual(contract["status"], "passed")

    def test_interface_contract_tests_must_reference_provided_interface(self):
        v = self.scaffold()
        manifest = (v / "component.toml").read_text()
        manifest += '\n[[interfaces.contract_tests]]\ninterface = "ui.missing@1.0"\ntests = ["tests/test_widget.py"]\n'
        (v / "component.toml").write_text(manifest)
        self.cli("component", "seal", str(v))
        code, out, _ = self.cli("--json", "component", "validate", str(v))
        self.assertEqual(code, 2)
        self.assertIn("must exactly match", " ".join(json.loads(out)["result"]["problems"]))

    def test_validate_catches_the_common_mistakes(self):
        v = self.scaffold()
        src = v / "files" / "src" / "widget.py"
        src.write_text("def broken(:\n")
        code, out, _ = self.cli("--json", "component", "validate", str(v))
        problems = " ".join(json.loads(out)["result"]["problems"])
        self.assertEqual(code, 2)
        self.assertIn("not valid Python", problems)
        self.assertIn("digest", problems)  # changed after sealing
        self.assertEqual(self.cli("component", "seal", str(v))[0], 0)
        self.assertEqual(self.cli("component", "validate", str(v))[0], 2)  # still the syntax error
        src.write_text("def ok():\n    return 1\n")
        manifest = (v / "component.toml").read_text()
        (v / "component.toml").write_text(manifest.replace('tests = ["tests/test_widget.py"]', 'tests = ["tests/ghost.py"]'))
        self.cli("component", "seal", str(v))
        code, out, _ = self.cli("--json", "component", "validate", str(v))
        self.assertIn("ghost.py", " ".join(json.loads(out)["result"]["problems"]))

    def test_validate_warns_about_secrets_and_missing_tests(self):
        v = self.scaffold()
        (v / "files" / "src" / "widget.py").write_text('API_KEY = "api_key=abcd1234abcd1234"\n')
        text = (v / "component.toml").read_text().replace('tests = ["tests/test_widget.py"]', "tests = []")
        (v / "component.toml").write_text(text)
        self.cli("component", "seal", str(v))
        r = json.loads(self.cli("--json", "component", "validate", str(v))[1])["result"]
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["warnings"]), 2)

    def test_invalid_patch_content_is_reported(self):
        v = self.scaffold()
        with open(v / "component.toml", "a") as fh:
            fh.write('\n[[integration.patches]]\nid = "bad-table"\nfile = "pyproject.toml"\nkind = "toml-table"\n'
                     "content = '''\n[unterminated\n'''\n")
        self.cli("component", "seal", str(v))
        r = json.loads(self.cli("--json", "component", "validate", str(v))[1])["result"]
        self.assertFalse(r["ok"])
        self.assertIn("not valid TOML", " ".join(r["problems"]))

    def test_pack_is_reproducible_and_installable_elsewhere(self):
        v = self.scaffold()
        z1, z2 = self.tmp / "a.zip", self.tmp / "b.zip"
        self.assertEqual(self.cli("component", "pack", str(v), "--out", str(z1))[0], 0)
        self.assertEqual(self.cli("component", "pack", str(v), "--out", str(z2))[0], 0)
        self.assertEqual(z1.read_bytes(), z2.read_bytes())
        other_home = self.tmp / "other-home"
        code, out, _ = self.cli("--json", "catalog", "add", str(z1), home=other_home)
        self.assertEqual(code, 0)
        self.assertEqual(self.cli("component", "verify", "acme.widget", home=other_home)[0], 0)

    def test_pack_refuses_invalid_components(self):
        v = self.scaffold()
        (v / "files" / "src" / "widget.py").write_text("x = 2\n")  # unsealed change
        self.assertEqual(self.cli("component", "pack", str(v), "--out", str(self.tmp / "x.zip"))[0], 2)

    def test_hostile_archives_are_rejected(self):
        for name, members, code in (
                ("slip.zip", {"acme.evil/1.0.0/../../escape.txt": b"x"}, 4),
                ("abs.zip", {"/etc/evil": b"x"}, 4),
                ("two.zip", {"a.b/1.0.0/component.toml": b"x", "c.d/1.0.0/component.toml": b"x"}, 2)):
            z = self.tmp / name
            with zipfile.ZipFile(z, "w") as zf:
                for k, v in members.items():
                    zf.writestr(k, v)
            self.assertEqual(self.cli("catalog", "add", str(z))[0], code, name)
        self.assertFalse((self.tmp / "escape.txt").exists())

    def test_tampered_catalog_copy_is_not_addable(self):
        v = self.scaffold()
        (v / "files" / "src" / "widget.py").write_text("x = 3\n")
        self.assertEqual(self.cli("catalog", "add", str(v))[0], 2)

    def test_bad_ids_and_names_rejected(self):
        for bad in ("Bad Name", "x"):
            self.assertEqual(self.cli("component", "new", bad, "--out", str(self.tmp / "o"))[0], 2)
        self.assertEqual(self.cli("component", "new", "acme.ok", "--out", str(self.tmp / "o"), "--archetype", "mobile")[0], 2)
