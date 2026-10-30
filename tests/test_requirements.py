import unittest
from pathlib import Path

from app_forge.compliance import load_requirements, validate_requirements

ROOT = Path(__file__).resolve().parent.parent


class RequirementsRegisterTests(unittest.TestCase):
    def test_register_is_valid(self):
        reqs = load_requirements(ROOT / "requirements.toml")
        self.assertEqual(validate_requirements(reqs), [])

    def test_linked_test_files_exist_unless_declared_gap(self):
        for r in load_requirements(ROOT / "requirements.toml"):
            if not r.implemented:
                continue  # documented gaps point at tests that do not exist yet
            for token in r.verified_by:
                self.assertTrue((ROOT / token).is_file(), f"{r.id} -> {token}")


if __name__ == "__main__":
    unittest.main()
