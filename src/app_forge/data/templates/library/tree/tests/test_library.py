import unittest

from {{package}}.library import add


class LibraryTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
