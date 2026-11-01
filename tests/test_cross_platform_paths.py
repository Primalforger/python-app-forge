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
