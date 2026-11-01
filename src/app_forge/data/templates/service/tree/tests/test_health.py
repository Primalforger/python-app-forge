import unittest
from {{package}}.health import clear_readiness_checks, readiness_payload, register_readiness_check

class ServiceHealthTests(unittest.TestCase):
    def test_ready_when_all_checks_pass(self):
        clear_readiness_checks()
        register_readiness_check("database", lambda: True)
        self.assertEqual(readiness_payload(), ({"status": "ready", "checks": {"database": True}}, 200))
    def test_not_ready_when_check_fails_or_raises(self):
        register_readiness_check("queue", lambda: False)
        register_readiness_check("database", lambda: (_ for _ in ()).throw(RuntimeError("private")))
        payload, status = readiness_payload()
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["checks"], {"queue": False, "database": False})
