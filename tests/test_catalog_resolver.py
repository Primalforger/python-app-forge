import json
import socket
import unittest
from unittest import mock

from app_forge.catalog.registry import BUILTIN_COMPONENTS
from app_forge.domain.errors import Unavailable
from tests.helpers import ForgeTestCase


class CatalogTests(ForgeTestCase):
    def test_builtin_catalog_valid_and_searchable_offline(self):
        def no_net(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket.socket, "connect", no_net), mock.patch("socket.create_connection", no_net):
            s = self.services()
            self.assertTrue(s.validate_catalog()["ok"])
            self.assertEqual([r["id"] for r in s.search_components("pagination")], ["forge.advanced-table"])
            self.assertTrue(s.search_components(category="quality"))
            self.assertTrue(s.search_components(capability="ui.themes"))
            self.assertEqual(s.search_components(archetype="service")[0]["state"], "installed")
            s.rebuild_catalog_index()

    def test_tampered_artifact_is_quarantined(self):
        v = self.custom_component("acme.tamper")
        (v / "files" / "src" / "tamper.py").write_text("VALUE = 2\n")
        r = self.services(builtin=False).validate_catalog()
        self.assertFalse(r["ok"])
        self.assertIn("digest", r["quarantined"][0]["error"])

    def test_bytecode_caches_do_not_break_artifact_digest(self):
        v = self.custom_component("acme.cache")
        cache = v / "files" / "src" / "__pycache__"
        cache.mkdir()
        (cache / "cache.cpython-312.pyc").write_bytes(b"\x00junk")
        self.assertTrue(self.services(builtin=False).validate_catalog()["ok"])

    def test_malformed_manifest_rejected_not_fatal(self):
        v = self.custom_component("acme.broken")
        (v / "component.toml").write_text("schema_version = 1\n[component]\nid='x'\n")
        r = self.services().validate_catalog()
        self.assertEqual(len(r["quarantined"]), 1)
        self.assertEqual(r["valid"], len(list(BUILTIN_COMPONENTS.glob("*/*"))))  # built-ins still usable

    def test_revoked_disabled_incompatible_and_remote_states(self):
        self.custom_component("acme.old")
        self.custom_component("acme.future", python=">=9.0")
        self.home.mkdir(exist_ok=True)
        (self.home / "revocations.json").write_text(json.dumps({"revoked": [
            {"id": "acme.old", "version": "1.0.0", "reason": "bad", "source": "test", "timestamp": "2026-01-01"}]}))
        (self.home / "catalog" / "remote-index.toml").write_text(
            '[[known]]\nid = "acme.remote"\nversion = "1.0.0"\nsummary = "not here"\n')
        s = self.services(builtin=False)
        states = {e["id"]: e["state"] for e in s.list_catalog()["components"]}
        self.assertEqual(states, {"acme.old": "revoked", "acme.future": "incompatible"})
        self.assertIn("stale", s.inspect_component("acme.old")["state_reason"])
        self.assertEqual(s.list_catalog()["remote_known"][0]["state"], "remote_unavailable")
        with self.assertRaises(Unavailable):
            s.inspect_component("acme.remote")

    def test_disable_enable(self):
        s = self.services()
        self.assertEqual(s.set_component_enabled("forge.themes", False)["state"], "disabled")
        self.assertEqual(s.set_component_enabled("forge.themes", True)["state"], "installed")


class ResolverTests(ForgeTestCase):
    def codes(self, s, req, **kw):
        return {p["code"] for p in s.resolve_dependencies(req, **kw)["problems"]}

    def test_order_and_transitive(self):
        r = self.services().resolve_dependencies({"forge.advanced-table": "*"}, archetype="desktop")
        self.assertEqual(r["install_order"], ["forge.themes@1.0.0", "forge.advanced-table@1.0.0"])

    def test_missing_dependency(self):
        self.custom_component("acme.a", requires={"acme.nope": "^1.0"})
        self.assertIn("missing", self.codes(self.services(), {"acme.a": "*"}))

    def test_incompatible_version(self):
        self.custom_component("acme.lib", "2.0.0")
        self.custom_component("acme.app", requires={"acme.lib": "^1.0"})
        self.assertTrue(self.codes(self.services(), {"acme.app": "*"}))

    def test_conflicting_constraints(self):
        self.custom_component("acme.lib", "1.0.0")
        self.custom_component("acme.lib", "2.0.0")
        self.custom_component("acme.x", requires={"acme.lib": "^1.0"})
        self.custom_component("acme.y", requires={"acme.lib": "^2.0"})
        self.assertIn("conflict", self.codes(self.services(), {"acme.x": "*", "acme.y": "*"}))

    def test_cycle(self):
        self.custom_component("acme.c1", requires={"acme.c2": "*"})
        self.custom_component("acme.c2", requires={"acme.c1": "*"})
        self.assertIn("cycle", self.codes(self.services(), {"acme.c1": "*"}))

    def test_archetype_filter_and_missing_interface(self):
        self.custom_component("acme.guionly", archetypes=("desktop",))
        self.assertTrue(self.codes(self.services(), {"acme.guionly": "*"}, archetype="cli"))
        self.custom_component("acme.needs", requires_if=("x.y@1.0",))
        self.assertIn("missing-interface", self.codes(self.services(), {"acme.needs": "*"}))

    def test_highest_compatible_version_chosen(self):
        self.custom_component("acme.lib", "1.0.0")
        self.custom_component("acme.lib", "1.4.0")
        self.custom_component("acme.lib", "2.0.0")
        r = self.services().resolve_dependencies({"acme.lib": "^1.0"})
        self.assertEqual(r["install_order"], ["acme.lib@1.4.0"])

    def test_interface_version_constraint_is_enforced(self):
        self.custom_component("acme.provider", provides=("ui.theme@2.0",))
        self.custom_component("acme.consumer", requires_if=("ui.theme@^1.0",))
        result = self.services().resolve_dependencies({"acme.provider": "*", "acme.consumer": "*"})
        self.assertIn("incompatible-interface", {p["code"] for p in result["problems"]})

    def test_interface_requirement_accepts_matching_provider_version(self):
        self.custom_component("acme.provider", provides=("ui.theme@2.1",))
        self.custom_component("acme.consumer", requires_if=("ui.theme@>=2.0",))
        result = self.services().resolve_dependencies({"acme.provider": "*", "acme.consumer": "*"})
        self.assertTrue(result["ok"], result["problems"])

    def test_interface_requirement_can_be_satisfied_by_existing_project_component(self):
        self.custom_component("acme.provider", provides=("ui.theme@2.1",))
        self.custom_component("acme.consumer", requires_if=("ui.theme@^2.0",))
        s = self.services()
        project = self.make_project(s, components=["acme.provider"])
        result = s.resolve_dependencies({"acme.consumer": "*"}, project=project)
        self.assertTrue(result["ok"], result["problems"])

    def test_invalid_interface_declaration_quarantines_component(self):
        v = self.custom_component("acme.invalid-interface", provides=("ui theme@1.0",))
        result = self.services(builtin=False).validate_catalog()
        self.assertFalse(result["ok"])
        self.assertTrue(any("interface name" in detail for item in result["quarantined"] for detail in item.get("details", [])))


if __name__ == "__main__":
    unittest.main()
