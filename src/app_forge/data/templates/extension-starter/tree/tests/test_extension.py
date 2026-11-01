import unittest

from {{package}}.extension import Plugin


class PluginTests(unittest.TestCase):
    def test_activate_returns_json_safe_status(self):
        self.assertEqual(Plugin().activate(), {"status": "ready", "plugin": "{{package}}"})

    def test_ping(self):
        self.assertEqual(Plugin().ping("test"), {"message": "test"})
