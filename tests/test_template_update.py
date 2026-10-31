from app_forge.domain.errors import ConflictFailure, ValidationFailure
from app_forge.templates.baseline import BASELINE_PATH, load_baseline
from tests.helpers import ForgeTestCase


class ProjectTemplateUpdatePlanningTests(ForgeTestCase):
    def _install_version(self, services, version):
        exported = self.tmp / f"cli-{version}"
        services.export_template("cli", exported)
        manifest = exported / "template.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(
            'version = "1.0.0"', f'version = "{version}"'), encoding="utf-8")
        services.import_template(exported)
        return exported

    def test_update_plan_preserves_local_edits_and_uses_approval_lifecycle(self):
        services = self.services()
        project = self.make_project(services)
        baseline = load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))
        owned = next(iter(baseline["files"]))
        target = project / owned
        target.write_text(target.read_text(encoding="utf-8") + "\n# local customization\n", encoding="utf-8")
        self._install_version(services, "2.0.0")
        plan = services.plan_template_update(project, "cli-typer@2.0.0")
        self.assertEqual(plan["kind"], "template-update")
        self.assertFalse(plan["conflicts"])
        self.assertIn(BASELINE_PATH, [c["path"] for c in services.preview_plan(plan["plan_id"], True)["changes"]])
        services.approve_plan(plan["plan_id"], "test maintainer")
        self.assertTrue(services.apply_plan(plan["plan_id"], verify=False)["ok"])
        self.assertIn("# local customization", target.read_text(encoding="utf-8"))
        self.assertEqual(load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))["template"]["version"], "2.0.0")

    def test_overlapping_upstream_and_local_edits_block_approval(self):
        services = self.services()
        project = self.make_project(services)
        baseline = load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))
        exported = self._install_version(services, "2.0.0")
        upstream = next(p for p in (exported / "tree").rglob("*") if p.is_file())
        owned = upstream.relative_to(exported / "tree").as_posix()
        if owned not in baseline["files"]:
            self.skipTest("selected file is not in the template baseline")
        (project / owned).write_text("local replacement\n", encoding="utf-8")
        upstream.write_text("upstream replacement\n", encoding="utf-8")
        self._install_version(services, "3.0.0")
        plan = services.plan_template_update(project, "cli-typer@3.0.0")
        self.assertIn("template-content-conflict", [c["code"] for c in plan["conflicts"]])
        with self.assertRaises(ConflictFailure):
            services.approve_plan(plan["plan_id"], "test maintainer")

    def test_missing_baseline_blocks_update(self):
        services = self.services()
        project = self.make_project(services)
        (project / BASELINE_PATH).unlink()
        with self.assertRaises(ValidationFailure):
            services.plan_template_update(project)


if __name__ == "__main__":
    import unittest
    unittest.main()
