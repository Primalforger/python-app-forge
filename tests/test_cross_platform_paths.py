"""Cross-platform manifest path regressions (G-19)."""
import tomllib
from app_forge.catalog.registry import seal_component
from app_forge.domain.errors import ValidationFailure
from app_forge.domain.models import parse_manifest
from tests.helpers import ForgeTestCase


class PortableManifestPathTests(ForgeTestCase):
    def test_windows_reserved_device_names_are_rejected(self):
        root = self.custom_component("acme.portable", files={"src/main.py": "VALUE = 1\n"})
        path = root / "component.toml"
        text = path.read_text(encoding="utf-8").replace(
            'dest = "src/{{package}}/main.py"', 'dest = "src/{{package}}/CON.py"'
        )
        path.write_text(text, encoding="utf-8")
        seal_component(root)
        with self.assertRaises(ValidationFailure):
            parse_manifest(tomllib.loads(path.read_text(encoding="utf-8")))

    def test_case_only_destination_collisions_are_rejected(self):
        root = self.custom_component("acme.portable", files={"src/first.py": "A = 1\n", "src/second.py": "B = 2\n"})
        path = root / "component.toml"
        text = path.read_text(encoding="utf-8")
        text = text.replace('dest = "src/{{package}}/first.py"', 'dest = "src/{{package}}/Main.py"')
        text = text.replace('dest = "src/{{package}}/second.py"', 'dest = "src/{{package}}/main.py"')
        path.write_text(text, encoding="utf-8")
        seal_component(root)
        with self.assertRaises(ValidationFailure):
            parse_manifest(tomllib.loads(path.read_text(encoding="utf-8")))

    def test_portable_path_helper_rejects_backslashes_and_invalid_names(self):
        from app_forge.domain.models import _portable_relative_path

        for value in ("src\\\\module.py", "src/bad:name.py", "src/trailing./file.py", "src/NUL.txt"):
            with self.subTest(value=value):
                self.assertNotEqual(_portable_relative_path(value), "")

    def test_portable_path_helper_rejects_oversized_windows_segment(self):
        from app_forge.domain.models import _portable_relative_path

        self.assertIn("255", _portable_relative_path("src/" + "a" * 256 + ".py"))

    def test_unicode_normalization_destination_collisions_are_rejected(self):
        root = self.custom_component(
            "acme.portable",
            files={"src/first.py": "A = 1\\n", "src/second.py": "B = 2\\n"},
        )
        path = root / "component.toml"
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            'dest = "src/{{package}}/first.py"',
            'dest = "src/{{package}}/caf\\u00e9.py"',
        )
        text = text.replace(
            'dest = "src/{{package}}/second.py"',
            'dest = "src/{{package}}/cafe\\u0301.py"',
        )
        path.write_text(text, encoding="utf-8")
        seal_component(root)
        with self.assertRaises(ValidationFailure):
            parse_manifest(tomllib.loads(path.read_text(encoding="utf-8")))
