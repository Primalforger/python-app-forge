import json
import tempfile
import unittest
from pathlib import Path

from app_forge.catalog.attestation import generate_keypair, sign_component, verify_component
from app_forge.catalog.authoring import add_to_catalog, pack_component
from app_forge.services import ForgeServices
from app_forge.domain.errors import SecurityBlock
from app_forge.settings import ForgeSettings
from tests.helpers import ForgeTestCase


class ComponentAttestationTests(ForgeTestCase):
    def test_ed25519_signature_verifies_and_detects_artifact_tampering(self):
        component = self.custom_component("acme.signed")
        private_key, public_key = self.tmp / "signing.pem", self.tmp / "signing.pub"
        generate_keypair(private_key, public_key, key_id="release-2026")
        sign_component(component, private_key, key_id="release-2026")
        trusted = self.tmp / "trusted"
        trusted.mkdir()
        (trusted / "release-2026.pub").write_bytes(public_key.read_bytes())
        result = verify_component(component, trusted)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["key_id"], "release-2026")

        payload = component / "files" / "src" / "signed.py"
        payload.write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(SecurityBlock, "digest"):
            verify_component(component, trusted)

    def test_unknown_signing_key_is_rejected(self):
        component = self.custom_component("acme.unknown")
        private_key, public_key = self.tmp / "private.pem", self.tmp / "public.pub"
        generate_keypair(private_key, public_key, key_id="not-trusted")
        sign_component(component, private_key, key_id="not-trusted")
        with self.assertRaisesRegex(SecurityBlock, "untrusted key"):
            verify_component(component, self.tmp / "empty-trust-store")


    def test_signed_archive_is_verified_when_added_to_catalog(self):
        source_root = self.tmp / "source"
        component = self.custom_component("acme.release", root=source_root)
        private_key, public_key = self.tmp / "release.pem", self.tmp / "release.pub"
        generate_keypair(private_key, public_key, key_id="release-key")
        sign_component(component, private_key, key_id="release-key")
        archive = pack_component(component, self.tmp / "release.zip")
        settings = ForgeSettings(home=self.home)
        settings.ensure()
        trusted = settings.trusted_keys_dir / "release-key.pub"
        trusted.write_bytes(public_key.read_bytes())
        added = add_to_catalog(archive, settings.user_catalog, trusted_keys=settings.trusted_keys_dir)
        self.assertEqual(added["added"], "acme.release@1.0.0")
        services = ForgeServices(settings, builtin_root=None)
        entry = services.registry.require("acme.release")
        self.assertEqual(entry.state, "installed")
        self.assertEqual(verify_component(entry.root, settings.trusted_keys_dir)["status"], "verified")

    def test_unsigned_policy_deny_quarantines_unsigned_components(self):
        settings = ForgeSettings(home=self.home, unsigned_component_policy="deny")
        self.custom_component("acme.unsigned", root=settings.user_catalog)
        services = ForgeServices(settings, builtin_root=None)
        report = services.validate_catalog()
        self.assertFalse(report["ok"])
        self.assertTrue(any("unsigned component rejected" in item["error"] for item in report["quarantined"]))

    def test_unsigned_policy_warn_keeps_legacy_components_available(self):
        settings = ForgeSettings(home=self.home, unsigned_component_policy="warn")
        self.custom_component("acme.legacy", root=settings.user_catalog)
        services = ForgeServices(settings, builtin_root=None)
        entry = services.registry.require("acme.legacy")
        self.assertEqual(entry.state, "installed")
        self.assertIn("unsigned artifact", entry.state_reason)


if __name__ == "__main__":
    unittest.main()
