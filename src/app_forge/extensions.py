"""Extension Host (MOD-15). Discovery is not authorisation: nothing is loaded until trusted and enabled."""
from __future__ import annotations

from importlib import metadata
from typing import Callable

from app_forge.domain.errors import SecurityBlock, ValidationFailure
from app_forge.security import TrustPolicy

GROUP = "app_forge.plugins"


class ExtensionHost:
    def __init__(self, store, entry_points: Callable[[], list] | None = None):
        self._store = store
        self._trust = TrustPolicy(store)
        self._eps = entry_points or (lambda: list(metadata.entry_points(group=GROUP)))

    def _find(self, name: str):
        for ep in self._eps():
            if ep.name == name:
                return ep
        raise ValidationFailure(f"No extension named {name!r} is installed",
                                hint=f"Extensions advertise themselves via the '{GROUP}' entry-point group.")

    def discover(self) -> list[dict]:
        """List installed extensions from package metadata. Does NOT import their code."""
        enabled = self._store.enabled_plugins()
        return [{"name": ep.name, "target": ep.value, "trust": self._trust.level(ep.name),
                 "enabled": ep.name in enabled} for ep in self._eps()]

    def inspect(self, name: str) -> dict:
        ep = self._find(name)
        return {"name": ep.name, "target": ep.value, "group": GROUP, "trust": self._trust.level(name),
                "enabled": name in self._store.enabled_plugins(),
                "isolation": "in-process (trusted only); process isolation is not implemented in this release"}

    def trust(self, name: str, level: str = "trusted") -> dict:
        self._find(name)
        if level not in ("trusted", "untrusted"):
            raise ValidationFailure("Trust level must be 'trusted' or 'untrusted'")
        self._store.set_trust(name, level)
        if level == "untrusted":
            self._store.set_enabled_plugin(name, False)
        return self.inspect(name)

    def enable(self, name: str) -> dict:
        self._find(name)
        self._trust.require_trusted(name)
        self._store.set_enabled_plugin(name, True)
        return self.inspect(name)

    def disable(self, name: str) -> dict:
        self._find(name)
        self._store.set_enabled_plugin(name, False)
        return self.inspect(name)

    def activate(self, name: str):
        """Load and return the extension object. Refuses anything not trusted and enabled."""
        ep = self._find(name)
        self._trust.require_trusted(name)
        if name not in self._store.enabled_plugins():
            raise SecurityBlock(f"Extension {name!r} is not enabled", hint=f"forge plugin enable {name}")
        return ep.load()
