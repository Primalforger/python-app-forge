"""Regression tests for the root-confined local file store."""
import tempfile
import unittest
from pathlib import Path

from app_forge.file_store import FileStoreError, LocalFileStore


class LocalFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "store"
        self.store = LocalFileStore(self.root, max_file_bytes=32)

    def test_round_trip_atomic_write_and_metadata(self):
        info = self.store.write_text("nested/data.txt", "hello")
        self.assertEqual(info.path, "nested/data.txt")
        self.assertEqual(info.size, 5)
        self.assertEqual(self.store.read_text("nested/data.txt"), "hello")
        self.assertEqual(self.store.read_bytes("nested/data.txt"), b"hello")

    def test_list_is_sorted_and_recursive_is_explicit(self):
        self.store.write_text("z.txt", "z")
        self.store.write_text("nested/a.txt", "a")
        self.assertEqual([x.path for x in self.store.list()], ["z.txt"])
        self.assertEqual([x.path for x in self.store.list(recursive=True)], ["nested/a.txt", "z.txt"])
        self.assertEqual([x.path for x in self.store.list("nested")], ["nested/a.txt"])

    def test_rejects_absolute_traversal_drive_and_ambiguous_paths(self):
        for path in ("../escape", "a/../../escape", "/tmp/x", "C:/escape", "a\\b", "", " a", "a//b", "./a"):
            with self.subTest(path=path), self.assertRaises(FileStoreError):
                self.store.write_text(path, "bad")

    def test_rejects_symlink_reads_writes_and_listing(self):
        outside = Path(self.temp.name) / "outside"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "link"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaises(FileStoreError):
            self.store.read_text("link")
        with self.assertRaises(FileStoreError):
            self.store.write_text("link", "overwrite")
        with self.assertRaises(FileStoreError):
            self.store.list(recursive=True)
        self.assertEqual(outside.read_text(encoding="utf-8"), "secret")

    def test_size_limits_and_non_regular_targets(self):
        with self.assertRaises(FileStoreError):
            self.store.write_bytes("large.bin", b"x" * 33)
        self.store.mkdir("directory")
        with self.assertRaises(FileStoreError):
            self.store.read_bytes("directory")
        with self.assertRaises(FileStoreError):
            self.store.delete("directory")

    def test_delete_and_missing_behavior(self):
        self.store.write_text("remove.txt", "x")
        self.assertTrue(self.store.delete("remove.txt"))
        self.assertFalse(self.store.delete("remove.txt", missing_ok=True))
        with self.assertRaises(FileNotFoundError):
            self.store.delete("missing.txt")

    def test_mkdir_and_invalid_configuration(self):
        self.assertTrue(self.store.mkdir("a/b").is_dir())
        with self.assertRaises(ValueError):
            LocalFileStore(self.root, max_file_bytes=0)


if __name__ == "__main__":
    unittest.main()
