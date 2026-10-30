import pathlib
import unittest

from {{package}} import __version__
from {{package}}.version_info import version_line


class VersionTests(unittest.TestCase):
    def test_line(self):
        self.assertEqual(version_line("tool", "1.2.3"), "tool 1.2.3")
        self.assertTrue(__version__)

    def test_cli_registers_the_command(self):
        cli = pathlib.Path(__file__).resolve().parent.parent / "src" / "{{package}}" / "cli.py"
        self.assertIn("def version()", cli.read_text(encoding="utf-8"))
