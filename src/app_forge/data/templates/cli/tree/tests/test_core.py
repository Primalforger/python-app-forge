import unittest

from {{package}}.core import greet


class GreetTests(unittest.TestCase):
    def test_greet(self):
        self.assertEqual(greet("ada"), "Hello, ada!")
        self.assertEqual(greet("ada", shout=True), "HELLO, ADA!")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            greet("")
