"""Generated web-template authentication and readiness tests."""
import os
import unittest
from unittest.mock import patch
from {{package}}.auth import decode_token, issue_token
from {{package}}.health import clear_readiness_checks, readiness_payload, register_readiness_check

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"APP_JWT_SECRET": "test-secret-that-is-at-least-thirty-two-bytes",
            "APP_JWT_ISSUER": "test-issuer", "APP_JWT_AUDIENCE": "test-audience"})
        self.env.start()
    def tearDown(self):
        self.env.stop()
    def test_token_round_trip(self):
        principal = decode_token(issue_token("user-1", ["reader", "editor"]))
        self.assertEqual(principal.subject, "user-1")
        self.assertEqual(principal.roles, frozenset({"reader", "editor"}))
    def test_weak_secret_is_rejected(self):
        with patch.dict(os.environ, {"APP_JWT_SECRET": "short"}):
            with self.assertRaises(RuntimeError):
                issue_token("user-1", ["reader"])
    def test_invalid_token_is_rejected(self):
        with self.assertRaises(Exception):
            decode_token("not-a-token")

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        clear_readiness_checks()
    def tearDown(self):
        clear_readiness_checks()
    def test_all_checks_must_be_exactly_true(self):
        register_readiness_check("database", lambda: True)
        register_readiness_check("queue", lambda: False)
        self.assertEqual(readiness_payload(), ({"status": "not_ready", "checks": {"database": True, "queue": False}}, 503))
    def test_exception_marks_check_unready(self):
        def fail():
            raise RuntimeError("private detail")
        register_readiness_check("database", fail)
        self.assertEqual(readiness_payload(), ({"status": "not_ready", "checks": {"database": False}}, 503))
