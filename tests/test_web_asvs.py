from __future__ import annotations

from tests.helpers import ForgeTestCase


class WebTemplateASVSTests(ForgeTestCase):
    def test_generated_web_template_contains_versioned_asvs_map_and_security_tests(self):
        output = self.tmp / "asvs-web"
        self.services().create_project("web", {"name": "ASVS Web"}, output)

        mapping = output / "ASVS.md"
        checks = output / "tests" / "test_asvs.py"
        self.assertTrue(mapping.is_file())
        self.assertTrue(checks.is_file())
        map_text = mapping.read_text(encoding="utf-8")
        test_text = checks.read_text(encoding="utf-8")

        self.assertIn("OWASP ASVS 5.0.0", map_text)
        self.assertIn("Known gaps and deployment responsibilities", map_text)
        self.assertIn("not a pass", map_text)
        self.assertIn("test_authentication_and_role_authorization", test_text)
        self.assertIn("test_security_headers_and_docs_are_secure_by_default", test_text)
        self.assertIn("test_unsafe_host_and_cors_wildcard_fail_closed", test_text)
        self.assertNotIn("{{package}}", test_text)
