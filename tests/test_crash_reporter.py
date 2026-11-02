"""Tests for the local-only desktop crash reporter."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from app_forge.crash_reporter import CrashReporter


class CrashReporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reports = self.root / "crashes"

    def test_writes_redacted_report_without_locals(self):
        reporter = CrashReporter(self.reports)
        password = "super-secret-value"
        try:
            raise RuntimeError(f"password={password} token=ghp_" + "A" * 30)
        except RuntimeError as exc:
            path = reporter.capture_exception(exc, context="verification")
        report = json.loads(path.read_text(encoding="utf-8"))
        rendered = json.dumps(report)
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["context"], "verification")
        self.assertFalse(report["network_upload"])
        self.assertNotIn(password, rendered)
        self.assertNotIn("ghp_" + "A" * 30, rendered)
        self.assertNotIn("password=", rendered)
        self.assertNotIn("super-secret-value", rendered)

    def test_report_permissions_are_private_on_posix(self):
        path = CrashReporter(self.reports).capture_exception(ValueError("safe"))
        if os.name == "posix":
            self.assertEqual(self.reports.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_prunes_oldest_reports_to_configured_bound(self):
        reporter = CrashReporter(self.reports, max_reports=2)
        paths = [reporter.capture_exception(ValueError(str(i))) for i in range(3)]
        remaining = sorted(self.reports.glob("crash-*.json"))
        self.assertEqual(len(remaining), 2)
        self.assertNotIn(paths[0], remaining)

    def test_rejects_invalid_report_limit(self):
        for value in (0, -1, 501, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CrashReporter(self.reports, max_reports=value)

    def test_does_not_capture_exception_locals(self):
        reporter = CrashReporter(self.reports)
        sensitive_local = "do-not-serialize-local"
        try:
            raise RuntimeError("failure")
        except RuntimeError as exc:
            path = reporter.capture_exception(exc)
        self.assertNotIn(sensitive_local, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
