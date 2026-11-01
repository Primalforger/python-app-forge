from __future__ import annotations

import unittest

from app_forge.change_impact import (
    ChangeImpact, render_change_impact, to_compliance_record, validate_change_impact,
)
from app_forge.compliance_artifacts import validate_artifact


def sample(**changes) -> ChangeImpact:
    values = {
        "change_id": "CHG-104",
        "title": "Replace session token storage",
        "description": "Move session tokens from local storage to secure cookies.",
        "change_type": "security",
        "affected_systems": ("web client", "authentication API"),
        "impacted_requirements": ("SEC-01", "AUTH-04"),
        "impact_level": "high",
        "impact_assessment": "Authentication behavior and browser integration change.",
        "compatibility": "Existing clients require a coordinated rollout.",
        "security_privacy": "Reduces token exposure to script access; cookie settings require review.",
        "operational": "Monitor authentication failures during rollout.",
        "data_migration": "Existing sessions must be invalidated or migrated safely.",
        "rollback_plan": "Restore previous token flow and revoke newly issued sessions.",
        "verification_plan": "Run auth integration tests and verify cookie flags in a browser.",
        "owner": "Identity team",
        "assessment_date": "2026-11-01",
    }
    values.update(changes)
    return ChangeImpact(**values)


class ChangeImpactTests(unittest.TestCase):
    def test_render_contains_traceability_impacts_and_review_checklist(self):
        rendered = render_change_impact(sample())
        for expected in ("CHG-104", "SEC-01", "Compatibility and interfaces",
                         "Security and privacy", "Data and migration",
                         "Rollback and recovery", "Verification and evidence",
                         "Review and approval checklist"):
            self.assertIn(expected, rendered)

    def test_compliance_adapter_produces_valid_cmp09_record(self):
        record = to_compliance_record(sample())
        self.assertEqual(validate_artifact("CMP-09", record), record)
        self.assertEqual(record["impacted_requirements"], ["SEC-01", "AUTH-04"])
        self.assertIn("high impact", record["impact_assessment"])

    def test_empty_impacted_requirements_are_explicitly_incomplete(self):
        item = sample(impacted_requirements=())
        self.assertIn("traceability review remains incomplete", render_change_impact(item))
        record = to_compliance_record(item)
        self.assertIn("review remains incomplete", record["impacted_requirements"][0])
        self.assertEqual(validate_artifact("CMP-09", record), record)

    def test_duplicate_and_malformed_requirement_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_change_impact(sample(impacted_requirements=("SEC-01", "sec-01")))
        with self.assertRaisesRegex(ValueError, "invalid requirement"):
            validate_change_impact(sample(impacted_requirements=("bad id",)))

    def test_required_fields_and_enums_are_validated(self):
        with self.assertRaisesRegex(ValueError, "impact_level"):
            validate_change_impact(sample(impact_level="extreme"))
        with self.assertRaisesRegex(ValueError, "change_type"):
            validate_change_impact(sample(change_type="unknown"))
        with self.assertRaisesRegex(ValueError, "owner"):
            validate_change_impact(sample(owner=" "))

    def test_date_and_single_line_title_are_validated(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_change_impact(sample(assessment_date="2026-1-1"))
        with self.assertRaisesRegex(ValueError, "single line"):
            validate_change_impact(sample(title="Bad\nTitle"))

    def test_iterable_fields_reject_strings_and_duplicates(self):
        with self.assertRaisesRegex(TypeError, "not a string"):
            validate_change_impact(sample(affected_systems="web"))
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_change_impact(sample(affected_systems=("web", "WEB")))


if __name__ == "__main__":
    unittest.main()
