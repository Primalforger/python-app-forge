import unittest

from app_forge.templates.baseline import BASELINE_PATH, load_baseline
from tests.helpers import ForgeTestCase


class GeneratedTemplateBaselineTests(ForgeTestCase):
    def test_project_creation_persists_exact_rendered_template_baseline(self):
        services = self.services()
        out = self.tmp / "with-baseline"
        services.create_project("cli", {"name": "Baseline App"}, out)

        baseline = load_baseline((out / BASELINE_PATH).read_text(encoding="utf-8"))
        info = services.templates.get("cli")
        variables = services.templates.validate_inputs(info, {"name": "Baseline App"})
        expected = services.templates.render(info, variables)
        self.assertEqual(baseline["template"], {
            "id": info.id, "version": info.version, "archetype": info.archetype,
        })
        self.assertEqual({path: record["content"] for path, record in baseline["files"].items()}, expected)
        self.assertNotIn("forge.toml", baseline["files"])
        self.assertNotIn(BASELINE_PATH, baseline["files"])

    def test_baseline_is_included_in_dry_run_without_writing(self):
        out = self.tmp / "dry-baseline"
        result = self.services().create_project("cli", {"name": "Dry Baseline"}, out, dry_run=True)
        self.assertIn(BASELINE_PATH, [item["path"] for item in result["files"]])
        self.assertFalse(out.exists())

    def test_component_contributions_are_not_misrepresented_as_template_files(self):
        services = self.services()
        out = self.tmp / "with-component"
        services.create_project("web", {"name": "Component Baseline"}, out,
                                components=["forge.forms-validation"])
        baseline = load_baseline((out / BASELINE_PATH).read_text(encoding="utf-8"))
        self.assertNotIn("tests/test_forms.py", baseline["files"])
        self.assertTrue((out / "tests/test_forms.py").is_file())


if __name__ == "__main__":
    unittest.main()
