import os
import stat
import subprocess
import sys
import unittest
from unittest import mock

from app_forge.domain.errors import ConflictFailure
from app_forge.locks import lock_path, project_lock
from tests.helpers import ForgeTestCase


class ManifestDigestTests(ForgeTestCase):  # G-02
    def reasons(self, s):
        return [q["error"] for q in s.validate_catalog()["quarantined"]]

    def test_editing_any_manifest_field_after_sealing_is_detected(self):
        for old, new in (('permissions = ["filesystem.project"]', 'permissions = ["filesystem.project", "network"]'),
                         ('summary = "test component"', 'summary = "totally different"'),
                         ('license = "MIT"', 'license = "GPL-3.0"')):
            v = self.custom_component("acme.sealed")
            m = v / "component.toml"
            self.assertTrue(self.services(builtin=False).validate_catalog()["ok"])
            text = m.read_text()
            self.assertIn(old, text)
            m.write_text(text.replace(old, new))
            reasons = self.reasons(self.services(builtin=False))
            self.assertTrue(any("digest" in r for r in reasons), (old, reasons))
            import shutil
            shutil.rmtree(self.home / "catalog")

    def test_resealing_accepts_a_legitimate_manifest_change(self):
        from app_forge.catalog.registry import seal_component
        v = self.custom_component("acme.sealed")
        (v / "component.toml").write_text((v / "component.toml").read_text().replace("test component", "edited"))
        seal_component(v)
        self.assertTrue(self.services(builtin=False).validate_catalog()["ok"])

    def test_builtin_components_are_sealed_over_their_manifests(self):
        self.assertTrue(self.services().validate_catalog()["ok"])


class ProjectLockTests(ForgeTestCase):  # G-05
    def setUp(self):
        super().setUp()
        self.s = self.services()
        self.proj = self.make_project(self.s, "cli", "Lock App")

    def approved_plan(self):
        p = self.s.plan_add(self.proj, {"forge.forms-validation": "*"})
        self.s.approve_plan(p["plan_id"], "t")
        return p["plan_id"]

    def test_second_operation_is_refused_while_locked(self):
        pid = self.approved_plan()
        with project_lock(self.s.settings.locks_dir, self.proj, "someone else"):
            with self.assertRaises(ConflictFailure) as cm:
                self.s.apply_plan(pid)
            self.assertIn("locked", cm.exception.message)
            with self.assertRaises(ConflictFailure):
                self.s.recover_plan(pid)
            self.assertTrue(self.s.lock_status(self.proj)["locked"])
        self.assertEqual(self.s.apply_plan(pid)["status"], "applied")  # free again
        self.assertFalse(self.s.lock_status(self.proj)["locked"])

    def test_lock_released_after_failure(self):
        pid = self.approved_plan()
        rep = self.s.integration.apply(pid, fault=lambda path, i: (_ for _ in ()).throw(OSError("boom")))
        self.assertFalse(rep["ok"])
        self.assertFalse(self.s.lock_status(self.proj)["locked"])

    def test_stale_lock_from_dead_process_is_taken_over(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        path = lock_path(self.s.settings.locks_dir, self.proj)
        path.parent.mkdir(parents=True, exist_ok=True)
        import json, socket
        path.write_text(json.dumps({"pid": proc.pid, "host": socket.gethostname(), "operation": "dead", "since": "x"}))
        pid = self.approved_plan()
        self.assertEqual(self.s.apply_plan(pid)["status"], "applied")

    def test_lock_from_another_host_is_never_assumed_stale(self):
        path = lock_path(self.s.settings.locks_dir, self.proj)
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        path.write_text(json.dumps({"pid": 1, "host": "some-other-machine", "operation": "x", "since": "x"}))
        with self.assertRaises(ConflictFailure):
            with project_lock(self.s.settings.locks_dir, self.proj, "me"):
                pass
        self.assertTrue(self.s.unlock_project(self.proj)["unlocked"])
        with project_lock(self.s.settings.locks_dir, self.proj, "me"):
            pass

    def test_unlock_requires_confirmation_on_cli(self):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from app_forge.cli.main import main
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["--home", str(self.home), "--non-interactive", "project", "unlock", str(self.proj)]), 2)
            self.assertEqual(main(["--home", str(self.home), "--non-interactive", "project", "unlock", str(self.proj),
                                   "--yes"]), 0)


class VerificationEnvironmentTests(ForgeTestCase):  # G-03
    def project_with_test(self, body, name="Env App"):
        proj = self.make_project(self.services(), "cli", name)
        (proj / "tests" / "test_core.py").write_text("import os\nimport unittest\n\nclass T(unittest.TestCase):\n"
                                                     "    def test_it(self):\n" + "".join(f"        {l}\n" for l in body.splitlines()))
        return proj

    def test_secrets_in_the_environment_are_not_visible_to_project_tests(self):
        proj = self.project_with_test("self.assertIsNone(os.environ.get('FORGE_TEST_SECRET'))\n"
                                      "self.assertIsNone(os.environ.get('AWS_SECRET_ACCESS_KEY'))")
        with mock.patch.dict(os.environ, {"FORGE_TEST_SECRET": "s3cret", "AWS_SECRET_ACCESS_KEY": "k"}):
            self.assertEqual(self.services().verify_project(proj)["overall"], "passed")

    def test_explicit_passthrough_is_honoured(self):
        proj = self.project_with_test("self.assertEqual(os.environ.get('FORGE_TEST_SECRET'), 'ok-to-share')")
        (proj / "pyproject.toml").write_text((proj / "pyproject.toml").read_text() +
                                             '\n[tool.forge.verify]\nenv_passthrough = ["FORGE_TEST_SECRET"]\n')
        with mock.patch.dict(os.environ, {"FORGE_TEST_SECRET": "ok-to-share"}):
            self.assertEqual(self.services().verify_project(proj)["overall"], "passed")

    def test_missing_third_party_dependency_is_blocked_not_failed(self):
        proj = self.make_project(self.services(), "cli", "Blocked App")
        (proj / "tests" / "test_core.py").write_text("import definitely_not_installed_pkg\n")
        s = self.services()
        r = s.verify_project(proj)
        self.assertEqual(r["overall"], "incomplete")  # syntax passed, tests could not run: never "passed"
        self.assertFalse(r["complete"])
        self.assertIn("tests", r["not_run"])
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from app_forge.cli.main import main
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["--home", str(self.home), "test", "run", str(proj)]), 7)
        self.assertIn("definitely_not_installed_pkg", r["evidence"][-1]["detail"] + r["evidence"][-2]["detail"])
        self.assertEqual(s.compliance_report(None, proj)["summary"]["Blocked"], 1)

    def test_missing_own_module_is_a_real_failure(self):
        proj = self.make_project(self.services(), "cli", "Own App")
        (proj / "tests" / "test_core.py").write_text("from own_app import does_not_exist\n")
        self.assertEqual(self.services().verify_project(proj)["overall"], "failed")

    @unittest.skipIf(os.name == "nt", "uses a POSIX shell wrapper")
    def test_project_virtualenv_interpreter_is_used(self):
        proj = self.make_project(self.services(), "cli", "Venv App")
        marker = self.tmp / "venv-used"
        py = proj / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text(f'#!/bin/sh\necho used >> "{marker}"\nexec "{sys.executable}" "$@"\n')
        py.chmod(py.stat().st_mode | stat.S_IEXEC)
        r = self.services().verify_project(proj, checks=("tests",))
        self.assertTrue(marker.exists())
        self.assertEqual(r["overall"], "passed")
        self.assertIn("virtual environment", r["evidence"][-1]["detail"])


if __name__ == "__main__":
    unittest.main()
