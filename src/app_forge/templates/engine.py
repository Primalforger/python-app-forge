"""Template Engine (MOD-05): versioned templates, validated inputs, safe, deterministic rendering.

Rendering only substitutes {{variable}} placeholders. No template code is ever executed.
"""
from __future__ import annotations

import keyword
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

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
    kept = [ln for ln in m.group(1).splitlines(keepends=True)
            if not (re.search(r'"([^"]+)"', ln) and package_names([re.search(r'"([^"]+)"', ln).group(1)])[0] in names)]
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

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "version": self.version, "archetype": self.archetype,
                "summary": self.summary, "python_packages": self.python_packages,
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
        if problems:
            raise ValidationFailure(f"Invalid template at {tdir}", details=problems)
        return TemplateInfo(t["id"], t["name"], t["version"], t["archetype"], t["summary"],
                            list(d.get("python_packages", [])), list(d.get("dev_packages", [])),
                            e["module"], e["function"], tdir, bool(t.get("standalone", False)))

    def list(self) -> list[TemplateInfo]:
        out = []
        for root in self._roots:
            for tdir in sorted(root.glob("*/template.toml")):
                if not tdir.parent.name.startswith("_"):
                    out.append(self._load(tdir.parent))
        return out

    def get(self, template_id: str) -> TemplateInfo:
        for t in self.list():
            if t.id == template_id or t.archetype == template_id:
                return t
        raise ValidationFailure(f"Unknown template or archetype {template_id!r}",
                                hint="Run: forge template list")

    def validate_inputs(self, info: TemplateInfo, raw: dict) -> dict[str, str]:
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
                "python_version": pyv, "archetype": info.archetype, "template_version": info.version,
                "forge_version": __version__, "entry_module": info.entry_module,
                "entry_function": info.entry_function}

    def render(self, info: TemplateInfo, variables: dict[str, str]) -> dict[str, str]:
        """Return {relative_path: content}. Deterministic: no timestamps or randomness."""
        variables = dict(variables)

        def block(pkgs: list[str]) -> str:
            return "".join(f'    "{p}",\n' for p in pkgs)
        variables["dependencies_block"] = block(info.python_packages)
        variables["dev_dependencies_block"] = block(info.dev_packages)
        files: dict[str, str] = {}
        common = info.root.parent / "_common" / "tree"
        if not common.is_dir():
            common = TEMPLATES_ROOT / "_common" / "tree"  # user templates inherit the built-in common files
        trees = [info.root / "tree"] if info.standalone else [common, info.root / "tree"]
        for tree in trees:
            if not tree.is_dir():
                continue
            for src in sorted(p for p in tree.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                                  and p.suffix not in (".pyc", ".pyo")):
                parts = []
                for part in src.relative_to(tree).parts:
                    part = "." + part[4:] if part.startswith("dot_") else part
                    parts.append(part.replace("__package__", variables["package"]))
                files["/".join(parts)] = render_text(src.read_text(encoding="utf-8"), variables)
        return dict(sorted(files.items()))
