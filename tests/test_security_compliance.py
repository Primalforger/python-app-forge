import json
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app_forge.compliance import build_report, evaluate, load_requirements, validate_requirements
from app_forge.domain.errors import SecurityBlock, ValidationFailure
from app_forge.domain.models import Requirement
from app_forge.extensions import ExtensionHost
from app_forge.security import redact, run_command, safe_join
from tests.helpers import ForgeTestCase


class SecurityTests(ForgeTestCase):
    def test_safe_join(self):
        root = self.tmp
        self.assertEqual(safe_join(root, "a/b.py"), root / "a" / "b.py")
        for bad in ("../x", "/etc/passwd", "a/../../x", "C:/x", "", " a"):
            with self.assertRaises(SecurityBlock, msg=bad):
                safe_join(root, bad)

    def test_redaction(self):
        out = redact("password=hunter2 token: abc123 ghp_" + "a" * 30)
        self.assertNotIn("hunter2", out)
        self.assertNotIn("abc123", out)
        self.assertNotIn("ghp_", out)

    def test_no_shell_execution(self):
        with self.assertRaises(SecurityBlock):
            run_command("echo hi; rm -rf /", cwd=self.tmp)  # type: ignore[arg-type]

    def test_untrusted_extension_never_executes(self):  # AT-012
        loaded = []

        class EP:
            name, value = "acme-ext", "acme.ext:Plugin"

            def load(self):
                loaded.append(1)
                return object()

        s = self.services()
        host = ExtensionHost(s.store, lambda: [EP()])
        self.assertEqual(host.discover()[0]["trust"], "untrusted")
        self.assertEqual(loaded, [])  # discovery does not import
        for action in (host.enable, host.activate):
            with self.assertRaises(SecurityBlock):
                action("acme-ext")
        self.assertEqual(loaded, [])
        host.trust("acme-ext")
        with self.assertRaises(SecurityBlock):  # trusted but not yet enabled
            host.activate("acme-ext")
        host.enable("acme-ext")
        from unittest.mock import patch
        worker_response = b'{"version":1,"ok":true,"result":null}\n'
        with patch("app_forge.extensions.subprocess.run",
                   return_value=SimpleNamespace(stdout=worker_response, returncode=0)) as run:
            host.activate("acme-ext")
        run.assert_called_once()
        self.assertEqual(loaded, [])  # activation is delegated to the child worker
        host.trust("acme-ext", "untrusted")  # revoking trust also disables
        with self.assertRaises(SecurityBlock):
            host.activate("acme-ext")

    def test_history_does_not_leak_secrets_in_logs(self):
        from app_forge.observability import JsonFormatter
        import logging
        rec = logging.LogRecord("x", logging.INFO, "f", 1, "api_key=SECRET123", None, None)
        self.assertNotIn("SECRET123", JsonFormatter().format(rec))


class ComplianceTests(ForgeTestCase):
    def ev(self, check_id, status="passed"):
        return {"run_id": "r", "subject": "s", "check_id": check_id, "status": status}

    def test_status_semantics(self):
        reqs = [
            Requirement("R1", "t", acceptance="a", verified_by=["tests/a.py"], implemented=True),
            Requirement("R2", "t", acceptance="a", verified_by=["tests/b.py"], implemented=True),
            Requirement("R3", "t", acceptance="a", verified_by=["tests/c.py"], implemented=True),
            Requirement("R4", "t", acceptance="a", verified_by=["tests/d.py"]),
            Requirement("R5", "t", acceptance="a", implemented=True),
            Requirement("R6", "t", acceptance="a"),
            Requirement("R7", "t", acceptance="a", not_applicable="desktop only"),
            Requirement("R8", "t", acceptance="a", verified_by=["tests/z.py"],
                        exception={"approver": "me", "rationale": "waived", "expires": "2999-01-01"}),
            Requirement("R9", "t", acceptance="a", verified_by=["tests/z.py"],
                        exception={"approver": "me", "rationale": "waived", "expires": "2000-01-01"}),
            Requirement("R10", "t", acceptance="a", verified_by=["tests/a.py", "tests/missing.py"], implemented=True),
        ]
        evidence = [self.ev("tests/a.py::T::t1"), self.ev("tests/b.py::T::t1"), self.ev("tests/b.py::T::t2", "failed"),
                    self.ev("tests/c.py::T::t1", "not_run")]
        st = {r["id"]: r["status"] for r in evaluate(reqs, evidence, today=date(2026, 10, 28))}
        self.assertEqual(st, {"R1": "Verified", "R2": "Failed", "R3": "Blocked", "R4": "Planned", "R5": "Implemented",
                              "R6": "Not assessed", "R7": "Not applicable", "R8": "Exception approved",
                              "R9": "Planned", "R10": "Implemented"})

    def test_existing_file_is_not_evidence(self):
        reqs = [Requirement("R1", "t", acceptance="a", verified_by=["tests/test_core.py"], implemented=True)]
        self.assertEqual(evaluate(reqs, [])[0]["status"], "Implemented")  # never "Verified" without evidence

    def test_report_has_gaps_and_no_certification_claim(self):
        rep = build_report([Requirement("R1", "t", acceptance="a")], [], subject="x", run_id=None)
        self.assertEqual(rep["gaps"], ["R1"])
        self.assertIn("not a certification", rep["disclaimer"])

    def test_requirement_validation(self):
        probs = validate_requirements([Requirement("R1", "t"), Requirement("R1", "t", priority="P9", parent="NOPE")])
        self.assertGreaterEqual(len(probs), 4)

    def test_generated_project_trace_end_to_end_and_evidence_export(self):  # AT-010
        s = self.services()
        proj = self.make_project(s, "cli")
        s.verify_project(proj)
        rep = s.compliance_report(None, proj)
        self.assertEqual(rep["summary"]["Verified"], 1)
        out = s.export_evidence(None, proj, self.tmp / "pkg")
        manifest = json.loads((self.tmp / "pkg" / "MANIFEST.sha256.json").read_text())
        from app_forge.security import sha256_text
        for name, digest in manifest.items():
            self.assertEqual(sha256_text((self.tmp / "pkg" / name).read_text()), digest)
        self.assertIn("compliance-report.md", out["files"])

    def test_missing_tool_is_not_run_not_passed(self):
        import shutil
        if shutil.which("ruff"):
            self.skipTest("ruff installed")
        s = self.services()
        r = s.verify_project(self.make_project(s), checks=("ruff",))
        self.assertEqual((r["overall"], r["not_run"]), ("not_run", ["ruff"]))

    def test_failing_tests_make_requirement_failed(self):
        s = self.services()
        proj = self.make_project(s)
        (proj / "tests" / "test_core.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('x')\n")
        self.assertEqual(s.verify_project(proj)["overall"], "failed")
        self.assertEqual(s.compliance_report(None, proj)["summary"]["Failed"], 1)

    def test_syntax_error_detected_without_execution(self):
        s = self.services()
        proj = self.make_project(s)
        (proj / "src" / "demo_app" / "broken.py").write_text("def (:\n")
        r = s.verify_project(proj, checks=("syntax",))
        self.assertEqual(r["overall"], "failed")


if __name__ == "__main__":
    unittest.main()
