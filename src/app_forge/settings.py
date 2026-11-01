"""Configuration Service (MOD-12): platform settings. Secrets are never stored here."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ForgeSettings:
    home: Path
    offline: bool = True
    extra_catalog_roots: list[Path] = field(default_factory=list)
    unsigned_component_policy: str = "warn"
    catalog_sources: list[str] = field(default_factory=list)
    plan_retention_days: int = 30
    checkpoint_retention_days: int = 30
    evidence_retention_days: int = 365
    operation_retention_days: int = 365

    @classmethod
    def load(cls, home: Path | None = None) -> "ForgeSettings":
        home = Path(home or os.environ.get("FORGE_HOME") or Path.home() / ".app_forge")
        s = cls(home=home)
        cfg = home / "settings.toml"
        if cfg.is_file():
            data = tomllib.loads(cfg.read_text(encoding="utf-8"))
            s.offline = bool(data.get("offline", True))
            s.extra_catalog_roots = [Path(p) for p in data.get("catalog_roots", [])]
            s.unsigned_component_policy = str(data.get("unsigned_component_policy", "warn"))
            s.catalog_sources = [str(url) for url in data.get("catalog_sources", [])]
            retention = data.get("retention", {})
            if not isinstance(retention, dict):
                raise ValueError("[retention] must be a TOML table")
            for key in ("plan_retention_days", "checkpoint_retention_days", "evidence_retention_days", "operation_retention_days"):
                if key in retention:
                    value = retention[key]
                    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 36500:
                        raise ValueError(f"retention.{key} must be an integer between 1 and 36500")
                    setattr(s, key, value)
        if s.unsigned_component_policy not in ("allow", "warn", "deny"):
            raise ValueError("unsigned_component_policy must be allow, warn, or deny")
        return s

    @property
    def db_path(self) -> Path:
        return self.home / "forge.db"

    @property
    def plans_dir(self) -> Path:
        return self.home / "plans"

    @property
    def checkpoints_dir(self) -> Path:
        return self.home / "checkpoints"

    @property
    def locks_dir(self) -> Path:
        return self.home / "locks"

    @property
    def user_catalog(self) -> Path:
        return self.home / "catalog"

    @property
    def trusted_keys_dir(self) -> Path:
        return self.home / "trusted-keys"

    @property
    def revocations_file(self) -> Path:
        return self.home / "revocations.json"

    def ensure(self) -> None:
        for p in (self.home, self.plans_dir, self.checkpoints_dir, self.user_catalog, self.trusted_keys_dir):
            p.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        return {"home": str(self.home), "offline": self.offline,
                "extra_catalog_roots": [str(p) for p in self.extra_catalog_roots],
                "unsigned_component_policy": self.unsigned_component_policy,
                "catalog_sources": list(self.catalog_sources),
                "retention": {"plan_retention_days": self.plan_retention_days,
                              "checkpoint_retention_days": self.checkpoint_retention_days,
                              "evidence_retention_days": self.evidence_retention_days,
                              "operation_retention_days": self.operation_retention_days},
                "db_path": str(self.db_path), "user_catalog": str(self.user_catalog)}
