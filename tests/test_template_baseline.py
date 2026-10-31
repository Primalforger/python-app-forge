import unittest

from app_forge.domain.errors import ConflictFailure, ValidationFailure
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


class VersionedTemplateCatalogTests(ForgeTestCase):
    def test_import_keeps_multiple_versions_and_resolves_exact_or_latest(self):
        services = self.services()
        first = self.tmp / "template-v2"
        services.export_template("cli", first)
        manifest = first / "template.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace('version = "1.0.0"', 'version = "2.0.0"'),
            encoding="utf-8",
        )
        services.import_template(first)

        self.assertEqual(services.templates.get("cli-typer").version, "2.0.0")
        self.assertEqual(services.templates.get("cli-typer@1.0.0").version, "1.0.0")
        self.assertEqual(services.templates.get("cli-typer@2.0.0").version, "2.0.0")
        self.assertEqual(services.templates.get("cli").version, "2.0.0")

        with self.assertRaises(ValidationFailure):
            services.templates.get("cli-typer@9.9.9")

    def test_import_rejects_duplicate_template_version(self):
        services = self.services()
        first = self.tmp / "template-copy-a"
        second = self.tmp / "template-copy-b"
        services.export_template("cli", first)
        services.export_template("cli", second)
        for template_path in (first, second):
            manifest = template_path / "template.toml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    'version = "1.0.0"', 'version = "2.0.0"'
                ),
                encoding="utf-8",
            )
        services.import_template(first)
        with self.assertRaises(ConflictFailure):
            services.import_template(second)
