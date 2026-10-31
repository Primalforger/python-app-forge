import unittest

from app_forge.domain.errors import ValidationFailure
from app_forge.supply_chain import build_cyclonedx, build_spdx, check_license_policy


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


if __name__ == "__main__":
    unittest.main()
