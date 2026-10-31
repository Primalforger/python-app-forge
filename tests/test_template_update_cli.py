from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import json
import unittest

from app_forge.cli.main import _emit


class TemplateUpdatePreviewRenderingTests(unittest.TestCase):
    def setUp(self):
        self.preview = {
            "kind": "template-update",
            "plan_id": "plan-123",
            "project_path": "/tmp/example",
            "change_summary": {
                "total": 2, "create": 1, "modify": 1, "delete": 0,
                "manual": 0, "conflicts": 1, "warnings": 0,
            },
            "review": [
                {"action": "create", "count": 1, "files": [
                    {"path": "docs/new.md", "reason": "Added upstream", "diff": "--- a/docs/new.md\n+++ b/docs/new.md\n+hello\n"}
                ]},
                {"action": "modify", "count": 1, "files": [
                    {"path": "README.md", "reason": "Updated", "before_state": "drifted", "diff": None}
                ]},
            ],
            "conflicts": [{
                "code": "template-content-conflict",
                "path": "README.md",
                "message": "Local and upstream edits overlap",
                "resolution": "Reconcile the local and upstream edits",
            }],
            "warnings": [],
        }

    def render(self, *, as_json=False):
        output = StringIO()
        with redirect_stdout(output):
            _emit(SimpleNamespace(json=as_json), self.preview)
        return output.getvalue()

    def test_terminal_preview_groups_changes_and_explains_diff_state(self):
        output = self.render()
        self.assertIn("2 total | +1 create | ~1 modify | -0 delete | 0 manual", output)
        self.assertIn("CREATE (1)", output)
        self.assertIn("docs/new.md", output)
        self.assertIn("+hello", output)
        self.assertIn("Before-state: drifted; diff omitted", output)
        self.assertIn("Reconcile the local and upstream edits", output)

    def test_json_output_remains_machine_readable_and_complete(self):
        payload = json.loads(self.render(as_json=True))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"], self.preview)

    def test_non_template_preview_keeps_generic_renderer(self):
        output = StringIO()
        with redirect_stdout(output):
            _emit(SimpleNamespace(json=False), {"kind": "component", "status": "ready"})
        self.assertIn("kind: component", output.getvalue())
        self.assertNotIn("Template update preview", output.getvalue())


if __name__ == "__main__":
    unittest.main()
