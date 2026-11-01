"""Dependency Resolver (MOD-07): deterministic resolution with explicit failure reporting."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app_forge.catalog.registry import CatalogEntry, ComponentRegistry
from app_forge.domain.errors import ConflictFailure
from app_forge.domain.interfaces import parse_interface
from app_forge.domain.versioning import Constraint, Version


@dataclass
class Resolution:
    order: list[CatalogEntry] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)  # {code, message, component}

    @property
    def ok(self) -> bool:
        return not self.problems

    def raise_if_failed(self) -> None:
        if self.problems:
            raise ConflictFailure("Dependency resolution failed",
                                  details=[f"[{p['code']}] {p['message']}" for p in self.problems])

    def to_dict(self) -> dict:
        return {"ok": self.ok, "install_order": [f"{e.manifest.id}@{e.manifest.version}" for e in self.order],
                "problems": self.problems}


def resolve(registry: ComponentRegistry, requested: dict[str, str], *, archetype: str | Sequence[str] | None = None,
            already: dict[str, str] | None = None) -> Resolution:
    """Resolve `requested` ({component_id: constraint}) plus transitive dependencies.

    `already` maps component ids already present in the project to their versions.
    Highest allowed version is chosen; all constraints on a component must hold at once.
    """
    already = already or {}
    archetypes = {archetype} if isinstance(archetype, str) else set(archetype or ())
    res = Resolution()
    constraints: dict[str, list[tuple[str, Constraint]]] = {}  # id -> [(who, constraint)]
    chosen: dict[str, CatalogEntry] = {}
    graph: dict[str, list[str]] = {}

    def problem(code: str, message: str, component: str = "") -> None:
        if not any(p["code"] == code and p["message"] == message for p in res.problems):
            res.problems.append({"code": code, "message": message, "component": component})

    def visit(cid: str, who: str, constraint: Constraint, stack: tuple[str, ...]) -> None:
        constraints.setdefault(cid, []).append((who, constraint))
        if cid in already:
            if not constraint.allows(Version.parse(already[cid])):
                problem("conflict", f"{who} needs {cid} {constraint}, project has {already[cid]}", cid)
            return
        versions = registry.versions(cid)
        if not versions:
            problem("missing", f"{who} requires {cid} {constraint} which is not in the local catalog", cid)
            return
        candidates = [e for e in versions if e.state == "installed"
                      and all(c.allows(e.manifest.semver) for _, c in constraints[cid])]
        if archetypes:
            candidates = [e for e in candidates if archetypes.intersection(e.manifest.archetypes)]
        if not candidates:
            states = {e.manifest.version: e.state for e in versions}
            wants = "; ".join(f"{w} needs {c}" for w, c in constraints[cid])
            problem("conflict" if len(constraints[cid]) > 1 else "unsatisfiable",
                    f"No usable version of {cid} satisfies [{wants}] (available: {states}"
                    + (f", archetypes {sorted(archetypes)}" if archetypes else "") + ")", cid)
            return
        entry = candidates[0]
        if cid in chosen and chosen[cid].manifest.version != entry.manifest.version:
            problem("conflict", f"{cid} resolved to both {chosen[cid].manifest.version} and "
                                f"{entry.manifest.version}", cid)
        chosen[cid] = entry
        deps = graph.setdefault(cid, [])
        for dep_id, dep_c in entry.manifest.requires.items():
            if dep_id in stack or dep_id == cid:
                problem("cycle", " -> ".join([*stack, cid, dep_id]), cid)
                continue
            if dep_id not in deps:
                deps.append(dep_id)
            visit(dep_id, cid, Constraint.parse(dep_c), (*stack, cid))

    for cid, cstr in requested.items():
        visit(cid, "request", Constraint.parse(cstr), ())

    # Interface requirements are contracts, not just names: validate the requested
    # version against providers selected in this resolution or already in the project.
    providers: dict[str, list[Version]] = {}
    for entry in chosen.values():
        for declaration in entry.manifest.provides:
            spec = parse_interface(declaration, provider=True)
            if spec.version is not None:
                providers.setdefault(spec.name, []).append(spec.version)
    for component_id, component_version in already.items():
        existing = registry.get(component_id, component_version)
        if existing is None:
            continue
        for declaration in existing.manifest.provides:
            spec = parse_interface(declaration, provider=True)
            if spec.version is not None:
                providers.setdefault(spec.name, []).append(spec.version)

    for entry in chosen.values():
        for need in entry.manifest.requires_interfaces:
            spec = parse_interface(need)
            available = providers.get(spec.name, [])
            if not available:
                problem("missing-interface",
                        f"{entry.manifest.id} requires interface {need} which nothing provides",
                        entry.manifest.id)
            elif spec.constraint and not any(spec.constraint.allows(v) for v in available):
                versions = ", ".join(str(v) for v in sorted(set(available)))
                problem("incompatible-interface",
                        f"{entry.manifest.id} requires interface {need}, available versions: {versions}",
                        entry.manifest.id)

    if not res.problems:  # topological order, deterministic (sorted ids as tie-breaker)
        done: list[str] = []
        visiting: set[str] = set()

        def topo(n: str) -> None:
            if n in done or n not in chosen:
                return
            visiting.add(n)
            for d in sorted(graph.get(n, [])):
                if d in visiting:
                    problem("cycle", f"{n} -> {d}", n)
                    continue
                topo(d)
            visiting.discard(n)
            done.append(n)

        for n in sorted(chosen):
            topo(n)
        res.order = [chosen[n] for n in done]
    return res
