import unittest
import json
from pathlib import Path

from jsonschema import Draft7Validator

from app_forge.domain.errors import ValidationFailure
from app_forge.supply_chain import (build_cyclonedx, build_spdx, check_license_policy,\n                                    generate_sboms, serialize_sbom)


class SupplyChainTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {
            "project": "sample-app",
            "generated_at": "2026-10-31T00:00:00Z",
            "python_dependencies": ["requests", "Pydantic"],
            "components": [
                {"id": "acme.logging", "version": "1.2.0", "license": "MIT",
                 "publisher": "Acme"},
                {"id": "acme.legacy", "version": "2.0.0", "license": "GPL-3.0-only",
                 "publisher": "Acme"},
            ],
        }

    def test_generated_documents_validate_against_official_json_schemas(self):
        schema_dir = Path(__file__).parent / "schemas"
        cyclonedx_schema = json.loads(
            (schema_dir / "cyclonedx-bom-1.5.schema.json").read_text(encoding="utf-8")
        )
        spdx_schema = json.loads(
            (schema_dir / "spdx-2.3.schema.json").read_text(encoding="utf-8")
        )
        cyclonedx = build_cyclonedx(self.inventory)
        spdx = build_spdx(self.inventory)
        Draft7Validator.check_schema(cyclonedx_schema)
        Draft7Validator.check_schema(spdx_schema)
        Draft7Validator(cyclonedx_schema).validate(cyclonedx)
        Draft7Validator(spdx_schema).validate(spdx)

    def test_cyclonedx_document_has_expected_format_and_components(self):
        bom = build_cyclonedx(self.inventory)
        self.assertEqual((bom["bomFormat"], bom["specVersion"]), ("CycloneDX", "1.5"))
        self.assertTrue(bom["serialNumber"].startswith("urn:uuid:"))
        self.assertEqual(len(bom["components"]), 4)
        self.assertIn("pkg:pypi/pydantic", [item["purl"] for item in bom["components"]])

    def test_spdx_document_has_packages_and_relationships(self):
        doc = build_spdx(self.inventory)
        self.assertEqual(doc["spdxVersion"], "SPDX-2.3")
        self.assertEqual(len(doc["packages"]), 4)
        self.assertEqual(len(doc["relationships"]), 4)
        self.assertEqual(doc["packages"][0]["downloadLocation"], "NOASSERTION")

    def test_license_policy_reports_denied_and_unknown_separately(self):
        report = check_license_policy(self.inventory, ["GPL-3.0-only"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["findings"][0]["component"], "acme.legacy")
        self.assertEqual(len(report["unknown"]), 2)
        self.assertIn("not a legal opinion", report["disclaimer"])

    def test_unknown_licences_are_not_implicitly_approved(self):
        report = check_license_policy({"components": [{"id": "x", "license": "unknown"}],
                                       "python_dependencies": []})
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["unknown"]), 1)

    def test_invalid_dependency_name_is_rejected(self):
        with self.assertRaises(ValidationFailure):
            build_cyclonedx({"python_dependencies": ["../escape"], "components": []})


    def test_inventory_rejects_malformed_entries_and_duplicate_components(self):
        invalid = [
            {"components": ["not-an-object"], "python_dependencies": []},
            {"components": [{"id": "x", "version": ""}], "python_dependencies": []},
            {"components": [{"id": "x", "version": "1"}, {"id": "x", "version": "1"}],
             "python_dependencies": []},
            {"components": [], "python_dependencies": ["../escape"]},
        ]
        for inventory in invalid:
            with self.subTest(inventory=inventory), self.assertRaises(ValidationFailure):
                build_spdx(inventory)

    def test_invalid_spdx_creation_timestamp_is_rejected(self):
        with self.assertRaises(ValidationFailure):
            build_spdx({"generated_at": "not-a-date", "components": [], "python_dependencies": []})

    def test_spdx_license_expression_is_preserved(self):
        inventory = {"components": [{"id": "x", "version": "1", "license": "MIT OR Apache-2.0"}],
                     "python_dependencies": []}
        self.assertEqual(build_spdx(inventory)["packages"][0]["licenseDeclared"], "MIT OR Apache-2.0")
        self.assertEqual(build_cyclonedx(inventory)["components"][0]["licenses"],
                         [{"expression": "MIT OR Apache-2.0"}])

    def test_deny_list_matches_terms_inside_license_expression(self):
        inventory = {"components": [{"id": "x", "version": "1", "license": "MIT OR GPL-3.0-only"}],
                     "python_dependencies": []}
        report = check_license_policy(inventory, ["gpl-3.0-only"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["findings"][0]["matched_denied_licenses"], ["gpl-3.0-only"])

    def test_dependency_names_are_normalized_and_deduplicated(self):
        inventory = {"components": [], "python_dependencies": ["Pydantic", "pydantic", "requests"]}
        purls = [item["purl"] for item in build_cyclonedx(inventory)["components"]]
        self.assertEqual(purls, ["pkg:pypi/pydantic", "pkg:pypi/requests"])

    def test_unknown_license_metadata_remains_explicit_in_both_sboms(self):
        inventory = {"components": [{"id": "x", "version": "1", "license": "unknown"}],
                     "python_dependencies": []}
        self.assertEqual(build_cyclonedx(inventory)["components"][0]["licenses"], [])
        self.assertEqual(build_spdx(inventory)["packages"][0]["licenseDeclared"], "NOASSERTION")


if __name__ == "__main__":
    unittest.main()
