"""Core domain concepts: components, change plans, evidence, requirements."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from app_forge.domain.errors import ValidationFailure
from app_forge.domain.interfaces import parse_interface, validate_interface_declarations
from app_forge.domain.versioning import Constraint, Version, is_semver

ARCHETYPES = ("desktop", "web", "cli", "service")
PLATFORMS = ("windows", "linux", "macos")
CATEGORIES = ("ui", "data-presentation", "input", "storage", "api", "operations", "security",
              "quality", "tooling", "automation")
ARTIFACT_TYPES = ("platform-component", "generated-project-component", "external-dependency", "template")
TRUST_LEVELS = ("builtin", "trusted", "untrusted")
PERMISSIONS = ("filesystem.project", "filesystem.user", "network", "process", "credentials")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")


@dataclass(frozen=True)
class FileContribution:
    src: str
    dest: str  # may contain {{package}}
    binary: bool = False


PATCH_KINDS = ("insert", "toml-table", "json-merge", "yaml-merge", "framework-register")
COMMENT_STYLES = ("#", "//", "--", ";", "%")
PATCH_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
ANCHOR_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


@dataclass(frozen=True)
class Patch:
    """An edit to an existing file. `insert` adds a marked block at a named anchor; `toml-table` appends new
    tables; `json-merge` adds missing keys. Kinds are deliberately conservative: they add, they never rewrite."""
    id: str
    file: str  # may contain {{package}}
    kind: str
    anchor: str = ""
    position: str = "after"
    comment: str = "#"
    content: str = ""
    data: dict = field(default_factory=dict)
    registration: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InterfaceContract:
    interface: str
    tests: tuple[str, ...]


@dataclass(frozen=True)
class ComponentManifest:
    id: str
    name: str
    version: str
    schema_version: int
    summary: str
    category: str
    artifact_type: str
    keywords: tuple[str, ...]
    documentation: str
    publisher: str
    contact: str
    license: str
    third_party_licenses: tuple[str, ...]
    python: str
    platforms: tuple[str, ...]
    archetypes: tuple[str, ...]
    platform_api: str
    requires: dict[str, str]
    optional: dict[str, str]
    python_packages: tuple[str, ...]
    provides: tuple[str, ...]
    requires_interfaces: tuple[str, ...]
    interface_contract_tests: tuple[InterfaceContract, ...]
    config_defaults: dict[str, Any]
    secrets: tuple[str, ...]
    files: tuple[FileContribution, ...]
    patches: tuple[Patch, ...]
    lifecycle: dict[str, Any]
    verification_tests: tuple[str, ...]
    trust: str
    permissions: tuple[str, ...]
    network: bool
    advisories: tuple[str, ...]
    source: str
    digest: str
    status: str
    compatibility_window: str
    known_limitations: tuple[str, ...]

    @property
    def semver(self) -> Version:
        return Version.parse(self.version)

    def capabilities(self) -> list[str]:
        return [p.split("@")[0] for p in self.provides]

    def to_dict(self) -> dict:
        return asdict(self)


def _req(d: dict, key: str, kind: type, problems: list[str], where: str = "") -> Any:
    if key not in d:
        problems.append(f"missing required field '{where}{key}'")
        return None
    if not isinstance(d[key], kind):
        problems.append(f"field '{where}{key}' must be {kind.__name__}")
        return None
    return d[key]


def _portable_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        return "path must be a non-empty relative path"
    if value.startswith("/") or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return "path must be relative and use forward-slash separators"
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "path contains an unsafe segment"
    for part in parts:
        if part.endswith((".", " ")) or any(ord(ch) < 32 or ch in '<>:\"|?*' for ch in part):
            return "path contains a character unsupported on Windows"
        if part.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            return "path contains a reserved Windows device name"
    return ""


def parse_manifest(data: dict) -> ComponentManifest:
    """Validate a manifest dict (schema v1). Nothing is inferred; missing required values fail."""
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    c = data.get("component", {})
    own, lic, comp = data.get("ownership", {}), data.get("licensing", {}), data.get("compatibility", {})
    dep, ifc = data.get("dependencies", {}), data.get("interfaces", {})
    conf, integ = data.get("configuration", {}), data.get("integration", {})
    life, ver = data.get("lifecycle", {}), data.get("verification", {})
    sec, prov, sup = data.get("security", {}), data.get("provenance", {}), data.get("support", {})

    cid = _req(c, "id", str, p, "component.")
    if cid and not ID_RE.match(cid):
        p.append(f"component.id {cid!r} must match {ID_RE.pattern}")
    name = _req(c, "name", str, p, "component.")
    version = _req(c, "version", str, p, "component.")
    if version and not is_semver(version):
        p.append(f"component.version {version!r} is not MAJOR.MINOR.PATCH")
    summary = _req(c, "summary", str, p, "component.")
    category = _req(c, "category", str, p, "component.")
    if category and category not in CATEGORIES:
        p.append(f"component.category must be one of {CATEGORIES}")
    atype = c.get("artifact_type", "generated-project-component")
    if atype not in ARTIFACT_TYPES:
        p.append(f"component.artifact_type must be one of {ARTIFACT_TYPES}")
    publisher = _req(own, "publisher", str, p, "ownership.")
    license_ = _req(lic, "license", str, p, "licensing.")
    python = _req(comp, "python", str, p, "compatibility.")
    archetypes = _req(comp, "archetypes", list, p, "compatibility.") or []
    platforms = _req(comp, "platforms", list, p, "compatibility.") or []
    for a in archetypes:
        if a not in ARCHETYPES:
            p.append(f"unknown archetype {a!r}")
    for pl in platforms:
        if pl not in PLATFORMS:
            p.append(f"unknown platform {pl!r}")
    if python:
        try:
            Constraint.parse(python)
        except ValidationFailure as e:
            p.append(f"compatibility.python: {e.message}")
    requires = dict(dep.get("components", {}))
    optional = dict(dep.get("optional", {}))
    for k, v in {**requires, **optional}.items():
        try:
            Constraint.parse(v)
        except ValidationFailure as e:
            p.append(f"dependency {k}: {e.message}")
    files = []
    source_names: dict[str, str] = {}
    destination_names: dict[str, str] = {}
    for f in integ.get("files", []):
        if not isinstance(f, dict) or "src" not in f or "dest" not in f:
            p.append("each integration.files entry needs 'src' and 'dest'")
            continue
        src, dest = f["src"], f["dest"]
        for field_name, path_value in (("integration.files src", src), ("integration.files dest", dest)):
            error = _portable_relative_path(path_value)
            if error:
                p.append(f"{field_name} {path_value!r}: {error}")
        if isinstance(src, str):
            folded = src.casefold()
            if folded in source_names and source_names[folded] != src:
                p.append(f"integration.files sources {source_names[folded]!r} and {src!r} collide on case-insensitive filesystems")
            source_names[folded] = src
        if isinstance(dest, str):
            folded = dest.replace("{{package}}", "__forge_package__").casefold()
            if folded in destination_names:
                p.append(f"integration.files destinations {destination_names[folded]!r} and {dest!r} collide on case-insensitive filesystems")
            destination_names[folded] = dest
        if "binary" in f and not isinstance(f["binary"], bool):
            p.append(f"integration.files binary flag for {src!r} must be boolean")
        files.append(FileContribution(src, dest, f.get("binary", False)))
    patches, seen_ids = [], set()
    for i, raw in enumerate(integ.get("patches", [])):
        where = f"integration.patches[{i}]"
        if not isinstance(raw, dict):
            p.append(f"{where} must be a table")
            continue
        pid, kind, pfile = raw.get("id", ""), raw.get("kind", ""), raw.get("file", "")
        if not PATCH_ID_RE.match(str(pid)):
            p.append(f"{where}.id {pid!r} must match {PATCH_ID_RE.pattern}")
        if pid in seen_ids:
            p.append(f"{where}.id {pid!r} is duplicated")
        seen_ids.add(pid)
        if kind not in PATCH_KINDS:
            p.append(f"{where}.kind must be one of {PATCH_KINDS}")
        if not pfile or str(pfile).startswith("/") or ".." in str(pfile).replace("\\", "/").split("/"):
            p.append(f"{where}.file {pfile!r} must be a relative path without '..'")
        else:
            path_error = _portable_relative_path(pfile)
            if path_error:
                p.append(f"{where}.file {pfile!r}: {path_error}")
        comment, position = raw.get("comment", "#"), raw.get("position", "after")
        if comment not in COMMENT_STYLES:
            p.append(f"{where}.comment must be one of {COMMENT_STYLES}")
        if kind == "insert":
            if not ANCHOR_RE.match(str(raw.get("anchor", ""))):
                p.append(f"{where}.anchor must match {ANCHOR_RE.pattern}")
            if position not in ("before", "after"):
                p.append(f"{where}.position must be 'before' or 'after'")
            if not str(raw.get("content", "")).strip():
                p.append(f"{where}.content is required for insert patches")
        elif kind == "toml-table" and not str(raw.get("content", "")).strip():
            p.append(f"{where}.content is required for toml-table patches")
        elif kind in ("json-merge", "yaml-merge") and not (isinstance(raw.get("data"), dict) and raw["data"]):
            p.append(f"{where}.data (a non-empty table) is required for {kind} patches")
        registration = raw.get("registration", {})
        if kind == "framework-register":
            if not isinstance(registration, dict):
                p.append(f"{where}.registration must be a table")
                registration = {}
            framework = registration.get("framework")
            if framework not in ("fastapi", "flask", "django"):
                p.append(f"{where}.registration.framework must be fastapi|flask|django")
            for key in ("module", "symbol"):
                value = registration.get(key, "")
                if not isinstance(value, str) or not value or not all(part.isidentifier() for part in value.replace("{{package}}", "forge_package").split(".")):
                    p.append(f"{where}.registration.{key} must be a dotted Python identifier")
            application = registration.get("application", "")
            if application and (not isinstance(application, str) or not application.isidentifier()):
                p.append(f"{where}.registration.application must be a Python identifier")
            route = registration.get("route", "")
            if not isinstance(route, str) or any(ch in route for ch in '\\r\\n"\\\\'):
                p.append(f"{where}.registration.route must be a simple URL prefix")
            if comment != "#":
                p.append(f"{where}.comment must be '#' for Python framework registrations")
        patches.append(Patch(str(pid), str(pfile), str(kind), str(raw.get("anchor", "")), position, comment,
                             str(raw.get("content", "")), dict(raw.get("data", {})) if isinstance(raw.get("data"), dict) else {},
                             dict(registration) if isinstance(registration, dict) else {}))
    trust = _req(sec, "trust", str, p, "security.")
    if trust and trust not in TRUST_LEVELS:
        p.append(f"security.trust must be one of {TRUST_LEVELS}")
    perms = sec.get("permissions", [])
    for perm in perms:
        if perm not in PERMISSIONS:
            p.append(f"unknown permission {perm!r}")
    network = _req(sec, "network", bool, p, "security.")
    if network and "network" not in perms:
        p.append("security.network=true requires 'network' in security.permissions")
    digest = _req(prov, "digest", str, p, "provenance.")
    if digest and not DIGEST_RE.match(digest):
        p.append("provenance.digest must look like sha256:<64 hex chars>")
    source = _req(prov, "source", str, p, "provenance.")
    status = _req(sup, "status", str, p, "support.")
    if status and status not in ("stable", "preview", "deprecated"):
        p.append("support.status must be stable|preview|deprecated")
    interface_problems = validate_interface_declarations(
        tuple(ifc.get("provides", [])), tuple(ifc.get("requires", []))
    )
    p.extend(interface_problems)
    contract_tests: list[InterfaceContract] = []
    seen_contracts: set[str] = set()
    provided = set(ifc.get("provides", []))
    raw_contracts = ifc.get("contract_tests", [])
    if not isinstance(raw_contracts, list):
        p.append("interfaces.contract_tests must be an array of tables")
        raw_contracts = []
    for i, raw in enumerate(raw_contracts):
        where = f"interfaces.contract_tests[{i}]"
        if not isinstance(raw, dict):
            p.append(f"{where} must be a table")
            continue
        interface, tests = raw.get("interface"), raw.get("tests")
        if not isinstance(interface, str) or interface not in provided:
            p.append(f"{where}.interface must exactly match an entry in interfaces.provides")
        if isinstance(interface, str) and interface in seen_contracts:
            p.append(f"{where}.interface {interface!r} is duplicated")
        if isinstance(interface, str):
            seen_contracts.add(interface)
        if not isinstance(tests, list) or not tests or any(not isinstance(t, str) or not t.strip() for t in tests):
            p.append(f"{where}.tests must be a non-empty array of relative test paths")
            tests = []
        for test in tests:
            normalized = test.replace("\\", "/")
            if normalized.startswith("/") or "\x00" in test or ".." in normalized.split("/"):
                p.append(f"{where}.tests contains unsafe path {test!r}")
        if isinstance(interface, str) and isinstance(tests, list):
            contract_tests.append(InterfaceContract(interface, tuple(tests)))
    if p:
        raise ValidationFailure(f"Invalid component manifest ({cid or '?'})", details=p)
    return ComponentManifest(
        id=cid, name=name, version=version, schema_version=1, summary=summary, category=category,
        artifact_type=atype, keywords=tuple(c.get("keywords", [])), documentation=c.get("documentation", ""),
        publisher=publisher, contact=own.get("contact", ""), license=license_,
        third_party_licenses=tuple(lic.get("third_party", [])), python=python,
        platforms=tuple(platforms), archetypes=tuple(archetypes), platform_api=str(comp.get("platform_api", "1")),
        requires=requires, optional=optional, python_packages=tuple(dep.get("python_packages", [])),
        provides=tuple(ifc.get("provides", [])), requires_interfaces=tuple(ifc.get("requires", [])),
        interface_contract_tests=tuple(contract_tests),
        config_defaults=dict(conf.get("defaults", {})), secrets=tuple(conf.get("secrets", [])),
        files=tuple(files), patches=tuple(patches), lifecycle=dict(life), verification_tests=tuple(ver.get("tests", [])),
        trust=trust, permissions=tuple(perms), network=bool(network), advisories=tuple(sec.get("advisories", [])),
        source=source, digest=digest, status=status,
        compatibility_window=sup.get("compatibility_window", ""),
        known_limitations=tuple(sup.get("known_limitations", [])))


# ----- change plans -----------------------------------------------------------------------

@dataclass
class FileChange:
    action: str  # create | modify | delete | manual
    path: str
    reason: str = ""
    component: str = ""
    content: str | None = None
    before_sha: str | None = None
    after_sha: str | None = None
    content_encoding: str = "utf-8"
    mode: int | None = None


@dataclass
class ChangePlan:
    plan_id: str
    project_path: str
    kind: str  # add | remove
    level: int
    components: list[str]
    changes: list[FileChange] = field(default_factory=list)
    dependency_changes: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "planned"
    approved_by: str | None = None
    digest: str = ""
    created_at: str = ""

    def to_dict(self, include_content: bool = True) -> dict:
        d = asdict(self)
        if not include_content:
            for c in d["changes"]:
                c.pop("content", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ChangePlan":
        d = dict(d)
        d["changes"] = [FileChange(**c) for c in d.get("changes", [])]
        return cls(**d)


# ----- compliance -------------------------------------------------------------------------

class Status(str, Enum):
    NOT_ASSESSED = "Not assessed"
    NOT_APPLICABLE = "Not applicable"
    PLANNED = "Planned"
    IMPLEMENTED = "Implemented"
    VERIFIED = "Verified"
    FAILED = "Failed"
    BLOCKED = "Blocked"
    EXCEPTION = "Exception approved"


@dataclass
class Requirement:
    id: str
    title: str
    description: str = ""
    priority: str = "P0"
    source: str = ""
    method: str = "test"
    acceptance: str = ""
    parent: str = ""
    modules: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    verified_by: list[str] = field(default_factory=list)
    implemented: bool = False
    not_applicable: str = ""
    exception: dict = field(default_factory=dict)


@dataclass
class Evidence:
    run_id: str
    subject: str
    check_id: str
    status: str  # passed | failed | not_run
    detail: str = ""
    duration_s: float = 0.0
    recorded_at: str = ""
