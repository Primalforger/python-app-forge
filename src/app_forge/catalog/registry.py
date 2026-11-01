"""Component Registry (MOD-06): local-first catalog. The SQLite index is a rebuildable cache."""
from __future__ import annotations

import json
import platform
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from app_forge.domain.errors import ForgeError, SecurityBlock, Unavailable, ValidationFailure
from app_forge.catalog.attestation import verify_component
from app_forge.domain.models import ComponentManifest, parse_manifest
from app_forge.domain.versioning import Constraint, Version
from app_forge.security import sha256_bytes

BUILTIN_COMPONENTS = Path(__file__).resolve().parent.parent / "data" / "components"

STATES = ("installed", "disabled", "revoked", "incompatible", "remote_unavailable", "cached")


def compute_digest(files_dir: Path) -> str:
    """Deterministic digest over relative paths and bytes of the component's files/ tree."""
    parts = []
    if files_dir.is_dir():
        for p in sorted(files_dir.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"):
                # bytecode caches are created by installers/interpreters and are not part of the artifact
                rel = p.relative_to(files_dir).as_posix()
                parts.append(rel.encode() + b"\0" + sha256_bytes(p.read_bytes()).encode() + b"\n")
    return "sha256:" + sha256_bytes(b"".join(parts))


_DIGEST_LINE = re.compile(r'(?m)^digest\s*=\s*"sha256:[0-9a-f]*"')


def compute_artifact_digest(version_dir: Path) -> str:
    """Digest over the files/ tree AND component.toml (with its own digest line neutralised).

    Editing any manifest field (paths, permissions, dependencies) after sealing changes this value.
    """
    manifest_text = (version_dir / "component.toml").read_bytes().decode("utf-8")
    normalised, n = _DIGEST_LINE.subn('digest = "sha256:' + "0" * 64 + '"', manifest_text)
    if n != 1:
        raise ValidationFailure(f"{version_dir / 'component.toml'} must contain exactly one provenance digest line")
    return "sha256:" + sha256_bytes((compute_digest(version_dir / "files") + "\n" + normalised).encode("utf-8"))


def seal_component(version_dir: Path) -> str:
    """Rewrite provenance.digest in component.toml so it covers files/ and the manifest. Release tool."""
    manifest = version_dir / "component.toml"
    text = manifest.read_bytes().decode("utf-8")
    digest = compute_artifact_digest(version_dir)
    new, n = _DIGEST_LINE.subn(f'digest = "{digest}"', text)
    if n != 1:
        raise ValidationFailure(f"{manifest} must contain exactly one provenance digest line")
    manifest.write_bytes(new.encode("utf-8"))
    return digest


def current_platform() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")


@dataclass
class CatalogEntry:
    manifest: ComponentManifest
    root: Path  # version directory
    source: str
    state: str = "installed"
    state_reason: str = ""

    @property
    def files_dir(self) -> Path:
        return self.root / "files"

    def summary(self) -> dict:
        m = self.manifest
        return {"id": m.id, "version": m.version, "name": m.name, "category": m.category,
                "summary": m.summary, "state": self.state, "state_reason": self.state_reason,
                "source": self.source, "archetypes": list(m.archetypes), "provides": list(m.provides),
                "trust": m.trust, "status": m.status}


@dataclass
class ScanResult:
    entries: list[CatalogEntry] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)
    remote_known: list[dict] = field(default_factory=list)


class ComponentRegistry:
    def __init__(self, roots: list[tuple[str, Path]], store, revocations_file: Path | None = None,
                 trusted_keys_dir: Path | None = None, unsigned_policy: str = "warn"):
        self._roots = roots
        self._store = store
        self._revocations_file = revocations_file
        self._trusted_keys_dir = trusted_keys_dir or Path(".") / "trusted-keys"
        self._unsigned_policy = unsigned_policy
        if unsigned_policy not in ("allow", "warn", "deny"):
            raise ValueError("unsigned_policy must be allow, warn, or deny")
        self._scan: ScanResult | None = None

    # -- loading ---------------------------------------------------------------------------
    def scan(self, refresh: bool = False) -> ScanResult:
        if self._scan is not None and not refresh:
            return self._scan
        res = ScanResult()
        revoked = self._load_revocations()
        disabled = self._store.disabled_components()
        for source, root in self._roots:
            if not root.is_dir():
                continue
            for mf in sorted(root.glob("*/*/component.toml")):
                vdir = mf.parent
                try:
                    data = tomllib.loads(mf.read_text(encoding="utf-8"))
                    manifest = parse_manifest(data)
                    if (vdir.parent.name != manifest.id) or (vdir.name != manifest.version):
                        raise ValidationFailure("directory layout must be <id>/<version>/component.toml "
                                                "and match the manifest id and version")
                    actual = compute_artifact_digest(vdir)
                    if actual != manifest.digest:
                        raise ValidationFailure("artifact digest mismatch",
                                                details=[f"manifest: {manifest.digest}", f"actual:   {actual}"])
                    signature = verify_component(vdir, self._trusted_keys_dir)
                    if signature["status"] == "unsigned" and self._unsigned_policy == "deny":
                        raise SecurityBlock("unsigned component rejected by unsigned_component_policy=deny")
                except (tomllib.TOMLDecodeError, ForgeError) as exc:
                    res.quarantined.append({"path": str(mf), "source": source, "error": str(exc),
                                            "details": getattr(exc, "details", [])})
                    continue
                entry = CatalogEntry(manifest, vdir, source)
                if signature["status"] == "unsigned" and self._unsigned_policy == "warn":
                    entry.state_reason = "unsigned artifact accepted by warning policy"
                key = (manifest.id, manifest.version)
                if key in revoked:
                    entry.state, entry.state_reason = "revoked", revoked[key]
                elif manifest.id in disabled:
                    entry.state, entry.state_reason = "disabled", "disabled by user"
                else:
                    reason = self._incompatibility(manifest)
                    if reason:
                        entry.state, entry.state_reason = "incompatible", reason
                res.entries.append(entry)
            ridx = root / "remote-index.toml"
            if ridx.is_file():
                try:
                    for item in tomllib.loads(ridx.read_text(encoding="utf-8")).get("known", []):
                        res.remote_known.append({**item, "state": "remote_unavailable", "source": source})
                except tomllib.TOMLDecodeError:
                    res.quarantined.append({"path": str(ridx), "source": source, "error": "invalid TOML"})
        self._scan = res
        return res

    def _load_revocations(self) -> dict[tuple[str, str], str]:
        out: dict[tuple[str, str], str] = {}
        f = self._revocations_file
        if f and f.is_file():
            try:
                for r in json.loads(f.read_text(encoding="utf-8")).get("revoked", []):
                    out[(r["id"], r["version"])] = (
                        f"{r.get('reason', 'revoked')} (source: {r.get('source', '?')}, "
                        f"as of {r.get('timestamp', '?')}; local data may be stale)")
            except (json.JSONDecodeError, KeyError):
                pass
        return out

    @staticmethod
    def _incompatibility(m: ComponentManifest) -> str:
        py = Version(sys.version_info.major, sys.version_info.minor)
        if not Constraint.parse(m.python).allows(py):
            return f"requires Python {m.python}; running {py}"
        if current_platform() not in m.platforms:
            return f"does not support platform {current_platform()}"
        return ""

    # -- queries ---------------------------------------------------------------------------
    def entries(self) -> list[CatalogEntry]:
        return self.scan().entries

    def versions(self, component_id: str) -> list[CatalogEntry]:
        return sorted((e for e in self.entries() if e.manifest.id == component_id),
                      key=lambda e: e.manifest.semver, reverse=True)

    def get(self, component_id: str, version: str | None = None, *, usable_only: bool = False
            ) -> CatalogEntry | None:
        for e in self.versions(component_id):
            if version and e.manifest.version != version:
                continue
            if usable_only and e.state != "installed":
                continue
            return e
        return None

    def require(self, component_id: str, version: str | None = None) -> CatalogEntry:
        e = self.get(component_id, version)
        if e is None:
            known = [k for k in self.scan().remote_known if k.get("id") == component_id]
            if known:
                raise Unavailable(f"Component {component_id!r} is known but not available offline",
                                  hint="Place its verified artifact in a catalog root, or refresh online.")
            raise ValidationFailure(f"Unknown component {component_id!r}")
        return e

    def search(self, query: str = "", *, category: str | None = None, capability: str | None = None,
               archetype: str | None = None, state: str | None = None, latest_only: bool = True
               ) -> list[CatalogEntry]:
        q = query.lower().strip()
        out, seen = [], set()
        for e in sorted(self.entries(), key=lambda e: (e.manifest.id, [-x for x in
                                                                        (e.manifest.semver.major, e.manifest.semver.minor, e.manifest.semver.patch)])):
            m = e.manifest
            if latest_only and m.id in seen:
                continue
            if category and m.category != category:
                continue
            if capability and capability not in m.capabilities():
                continue
            if archetype and archetype not in m.archetypes:
                continue
            if state and e.state != state:
                continue
            hay = " ".join([m.id, m.name, m.summary, *m.keywords]).lower()
            if q and q not in hay:
                continue
            seen.add(m.id)
            out.append(e)
        return out

    def provider_of(self, capability: str) -> list[CatalogEntry]:
        return [e for e in self.entries() if capability in e.manifest.capabilities() and e.state == "installed"]

    # -- maintenance -----------------------------------------------------------------------
    def rebuild_index(self) -> dict:
        res = self.scan(refresh=True)
        rows = [{"component_id": e.manifest.id, "version": e.manifest.version, "category": e.manifest.category,
                 "summary": e.manifest.summary, "state": e.state, "source": e.source,
                 "digest": e.manifest.digest} for e in res.entries]
        rows += [{"component_id": k.get("id", "?"), "version": k.get("version", "?"), "category": k.get("category", ""),
                  "summary": k.get("summary", ""), "state": "remote_unavailable", "source": k["source"],
                  "digest": ""} for k in res.remote_known]
        self._store.replace_index(rows)
        return {"indexed": len(rows), "quarantined": res.quarantined}

    def validate(self) -> dict:
        res = self.scan(refresh=True)
        return {"valid": len(res.entries), "quarantined": res.quarantined,
                "ok": not res.quarantined}
