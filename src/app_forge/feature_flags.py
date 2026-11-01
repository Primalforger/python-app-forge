"""Thread-safe, in-process feature flag registry.

Flags have explicit boolean defaults and optional runtime overrides. The
registry is deliberately local and deterministic: it performs no network or
environment reads and does not persist executable configuration.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Mapping

_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("flag name must start with a lowercase letter and contain only lowercase letters, digits, '.', '_' or '-'")
    return name


def _validate_bool(value: bool, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


class FeatureFlags:
    """A thread-safe registry of boolean feature flags and runtime overrides."""

    def __init__(self, flags: Mapping[str, bool] | None = None) -> None:
        self._lock = threading.RLock()
        self._defaults: dict[str, bool] = {}
        self._overrides: dict[str, bool] = {}
        if flags is not None:
            if not isinstance(flags, Mapping):
                raise TypeError("flags must be a mapping of names to booleans")
            for name, enabled in flags.items():
                self.register(name, enabled)

    def register(self, name: str, default: bool = False) -> None:
        """Register a flag; duplicate names are rejected rather than replaced."""
        key = _validate_name(name)
        value = _validate_bool(default, "default")
        with self._lock:
            if key in self._defaults:
                raise ValueError(f"feature flag {key!r} is already registered")
            self._defaults[key] = value

    def is_enabled(self, name: str) -> bool:
        """Return the active value, raising KeyError for unknown flags."""
        key = _validate_name(name)
        with self._lock:
            if key not in self._defaults:
                raise KeyError(f"unknown feature flag: {key}")
            return self._overrides.get(key, self._defaults[key])

    def set_override(self, name: str, enabled: bool) -> None:
        """Set a runtime value without changing the registered default."""
        key = _validate_name(name)
        value = _validate_bool(enabled, "enabled")
        with self._lock:
            if key not in self._defaults:
                raise KeyError(f"unknown feature flag: {key}")
            self._overrides[key] = value

    def clear_override(self, name: str) -> bool:
        """Remove a runtime override; return whether one existed."""
        key = _validate_name(name)
        with self._lock:
            if key not in self._defaults:
                raise KeyError(f"unknown feature flag: {key}")
            if key not in self._overrides:
                return False
            del self._overrides[key]
            return True

    def snapshot(self) -> dict[str, bool]:
        """Return a stable copy of all currently evaluated flag values."""
        with self._lock:
            return {
                name: self._overrides.get(name, default)
                for name, default in self._defaults.items()
            }

    def defaults(self) -> dict[str, bool]:
        """Return a copy of registered defaults, excluding runtime overrides."""
        with self._lock:
            return self._defaults.copy()
