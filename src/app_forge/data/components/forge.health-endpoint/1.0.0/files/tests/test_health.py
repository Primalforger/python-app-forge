import unittest

from {{package}}.health import health_payload


class HealthTests(unittest.TestCase):
    def test_ok_when_all_checks_pass(self):
        self.assertEqual(health_payload({"db": True})["status"], "ok")
        self.assertEqual(health_payload()["status"], "ok")

    def test_degraded_when_any_check_fails_or_is_not_strictly_true(self):
        self.assertEqual(health_payload({"db": True, "queue": False})["status"], "degraded")
        self.assertEqual(health_payload({"db": 1})["status"], "degraded")

    def test_api_module_registers_the_route(self):
        import pathlib
        api = pathlib.Path(__file__).resolve().parent.parent / "src" / "{{package}}" / "api.py"
        self.assertIn('@app.get("/healthz")', api.read_text(encoding="utf-8"))
