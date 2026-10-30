"""Profile-based settings. Ordinary config lives in TOML; secrets are read from the environment only."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    values: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)
    profile: str = "default"

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def secret(self, name: str) -> str:
        if name not in self.secrets:
            raise KeyError(f"Secret {name!r} is not set (provide it via environment variable)")
        return self.secrets[name]

    def redacted(self) -> dict:
        return {"profile": self.profile, "values": dict(self.values),
                "secrets": {k: "[REDACTED]" for k in self.secrets}}


def load_settings(path: Path | str | None = None, profile: str = "default", *,
                  secret_names: tuple[str, ...] = (), env_prefix: str = "APP_", environ=None) -> Settings:
    """Merge [default] with [<profile>] from a TOML file, then environment overrides (APP_<KEY>)."""
    environ = os.environ if environ is None else environ
    values: dict = {}
    if path and Path(path).is_file():
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        values.update(data.get("default", {}))
        if profile != "default":
            if profile not in data:
                raise KeyError(f"Profile {profile!r} not found in {path}")
            values.update(data[profile])
    for key in list(values):
        if key in secret_names:
            raise ValueError(f"Secret {key!r} must not be stored in a config file")
        env_key = env_prefix + key.upper()
        if env_key in environ:
            values[key] = environ[env_key]
    secrets = {n: environ[env_prefix + n.upper()] for n in secret_names if env_prefix + n.upper() in environ}
    return Settings(values, secrets, profile)
