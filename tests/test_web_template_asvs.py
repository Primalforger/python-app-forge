"""Regression tests for the built-in web template security baseline."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "app_forge" / "data" / "templates" / "web" / "tree"
API = WEB / "src" / "__package__" / "api.py"
SECURITY = WEB / "src" / "__package__" / "security.py"
AUTH = WEB / "src" / "__package__" / "auth.py"
PROBLEMS = WEB / "src" / "__package__" / "problems.py"
ASVS = ROOT / "docs" / "web-template-asvs.md"


class WebTemplateASVSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = API.read_text(encoding="utf-8")
        cls.security = SECURITY.read_text(encoding="utf-8")
        cls.auth = AUTH.read_text(encoding="utf-8")
        cls.problems = PROBLEMS.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source.replace("{{package}}", "sample_app"))

    def test_host_allowlist_is_explicit_and_rejects_wildcards(self):
        self.assertIn('APP_ALLOWED_HOSTS", "127.0.0.1,localhost"', self.source)
        self.assertIn('if not hosts or "*" in hosts:', self.source)
        self.assertIn("TrustedHostMiddleware", self.source)

    def test_security_headers_and_https_only_hsts_are_present(self):
        for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
                       "Permissions-Policy", "Content-Security-Policy", "Strict-Transport-Security"):
            with self.subTest(header=header):
                self.assertIn(header, self.security)
        self.assertIn('if request.url.scheme == "https":', self.security)
        self.assertTrue(any(isinstance(n, ast.AsyncFunctionDef) and n.name == "rate_limit_and_headers"
                            for n in ast.walk(ast.parse(self.security))))

    def test_request_validation_and_error_handlers_remain(self):
        self.assertIn("class ItemIn(BaseModel):", self.source)
        self.assertIn("name: str = Field(min_length=1, max_length=100)", self.source)
        self.assertIn('docs_url="/docs" if docs_enabled else None', self.source)
        self.assertIn('openapi_url="/openapi.json" if docs_enabled else None', self.source)
        self.assertIn("install_problem_handlers", self.source)
        self.assertIn("require_roles", self.source)
        self.assertIn("readiness_payload", self.source)
        self.assertIn('algorithms=["HS256"]', self.auth)
        self.assertIn('issuer=issuer', self.auth)
        self.assertIn('audience=audience', self.auth)
        self.assertIn("require_roles", self.auth)
        self.assertIn("application/problem+json", self.problems)
        self.assertIn("unexpected error occurred", self.problems)

    def test_cors_is_explicit_and_docs_are_opt_in(self):
        self.assertIn("CORSMiddleware", self.security)
        self.assertIn('if "*" in origins:', self.security)
        self.assertIn("allow_credentials=False", self.security)
        self.assertIn("APP_ENABLE_API_DOCS", self.source)

    def test_asvs_mapping_records_implemented_and_missing_controls(self):
        mapping = ASVS.read_text(encoding="utf-8")
        for token in ("ASVS 4.0.3", "V2 Authentication", "V4 Access Control",
                      "V5 Validation", "V13 API", "Not implemented", "deployment"):
            with self.subTest(token=token):
                self.assertIn(token, mapping)
