from __future__ import annotations

import unittest

from app_forge.compliance_artifacts import validate_artifact
from app_forge.threat_model import (
    STRIDECategory,
    Threat,
    ThreatModel,
    render_threat_model,
    to_compliance_record,
    validate_threat_model,
)


def sample(**changes) -> ThreatModel:
    values = {
        "system": "Payments API",
        "scope": "Public API, worker, and payment database.",
        "assets": ("customer data", "payment credentials"),
        "trust_boundaries": ("Internet to API gateway", "API to database"),
        "threats": (
            Threat(
                id="THR-001",
                category=STRIDECategory.SPOOFING,
                asset="payment credentials",
                description="Stolen credentials may be used to impersonate a customer.",
                impact="Unauthorized payment activity.",
                mitigation="Require MFA and rotate compromised credentials.",
                residual_risk="Phishing remains possible.",
            ),
        ),
    }
    values.update(changes)
    return ThreatModel(**values)


class ThreatModelTests(unittest.TestCase):
    def test_render_includes_all_stride_categories_and_review_prompts(self):
        rendered = render_threat_model(sample())
        for category in STRIDECategory:
            self.assertIn(f"### {category.value}", rendered)
        self.assertIn("THR-001", rendered)
        self.assertIn("Phishing remains possible.", rendered)
        self.assertIn("not an automated security scan", rendered)
        self.assertIn("- [ ]", rendered)

    def test_compliance_record_is_valid_cmp08_payload(self):
        record = to_compliance_record(sample())
        self.assertEqual(validate_artifact("CMP-08", record), record)
        self.assertIn("[Spoofing]", record["threats"][0])
        self.assertIn("THR-001", record["mitigations"][0])

    def test_empty_threat_list_is_explicitly_incomplete_not_no_risk(self):
        model = sample(threats=())
        rendered = render_threat_model(model)
        self.assertIn("No threats recorded in this category", rendered)
        record = to_compliance_record(model)
        self.assertIn("assessment remains incomplete", record["threats"][0])
        self.assertEqual(validate_artifact("CMP-08", record), record)

    def test_duplicate_threat_ids_rejected_case_insensitively(self):
        first = sample().threats[0]
        duplicate = Threat(
            id="thr-001", category=STRIDECategory.TAMPERING,
            asset="customer data", description="Alter a balance.",
            impact="Incorrect balance.", mitigation="Sign records.",
            residual_risk="Key compromise.",
        )
        with self.assertRaisesRegex(ValueError, "duplicate threat id"):
            validate_threat_model(sample(threats=(first, duplicate)))

    def test_threat_must_reference_declared_asset(self):
        threat = Threat(
            id="THR-2", category=STRIDECategory.TAMPERING,
            asset="unknown", description="Modify data.", impact="Data loss.",
            mitigation="Use integrity checks.", residual_risk="Insider risk.",
        )
        with self.assertRaisesRegex(ValueError, "declared asset"):
            validate_threat_model(sample(threats=(threat,)))

    def test_required_content_and_enum_are_validated(self):
        with self.assertRaisesRegex(ValueError, "system"):
            validate_threat_model(sample(system=" "))
        with self.assertRaisesRegex(ValueError, "STRIDECategory"):
            validate_threat_model(sample(threats=(
                Threat("THR-1", "Spoofing", "customer data", "x", "y", "z", "r"),
            )))

    def test_assets_are_nonempty_and_unique(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_threat_model(sample(assets=("Customer data", "customer data")))
        with self.assertRaisesRegex(ValueError, "at least one"):
            validate_threat_model(sample(assets=()))


if __name__ == "__main__":
    unittest.main()
