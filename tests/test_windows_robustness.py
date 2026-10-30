"""Regression tests for problems found by running the suite on Windows."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from app_forge.domain.models import Patch
from app_forge.locks import pid_alive
from app_forge.patching import apply_patch, remove_patch
from tests.helpers import ForgeTestCase

ROOT = Path(__file__).resolve().parent.parent


def crlf(path: Path) -> None:
    """What a Windows editor does when it saves: convert LF line endings to CRLF."""
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


class PidLivenessTests(unittest.TestCase):
    def test_own_pid_alive_and_exited_process_dead_even_while_we_hold_its_handle(self):
        self.assertTrue(pid_alive(os.getpid()))
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        # `proc` is still referenced: on Windows its handle is open and OpenProcess alone would say "alive".
        self.assertFalse(pid_alive(proc.pid))
        self.assertFalse(pid_alive(0))
        self.assertFalse(pid_alive(-5))


class LineEndingToleranceTests(unittest.TestCase):
    SRC = "def f():\n    # forge:anchor routers\n    return 1\n"
    P = Patch("reg", "a.py", "insert", "routers", "after", "#", "x = 1\n")

    def test_block_survives_whole_file_crlf_conversion(self):
        r = apply_patch(self.SRC, self.P, "acme.c", "pkg")
        converted = r.new_text.replace("\n", "\r\n")
        self.assertEqual(apply_patch(converted, self.P, "acme.c", "pkg").status, "unchanged")
        self.assertEqual(remove_patch(converted, "acme.c", "reg", r.sha256), self.SRC.replace("\n", "\r\n"))

    def test_a_real_edit_is_still_detected_in_a_converted_file(self):
        from app_forge.patching import PatchConflict
        r = apply_patch(self.SRC, self.P, "acme.c", "pkg")
        edited = r.new_text.replace("x = 1", "x = 2").replace("\n", "\r\n")
        with self.assertRaises(PatchConflict) as cm:
            remove_patch(edited, "acme.c", "reg", r.sha256)
        self.assertEqual(cm.exception.code, "patch-modified")


class EditorConversionIntegrationTests(ForgeTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.services()

    def install(self, proj, cid):
        p = self.s.plan_add(proj, {cid: "*"})
        self.s.approve_plan(p["plan_id"], "t")
        self.assertEqual(self.s.apply_plan(p["plan_id"])["status"], "applied")

    def test_untouched_files_converted_to_crlf_are_not_reported_as_edited(self):
        proj = self.make_project(self.s, "cli", "Crlf App")
        self.install(proj, "forge.forms-validation")
        crlf(proj / "tests/test_forms.py")
        crlf(proj / "src/crlf_app/forms.py")
        rp = self.s.plan_remove(proj, ["forge.forms-validation"])
        self.assertEqual(rp["conflicts"], [])
        self.s.approve_plan(rp["plan_id"], "t")
        self.assertEqual(self.s.apply_plan(rp["plan_id"])["status"], "applied")
        self.assertFalse((proj / "src/crlf_app/forms.py").exists())

    def test_crlf_conversion_plus_a_real_edit_is_still_a_conflict(self):
        proj = self.make_project(self.s, "cli", "Crlf Edit")
        self.install(proj, "forge.forms-validation")
        f = proj / "src/crlf_edit/forms.py"
        f.write_bytes(f.read_bytes() + b"# mine\r\n")
        self.assertEqual([c["code"] for c in self.s.plan_remove(proj, ["forge.forms-validation"])["conflicts"]],
                         ["modified-since-install"])

    def test_patched_file_converted_to_crlf_can_still_be_unpatched(self):
        proj = self.make_project(self.s, "web", "Crlf Web")
        self.install(proj, "forge.health-endpoint")
        crlf(proj / "src/crlf_web/api.py")
        rp = self.s.plan_remove(proj, ["forge.health-endpoint"])
        self.assertEqual(rp["conflicts"], [])
        self.s.approve_plan(rp["plan_id"], "t")
        self.assertEqual(self.s.apply_plan(rp["plan_id"])["status"], "applied")
        self.assertNotIn("healthz", (proj / "src/crlf_web/api.py").read_text())

    def test_upgrade_works_on_files_an_editor_converted_to_crlf(self):
        self.custom_component("acme.lib", "1.0.0", files={"src/lib_mod.py": "V = 1\n"})
        self.custom_component("acme.lib", "1.1.0", files={"src/lib_mod.py": "V = 2\n"})
        s = self.services()
        proj = self.make_project(s, "cli", "Crlf Up")
        p = s.plan_add(proj, {"acme.lib": "==1.0.0"})
        s.approve_plan(p["plan_id"], "t")
        s.apply_plan(p["plan_id"])
        crlf(proj / "src/crlf_up/lib_mod.py")
        up = s.plan_upgrade(proj, ["acme.lib"])
        self.assertEqual(up["conflicts"], [])
        s.approve_plan(up["plan_id"], "t")
        self.assertEqual(s.apply_plan(up["plan_id"])["status"], "applied")


class CheckoutGuardTests(unittest.TestCase):
    def test_tests_refuse_to_run_against_a_different_copy_of_app_forge(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "app_forge"
            fake.mkdir()
            (fake / "__init__.py").write_text("__version__ = 'old'\n")
            env = {**os.environ, "PYTHONPATH": td}
            r = subprocess.run([sys.executable, "-c", "import tests"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pip install -e .", r.stderr)


if __name__ == "__main__":
    unittest.main()
