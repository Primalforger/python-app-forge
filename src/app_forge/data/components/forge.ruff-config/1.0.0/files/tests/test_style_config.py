import pathlib
import tomllib
import unittest


class StyleConfigTests(unittest.TestCase):
    def test_ruff_tables_present_and_pyproject_still_valid(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["tool"]["ruff"]["line-length"], 100)
        self.assertIn("F", data["tool"]["ruff"]["lint"]["select"])
        self.assertIn("project", data)  # the original content is untouched
