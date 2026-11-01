"""Regression tests for the built-in web template's documented ASVS baseline."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "app_forge" / "data" / "templates" / "web" / "tree"
API = WEB / "src" / "__package__" / "api.py"
ASVS = ROOT / "docs" / "web-template-asvs.md"


class WebTemplateASVSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = API.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source.replace("{{package}}", "sample_app"))

    def test_host_allowlist_is_explicit_and_rejects_wildcards(self):
        self.assertIn('APP_ALLOWED_HOSTS", "127.0.0.1,localhost"', self.source)
        self.assertIn('if not hosts or "*" in hosts:', self.source)
        self.assertIn("TrustedHostMiddleware", self.source)

    def test_security_headers_and_https_only_hsts_are_present(self):
        for header in (
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Permissions-Policy",
            "Content-Security-Policy",
            "Strict-Transport-Security",
        ):
            with self.subTest(header=header):
                self.assertIn(header, self.source)
        self.assertIn('if request.url.scheme == "https":', self.source)

    def test_request_validation_and_safe_error_responses_remain(self):
        self.assertIn("class ItemIn(BaseModel):", self.source)
        self.assertIn("name: str = Field(min_length=1, max_length=100)", self.source)
        self.assertIn('docs_url="/docs" if docs_enabled else None', self.source)
        self.assertIn('openapi_url="/openapi.json" if docs_enabled else None', self.source)
        self.assertIn('detail="invalid item"', self.source)
        self.assertIn('detail="item not found"', self.source)
        self.assertNotIn("detail=str(exc)", self.source)
        self.assertIsNotNone(next((n for n in ast.walk(self.tree) if isinstance(n, ast.AsyncFunctionDef)
                                   and n.name == "security_headers"), None))

    def test_template_does_not_enable_wildcard_cors(self):
        self.assertNotIn("CORSMiddleware", self.source)
        self.assertNotIn('allow_origins=["*"]', self.source)
        self.assertIn('APP_ENABLE_API_DOCS', self.source)

    def test_asvs_mapping_records_implemented_and_missing_controls(self):
        mapping = ASVS.read_text(encoding="utf-8")
        for token in ("ASVS 4.0.3", "V2 Authentication", "V4 Access Control",
                      "V5 Validation", "V13 API", "Not implemented", "deployment"):
            with self.subTest(token=token):
                self.assertIn(token, mapping)
