"""Reading and writing the metadata Forge keeps inside a project (forge.toml, .forge/components.toml)."""
from __future__ import annotations

import tomllib
from pathlib import Path

from app_forge import tomlw

FORGE_TOML = "forge.toml"
COMPONENTS_TOML = ".forge/components.toml"


def read_forge_toml(root: Path) -> dict | None:
    p = root / FORGE_TOML
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def read_components(root: Path) -> dict:
    p = root / COMPONENTS_TOML
    data = tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    return {"components": list(data.get("components", [])), "managed_files": list(data.get("managed_files", [])),
            "patches": list(data.get("patches", []))}


def components_text(data: dict) -> str:
    body: dict[str, object] = {"schema_version": 1}
    if data["components"]:
        body["components"] = sorted(data["components"], key=lambda c: c["id"])
    if data["managed_files"]:
        body["managed_files"] = sorted(data["managed_files"], key=lambda f: f["path"])
    if data.get("patches"):
        body["patches"] = sorted(data["patches"], key=lambda r: (r["component"], r["id"]))
    return tomlw.dumps(body)


def forge_toml_text(variables: dict, template_id: str, template_version: str) -> str:
    return tomlw.dumps({
        "schema_version": 1,
        "project": {"name": variables["name"], "package": variables["package"], "archetype": variables["archetype"],
                    "python": variables["python_version"], "description": variables["description"],
                    "author": variables["author"]},
        "template": {"id": template_id, "version": template_version},
        "generator": {"forge_version": variables["forge_version"]},
    })
