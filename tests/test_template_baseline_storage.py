import json
import unittest

from app_forge.templates.baseline import BASELINE_PATH, create_baseline, load_baseline


class TemplateBaselineTests(unittest.TestCase):
    def test_round_trip_preserves_exact_text_and_template_identity(self):
        text = create_baseline("forge.cli", "1.2.0", "cli",
                               {"src/app.py": "line one\r\nline two", "README.md": "héllo\n"})
        loaded = load_baseline(text)
        self.assertEqual(loaded["template"], {"id": "forge.cli", "version": "1.2.0", "archetype": "cli"})
        self.assertEqual(loaded["files"]["src/app.py"]["content"], "line one\r\nline two")
        self.assertEqual(loaded["files"]["README.md"]["content"], "héllo\n")
        self.assertEqual(BASELINE_PATH, ".forge/template-baseline.json")

    def test_baseline_is_deterministic(self):
        a = create_baseline("forge.cli", "1.0", "cli", {"b": "B", "a": "A"})
        b = create_baseline("forge.cli", "1.0", "cli", {"a": "A", "b": "B"})
        self.assertEqual(a, b)

    def test_content_tampering_is_rejected(self):
        envelope = json.loads(create_baseline("forge.cli", "1.0", "cli", {"a.py": "original"}))
        envelope["files"]["a.py"]["content"] = "tampered"
        with self.assertRaisesRegex(ValueError, "content checksum"):
            load_baseline(json.dumps(envelope))

    def test_metadata_tampering_is_rejected(self):
        envelope = json.loads(create_baseline("forge.cli", "1.0", "cli", {"a.py": "x"}))
        envelope["template"]["version"] = "9.9"
        with self.assertRaisesRegex(ValueError, "baseline checksum"):
            load_baseline(json.dumps(envelope))

    def test_unsupported_schema_is_rejected(self):
        envelope = json.loads(create_baseline("forge.cli", "1.0", "cli", {}))
        envelope["schema_version"] = 99
        with self.assertRaisesRegex(ValueError, "unsupported"):
            load_baseline(json.dumps(envelope))

    def test_path_traversal_and_reserved_paths_are_rejected(self):
        for path in ("../escape.py", "/absolute.py", "src/../escape.py", "a\\b.py", BASELINE_PATH):
            with self.subTest(path=path), self.assertRaises(ValueError):
                create_baseline("forge.cli", "1.0", "cli", {path: "x"})

    def test_invalid_document_shape_is_rejected(self):
        for text in ("not json", "[]", "{}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_baseline(text)


if __name__ == "__main__":
    unittest.main()
