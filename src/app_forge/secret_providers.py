"""Secret storage adapters with explicit reveal semantics and redacted representations.

Environment variables are read-only. The optional keyring adapter loads its
backend lazily. The JSON file adapter is plaintext at rest and therefore relies
on strict owner-only filesystem permissions; use an OS keyring for stronger
at-rest protection.
"""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
from pathlib import Path
from typing import Protocol

_SCHEMA = 1
_MAX_STORE_BYTES = 1_048_576
_SECRET_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


class SecretProviderError(RuntimeError):
    """A provider operation failed; messages never contain secret values."""


class SecretValue:
    """A secret whose string and representation are always redacted."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("secret value must be a string")
        self.__value = value

    def reveal(self) -> str:
        """Explicitly expose the underlying value to the caller."""
        return self.__value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __format__(self, _format_spec: str) -> str:
        return "<redacted>"


class SecretProvider(Protocol):
    """Minimal named-secret interface shared by all providers."""

    def get(self, name: str) -> SecretValue | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not _SECRET_NAME.fullmatch(name):
        raise ValueError("secret name must be 1-128 safe identifier characters")
    return name


def _validate_value(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("secret value must be a non-empty string")
    if len(value.encode("utf-8")) > _MAX_STORE_BYTES:
        raise ValueError("secret value exceeds the storage limit")
    return value


class EnvironmentSecretProvider:
    """Read secrets from environment variables without mutating process state."""

    def __init__(self, *, prefix: str = "") -> None:
        if not isinstance(prefix, str) or (prefix and not re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix)):
            raise ValueError("prefix must contain uppercase environment-name characters")
        self.prefix = prefix

    def get(self, name: str) -> SecretValue | None:
        key = self.prefix + _validate_name(name)
        value = os.environ.get(key)
        return SecretValue(value) if value is not None else None

    def set(self, name: str, value: str) -> None:
        _validate_name(name)
        _validate_value(value)
        raise NotImplementedError("environment secrets are read-only")

    def delete(self, name: str) -> bool:
        _validate_name(name)
        raise NotImplementedError("environment secrets are read-only")


class KeyringSecretProvider:
    """Use the optional 'keyring' package and the host's configured secure backend."""

    def __init__(self, service_name: str) -> None:
        if not isinstance(service_name, str) or not service_name.strip() or len(service_name) > 128:
            raise ValueError("service_name must be a non-empty string of at most 128 characters")
        self.service_name = service_name

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:
            raise SecretProviderError("install the 'keyring' extra to use OS keyring storage") from exc
        return keyring

    def get(self, name: str) -> SecretValue | None:
        selected = _validate_name(name)
        try:
            value = self._keyring().get_password(self.service_name, selected)
        except Exception as exc:
            raise SecretProviderError("OS keyring read failed") from exc
        return SecretValue(value) if value is not None else None

    def set(self, name: str, value: str) -> None:
        selected = _validate_name(name)
        secret = _validate_value(value)
        try:
            self._keyring().set_password(self.service_name, selected, secret)
        except Exception as exc:
            raise SecretProviderError("OS keyring write failed") from exc

    def delete(self, name: str) -> bool:
        selected = _validate_name(name)
        keyring = self._keyring()
        try:
            existing = keyring.get_password(self.service_name, selected)
            if existing is None:
                return False
            keyring.delete_password(self.service_name, selected)
            return True
        except Exception as exc:
            raise SecretProviderError("OS keyring delete failed") from exc


class FileSecretProvider:
    """Owner-permission-only JSON secret store; values are plaintext at rest.

    The file is created with mode 0600 and rejected if it is a symlink or has
    any group/other permissions. Writes use fsync and atomic replacement.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()
        self._check_path()

    def _check_path(self) -> None:
        if self.path.is_symlink():
            raise SecretProviderError("secret store must not be a symbolic link")
        if self.path.exists():
            if not self.path.is_file():
                raise SecretProviderError("secret store path must be a regular file")
            if os.name == "posix" and stat.S_IMODE(self.path.stat().st_mode) & 0o077:
                raise SecretProviderError("secret store permissions must be owner-only (0600)")

    def _load(self) -> dict[str, str]:
        self._check_path()
        if not self.path.exists():
            return {}
        try:
            raw_bytes = self.path.read_bytes()
            if len(raw_bytes) > _MAX_STORE_BYTES:
                raise SecretProviderError("secret store exceeds the size limit")
            raw = json.loads(raw_bytes.decode("utf-8"))
        except SecretProviderError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretProviderError("secret store is unreadable or malformed") from exc
        if not isinstance(raw, dict) or raw.get("schema") != _SCHEMA or not isinstance(raw.get("secrets"), dict):
            raise SecretProviderError("secret store has an unsupported format")
        secrets = raw["secrets"]
        if any(not isinstance(k, str) or not _SECRET_NAME.fullmatch(k) or not isinstance(v, str) or not v
               for k, v in secrets.items()):
            raise SecretProviderError("secret store contains invalid records")
        return secrets

    def _save(self, secrets: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema": _SCHEMA, "secrets": secrets},
                             ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > _MAX_STORE_BYTES:
            raise ValueError("secret store exceeds the size limit")
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_path()
            os.replace(temporary, self.path)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def get(self, name: str) -> SecretValue | None:
        selected = _validate_name(name)
        with self._lock:
            value = self._load().get(selected)
            return SecretValue(value) if value is not None else None

    def set(self, name: str, value: str) -> None:
        selected, secret = _validate_name(name), _validate_value(value)
        with self._lock:
            records = self._load()
            records[selected] = secret
            self._save(records)

    def delete(self, name: str) -> bool:
        selected = _validate_name(name)
        with self._lock:
            records = self._load()
            if selected not in records:
                return False
            del records[selected]
            self._save(records)
            return True
