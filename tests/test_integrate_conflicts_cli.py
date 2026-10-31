from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock

from app_forge.cli.main import _emit, c_integrate


class IntegrateConflictInspectionTests(unittest.TestCase):
    def setUp(self):
        self.preview = {
            "kind": "template-update",
            "plan_id": "plan-456",
            "conflicts": [
                {"code": "content-conflict", "path": "README.md",
                 "message": "Local and incoming edits overlap",
                 "resolution": "Reconcile the two versions manually"},
                {"code": "unowned-path-collision", "path": "src/app.py",
                 "message": "The path is already owned by the project",
                 "resolution": "Move or rename the existing file before retrying"},
            ],
        }
        self.services = Mock()
        self.services.preview_plan.return_value = self.preview

    def test_conflicts_action_returns_only_filtered_conflicts(self):
        args = SimpleNamespace(action="conflicts", plan_id="plan-456",
                                code="content-conflict", path=None, content=False)
        result, code = c_integrate(self.services, args)
        self.services.preview_plan.assert_called_once_with("plan-456", with_content=False)
        self.assertEqual(code, 0)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["conflicts"][0]["path"], "README.md")

    def test_path_filter_can_select_one_conflict(self):
        args = SimpleNamespace(action="conflicts", plan_id="plan-456",
                                code=None, path="src/app.py", content=False)
        result, _ = c_integrate(self.services, args)
        self.assertEqual([item["code"] for item in result["conflicts"]],
                         ["unowned-path-collision"])

    def test_terminal_report_shows_resolution_guidance(self):
        output = StringIO()
        report = {"kind": "conflict-report", "plan_id": "plan-456",
                  "conflicts": self.preview["conflicts"]}
        with redirect_stdout(output):
            _emit(SimpleNamespace(json=False), report)
        rendered = output.getvalue()
        self.assertIn("content-conflict", rendered)
        self.assertIn("README.md", rendered)
        self.assertIn("Reconcile the two versions manually", rendered)

    def test_json_output_remains_structured(self):
        output = StringIO()
        report = {"kind": "conflict-report", "plan_id": "plan-456",
                  "count": 0, "conflicts": []}
        with redirect_stdout(output):
            _emit(SimpleNamespace(json=True), report)
        self.assertEqual(json.loads(output.getvalue())["result"], report)


if __name__ == "__main__":
    unittest.main()
