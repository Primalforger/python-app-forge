import unittest

from app_forge.domain.errors import ValidationFailure
from app_forge.license_scanner import parse_spdx_expression, scan_licenses


class LicenseScannerTests(unittest.TestCase):
    def test_parse_expression_precedence_and_parentheses(self):
        self.assertEqual(
            parse_spdx_expression("(MIT OR Apache-2.0) AND BSD-3-Clause"),
            ("MIT", "Apache-2.0", "BSD-3-Clause"),
        )

    def test_with_exception_is_not_treated_as_a_license(self):
        self.assertEqual(parse_spdx_expression("GPL-2.0-only WITH Classpath-exception-2.0"),
                         ("GPL-2.0-only",))

    def test_rejects_malformed_expressions(self):
        for expression in ("", "MIT AND", "OR MIT", "MIT Apache-2.0", "(MIT OR Apache-2.0",
                           "MIT WITH", "MIT OR OR Apache-2.0", "MIT & GPL-3.0-only"):
            with self.subTest(expression=expression), self.assertRaises(ValidationFailure):
                parse_spdx_expression(expression)

    def test_denied_identifier_inside_expression_is_found(self):
        report = scan_licenses(
            {"components": [{"id": "legacy", "version": "1.0", "license": "MIT OR GPL-3.0-only"}],
             "python_dependencies": []},
            ["gpl-3.0-only"],
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["findings"][0]["matched_denied_licenses"], ["gpl-3.0-only"])

    def test_exception_identifier_does_not_trigger_denied_license(self):
        report = scan_licenses(
            {"components": [{"id": "pkg", "version": "1", "license": "MIT WITH GPL-exception"}],
             "python_dependencies": []},
            ["GPL-exception"],
        )
        self.assertTrue(report["ok"])

    def test_unknown_and_unresolved_metadata_remain_explicit(self):
        report = scan_licenses(
            {"components": [{"id": "unknown", "version": "1", "license": "NOASSERTION"},
                            {"id": "known", "version": "1", "license": "MIT"}],
             "python_dependencies": ["requests"]},
            ["GPL-3.0-only"],
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["components_unknown"], 1)
        self.assertEqual(report["dependencies_unresolved"], 1)
        self.assertEqual(len(report["unknown"]), 2)

    def test_invalid_inventory_is_rejected(self):
        invalid = [None, {"components": "bad", "python_dependencies": []},
                   {"components": ["bad"], "python_dependencies": []},
                   {"components": [{"id": "", "version": "1", "license": "MIT"}],
                    "python_dependencies": []},
                   {"components": [{"id": "x", "version": "1", "license": "MIT"}],
                    "python_dependencies": [None]}]
        for inventory in invalid:
            with self.subTest(inventory=inventory), self.assertRaises(ValidationFailure):
                scan_licenses(inventory)  # type: ignore[arg-type]

    def test_invalid_denied_policy_is_rejected(self):
        with self.assertRaises(ValidationFailure):
            scan_licenses({"components": [], "python_dependencies": []}, [""])


if __name__ == "__main__":
    unittest.main()
