"""Template Engine (MOD-05): versioned templates, validated inputs, safe, deterministic rendering.

Rendering only substitutes {{variable}} placeholders. No template code is ever executed.
"""
from __future__ import annotations

import keyword
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from app_forge import __version__
from app_forge.domain.errors import ValidationFailure
from app_forge.domain.models import ARCHETYPES

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "data" / "templates"
_VAR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{1,63}$")
_SAFE_TEXT = re.compile(r'^[^"\\\r\n]{0,200}$')
_PY_VERSION = re.compile(r"^3\.(\d{1,2})$")


def render_text(text: str, variables: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            raise ValidationFailure(f"Template references unknown variable {{{{{key}}}}}")
        return variables[key]
    return _VAR.sub(sub, text)


def slugify_package(name: str) -> str:
    pkg = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not pkg or pkg[0].isdigit():
        pkg = "app_" + pkg
    return pkg


def package_name_problems(pkg: str) -> list[str]:
    out = []
    if not pkg.isidentifier():
        out.append(f"package name {pkg!r} is not a valid Python identifier")
    if keyword.iskeyword(pkg):
        out.append(f"package name {pkg!r} is a Python keyword")
    return out


def package_names(pkgs: list[str] | tuple[str, ...]) -> list[str]:
    return [re.split(r"[<>=!~;\[ ]", p, maxsplit=1)[0].strip().lower().replace("_", "-") for p in pkgs]


def add_dependencies(pyproject_text: str, packages: list[str]) -> tuple[str | None, list[str]]:
    """Add packages to [project].dependencies. Returns (new_text|None, added). None = cannot edit safely."""
    m = re.search(r"(?ms)^dependencies\s*=\s*\[\n(.*?)^\]", pyproject_text)
    if not m:
        return None, []
    existing = set(package_names(re.findall(r'"([^"]+)"', m.group(1))))
    added, lines = [], ""
    for p in packages:
        if package_names([p])[0] not in existing:
            lines += f'    "{p}",\n'
            added.append(p)
            existing.add(package_names([p])[0])
    if not added:
        return pyproject_text, []
    return pyproject_text[:m.end(1)] + lines + pyproject_text[m.end(1):], added


def remove_dependencies(pyproject_text: str, packages: list[str]) -> str | None:
    names = set(package_names(packages))
    m = re.search(r"(?ms)^dependencies\s*=\s*\[\n(.*?)^\]", pyproject_text)
    if not m:
        return None
    kept = []
    for line in m.group(1).splitlines(keepends=True):
        match = re.search(r'"([^"]+)"', line)
        if match is None or package_names([match.group(1)])[0] not in names:
            kept.append(line)
    return pyproject_text[:m.start(1)] + "".join(kept) + pyproject_text[m.end(1):]


@dataclass
class TemplateInfo:
    id: str
    name: str
    version: str
    archetype: str
    summary: str
    python_packages: list[str]
    dev_packages: list[str]
    entry_module: str
    entry_function: str
    root: Path
    standalone: bool = False
    archetypes: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "version": self.version, "archetype": self.archetype,
                "summary": self.summary, "archetypes": list(self.archetypes or (self.archetype,)),
                "includes": list(self.includes), "python_packages": self.python_packages,
                "dev_packages": self.dev_packages,
                "inputs": ["name (required)", "package", "description", "author", "python_version"]}


class TemplateEngine:
    def __init__(self, roots: list[Path] | None = None):
        self._roots = roots or [TEMPLATES_ROOT]

    def _load(self, tdir: Path) -> TemplateInfo:
        data = tomllib.loads((tdir / "template.toml").read_text(encoding="utf-8"))
        t, d, e = data.get("template", {}), data.get("dependencies", {}), data.get("entry", {})
        problems = [f"missing template.{k}" for k in ("id", "name", "version", "archetype", "summary") if k not in t]
        if t.get("archetype") not in ARCHETYPES:
            problems.append(f"template.archetype must be one of {ARCHETYPES}")
        if not e.get("module") or not e.get("function"):
            problems.append("entry.module and entry.function are required")
        archetypes = t.get("archetypes", [t.get("archetype")])
        includes = t.get("includes", [])
        if not isinstance(archetypes, list) or not archetypes or any(a not in ARCHETYPES for a in archetypes):
            problems.append(f"template.archetypes must be a non-empty list drawn from {ARCHETYPES}")
            archetypes = [t.get("archetype")]
        if t.get("archetype") not in archetypes:
            problems.append("template.archetype must be included in template.archetypes")
        if not isinstance(includes, list) or any(not isinstance(item, str) or not item for item in includes):
            problems.append("template.includes must be a list of non-empty template IDs")
            includes = []
        if problems:
            raise ValidationFailure(f"Invalid template at {tdir}", details=problems)
        return TemplateInfo(t["id"], t["name"], t["version"], t["archetype"], t["summary"],
                            list(d.get("python_packages", [])), list(d.get("dev_packages", [])),
                            e["module"], e["function"], tdir, bool(t.get("standalone", False)),
                            tuple(archetypes), tuple(includes))

    def list(self) -> list[TemplateInfo]:
        out = []
        for root in self._roots:
            for tdir in sorted(root.glob("*/template.toml")):
                if not tdir.parent.name.startswith("_"):
                    out.append(self._load(tdir.parent))
        return out

    def get(self, template_id: str, version: str | None = None) -> TemplateInfo:
        """Resolve a template by ID, optionally pinning an exact version (ID@VERSION is also accepted).

        An unpinned ID selects the newest available version, so adding a version never makes
        template selection depend on filesystem traversal order.
        """
        if "@" in template_id:
            if version is not None:
                raise ValidationFailure("Specify a template version either as ID@VERSION or --version, not both")
            template_id, version = template_id.rsplit("@", 1)
            if not version:
                raise ValidationFailure("Template version after '@' must not be empty")
        templates = self.list()
        matches = [t for t in templates if t.id == template_id]
        if not matches and version is None:
            matches = [t for t in templates if t.archetype == template_id and len(t.archetypes or (t.archetype,)) == 1]
        if version is not None:
            matches = [t for t in matches if t.version == version]
        if not matches:
            requested = f"{template_id}@{version}" if version else template_id
            raise ValidationFailure(f"Unknown template or archetype {requested!r}",
                                    hint="Run: forge template list")
        def version_key(info: TemplateInfo) -> tuple[int, ...]:
            try:
                return tuple(int(part) for part in info.version.split("."))
            except ValueError:
                return (0,)
        return max(matches, key=version_key)

    def validate_inputs(self, info: TemplateInfo, raw: dict) -> dict[str, Any]:
        p: list[str] = []
        name = str(raw.get("name", ""))
        if not _NAME.match(name):
            p.append("name must be 2-64 chars: a letter, then letters, digits, space, '_' or '-'")
        package = str(raw.get("package") or slugify_package(name))
        p += package_name_problems(package)
        desc = str(raw.get("description") or f"{name} - generated by Python App Forge")
        author = str(raw.get("author") or "Unknown")
        for label, value in (("description", desc), ("author", author)):
            if not _SAFE_TEXT.match(value):
                p.append(f"{label} must be under 200 chars and contain no quotes, backslashes or newlines")
        pyv = str(raw.get("python_version") or "3.11")
        if not _PY_VERSION.match(pyv) or int(pyv.split(".")[1]) < 11:
            p.append("python_version must be 3.11 or newer, e.g. 3.12")
        if p:
            raise ValidationFailure("Invalid project configuration", details=p)
        dist = package.replace("_", "-")
        return {"name": name, "package": package, "dist": dist, "description": desc, "author": author,
                "python_version": pyv, "archetype": info.archetype,
                "archetypes": list(info.archetypes or (info.archetype,)), "template_version": info.version,
                "forge_version": __version__, "entry_module": info.entry_module,
                "entry_function": info.entry_function}

    def expand(self, info: TemplateInfo) -> List[TemplateInfo]:
        """Resolve a bundle's pinned template dependencies in deterministic, cycle-safe order."""
        ordered: list[TemplateInfo] = []
        seen: set[tuple[str, str]] = set()
        versions: dict[str, str] = {}
        visiting: list[str] = []

        def visit(current: TemplateInfo) -> None:
            if current.id in visiting:
                raise ValidationFailure("Template include cycle: " + " -> ".join([*visiting, current.id]))
            identity = (current.id, current.version)
            if current.id in versions and versions[current.id] != current.version:
                raise ValidationFailure(f"Template bundle includes multiple versions of {current.id!r}")
            if identity in seen:
                return
            versions[current.id] = current.version
            visiting.append(current.id)
            for include in current.includes:
                visit(self.get(include))
            visiting.pop()
            seen.add(identity)
            ordered.append(current)

        visit(info)
        actual_archetypes = {a for item in ordered for a in (item.archetypes or (item.archetype,))}
        declared_archetypes = set(info.archetypes or (info.archetype,))
        if actual_archetypes != declared_archetypes:
            raise ValidationFailure(
                f"Template {info.id!r} declares archetypes {sorted(declared_archetypes)} "
                f"but its included templates provide {sorted(actual_archetypes)}")
        return ordered

    def render(self, info: TemplateInfo, variables: dict[str, Any]) -> dict[str, str]:
        """Render all included template trees into one shared package without overwriting collisions."""
        expanded = self.expand(info)
        variables = dict(variables)
        python_packages = list(dict.fromkeys(p for item in expanded for p in item.python_packages))
        dev_packages = list(dict.fromkeys(p for item in expanded for p in item.dev_packages))

        def block(pkgs: list[str]) -> str:
            return "".join(f'    "{p}",\n' for p in pkgs)
        variables["dependencies_block"] = block(python_packages)
        variables["dev_dependencies_block"] = block(dev_packages)
        render_variables = {key: value for key, value in variables.items() if isinstance(value, str)}
        files: dict[str, str] = {}
        common_originals: dict[str, str] = {}
        common_overridden: set[str] = set()
        common_added = False
        for item in expanded:
            common = item.root.parent / "_common" / "tree"
            if not common.is_dir():
                common = TEMPLATES_ROOT / "_common" / "tree"
            trees = [item.root / "tree"] if item.standalone else (
                ([] if common_added else [common]) + [item.root / "tree"])
            if not item.standalone:
                common_added = True
            for tree in trees:
                if not tree.is_dir():
                    continue
                is_common = tree == common and not item.standalone
                for src in sorted(p for p in tree.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                                  and p.suffix not in (".pyc", ".pyo")):
                    parts = []
                    for part in src.relative_to(tree).parts:
                        part = "." + part[4:] if part.startswith("dot_") else part
                        parts.append(part.replace("__package__", variables["package"]))
                    rel = "/".join(parts)
                    content = render_text(src.read_text(encoding="utf-8"), render_variables)
                    if is_common:
                        common_originals[rel] = content
                        files[rel] = content
                        continue
                    # Exported standalone bundles contain a materialized copy of common files.
                    # Do not let that copy erase a more specific included-template override.
                    if item.standalone and item.includes and rel in common_originals and content == common_originals[rel]:
                        continue
                    # A bundle's own standalone tree is the final, explicit override layer.
                    if item is info and item.standalone and item.includes and rel in common_originals:
                        files[rel] = content
                        common_overridden.add(rel)
                        continue
                    if rel in common_originals and rel not in common_overridden:
                        files[rel] = content
                        common_overridden.add(rel)
                    elif rel in files and files[rel] != content:
                        raise ValidationFailure(f"Included templates both define {rel!r} with different content")
                    else:
                        files[rel] = content
        return dict(sorted(files.items()))
