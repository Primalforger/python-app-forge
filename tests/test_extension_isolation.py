import unittest


class ExtensionWorkerPlaceholderTests(unittest.TestCase):
    def test_protocol_version_is_stable(self):
        from app_forge.extension_worker import PROTOCOL_VERSION
        self.assertEqual(PROTOCOL_VERSION, 1)
