"""HTTP-level tests for generated FastAPI security defaults."""
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from {{package}}.api import create_app
from {{package}}.auth import issue_token
from {{package}}.health import clear_readiness_checks, register_readiness_check

class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"APP_ALLOWED_HOSTS": "testserver",
            "APP_JWT_SECRET": "test-secret-that-is-at-least-thirty-two-bytes",
            "APP_RATE_LIMIT_REQUESTS": "100"})
        self.env.start()
        clear_readiness_checks()
        self.client = TestClient(create_app())
    def tearDown(self):
        self.client.close()
        clear_readiness_checks()
        self.env.stop()
    def test_authentication_and_rbac(self):
        self.assertEqual(self.client.get("/items").status_code, 401)
        reader = issue_token("reader-1", ["reader"])
        editor = issue_token("editor-1", ["editor"])
        self.assertEqual(self.client.get("/items", headers={"Authorization": f"Bearer {reader}"}).status_code, 200)
        self.assertEqual(self.client.post("/items", json={"name": "x"}, headers={"Authorization": f"Bearer {reader}"}).status_code, 403)
        self.assertEqual(self.client.post("/items", json={"name": "x"}, headers={"Authorization": f"Bearer {editor}"}).status_code, 201)
    def test_problem_details_and_headers(self):
        token = issue_token("u", ["reader"])
        response = self.client.get("/items/not-an-integer", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        self.assertIn("X-Content-Type-Options", response.headers)
    def test_liveness_and_readiness(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        register_readiness_check("db", lambda: False)
        self.assertEqual(self.client.get("/health/ready").status_code, 503)
    def test_rate_limit_returns_problem_details_and_retry_after(self):
        with patch.dict(os.environ, {"APP_RATE_LIMIT_REQUESTS": "1"}):
            client = TestClient(create_app())
            try:
                self.assertEqual(client.get("/health/live").status_code, 200)
                response = client.get("/health/live")
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers["content-type"], "application/problem+json")
                self.assertIn("Retry-After", response.headers)
            finally:
                client.close()
    def test_wildcard_cors_is_rejected(self):
        with patch.dict(os.environ, {"APP_CORS_ORIGINS": "*"}):
            with self.assertRaises(RuntimeError):
                create_app()
