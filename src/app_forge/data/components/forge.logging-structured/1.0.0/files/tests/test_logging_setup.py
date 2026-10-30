import io
import json
import logging
import unittest

from {{package}} import logging_setup


class LoggingTests(unittest.TestCase):
    def test_json_lines_with_operation_id_and_redaction(self):
        buf = io.StringIO()
        logging_setup.configure(logging.INFO, buf)
        op = logging_setup.new_operation()
        logging.getLogger("t").info("login password=hunter2 ok")
        rec = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(rec["operation_id"], op)
        self.assertNotIn("hunter2", rec["message"])
        self.assertIn("[REDACTED]", rec["message"])
