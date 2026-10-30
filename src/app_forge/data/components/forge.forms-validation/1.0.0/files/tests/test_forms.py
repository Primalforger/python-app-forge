import unittest

from {{package}}.forms import Field, validate

SCHEMA = [Field("name", required=True, minimum=2), Field("age", "int", minimum=0, maximum=150),
          Field("role", "choice", choices=("a", "b")), Field("code", pattern=r"[A-Z]{3}")]


class FormTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(SCHEMA, {"name": "Al", "age": "42", "role": "a", "code": "ABC"}), {})

    def test_required_and_types(self):
        errs = validate(SCHEMA, {"name": " ", "age": "x"})
        self.assertEqual(set(errs), {"name", "age"})

    def test_ranges_choices_patterns(self):
        errs = validate(SCHEMA, {"name": "Al", "age": "200", "role": "z", "code": "abc"})
        self.assertEqual(set(errs), {"age", "role", "code"})
