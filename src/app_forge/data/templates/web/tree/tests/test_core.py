import unittest

from {{package}}.core import ItemStore


class ItemStoreTests(unittest.TestCase):
    def test_add_and_get(self):
        s = ItemStore()
        item = s.add(" widget ")
        self.assertEqual(s.get(item["id"]), {"id": 1, "name": "widget"})
        self.assertEqual(len(s.list()), 1)

    def test_validation(self):
        s = ItemStore()
        with self.assertRaises(ValueError):
            s.add("")
        with self.assertRaises(ValueError):
            s.add("x" * 101)

    def test_missing(self):
        with self.assertRaises(KeyError):
            ItemStore().get(99)
