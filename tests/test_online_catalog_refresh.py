from __future__ import annotations

import hashlib
import json
import threading
import io
import zipfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app_forge.catalog.attestation import generate_keypair, sign_component
from app_forge.catalog.authoring import pack_component
from app_forge.domain.errors import SecurityBlock, Unavailable
from app_forge.services import ForgeServices
from app_forge.settings import ForgeSettings
from tests.helpers import ForgeTestCase


class _Handler(BaseHTTPRequestHandler):
    payloads: dict[str, bytes] = {}

    def do_GET(self):
        payload = self.payloads.get(self.path)
        if payload is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


class OnlineCatalogRefreshTests(ForgeTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _publish(self, component_id="acme.remote", tamper_archive=False):
        component = self.custom_component(component_id)
        private, public = self.tmp / "release.pem", self.tmp / "release.pub"
        generate_keypair(private, public, key_id="remote-release")
        sign_component(component, private, key_id="remote-release")
        archive = pack_component(component, self.tmp / "artifact.zip")
        payload = archive.read_bytes()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if tamper_archive:
            with zipfile.ZipFile(io.BytesIO(payload)) as source:
                members = [(name, source.read(name)) for name in source.namelist()]
            rewritten = io.BytesIO()
            with zipfile.ZipFile(rewritten, "w", zipfile.ZIP_DEFLATED) as target:
                for name, data in members:
                    if name.endswith("/files/src/signed.py"):
                        data += b"\\n# tampered after signing\\n"
                    target.writestr(name, data)
            payload = rewritten.getvalue()
        _Handler.payloads["/artifact.zip"] = payload
        index = {"schema_version": 1, "components": [{
            "id": component_id, "version": "1.0.0", "url": "/artifact.zip", "sha256": digest
        }]}
        _Handler.payloads["/index.json"] = json.dumps(index).encode()
        return public

    def _services(self):
        settings = ForgeSettings(home=self.home, offline=False,
                                 catalog_sources=[self.base_url + "/index.json"])
        settings.ensure()
        return ForgeServices(settings, builtin_root=None)

    def test_refresh_downloads_then_verifies_and_installs_signed_artifact(self):
        public = self._publish()
        services = self._services()
        (services.settings.trusted_keys_dir / "remote-release.pub").write_bytes(public.read_bytes())
        result = services.refresh_catalog()
        self.assertEqual(result["refreshed"], 1)
        entry = services.registry.require("acme.remote")
        self.assertEqual(entry.state, "installed")

    def test_refresh_rejects_tampered_archive_before_import(self):
        public = self._publish(tamper_archive=True)
        services = self._services()
        (services.settings.trusted_keys_dir / "remote-release.pub").write_bytes(public.read_bytes())
        with self.assertRaises(SecurityBlock):
            services.refresh_catalog()
        self.assertFalse((services.settings.user_catalog / "acme.remote").exists())

    def test_offline_mode_blocks_explicit_refresh_without_network_access(self):
        self._publish()
        settings = ForgeSettings(home=self.home, offline=True,
                                 catalog_sources=[self.base_url + "/index.json"])
        services = ForgeServices(settings, builtin_root=None)
        with self.assertRaises(Unavailable):
            services.refresh_catalog()
        self.assertFalse((settings.user_catalog / "acme.remote").exists())


if __name__ == "__main__":
    unittest.main()
