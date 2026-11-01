import unittest
from {{package}}.readiness import clear_readiness_checks, liveness_payload, readiness_payload, register_readiness_check

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        clear_readiness_checks()
    def tearDown(self):
        clear_readiness_checks()
    def test_liveness_is_independent_of_dependencies(self):
        self.assertEqual(liveness_payload(), {"status": "ok"})
    def test_readiness_requires_every_check_to_be_exactly_true(self):
        register_readiness_check("database", lambda: True)
        register_readiness_check("queue", lambda: False)
        self.assertEqual(readiness_payload(), ({"status": "not_ready", "checks": {"database": True, "queue": False}}, 503))
    def test_check_exceptions_fail_closed(self):
        def fail():
            raise RuntimeError("private detail")
        register_readiness_check("database", fail)
        self.assertEqual(readiness_payload(), ({"status": "not_ready", "checks": {"database": False}}, 503))
