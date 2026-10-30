import unittest

from {{package}}.core import AppState, greeting


class CoreTests(unittest.TestCase):
    def test_greeting(self):
        self.assertEqual(greeting(" Ada "), "Hello, Ada!")

    def test_greeting_rejects_empty(self):
        with self.assertRaises(ValueError):
            greeting("  ")

    def test_counter(self):
        s = AppState()
        s.increment()
        self.assertEqual(s.increment(), 2)
