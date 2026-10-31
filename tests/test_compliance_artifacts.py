import json
import unittest
from pathlib import Path

from app_forge.compliance_artifacts import load_artifacts, save_artifact, validate_artifact
from app_forge.domain.errors import SecurityBlock, ValidationFailure
from tests.helpers import ForgeTestCase


class ComplianceArtifactTests(ForgeTestCase):
    def test_each_artifact_requires_its_core_fields(self):
        samples = {
            "CMP-05": {"interfaces": [{"name": "ui.theme", "provider": "theme-core",
                                       "version": "2.0", "contract": "ThemeProvider"}]},
            "CMP-08": {"scope": "web API", "assets": ["credentials"], "threats": ["spoofing"],
                       "mitigations": ["OIDC"], "residual_risks": ["availability"]},
            "CMP-09": {"change": "upgrade auth", "impacted_requirements": ["SEC-01"],
                       "impact_assessment": "Token validation changes"},
            "CMP-10": {"release": "1.2.0", "verification_run": "run-123",
                       "artifacts": ["wheel"], "approvals": ["release-manager"]},
            "CMP-11": {"exceptions": [{"id": "EX-1", "requirement": "SEC-02",
                                       "approver": "security-lead", "rationale": "migration window",
                                       "expires": "2027-01-01"}]},
        }
        for code, payload in samples.items():
            with self.subTest(code=code):
                self.assertEqual(validate_artifact(code, payload), payload)

    def test_missing_fields_and_unknown_types_are_rejected(self):
        with self.assertRaises(ValidationFailure):
            validate_artifact("CMP-08", {"scope": "web"})
        with self.assertRaises(ValidationFailure):
            validate_artifact("CMP-99", {})

    def test_artifact_saved_and_reloaded(self):
        project = self.make_project(self.services(), "cli")
        payload = {"change": "update API", "impacted_requirements": ["API-01"],
                   "impact_assessment": "Backward compatible"}
        result = save_artifact(project, "CMP-09", payload)
        self.assertTrue(Path(result["path"]).is_file())
        loaded = load_artifacts(project)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["record"], payload)

    def test_symlinked_artifact_target_is_rejected(self):
        project = self.make_project(self.services(), "cli")
        directory = project / ".forge" / "compliance"
        directory.mkdir(parents=True)
        target = directory / "change-impact.json"
        target.symlink_to(self.tmp / "outside.json")
        with self.assertRaises(SecurityBlock):
            save_artifact(project, "CMP-09", {
                "change": "x", "impacted_requirements": [], "impact_assessment": "x"
            })

    def test_evidence_package_contains_compliance_artifacts(self):
        services = self.services()
        project = self.make_project(services, "cli")
        services.create_compliance_artifact("CMP-10", project, {
            "release": "0.1.0", "verification_run": "manual-review",
            "artifacts": ["wheel"], "approvals": ["maintainer"]
        })
        result = services.export_evidence(None, project, self.tmp / "evidence")
        package = self.tmp / "evidence"
        self.assertIn("compliance-artifacts.json", result["files"])
        data = json.loads((package / "compliance-artifacts.json").read_text())
        self.assertEqual(data[0]["artifact"], "CMP-10")
        manifest = json.loads((package / "MANIFEST.sha256.json").read_text())
        self.assertIn("compliance-artifacts.json", manifest)


if __name__ == "__main__":
    unittest.main()
