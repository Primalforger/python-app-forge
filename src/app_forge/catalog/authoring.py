"""Component authoring tools (G-07): scaffold, validate, pack and add components to a catalog."""
from __future__ import annotations

import shutil
import tempfile
import tomllib
import zipfile
from pathlib import Path

from app_forge.catalog.registry import compute_artifact_digest, seal_component
from app_forge.domain.errors import ConflictFailure, SecurityBlock, ValidationFailure
from app_forge.domain.models import ARCHETYPES, CATEGORIES, ID_RE, parse_manifest
from app_forge.security import redact, safe_join
from app_forge.templates.engine import render_text

ZIP_TIME = (2020, 1, 1, 0, 0, 0)  # fixed so packing is reproducible


def module_name(component_id: str) -> str:
    return component_id.split(".")[-1].replace("-", "_")


def scaffold_component(out_root: Path, component_id: str, *, archetypes: list[str] | None = None,
                       category: str = "tooling", summary: str = "", publisher: str = "Your Name",
                       version: str = "1.0.0") -> Path:
    archetypes = archetypes or list(ARCHETYPES)
    problems = []
    if not ID_RE.match(component_id):
        problems.append(f"id must match {ID_RE.pattern}")
    if category not in CATEGORIES:
        problems.append(f"category must be one of {CATEGORIES}")
    problems += [f"unknown archetype {a!r}" for a in archetypes if a not in ARCHETYPES]
    if problems:
        raise ValidationFailure("Cannot scaffold component", details=problems)
    vdir = Path(out_root) / component_id / version
    if vdir.exists():
        raise ConflictFailure(f"{vdir} already exists")
    mod = module_name(component_id)
    (vdir / "files" / "src").mkdir(parents=True)
    (vdir / "files" / "tests").mkdir(parents=True)
    (vdir / "files" / "src" / f"{mod}.py").write_text(
        f'"""{summary or component_id}."""\nfrom __future__ import annotations\n\n\ndef hello() -> str:\n'
        f'    return "hello from {component_id}"\n', encoding="utf-8")
    (vdir / "files" / "tests" / f"test_{mod}.py").write_text(
        f"import unittest\n\nfrom {{{{package}}}}.{mod} import hello\n\n\nclass {mod.title().replace('_', '')}Tests(unittest.TestCase):\n"
        f"    def test_hello(self):\n        self.assertIn(\"hello\", hello())\n", encoding="utf-8")
    arr = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
    (vdir / "component.toml").write_text(f'''schema_version = 1

[component]
id = "{component_id}"
name = "{component_id.split('.')[-1].replace('-', ' ').title()}"
version = "{version}"
summary = "{summary or 'Describe what this component adds.'}"
category = "{category}"
artifact_type = "generated-project-component"
keywords = []
documentation = "Describe how to use the contributed files."

[ownership]
publisher = "{publisher}"
contact = ""

[licensing]
license = "MIT"
third_party = []

[compatibility]
python = ">=3.11"
platforms = ["windows", "linux", "macos"]
archetypes = {arr(archetypes)}
platform_api = "1"

[dependencies]
python_packages = []

[dependencies.components]

[interfaces]
provides = []
requires = []

[configuration]
secrets = []

[configuration.defaults]

[[integration.files]]
src = "files/src/{mod}.py"
dest = "src/{{{{package}}}}/{mod}.py"

[[integration.files]]
src = "files/tests/test_{mod}.py"
dest = "tests/test_{mod}.py"

# To edit an existing file, add a patch (see docs/component-authoring.md):
# [[integration.patches]]
# id = "my-hook"
# file = "src/{{{{package}}}}/cli.py"
# kind = "insert"
# anchor = "commands"
# content = \'\'\'
# ...code...
# \'\'\'

[lifecycle]
install = "copy-files"
removal = true
upgrade = "remove-and-add"
migrations = []

[verification]
tests = ["tests/test_{mod}.py"]

[security]
trust = "trusted"
permissions = ["filesystem.project"]
network = false
advisories = []

[provenance]
source = "local"
digest = "sha256:{'0' * 64}"

[support]
status = "preview"
compatibility_window = ""
known_limitations = []
''', encoding="utf-8")
    seal_component(vdir)
    return vdir


def validate_component_dir(vdir: Path) -> dict:
    vdir = Path(vdir)
    problems: list[str] = []
    warnings: list[str] = []
    result = {"path": str(vdir), "component": None, "digest": None}
    mf = vdir / "component.toml"
    if not mf.is_file():
        return {**result, "ok": False, "problems": [f"{mf} not found (point at <id>/<version>)"], "warnings": []}
    try:
        manifest = parse_manifest(tomllib.loads(mf.read_text(encoding="utf-8")))
    except tomllib.TOMLDecodeError as exc:
        return {**result, "ok": False, "problems": [f"invalid TOML: {exc}"], "warnings": []}
    except ValidationFailure as exc:
        return {**result, "ok": False, "problems": exc.details or [exc.message], "warnings": []}
    result["component"] = f"{manifest.id}@{manifest.version}"
    if vdir.parent.name != manifest.id or vdir.name != manifest.version:
        problems.append(f"directory must be <{manifest.id}>/<{manifest.version}>/, found {vdir.parent.name}/{vdir.name}")
    actual = compute_artifact_digest(vdir)
    result["digest"] = actual
    if actual != manifest.digest:
        problems.append("provenance.digest does not match the files and manifest: run `forge component seal`")
    dests: dict[str, str] = {}
    for f in manifest.files:
        if not f.src.startswith("files/"):
            problems.append(f"integration.files src {f.src!r} must live under files/")
            continue
        try:
            src = safe_join(vdir, f.src)
        except SecurityBlock as exc:
            problems.append(exc.message)
            continue
        if not src.is_file():
            problems.append(f"integration.files src {f.src!r} does not exist")
            continue
        if f.dest in dests:
            problems.append(f"destination {f.dest!r} is written by more than one entry")
        dests[f.dest] = f.src
        try:
            text = src.read_text(encoding="utf-8")
            rendered = render_text(text, {"package": "sample_pkg"})
        except UnicodeDecodeError:
            problems.append(f"{f.src} is not UTF-8 text (binary assets are not supported yet)")
            continue
        except ValidationFailure as exc:
            problems.append(f"{f.src}: {exc.message}")
            continue
        if f.dest.endswith(".py"):
            try:
                compile(rendered, f.src, "exec")
            except SyntaxError as exc:
                problems.append(f"{f.src} is not valid Python after rendering: {exc.msg} (line {exc.lineno})")
        if redact(rendered) != rendered:
            warnings.append(f"{f.src} contains something that looks like a secret; never ship credentials")
    for t in manifest.verification_tests:
        if t not in dests:
            problems.append(f"verification test {t!r} is not contributed by any integration.files entry")
    if not manifest.verification_tests:
        warnings.append("no verification tests declared; `forge component verify` will prove very little")
    for patch in manifest.patches:
        try:
            body = render_text(patch.content, {"package": "sample_pkg"}) if patch.content else ""
            if patch.kind == "toml-table":
                tomllib.loads(body)
                if not body.lstrip().startswith(("[", "#")):
                    problems.append(f"patch {patch.id}: toml-table content must consist of tables only")
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"patch {patch.id}: content is not valid TOML: {exc}")
        except ValidationFailure as exc:
            problems.append(f"patch {patch.id}: {exc.message}")
    if manifest.network and "network" not in manifest.permissions:
        problems.append("network access must be declared in permissions")
    if manifest.trust == "builtin":
        warnings.append("trust 'builtin' is reserved for components shipped with App Forge")
    return {**result, "ok": not problems, "problems": problems, "warnings": warnings}


def pack_component(vdir: Path, out_zip: Path) -> Path:
    report = validate_component_dir(vdir)
    if not report["ok"]:
        raise ValidationFailure("Refusing to pack an invalid component", details=report["problems"])
    manifest = parse_manifest(tomllib.loads((Path(vdir) / "component.toml").read_text(encoding="utf-8")))
    prefix = f"{manifest.id}/{manifest.version}"
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    members = [Path(vdir) / "component.toml"] + sorted(
        p for p in (Path(vdir) / "files").rglob("*") if p.is_file() and "__pycache__" not in p.parts
        and p.suffix not in (".pyc", ".pyo"))
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in members:
            info = zipfile.ZipInfo(f"{prefix}/{p.relative_to(vdir).as_posix()}", ZIP_TIME)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, p.read_bytes())
    return out_zip


def _extract_safely(zip_path: Path, dest: Path) -> Path:
    with zipfile.ZipFile(zip_path) as z:
        roots = set()
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            parts = name.split("/")
            if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise SecurityBlock(f"Unsafe path in archive: {info.filename!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SecurityBlock(f"Archive contains a symlink: {info.filename!r}")
            if len(parts) >= 2:
                roots.add("/".join(parts[:2]))
        if len(roots) != 1:
            raise ValidationFailure("Archive must contain exactly one <id>/<version>/ component")
        z.extractall(dest)
    return dest / next(iter(roots))


def add_to_catalog(src: Path, catalog_root: Path) -> dict:
    """Validate a component directory or .zip and copy it into a catalog root. Never overwrites."""
    src = Path(src)
    with tempfile.TemporaryDirectory() as tmp:
        vdir = _extract_safely(src, Path(tmp)) if src.is_file() and src.suffix == ".zip" else src
        if any(p.is_symlink() for p in vdir.rglob("*")):
            raise SecurityBlock("Components containing symlinks are not added")
        report = validate_component_dir(vdir)
        if not report["ok"]:
            raise ValidationFailure("Component failed validation", details=report["problems"])
        manifest = parse_manifest(tomllib.loads((vdir / "component.toml").read_text(encoding="utf-8")))
        dest = Path(catalog_root) / manifest.id / manifest.version
        if dest.exists():
            raise ConflictFailure(f"{manifest.id}@{manifest.version} is already in the catalog (versions are immutable)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(vdir, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return {"added": f"{manifest.id}@{manifest.version}", "path": str(dest), "warnings": report["warnings"]}
