import unittest

from app_forge.domain.errors import ValidationFailure
from app_forge.domain.models import Patch, parse_manifest
from app_forge.patching import PatchConflict, apply_patch, remove_patch
from tests.helpers import ForgeTestCase


class FrameworkAdapterTests(unittest.TestCase):
    def patch(self, framework, module="pkg.routes", symbol="router", **kw):
        return Patch(
            "register", "src/pkg/main.py", "framework-register",
            registration={"framework": framework, "module": module, "symbol": symbol, **kw},
        )

    def test_fastapi_registration_is_static_idempotent_and_reversible(self):
        source = "from fastapi import FastAPI\napp = FastAPI()\n"
        patch = self.patch("fastapi", application="app")
        result = apply_patch(source, patch, "acme.routes", "pkg")
        self.assertIn("from pkg.routes import router", result.new_text)
        self.assertIn("app.include_router(router)", result.new_text)
        self.assertEqual(compile(result.new_text, "main.py", "exec"), None)
        again = apply_patch(result.new_text, patch, "acme.routes", "pkg")
        self.assertEqual((again.status, again.new_text), ("unchanged", result.new_text))
        self.assertEqual(remove_patch(result.new_text, "acme.routes", "register", result.sha256), source)

    def test_flask_registration_uses_blueprint_api(self):
        source = "from flask import Flask\napp = Flask(__name__)\n"
        result = apply_patch(source, self.patch("flask", symbol="blueprint", application="app"),
                             "acme.routes", "pkg")
        self.assertIn("app.register_blueprint(blueprint)", result.new_text)
        compile(result.new_text, "app.py", "exec")

    def test_django_registration_extends_urlpatterns(self):
        source = "urlpatterns = []\n"
        result = apply_patch(source, self.patch("django", symbol="urls", route="api/"),
                             "acme.routes", "pkg")
        self.assertIn('path("api/", include("pkg.routes"))', result.new_text)
        compile(result.new_text, "urls.py", "exec")

    def test_ambiguous_or_invalid_targets_fail_closed(self):
        with self.assertRaises(ValidationFailure):
            apply_patch("app = FastAPI()\nother = FastAPI()\n",
                        self.patch("fastapi"), "acme.routes", "pkg")
        with self.assertRaises(ValidationFailure):
            apply_patch("app = FastAPI(\n", self.patch("fastapi"), "acme.routes", "pkg")
        with self.assertRaises(ValidationFailure):
            apply_patch("app = FastAPI()\n", self.patch("fastapi", module="pkg;evil"),
                        "acme.routes", "pkg")

    def test_registration_patch_manifest_validation(self):
        from app_forge.catalog.registry import BUILTIN_COMPONENTS
        import pathlib
        import tomllib
        data = tomllib.loads((BUILTIN_COMPONENTS / "forge.themes/1.0.0/component.toml").read_text())
        data["integration"]["patches"] = [{
            "id": "register-api", "file": "src/pkg/main.py", "kind": "framework-register",
            "registration": {"framework": "fastapi", "module": "pkg.routes", "symbol": "router"},
        }]
        parsed = parse_manifest(data)
        self.assertEqual(parsed.patches[0].registration["framework"], "fastapi")
        data["integration"]["patches"][0]["registration"]["framework"] = "unknown"
        with self.assertRaises(ValidationFailure):
            parse_manifest(data)


class ThirdPartyFrameworkIntegrationTests(ForgeTestCase):
    def test_fastapi_component_registers_without_forge_anchor(self):
        component = self.custom_component(
            "acme.api-health",
            files={"src/health.py": "from fastapi import APIRouter\nrouter = APIRouter()\n"},
            python_packages=("fastapi>=0.110",),
            patches=['[[integration.patches]]\nid = "register-health"\nfile = "src/{{package}}/main.py"\n'
                     'kind = "framework-register"\n[integration.patches.registration]\n'
                     'framework = "fastapi"\nmodule = "{{package}}.health"\nsymbol = "router"\napplication = "app"\n'],
        )
        root = self.tmp / "third-party"
        (root / "src" / "legacy").mkdir(parents=True)
        (root / "src" / "legacy" / "__init__.py").write_text("")
        (root / "src" / "legacy" / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
        )
        (root / "pyproject.toml").write_text(
            '[project]\nname = "legacy"\nversion = "1.0"\ndependencies = ["fastapi>=0.110"]\n'
        )
        services = self.services()
        plan = services.plan_add(root, {"acme.api-health": "*"})
        self.assertEqual(plan["conflicts"], [])
        self.assertIn(("modify", "src/legacy/main.py"),
                      {(c["action"], c["path"]) for c in plan["changes"]})
        services.approve_plan(plan["plan_id"], "tester")
        result = services.apply_plan(plan["plan_id"], verify=False)
        self.assertEqual(result["status"], "applied")
        updated = (root / "src" / "legacy" / "main.py").read_text()
        self.assertIn("app.include_router(router)", updated)
        recovered = services.recover_plan(plan["plan_id"])
        self.assertEqual(recovered["status"], "rolled_back")
        self.assertEqual((root / "src" / "legacy" / "main.py").read_text(),
                         "from fastapi import FastAPI\napp = FastAPI()\n")


if __name__ == "__main__":
    unittest.main()
