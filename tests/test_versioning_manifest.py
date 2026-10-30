import tomllib
import unittest
from pathlib import Path

from app_forge.catalog.registry import BUILTIN_COMPONENTS
from app_forge.domain.errors import ValidationFailure
from app_forge.domain.models import parse_manifest
from app_forge.domain.versioning import Constraint, Version


class VersionTests(unittest.TestCase):
    def test_constraints(self):
        c = Constraint.parse("^1.2.0")
        self.assertTrue(c.allows(Version.parse("1.9.9")))
        self.assertFalse(c.allows(Version.parse("2.0.0")))
        self.assertTrue(Constraint.parse(">=1.0,<2.0").allows(Version.parse("1.5.0")))
        self.assertFalse(Constraint.parse("~1.2.0").allows(Version.parse("1.3.0")))
        self.assertTrue(Constraint.parse("*").allows(Version.parse("9.9.9")))

    def test_invalid(self):
        with self.assertRaises(ValidationFailure):
            Version.parse("one.two")
        with self.assertRaises(ValidationFailure):
            Constraint.parse(">>1")


class ManifestTests(unittest.TestCase):
    def good(self):
        return tomllib.loads((BUILTIN_COMPONENTS / "forge.themes/1.0.0/component.toml").read_text())

    def test_builtin_manifest_parses(self):
        m = parse_manifest(self.good())
        self.assertEqual(m.id, "forge.themes")
        self.assertIn("ui.themes", m.capabilities())

    def test_rejects_missing_required_fields(self):
        d = self.good()
        del d["ownership"]["publisher"]
        del d["provenance"]["digest"]
        with self.assertRaises(ValidationFailure) as cm:
            parse_manifest(d)
        self.assertTrue(any("publisher" in x for x in cm.exception.details))
        self.assertTrue(any("digest" in x for x in cm.exception.details))

    def test_rejects_bad_values(self):
        d = self.good()
        d["component"]["version"] = "1.0"
        d["security"]["trust"] = "root"
        d["integration"]["files"][0]["dest"] = "../escape.py"
        d["compatibility"]["python"] = "newish"
        with self.assertRaises(ValidationFailure) as cm:
            parse_manifest(d)
        self.assertGreaterEqual(len(cm.exception.details), 4)

    def test_network_requires_permission(self):
        d = self.good()
        d["security"]["network"] = True
        with self.assertRaises(ValidationFailure):
            parse_manifest(d)
