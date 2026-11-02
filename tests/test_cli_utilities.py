import io
import json
import unittest

import yaml

from app_forge.cli.formatters import format_output, format_table, format_text
from app_forge.cli.progress import ProgressReporter
from app_forge.cli.prompts import confirm
from app_forge.domain.errors import ValidationFailure


class FormatterTests(unittest.TestCase):
    def test_json_and_yaml_preserve_structured_values(self):
        value = [{"name": "café", "enabled": True}]
        self.assertEqual(json.loads(format_output(value, "json")), value)
        self.assertEqual(yaml.safe_load(format_output(value, "yaml")), value)

    def test_table_columns_are_union_and_deterministic(self):
        rendered = format_table([{"id": "a", "name": "Alpha"}, {"id": "b", "extra": 3}])
        self.assertEqual(rendered.splitlines()[0], "id | name | extra")
        self.assertIn("b  |      | 3", rendered)

    def test_text_nested_and_empty_values(self):
        self.assertEqual(format_text({"items": []}), "items: []")
        self.assertEqual(format_output([], "table"), "(none)")

    def test_color_only_affects_table_header(self):
        value = [{"id": "x"}]
        self.assertIn("\033[1m", format_output(value, "table", color=True))
        self.assertNotIn("\033", format_output(value, "json", color=True))

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            format_output({}, "xml")


class ProgressTests(unittest.TestCase):
    def test_always_emits_only_to_supplied_stderr_stream(self):
        stream = io.StringIO()
        reporter = ProgressReporter("always", stream=stream)
        reporter.start("doctor")
        reporter.finish(0)
        self.assertEqual(stream.getvalue().splitlines(), ["forge: running doctor", "forge: completed"])

    def test_never_suppresses_output(self):
        stream = io.StringIO()
        ProgressReporter("never", stream=stream).start("doctor")
        self.assertEqual(stream.getvalue(), "")


class PromptTests(unittest.TestCase):
    def test_yes_skips_prompt(self):
        confirm("proceed?", yes=True, input_fn=lambda _: self.fail("prompted"))

    def test_noninteractive_requires_yes(self):
        with self.assertRaises(ValidationFailure):
            confirm("proceed?", non_interactive=True, stdin=io.StringIO())

    def test_tty_acceptance_and_rejection(self):
        class TTY:
            def isatty(self):
                return True
        confirm("proceed?", stdin=TTY(), input_fn=lambda _: "yes")
        with self.assertRaises(ValidationFailure):
            confirm("proceed?", stdin=TTY(), input_fn=lambda _: "no")


if __name__ == "__main__":
    unittest.main()
