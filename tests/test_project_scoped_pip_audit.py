from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_forge.verification import VerificationEngine


class ProjectScopedPipAuditTests(unittest.TestCase):
    def _run(self, root: Path):
        rows = []
        with patch("app_forge.verification.shutil.which", return_value="/tools/pip-audit"), \
             patch("app_forge.verification.run_command",
                   return_value=SimpleNamespace(returncode=0, stdout="clean", stderr="")) as run:
            VerificationEngine()._tool(root, "pip-audit", lambda *row: rows.append(row), 30)
        return rows, run

    def test_pyproject_is_passed_as_the_audit_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
            rows, run = self._run(root)
        args = run.call_args.args[0]
        self.assertEqual(args, ["/tools/pip-audit", str(root)])
        self.assertEqual(rows[0][1], "passed")
        self.assertIn("pyproject.toml", rows[0][2])

    def test_pep751_lockfile_uses_locked_project_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
            (root / "pylock.toml").write_text("", encoding="utf-8")
            rows, run = self._run(root)
        self.assertEqual(run.call_args.args[0], ["/tools/pip-audit", "--locked", str(root)])
        self.assertIn("pylock.toml", rows[0][2])

    def test_requirements_files_are_audited_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("urllib3==1.26.18\n", encoding="utf-8")
            (root / "requirements-dev.txt").write_text("urllib3==2.2.0\n", encoding="utf-8")
            (root / "requirements").mkdir()
            (root / "requirements" / "test.txt").write_text("pytest==8.0.0\n", encoding="utf-8")
            rows = []
            with patch("app_forge.verification.shutil.which", return_value="/tools/pip-audit"), \
                 patch("app_forge.verification.run_command", side_effect=[
                     SimpleNamespace(returncode=0, stdout="runtime clean", stderr=""),
                     SimpleNamespace(returncode=0, stdout="dev clean", stderr=""),
                     SimpleNamespace(returncode=0, stdout="tests clean", stderr=""),
                 ]) as run:
                VerificationEngine()._tool(root, "pip-audit", lambda *row: rows.append(row), 30)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [
            ["/tools/pip-audit", "--requirement", "requirements-dev.txt"],
            ["/tools/pip-audit", "--requirement", "requirements.txt"],
            ["/tools/pip-audit", "--requirement", "requirements/test.txt"],
        ])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(rows[0][1], "passed")
        self.assertIn("requirements-dev.txt", rows[0][2])
        self.assertIn("requirements.txt", rows[0][2])
        self.assertIn("requirements/test.txt", rows[0][2])

    def test_failure_in_one_requirements_environment_fails_aggregate_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("urllib3==1.26.18\n", encoding="utf-8")
            (root / "requirements-dev.txt").write_text("urllib3==2.2.0\n", encoding="utf-8")
            rows = []
            with patch("app_forge.verification.shutil.which", return_value="/tools/pip-audit"), \
                 patch("app_forge.verification.run_command", side_effect=[
                     SimpleNamespace(returncode=0, stdout="clean", stderr=""),
                     SimpleNamespace(returncode=1, stdout="", stderr="vulnerability found"),
                 ]) as run:
                VerificationEngine()._tool(root, "pip-audit", lambda *row: rows.append(row), 30)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(rows[0][1], "failed")
        self.assertIn("vulnerability found", rows[0][2])

    def test_no_manifest_is_not_run_and_never_audits_forge_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            with patch("app_forge.verification.shutil.which", return_value="/tools/pip-audit"), \
                 patch("app_forge.verification.run_command") as run:
                VerificationEngine()._tool(
                    Path(tmp), "pip-audit", lambda *row: rows.append(row), 30
                )
        run.assert_not_called()
        self.assertEqual(rows[0][1], "not_run")
        self.assertIn("no supported dependency manifest", rows[0][2])


if __name__ == "__main__":
    unittest.main()
