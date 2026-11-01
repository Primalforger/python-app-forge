"""Tests for secret provider adapters."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_forge.secret_providers import (
    EnvironmentSecretProvider,
    FileSecretProvider,
    KeyringSecretProvider,
    SecretProviderError,
    SecretValue,
)


class SecretValueTests(unittest.TestCase):
    def test_string_and_repr_are_redacted(self) -> None:
        value = SecretValue("top-secret")
        self.assertEqual(value.reveal(), "top-secret")
        self.assertEqual(str(value), "<redacted>")
        self.assertEqual(repr(value), "SecretValue(<redacted>)")
        self.assertNotIn("top-secret", f"{value!r} {value}")


class EnvironmentProviderTests(unittest.TestCase):
    def test_reads_prefixed_environment_without_exposing_value(self) -> None:
        with patch.dict(os.environ, {"FORGE_API_TOKEN": "secret"}):
            result = EnvironmentSecretProvider(prefix="FORGE_").get("API_TOKEN")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.reveal(), "secret")
        self.assertEqual(EnvironmentSecretProvider(prefix="FORGE_").get("MISSING"), None)

    def test_is_read_only_and_validates_names(self) -> None:
        provider = EnvironmentSecretProvider()
        with self.assertRaises(NotImplementedError):
            provider.set("TOKEN", "secret")
        with self.assertRaises(ValueError):
            provider.get("../TOKEN")


class FileProviderTests(unittest.TestCase):
    def test_round_trip_delete_and_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            provider = FileSecretProvider(path)
            provider.set("TOKEN", "secret")
            result = provider.get("TOKEN")
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.reveal(), "secret")
            self.assertNotIn("secret", repr(result))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertTrue(provider.delete("TOKEN"))
            self.assertFalse(provider.delete("TOKEN"))
            self.assertIsNone(provider.get("TOKEN"))

    def test_rejects_permissive_file(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX file permission bits")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            path.write_text(json.dumps({"schema": 1, "secrets": {}}), encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(SecretProviderError):
                FileSecretProvider(path)

    def test_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            target.write_text('{"schema":1,"secrets":{}}', encoding="utf-8")
            link = Path(directory) / "link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(SecretProviderError):
                FileSecretProvider(link)

    def test_persists_across_instances_and_rejects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            FileSecretProvider(path).set("TOKEN", "persisted")
            result = FileSecretProvider(path).get("TOKEN")
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.reveal(), "persisted")
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(SecretProviderError):
                FileSecretProvider(path).get("TOKEN")

    def test_rejects_oversized_values_and_invalid_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = FileSecretProvider(Path(directory) / "secrets.json")
            with self.assertRaises(ValueError):
                provider.set("TOKEN", "x" * 1_048_577)
            with self.assertRaises(ValueError):
                provider.set("../TOKEN", "secret")


class KeyringProviderTests(unittest.TestCase):
    def test_keyring_calls_are_lazy_and_values_are_wrapped(self) -> None:
        class FakeKeyring:
            value = None

            @classmethod
            def get_password(cls, service: str, name: str):
                return cls.value

            @classmethod
            def set_password(cls, service: str, name: str, value: str):
                cls.value = value

            @classmethod
            def delete_password(cls, service: str, name: str):
                cls.value = None

        provider = KeyringSecretProvider("forge-tests")
        with patch.object(provider, "_keyring", return_value=FakeKeyring):
            provider.set("TOKEN", "secret")
            result = provider.get("TOKEN")
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.reveal(), "secret")
            self.assertTrue(provider.delete("TOKEN"))
            self.assertFalse(provider.delete("TOKEN"))

    def test_keyring_errors_are_sanitized(self) -> None:
        class BrokenKeyring:
            @staticmethod
            def get_password(*_args):
                raise RuntimeError("secret leaked by backend")
        provider = KeyringSecretProvider("forge-tests")
        with patch.object(provider, "_keyring", return_value=BrokenKeyring):
            with self.assertRaisesRegex(SecretProviderError, "OS keyring read failed") as caught:
                provider.get("TOKEN")
            self.assertNotIn("secret leaked", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
