from app_forge.domain.errors import ConflictFailure, SecurityBlock, ValidationFailure
from app_forge.templates.baseline import BASELINE_PATH, load_baseline
from tests.helpers import ForgeTestCase


class ProjectTemplateUpdatePlanningTests(ForgeTestCase):
    def _install_version(self, services, version):
        exported = self.tmp / f"cli-{version}"
        services.export_template("cli-typer@1.0.0", exported)
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
        manifest = exported / "template.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(
            'version = "2.0.0"', 'version = "3.0.0"'), encoding="utf-8")
        exported = exported.rename(self.tmp / "cli-3.0.0")
        services.import_template(exported)
        plan = services.plan_template_update(project, "cli-typer@3.0.0")
        self.assertIn("template-content-conflict", [c["code"] for c in plan["conflicts"]])
        with self.assertRaises(ConflictFailure):
            services.approve_plan(plan["plan_id"], "test maintainer")


    def test_update_plan_handles_upstream_additions_and_deletions(self):
        services = self.services()
        project = self.make_project(services)
        baseline = load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))
        self.assertTrue(baseline["files"])
        exported = self._install_version(services, "2.0.0")
        # Add a template-owned file and remove one from the incoming tree.
        (exported / "tree" / "docs" / "upstream-added.md").parent.mkdir(parents=True, exist_ok=True)
        (exported / "tree" / "docs" / "upstream-added.md").write_text("new upstream file\n", encoding="utf-8")
        removed = "README.md"
        self.assertIn(removed, baseline["files"])
        incoming_removed = exported / "tree" / removed
        self.assertTrue(incoming_removed.is_file())
        incoming_removed.unlink()
        manifest = exported / "template.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(
            'version = "2.0.0"', 'version = "3.0.0"'), encoding="utf-8")
        exported = exported.rename(self.tmp / "cli-3.0.0")
        services.import_template(exported)
        plan = services.plan_template_update(project, "cli-typer@3.0.0")
        self.assertFalse(plan["conflicts"])
        actions = {(c["path"], c["action"]) for c in services.preview_plan(plan["plan_id"], True)["changes"]}
        self.assertIn(("docs/upstream-added.md", "create"), actions)
        self.assertIn((removed, "delete"), actions)

    def test_unowned_path_collision_is_reviewable_and_blocks_approval(self):
        services = self.services()
        project = self.make_project(services)
        exported = self._install_version(services, "2.0.0")
        added = exported / "tree" / "docs" / "new-upstream.md"
        added.parent.mkdir(parents=True, exist_ok=True)
        added.write_text("upstream\n", encoding="utf-8")
        manifest = exported / "template.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(
            'version = "2.0.0"', 'version = "3.0.0"'), encoding="utf-8")
        exported = exported.rename(self.tmp / "cli-3.0.0")
        services.import_template(exported)
        (project / "docs").mkdir(exist_ok=True)
        (project / "docs" / "new-upstream.md").write_text("user-owned\n", encoding="utf-8")
        plan = services.plan_template_update(project, "cli-typer@3.0.0")
        self.assertIn("unowned-path-collision", [c["code"] for c in plan["conflicts"]])
        with self.assertRaises(ConflictFailure):
            services.approve_plan(plan["plan_id"], "test maintainer")

    def test_stale_template_update_plan_is_rejected_before_any_write(self):
        services = self.services()
        project = self.make_project(services)
        self._install_version(services, "2.0.0")
        plan = services.plan_template_update(project, "cli-typer@2.0.0")
        preview = services.preview_plan(plan["plan_id"], True)
        services.approve_plan(plan["plan_id"], "test maintainer")
        change = next(c for c in preview["changes"] if c["action"] in ("create", "modify", "delete"))
        target = project / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("changed after planning\n", encoding="utf-8")
        with self.assertRaises(ConflictFailure):
            services.apply_plan(plan["plan_id"], verify=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "changed after planning\n")
        self.assertEqual(services.integration.status(plan["plan_id"])["status"], "stale")

    def test_approved_plan_rejects_content_tampering_before_writing(self):
        services = self.services()
        project = self.make_project(services)
        self._install_version(services, "2.0.0")
        plan = services.plan_template_update(project, "cli-typer@2.0.0")
        services.approve_plan(plan["plan_id"], "test maintainer")
        saved = services.integration.load_plan(plan["plan_id"])
        change = next(c for c in saved.changes if c.action in ("create", "modify"))
        target = project / change.path
        original = target.read_bytes() if target.exists() else None
        change.content = "tampered content\n"
        services.integration.save_plan(saved)
        with self.assertRaises(SecurityBlock):
            services.integration.apply(plan["plan_id"], verify=False)
        if original is None:
            self.assertFalse(target.exists())
        else:
            self.assertEqual(target.read_bytes(), original)

    def test_successive_template_updates_advance_the_baseline(self):
        services = self.services()
        project = self.make_project(services)
        owned = "tests/__init__.py"
        self.assertIn(owned, load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))["files"])
        target = project / owned
        target.write_text(target.read_text(encoding="utf-8") + "\n# local customization\n", encoding="utf-8")
        self._install_version(services, "2.0.0")
        first = services.plan_template_update(project, "cli-typer@2.0.0")
        services.approve_plan(first["plan_id"], "test maintainer")
        self.assertTrue(services.apply_plan(first["plan_id"], verify=False)["ok"])
        self.assertEqual(load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))["template"]["version"],
                         "2.0.0")
        self._install_version(services, "3.0.0")
        second = services.plan_template_update(project, "cli-typer@3.0.0")
        self.assertFalse(second["conflicts"])
        services.approve_plan(second["plan_id"], "test maintainer")
        self.assertTrue(services.apply_plan(second["plan_id"], verify=False)["ok"])
        self.assertEqual(load_baseline((project / BASELINE_PATH).read_text(encoding="utf-8"))["template"]["version"],
                         "3.0.0")
        self.assertIn("# local customization", target.read_text(encoding="utf-8"))

    def test_interrupted_template_update_rolls_back_prior_writes(self):
        services = self.services()
        project = self.make_project(services)
        before = {p: (project / p).read_bytes() for p in load_baseline(
            (project / BASELINE_PATH).read_text(encoding="utf-8"))["files"]}
        self._install_version(services, "2.0.0")
        plan = services.plan_template_update(project, "cli-typer@2.0.0")
        services.approve_plan(plan["plan_id"], "test maintainer")
        def interrupt(path, index):
            if index == 1:
                raise RuntimeError("simulated process interruption")
        report = services.integration.apply(plan["plan_id"], verify=False, fault=interrupt)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "rolled_back")
        for path, content in before.items():
            self.assertEqual((project / path).read_bytes(), content)

    def test_recovery_preserves_a_user_edit_made_after_partial_apply(self):
        services = self.services()
        project = self.make_project(services)
        self._install_version(services, "2.0.0")
        plan = services.plan_template_update(project, "cli-typer@2.0.0")
        services.approve_plan(plan["plan_id"], "test maintainer")
        def interrupt(path, index):
            if index == 1:
                # The first path is already changed; simulate a concurrent user edit before recovery.
                first = next(c["path"] for c in plan["changes"] if c["action"] in ("create", "modify", "delete"))
                (project / first).write_text("concurrent user edit\n", encoding="utf-8")
                raise RuntimeError("simulated interruption")
        report = services.integration.apply(plan["plan_id"], verify=False, fault=interrupt)
        self.assertEqual(report["status"], "partially_recovered")
        self.assertTrue(report["recovery"]["preserved_user_changes"])

    def test_missing_baseline_blocks_update(self):
        services = self.services()
        project = self.make_project(services)
        (project / BASELINE_PATH).unlink()
        with self.assertRaises(ValidationFailure):
            services.plan_template_update(project)


if __name__ == "__main__":
    import unittest
    unittest.main()
