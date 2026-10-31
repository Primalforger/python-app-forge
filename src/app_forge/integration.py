"""Integration Engine (MOD-09): reviewed, transactional, recoverable changes to a project.

Lifecycle: discover -> analyze -> plan -> review/approve -> checkpoint -> apply -> verify -> finalize.
No project mutation happens before an approved plan exists. Plans live in the platform home,
not in the project. Recovery restores only files that still match what Forge wrote, so unrelated
user edits made in the meantime are preserved and reported.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from typing import Any
from pathlib import Path
from typing import Callable

from app_forge.analyzer import ProjectAnalyzer
from app_forge.catalog.registry import CatalogEntry, ComponentRegistry
from app_forge.domain.errors import ConflictFailure, SecurityBlock, ValidationFailure
from app_forge.domain.models import ChangePlan, FileChange
from app_forge.domain.pydeps import combine, compare as compare_requirements, parse_requirement, satisfiable
from app_forge.domain.versioning import Constraint, Version
from app_forge.locks import project_lock
from app_forge.observability import utcnow
from app_forge.patching import PatchConflict, apply_patch, remove_patch, target_path
from app_forge.projectmeta import (COMPONENTS_TOML, FORGE_TOML, components_text, forge_toml_text,
                                   read_components, read_forge_toml)
from app_forge.templates.baseline import BASELINE_PATH, create_baseline, load_baseline
from app_forge.templates.merge import merge_file_maps
from app_forge.resolver import resolve
from app_forge.security import safe_join, sha256_bytes, sha256_text
from app_forge.settings import ForgeSettings
from app_forge.templates.engine import TemplateEngine, add_dependencies, render_text
from app_forge.verification import VerificationEngine

FaultHook = Callable[[str, int], None]

_TEMPLATE_CONFLICT_GUIDANCE = {
    "non-text-template-file": (
        "Restore this path as readable UTF-8 text, or move the binary/custom file out of the "
        "template-owned path; then create a fresh update plan."
    ),
    "unowned-path-collision": (
        "Move or rename the existing user-owned file, or choose a different path in the incoming "
        "template; then create a fresh update plan. Forge will not overwrite the unowned file."
    ),
    "content-conflict": (
        "Reconcile the local and upstream edits manually in this file, preserving the intended "
        "parts of both; then create a fresh update plan against the reconciled project."
    ),
    "delete-modify": (
        "The local file was deleted while the template changed it. Restore the file and reconcile "
        "the upstream changes, or confirm the deletion by removing the path from the incoming "
        "template; then create a fresh update plan."
    ),
    "modify-delete": (
        "The local file was edited while the template removed it. Move the customization to another "
        "path or confirm the upstream removal by deleting the local file; then create a fresh plan."
    ),
    "add-add": (
        "Both the project and incoming template added different content at this path. Rename or "
        "merge one copy manually; then create a fresh update plan."
    ),
}


def _template_conflict(code: str, path: str, message: str) -> dict[str, str]:
    """Return a reviewable conflict with safe, concrete remediation guidance."""
    return {
        "code": code,
        "path": path,
        "message": message,
        "resolution": _TEMPLATE_CONFLICT_GUIDANCE.get(
            code.removeprefix("template-"),
            "Resolve the reported issue manually, then create a fresh template update plan.",
        ),
    }





def _sha(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def _nsha(path: Path) -> str | None:
    """SHA-256 of a text file with CRLF normalised to LF (bytes hash for binary files).

    Used only to decide "did the user change this file?"; before/after hashes for drift detection and
    recovery stay byte-exact. An editor converting line endings must not look like an edit.
    """
    if not path.is_file():
        return None
    data = path.read_bytes()
    try:
        return sha256_text(data.decode("utf-8").replace("\r\n", "\n"))
    except UnicodeDecodeError:
        return sha256_bytes(data)


def component_contributions(entry: CatalogEntry, package: str) -> list[tuple[str, str]]:
    """Render a component's file contributions as [(destination, content)]."""
    out = []
    for f in entry.manifest.files:
        src = safe_join(entry.root, f.src)
        out.append((render_text(f.dest, {"package": package}),
                    render_text(src.read_text(encoding="utf-8"), {"package": package})))
    return out


def plan_digest(plan: ChangePlan) -> str:
    body = {"project": plan.project_path, "kind": plan.kind, "components": plan.components,
            "changes": [(c.action, c.path, c.before_sha, c.after_sha,
                          sha256_text(c.content) if c.content is not None else None)
                         for c in plan.changes],
            "conflicts": plan.conflicts}
    return sha256_text(json.dumps(body, sort_keys=True))


class IntegrationEngine:
    def __init__(self, settings: ForgeSettings, registry: ComponentRegistry, store, *,
                 analyzer: ProjectAnalyzer | None = None, verifier: VerificationEngine | None = None,
                 templates: TemplateEngine | None = None):
        self._s = settings
        self._registry = registry
        self._store = store
        self._analyzer = analyzer or ProjectAnalyzer()
        self._verifier = verifier or VerificationEngine()
        self._templates = templates or TemplateEngine()

    # ------------------------------------------------------------------ plan persistence
    def _plan_path(self, plan_id: str) -> Path:
        if not plan_id.startswith("plan-") or not plan_id[5:].isalnum():
            raise ValidationFailure(f"Invalid plan id {plan_id!r}")
        return self._s.plans_dir / f"{plan_id}.json"

    def save_plan(self, plan: ChangePlan) -> None:
        self._s.plans_dir.mkdir(parents=True, exist_ok=True)
        self._plan_path(plan.plan_id).write_text(json.dumps(plan.to_dict(), indent=1, sort_keys=True),
                                                 encoding="utf-8")

    def load_plan(self, plan_id: str) -> ChangePlan:
        p = self._plan_path(plan_id)
        if not p.is_file():
            raise ValidationFailure(f"No such plan {plan_id!r}")
        return ChangePlan.from_dict(json.loads(p.read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ planning (read-only)
    def _new_plan(self, analysis: dict, kind: str, comps: list[str]) -> ChangePlan:
        return ChangePlan(plan_id="plan-" + uuid.uuid4().hex[:12], project_path=analysis["path"], kind=kind,
                          level=analysis["level"], components=comps, created_at=utcnow())

    def plan_template_update(self, project: str | Path, template: str | None = None) -> ChangePlan:
        """Plan a three-way update of template-owned files; never mutate the project here."""
        analysis = self._analyzer.analyze(project)
        if analysis["level"] == 4:
            raise ConflictFailure("Project not supported for automated changes (integration level 4)")
        root = Path(analysis["path"])
        forge = read_forge_toml(root)
        if not forge or not isinstance(forge.get("template"), dict):
            raise ValidationFailure("Project has no Forge template identity; adopted projects cannot be template-updated")
        baseline_path = safe_join(root, BASELINE_PATH)
        if baseline_path.is_symlink() or not baseline_path.is_file():
            raise ValidationFailure("Project has no readable template baseline; template update is unavailable")
        try:
            baseline = load_baseline(baseline_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValidationFailure(f"Cannot use the project template baseline: {exc}") from None
        old = baseline["template"]
        if (forge["template"].get("id"), forge["template"].get("version")) != (old["id"], old["version"]):
            raise ConflictFailure("forge.toml template identity does not match the stored template baseline")
        info = self._templates.get(template or old["id"])
        if info.id != old["id"]:
            raise ValidationFailure(f"Template update must retain template ID {old['id']!r}, not {info.id!r}")
        if info.archetype != old["archetype"]:
            raise ConflictFailure("Template archetype changed; automated project update cannot change project archetype")
        plan = self._new_plan(analysis, "template-update", [f"{old['id']}@{old['version']}", f"{info.id}@{info.version}"])
        plan.warnings += analysis["warnings"]
        if Version.parse(info.version) <= Version.parse(old["version"]):
            raise ValidationFailure(f"Target template {info.id}@{info.version} is not newer than project baseline {old['version']}")
        meta = forge.get("project", {})
        variables = self._templates.validate_inputs(info, {
            "name": meta.get("name", analysis["name"]), "package": meta.get("package", analysis.get("package") or ""),
            "description": meta.get("description", ""), "author": meta.get("author", ""),
            "python_version": meta.get("python", "3.11"),
        })
        incoming = self._templates.render(info, variables)
        base = {p: record["content"] for p, record in baseline["files"].items()}
        local: dict[str, str] = {}
        for path in sorted(base):
            target = safe_join(root, path)
            if target.is_symlink():
                raise SecurityBlock(f"Refusing to update symlink template file {path!r}")
            if target.is_file():
                try:
                    with target.open("r", encoding="utf-8", newline="") as stream:
                        local[path] = stream.read()
                except (OSError, UnicodeError):
                    plan.conflicts.append(_template_conflict(
                        "non-text-template-file", path, f"{path} is no longer readable UTF-8 text"))
        for path in sorted(set(incoming) - set(base)):
            target = safe_join(root, path)
            if target.is_symlink():
                raise SecurityBlock(f"Refusing to update symlink target {path!r}")
            if target.exists():
                plan.conflicts.append(_template_conflict(
                    "unowned-path-collision", path,
                    f"{path} exists but was not owned by the previous template"))
        merged = merge_file_maps(base, local, incoming)
        plan.conflicts.extend(
            _template_conflict(
                f"template-{c.kind}", c.path,
                f"{c.path} has an overlapping local/upstream change ({c.kind})",
            )
            for c in merged.conflicts
        )
        if plan.conflicts:
            return self._finish(plan)
        new_baseline = create_baseline(info.id, info.version, info.archetype, incoming)
        for path in sorted(set(base) | set(merged.files)):
            target = safe_join(root, path)
            before, content = _sha(target), merged.files.get(path)
            if content is None:
                if before is not None:
                    plan.changes.append(FileChange("delete", path, "removed by template update", "", None, before, None))
            else:
                after = sha256_text(content)
                if before != after:
                    plan.changes.append(FileChange("modify" if before else "create", path,
                                                   "three-way template update", "", content, before, after))
        plan.changes.append(FileChange("modify", BASELINE_PATH, "advance template merge baseline", "",
                                       new_baseline, _sha(baseline_path), sha256_text(new_baseline)))
        variables["forge_version"] = forge.get("generator", {}).get("forge_version", variables["forge_version"])
        forge_text = forge_toml_text(variables, info.id, info.version)
        forge_target = safe_join(root, FORGE_TOML)
        plan.changes.append(FileChange("modify", FORGE_TOML, "record updated template version", "",
                                       forge_text, _sha(forge_target), sha256_text(forge_text)))
        return self._finish(plan)

    def plan_add(self, project: str | Path, requested: dict[str, str]) -> ChangePlan:
        analysis = self._analyzer.analyze(project)
        if analysis["level"] == 4:
            raise ConflictFailure(
                "This project is not supported for automated changes (integration level 4: read-only)",
                details=analysis["confidence_reasons"] + analysis["warnings"],
                hint="Run `forge project analyze` for advice; add packaging metadata or adopt a template first.")
        root = Path(analysis["path"])
        plan = self._new_plan(analysis, "add", sorted(requested))
        plan.warnings += analysis["warnings"]
        dirty = set(analysis["git"]["dirty_paths"])
        forge = read_forge_toml(root)
        archetype = (forge or {}).get("project", {}).get("archetype")
        if not archetype and len(analysis["archetype_indicators"]) == 1:
            archetype = analysis["archetype_indicators"][0]
        if not archetype:
            plan.warnings.append("Project archetype could not be determined; archetype compatibility not checked.")
        installed = read_components(root)
        already = {c["id"]: c["version"] for c in installed["components"]}

        def conflict(code: str, path: str, message: str) -> None:
            plan.conflicts.append({"code": code, "path": path, "message": message})

        res = resolve(self._registry, requested, archetype=archetype, already=already)
        for p in res.problems:
            conflict(f"dependency-{p['code']}", "", p["message"])
        package = analysis["package"]
        if not package or (not forge and len(analysis["packages"]) > 1):
            conflict("package-undetermined", "", "Cannot determine the target Python package "
                     f"(candidates: {analysis['packages'] or 'none'}). Adopt the project with a forge.toml.")
        if plan.conflicts:
            return self._finish(plan)

        new_entries = [e for e in res.order if e.manifest.id not in already]
        if not new_entries:
            plan.warnings.append("All requested components are already installed; nothing to do.")
        new_components: list[dict[str, Any]] = []
        managed: list[dict[str, Any]] = []
        dest_owner: dict[str, str] = {}
        py_packages: list[tuple[str, str]] = []
        for entry in new_entries:
            m = entry.manifest
            new_components.append({"id": m.id, "version": m.version, "digest": m.digest})
            for dest, content in component_contributions(entry, package):
                if analysis["layout"] == "flat" and not forge and dest.startswith(f"src/{package}/"):
                    dest = dest[len("src/"):]  # flat-layout project: package lives at the repository root
                target = safe_join(root, dest)  # raises SecurityBlock on traversal / symlink escape
                rel = target.relative_to(root.resolve()).as_posix()
                if rel in dest_owner:
                    conflict("duplicate-destination", rel, f"{m.id} and {dest_owner[rel]} both write {rel}")
                    continue
                dest_owner[rel] = m.id
                current = _sha(target)
                after = sha256_text(content)
                if current is not None:
                    if _nsha(target) == after:
                        plan.warnings.append(f"{rel} already exists with identical content; left unmanaged")
                    else:
                        conflict("would-overwrite", rel, f"{rel} exists and differs; Forge never overwrites silently")
                    continue
                if rel in dirty:
                    conflict("dirty-overlap", rel, f"{rel} has uncommitted changes")
                    continue
                plan.changes.append(FileChange("create", rel, f"contributed by {m.id}", m.id, content, None, after))
                managed.append({"path": rel, "sha256": after, "component": m.id})
            py_packages += [(p, m.id) for p in m.python_packages]

        # dependencies
        if py_packages:
            self._dependency_changes(plan, root, analysis, [p for p, _ in py_packages], dirty, conflict)

        new_patch_records = []
        for entry in new_entries:
            for patch in entry.manifest.patches:
                rec = self._plan_patch(plan, root, analysis, forge, package, entry.manifest.id, patch, dirty, conflict)
                if rec:
                    new_patch_records.append(rec)

        # registration record
        if new_components:
            reg = {"components": installed["components"] + new_components,
                   "managed_files": installed["managed_files"] + managed,
                   "patches": installed["patches"] + new_patch_records}
            text = components_text(reg)
            target = root / COMPONENTS_TOML
            before = _sha(target)
            if COMPONENTS_TOML in dirty:
                conflict("dirty-overlap", COMPONENTS_TOML, f"{COMPONENTS_TOML} has uncommitted changes")
            else:
                plan.changes.append(FileChange("modify" if before else "create", COMPONENTS_TOML,
                                               "register installed components", "", text, before, sha256_text(text)))
        return self._finish(plan)

    @staticmethod
    def _dependency_changes(plan: ChangePlan, root: Path, analysis: dict, pkgs: list[str], dirty: set,
                            conflict) -> None:
        """Reason about Python requirements, then auto-edit [project].dependencies for Forge projects.

        Existing requirements are compared with what components need: incompatible ones block the plan,
        looser-than-needed ones are flagged for review (never silently rewritten), absent ones are added.
        """
        existing: dict[str, Any] = {}
        for raw in analysis.get("dependency_specs", []):
            r = parse_requirement(raw)
            existing.setdefault(r.name, r)
        wants: dict[str, list] = {}
        for raw in pkgs:
            r = parse_requirement(raw)
            wants.setdefault(r.name, []).append(r)
        to_add: list[str] = []
        for name, reqs in wants.items():
            want = reqs[0] if len(reqs) == 1 else combine(reqs)
            if len(reqs) > 1:
                if (not want.unknown) and not satisfiable(want):
                    conflict("dependency-incompatible", "pyproject.toml",
                             f"components need conflicting versions of {name}: " + " vs ".join(r.raw for r in reqs))
                    plan.dependency_changes.append({"package": name, "action": "incompatible", "mode": "blocked"})
                    continue
                plan.warnings.append(f"several components need {name}; using the combined requirement {want.raw!r}")
            if name not in existing:
                to_add.append(want.raw if len(reqs) > 1 else reqs[0].raw)
                continue
            verdict = compare_requirements(existing[name], want)
            kind = verdict["verdict"]
            if kind == "incompatible":
                conflict("dependency-incompatible", "pyproject.toml", verdict["message"])
                plan.dependency_changes.append({"package": name, "action": "incompatible", "mode": "blocked",
                                                "existing": existing[name].raw, "wanted": want.raw})
            elif kind == "satisfied":
                plan.dependency_changes.append({"package": name, "action": "already-present", "mode": "none"})
            else:  # compatible-but-looser, or unknown: a human decides; we never rewrite an existing requirement
                plan.dependency_changes.append({"package": name, "action": "needs-review", "mode": "manual",
                                                "existing": existing[name].raw, "wanted": want.raw})
                plan.warnings.append(f"review dependency {name}: {verdict['message']}")
        if not to_add:
            return
        pyproject = root / "pyproject.toml"
        auto = analysis["level"] == 1 and pyproject.is_file()
        if auto:
            old = pyproject.read_bytes().decode("utf-8")
            new_text, added = add_dependencies(old, to_add)
            if new_text is None:
                auto = False
            elif added:
                if "pyproject.toml" in dirty:
                    conflict("dirty-overlap", "pyproject.toml", "pyproject.toml has uncommitted changes")
                else:
                    plan.changes.append(FileChange("modify", "pyproject.toml", "add component dependencies",
                                                   "", new_text, sha256_bytes(old.encode()), sha256_text(new_text)))
                plan.dependency_changes += [{"package": parse_requirement(p).name, "action": "add", "mode": "auto",
                                             "spec": p} for p in added]
        if not auto:
            plan.dependency_changes += [{"package": parse_requirement(p).name, "action": "add", "mode": "manual",
                                         "spec": p} for p in to_add]
            plan.changes.append(FileChange("manual", "pyproject.toml", "add dependencies manually: " + ", ".join(to_add)))
            plan.warnings.append("Dependencies are not edited automatically for this project; apply them yourself.")

    def plan_upgrade(self, project: str | Path, ids: list[str]) -> ChangePlan:
        """Upgrade installed components to the newest usable version.

        Files still identical to what Forge installed are updated in place; files you edited are never
        overwritten (conflict). Files a newer version stops contributing are removed only if unedited.
        """
        analysis = self._analyzer.analyze(project)
        if analysis["level"] == 4:
            raise ConflictFailure("Project not supported for automated changes (integration level 4)")
        root = Path(analysis["path"])
        plan = self._new_plan(analysis, "upgrade", sorted(ids))
        plan.warnings += analysis["warnings"]
        dirty = set(analysis["git"]["dirty_paths"])
        forge = read_forge_toml(root)
        installed = read_components(root)
        have = {c["id"]: c for c in installed["components"]}

        def conflict(code, path, message):
            plan.conflicts.append({"code": code, "path": path, "message": message})

        for cid in ids:
            if cid not in have:
                raise ValidationFailure(f"Component {cid!r} is not installed in this project",
                                        details=[f"installed: {sorted(have)}"])
        package = analysis["package"]
        if not package or (not forge and len(analysis["packages"]) > 1):
            conflict("package-undetermined", "", "Cannot determine the target Python package")
            return self._finish(plan)
        archetype = (forge or {}).get("project", {}).get("archetype") or (
            analysis["archetype_indicators"][0] if len(analysis["archetype_indicators"]) == 1 else None)

        targets: dict[str, CatalogEntry] = {}
        for cid in ids:
            cur = Version.parse(have[cid]["version"])
            cands = [e for e in self._registry.versions(cid) if e.state == "installed" and e.manifest.semver > cur
                     and (not archetype or archetype in e.manifest.archetypes)]
            if not cands:
                plan.warnings.append(f"{cid} is already at the newest usable version ({cur})")
                continue
            targets[cid] = cands[0]  # versions() is sorted newest first
            if cands[0].manifest.semver.major > cur.major:
                plan.warnings.append(f"{cid}: major upgrade {cur} -> {cands[0].manifest.version}; review its notes")
        if not targets:
            return self._finish(plan)

        for other, c in have.items():  # do installed dependents still accept the new version?
            if other in targets:
                continue
            entry = self._registry.get(other, c["version"])
            if entry is None:
                continue
            for dep, cons in entry.manifest.requires.items():
                if dep in targets and not Constraint.parse(cons).allows(targets[dep].manifest.semver):
                    conflict("breaks-dependent", "", f"{other} requires {dep} {cons}; "
                             f"{targets[dep].manifest.version} does not satisfy it")
        res = resolve(self._registry, {cid: f"=={e.manifest.version}" for cid, e in targets.items()},
                      archetype=archetype, already={k: v["version"] for k, v in have.items() if k not in targets})
        for p in res.problems:
            conflict(f"dependency-{p['code']}", "", p["message"])
        if plan.conflicts:
            return self._finish(plan)

        components_new, managed, pkgs, patch_records = [], [], [], []
        for entry in res.order:
            m = entry.manifest
            old_files = ({f["path"]: f["sha256"] for f in installed["managed_files"] if f["component"] == m.id}
                         if m.id in targets else {})
            new_files: dict[str, str] = {}
            for dest, content in component_contributions(entry, package):
                if analysis["layout"] == "flat" and not forge and dest.startswith(f"src/{package}/"):
                    dest = dest[len("src/"):]
                new_files[safe_join(root, dest).relative_to(root.resolve()).as_posix()] = content
            for rel, content in new_files.items():
                current, after = _sha(safe_join(root, rel)), sha256_text(content)
                cur_n = _nsha(safe_join(root, rel))
                action = None
                if rel in old_files:
                    if cur_n == after:
                        managed.append({"path": rel, "sha256": after, "component": m.id})
                    elif current is None:
                        action = "create"
                        plan.warnings.append(f"{rel} was deleted after installation; it will be restored")
                    elif cur_n == old_files[rel]:
                        action = "modify"
                    else:
                        conflict("modified-since-install", rel, f"{rel} was edited after installation; "
                                 "Forge will not overwrite your changes")
                elif current is None:
                    action = "create"
                elif cur_n == after:
                    plan.warnings.append(f"{rel} already exists with identical content; left unmanaged")
                else:
                    conflict("would-overwrite", rel, f"{rel} exists and differs; Forge never overwrites silently")
                if action:
                    if rel in dirty:
                        conflict("dirty-overlap", rel, f"{rel} has uncommitted changes")
                    else:
                        plan.changes.append(FileChange(action, rel, f"{m.id} {have.get(m.id, {}).get('version', 'new')}"
                                                       f" -> {m.version}", m.id, content, current, after))
                        managed.append({"path": rel, "sha256": after, "component": m.id})
            for rel, recorded in old_files.items():
                if rel in new_files:
                    continue
                current = _sha(safe_join(root, rel))
                if current is None:
                    plan.warnings.append(f"{rel} is already gone")
                elif _nsha(safe_join(root, rel)) != recorded:
                    conflict("modified-since-install", rel, f"{rel} is no longer provided by {m.version} but was "
                             "edited; Forge will not delete your changes")
                elif rel in dirty:
                    conflict("dirty-overlap", rel, f"{rel} has uncommitted changes")
                else:
                    plan.changes.append(FileChange("delete", rel, f"no longer provided by {m.id} {m.version}", m.id,
                                                   None, current, None))
            components_new.append({"id": m.id, "version": m.version, "digest": m.digest})
            pkgs += list(m.python_packages)
        if pkgs:
            self._dependency_changes(plan, root, analysis, pkgs, dirty, conflict)
        for entry in res.order:  # patches after dependency edits so both can touch pyproject.toml
            m = entry.manifest
            old_recs = ({r["id"]: r for r in installed["patches"] if r["component"] == m.id}
                        if m.id in targets else {})
            for patch in m.patches:
                old = old_recs.get(patch.id)
                rec = self._plan_patch(plan, root, analysis, forge, package, m.id, patch, dirty, conflict,
                                       replace=old is not None, expect_sha=old["sha256"] if old else None)
                if rec:
                    patch_records.append(rec)
            for pid, old in old_recs.items():
                if pid not in {p.id for p in m.patches}:
                    self._plan_patch_removal(plan, root, m.id, old, dirty, conflict)
        if COMPONENTS_TOML in dirty:
            conflict("dirty-overlap", COMPONENTS_TOML, f"{COMPONENTS_TOML} has uncommitted changes")
        if not plan.conflicts:
            reg = {"components": [c for c in installed["components"] if c["id"] not in targets] + components_new,
                   "managed_files": [f for f in installed["managed_files"]
                                     if f["component"] not in {e.manifest.id for e in res.order}] + managed,
                   "patches": [r for r in installed["patches"]
                               if r["component"] not in {e.manifest.id for e in res.order}] + patch_records}
            text = components_text(reg)
            plan.changes.append(FileChange("modify", COMPONENTS_TOML, "record upgraded components", "", text,
                                           _sha(root / COMPONENTS_TOML), sha256_text(text)))
        return self._finish(plan)

    def upgrade_candidates(self, project: str | Path) -> list[dict]:
        """For each installed component: current version and the newest usable one (UI-008)."""
        analysis = self._analyzer.analyze(project)
        root = Path(analysis["path"])
        forge = read_forge_toml(root)
        archetype = (forge or {}).get("project", {}).get("archetype")
        out = []
        for c in read_components(root)["components"]:
            cur = Version.parse(c["version"])
            cands = [e for e in self._registry.versions(c["id"]) if e.state == "installed"
                     and e.manifest.semver > cur and (not archetype or archetype in e.manifest.archetypes)]
            entry = self._registry.get(c["id"], c["version"])
            out.append({"id": c["id"], "installed": c["version"],
                        "newest": cands[0].manifest.version if cands else c["version"],
                        "upgrade_available": bool(cands), "in_catalog": entry is not None,
                        "state": entry.state if entry else "unknown"})
        return out

    # ------------------------------------------------------------------ patches (G-01)
    @staticmethod
    def _stage(plan: ChangePlan, root: Path, rel: str):
        """Current text of `rel` as this plan would leave it: (text|None, pending_change|None)."""
        for c in plan.changes:
            if c.path == rel and c.action == "modify":
                return c.content, c
            if c.path == rel and c.action == "create":
                return None, c
        target = safe_join(root, rel)
        return (target.read_bytes().decode("utf-8") if target.is_file() else None), None

    @staticmethod
    def _stage_write(plan: ChangePlan, root: Path, rel: str, change, new_text: str, reason: str, comp: str) -> None:
        if change is not None:
            change.content, change.after_sha = new_text, sha256_text(new_text)
        else:
            plan.changes.append(FileChange("modify", rel, reason, comp, new_text, _sha(safe_join(root, rel)),
                                           sha256_text(new_text)))

    def _plan_patch(self, plan, root, analysis, forge, package, comp_id, patch, dirty, conflict, *,
                    replace=False, expect_sha=None):
        flat = analysis["layout"] == "flat" and not forge
        rel = safe_join(root, target_path(patch, package, flat=flat)).relative_to(root.resolve()).as_posix()
        text, change = self._stage(plan, root, rel)
        if change is not None and change.action == "create":
            conflict("patch-on-new-file", rel, f"{comp_id}:{patch.id} patches {rel}, which this plan creates")
            return None
        if text is None:
            conflict("patch-target-missing", rel, f"{comp_id}:{patch.id} needs {rel}, which does not exist")
            return None
        if change is None and rel in dirty:
            conflict("dirty-overlap", rel, f"{rel} has uncommitted changes")
            return None
        try:
            res = apply_patch(text, patch, comp_id, package, replace=replace, expect_sha=expect_sha)
        except PatchConflict as exc:
            conflict(exc.code, rel, exc.message)
            return None
        record = {"component": comp_id, "id": patch.id, "file": rel, "kind": patch.kind, "sha256": res.sha256}
        if res.status == "unchanged":
            if replace:
                return record
            plan.warnings.append(f"{comp_id}:{patch.id} is already present in {rel}; left unmanaged")
            return None
        self._stage_write(plan, root, rel, change, res.new_text, f"patch {comp_id}:{patch.id} ({patch.kind})", comp_id)
        if patch.kind == "json-merge":
            plan.warnings.append(f"{rel} will be re-serialised as JSON; json-merge patches are not auto-removed")
        return record

    def _plan_patch_removal(self, plan, root, comp_id, rec, dirty, conflict) -> None:
        rel = rec["file"]
        if rec["kind"] == "json-merge":
            plan.warnings.append(f"{comp_id}:{rec['id']} merged keys into {rel}; remove them manually if unwanted")
            return
        text, change = self._stage(plan, root, rel)
        if text is None:
            plan.warnings.append(f"{rel} is gone; nothing to unpatch for {comp_id}:{rec['id']}")
            return
        if change is None and rel in dirty:
            conflict("dirty-overlap", rel, f"{rel} has uncommitted changes")
            return
        try:
            new_text = remove_patch(text, comp_id, rec["id"], rec["sha256"])
        except PatchConflict as exc:
            if exc.code == "patch-block-missing":
                plan.warnings.append(f"{comp_id}:{rec['id']} block is already gone from {rel}")
            else:
                conflict(exc.code, rel, exc.message)
            return
        self._stage_write(plan, root, rel, change, new_text, f"remove patch {comp_id}:{rec['id']}", comp_id)

    def plan_remove(self, project: str | Path, ids: list[str]) -> ChangePlan:
        analysis = self._analyzer.analyze(project)
        if analysis["level"] == 4:
            raise ConflictFailure("Project not supported for automated changes (integration level 4)")
        root = Path(analysis["path"])
        plan = self._new_plan(analysis, "remove", sorted(ids))
        plan.warnings += analysis["warnings"]
        dirty = set(analysis["git"]["dirty_paths"])
        installed = read_components(root)
        have = {c["id"]: c for c in installed["components"]}

        def conflict(code, path, message):
            plan.conflicts.append({"code": code, "path": path, "message": message})

        for cid in ids:
            if cid not in have:
                raise ValidationFailure(f"Component {cid!r} is not installed in this project",
                                        details=[f"installed: {sorted(have)}"])
        for other_id, c in have.items():
            if other_id in ids:
                continue
            entry = self._registry.get(other_id, c["version"])
            if entry is None:
                plan.warnings.append(f"Manifest for installed {other_id}@{c['version']} not in catalog; "
                                     "cannot check whether it depends on the removal set")
                continue
            for dep in entry.manifest.requires:
                if dep in ids:
                    conflict("has-dependents", "", f"{other_id} depends on {dep}; remove it first")
        removed_files = set()
        for mf in installed["managed_files"]:
            if mf["component"] not in ids:
                continue
            target = safe_join(root, mf["path"])
            current = _sha(target)
            if current is None:
                plan.warnings.append(f"{mf['path']} is already gone")
            elif _nsha(target) != mf["sha256"]:
                conflict("modified-since-install", mf["path"],
                         f"{mf['path']} was edited after installation; Forge will not delete your changes")
            elif mf["path"] in dirty:
                conflict("dirty-overlap", mf["path"], f"{mf['path']} has uncommitted changes")
            else:
                plan.changes.append(FileChange("delete", mf["path"], f"owned by {mf['component']}",
                                               mf["component"], None, current, None))
            removed_files.add(mf["path"])
        for rec in installed["patches"]:
            if rec["component"] in ids:
                self._plan_patch_removal(plan, root, rec["component"], rec, dirty, conflict)
        if not plan.conflicts:
            reg = {"components": [c for c in installed["components"] if c["id"] not in ids],
                   "managed_files": [f for f in installed["managed_files"] if f["component"] not in ids],
                   "patches": [r for r in installed["patches"] if r["component"] not in ids]}
            text = components_text(reg)
            plan.changes.append(FileChange("modify", COMPONENTS_TOML, "unregister components", "", text,
                                           _sha(root / COMPONENTS_TOML), sha256_text(text)))
            for cid in ids:
                entry = self._registry.get(cid, have[cid]["version"])
                for p in (entry.manifest.python_packages if entry else ()):
                    plan.dependency_changes.append({"package": p, "action": "remove", "mode": "manual"})
            if plan.dependency_changes:
                plan.warnings.append("Python dependencies are never removed automatically; they may be shared.")
        return self._finish(plan)

    def _finish(self, plan: ChangePlan) -> ChangePlan:
        plan.digest = plan_digest(plan)
        plan.status = "planned"
        self.save_plan(plan)
        return plan

    # ------------------------------------------------------------------ approval
    def approve(self, plan_id: str, approver: str) -> ChangePlan:
        plan = self.load_plan(plan_id)
        if not approver.strip():
            raise ValidationFailure("An approver identity is required")
        if plan.status != "planned":
            raise ConflictFailure(f"Plan {plan_id} is {plan.status}; only 'planned' plans can be approved")
        if plan.conflicts:
            raise ConflictFailure("Plan has unresolved conflicts and cannot be approved",
                                  details=[f"[{c['code']}] {c['message']}" for c in plan.conflicts])
        if plan.digest != plan_digest(plan):
            raise SecurityBlock("Plan contents do not match their recorded digest")
        plan.status, plan.approved_by = "approved", approver
        self.save_plan(plan)
        return plan

    # ------------------------------------------------------------------ apply / recover
    def _ckpt_dir(self, plan_id: str) -> Path:
        return self._s.checkpoints_dir / plan_id

    def apply(self, plan_id: str, *, verify: bool = True, auto_recover: bool = False,
              fault: FaultHook | None = None) -> dict:
        plan = self.load_plan(plan_id)
        with project_lock(self._s.locks_dir, Path(plan.project_path), f"apply {plan_id}"):
            return self._apply_locked(plan_id, verify=verify, auto_recover=auto_recover, fault=fault)

    def _apply_locked(self, plan_id: str, *, verify: bool, auto_recover: bool, fault: FaultHook | None) -> dict:
        plan = self.load_plan(plan_id)
        if plan.status != "approved":
            raise SecurityBlock(f"Plan {plan_id} is {plan.status}: an approved plan is required before any change",
                                hint=f"forge integrate approve {plan_id} --by <name>")
        if plan.conflicts or plan.digest != plan_digest(plan):
            raise SecurityBlock("Plan failed integrity or conflict checks")
        root = Path(plan.project_path)
        if not root.is_dir():
            raise ValidationFailure(f"Project directory {root} no longer exists")
        actionable = [c for c in plan.changes if c.action in ("create", "modify", "delete")]
        for c in actionable:
            if c.action in ("create", "modify"):
                if (not isinstance(c.content, str) or not isinstance(c.after_sha, str)
                        or sha256_text(c.content) != c.after_sha):
                    raise SecurityBlock(f"Plan content for {c.path!r} does not match its recorded after hash")
                if c.action == "create" and c.before_sha is not None:
                    raise SecurityBlock(f"Create change for {c.path!r} has an unexpected before hash")
                if c.action == "modify" and not isinstance(c.before_sha, str):
                    raise SecurityBlock(f"Modify change for {c.path!r} has no valid before hash")
            elif c.content is not None or c.after_sha is not None or not isinstance(c.before_sha, str):
                raise SecurityBlock(f"Delete change for {c.path!r} has an invalid hash/content shape")
        for c in actionable:  # drift detection: the project must still match what was planned against
            if _sha(safe_join(root, c.path)) != c.before_sha:
                plan.status = "stale"
                self.save_plan(plan)
                raise ConflictFailure(f"{c.path} changed since the plan was created; create a new plan")

        # checkpoint: record before-state (content for modify/delete) without touching Git
        ck = self._ckpt_dir(plan_id)
        (ck / "blobs").mkdir(parents=True, exist_ok=True)
        entries = []
        for c in actionable:
            tgt = safe_join(root, c.path)
            if c.before_sha:
                (ck / "blobs" / c.before_sha).write_bytes(tgt.read_bytes())
            entries.append({"path": c.path, "action": c.action, "before_sha": c.before_sha, "after_sha": c.after_sha,
                            "existed_dirs": [p.relative_to(root).as_posix() for p in
                                             [tgt.parent, *tgt.parents] if p != root and root in p.parents and p.exists()]})
        (ck / "manifest.json").write_text(json.dumps({"plan_id": plan_id, "entries": entries}, indent=1),
                                          encoding="utf-8")
        report: dict = {"plan_id": plan_id, "project": str(root), "changed": [], "verification": None}
        try:
            for i, c in enumerate(actionable):
                if fault:
                    fault(c.path, i)
                self._apply_one(root, c)
                report["changed"].append(c.path)
        except BaseException as exc:  # includes injected faults and KeyboardInterrupt
            rec = self._recover(plan_id)
            plan = self.load_plan(plan_id)
            plan.status = rec["status"] if rec["status"] != "rolled_back" else "rolled_back"
            self.save_plan(plan)
            report.update({"status": plan.status, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                           "recovery": rec, "exit_code": 5})
            if isinstance(exc, KeyboardInterrupt):
                raise
            return report

        plan.status = "applied"
        if verify:
            vr = self._verifier.run(root, checks=("syntax", "tests"))
            self._store.add_evidence(vr["evidence"])
            report["verification"] = {k: vr[k] for k in ("run_id", "overall", "passed", "failed", "not_run", "complete")}
            if vr["overall"] == "failed":
                if auto_recover:
                    rec = self._recover(plan_id)
                    plan = self.load_plan(plan_id)
                    report["recovery"] = rec
                    plan.status = rec["status"]
                    report.update({"status": plan.status, "ok": False, "exit_code": 6})
                    self.save_plan(plan)
                    return report
                plan.status = "applied_verification_failed"
        self.save_plan(plan)
        ok = plan.status == "applied"
        report.update({"status": plan.status, "ok": ok, "exit_code": 0 if ok else 6})
        if ok and verify and report["verification"] and not report["verification"]["complete"]:
            report["note"] = ("Applied, but some checks did not run: " + ", ".join(report["verification"]["not_run"]))
        return report

    @staticmethod
    def _apply_one(root: Path, c: FileChange) -> None:
        """Apply one change using an exclusive, unpredictable sibling file.

        Predictable temporary names are unsafe in project-controlled directories: a planted
        symlink could redirect the write. Recheck the planned before-state immediately before
        mutation and again after staging the replacement.
        """
        target = safe_join(root, c.path)

        def check_expected_state() -> None:
            current = safe_join(root, c.path)
            if current.is_symlink():
                raise SecurityBlock(f"Refusing to replace symlink target {c.path!r}")
            if _sha(current) != c.before_sha:
                raise ConflictFailure(f"{c.path} changed while the plan was being applied; "
                                      "the change was not overwritten")

        check_expected_state()
        if c.action == "delete":
            target.unlink()
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (c.content or "").encode("utf-8")
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
        tmp: Path | None = None
        fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            for _ in range(10):
                candidate = target.with_name(f".{target.name}.forge-{uuid.uuid4().hex}.tmp")
                try:
                    fd = os.open(candidate, flags, 0o666)  # honours umask; never follows an existing link
                    tmp = candidate
                    break
                except FileExistsError:
                    continue
            if fd is None or tmp is None:
                raise FileExistsError(f"Could not allocate a unique temporary file for {c.path}")

            if mode is not None:
                os.chmod(tmp, mode)
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())

            check_expected_state()
            os.replace(tmp, target)
            tmp = None
        finally:
            if fd is not None:
                os.close(fd)
            if tmp is not None:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass

    def recover(self, plan_id: str) -> dict:
        plan = self.load_plan(plan_id)
        with project_lock(self._s.locks_dir, Path(plan.project_path), f"recover {plan_id}"):
            return self._recover(plan_id)

    def _recover(self, plan_id: str) -> dict:
        plan = self.load_plan(plan_id)
        ck = self._ckpt_dir(plan_id)
        mf = ck / "manifest.json"
        if not mf.is_file():
            raise ValidationFailure(f"No checkpoint exists for {plan_id}; nothing to recover")
        root = Path(plan.project_path)
        entries = json.loads(mf.read_text(encoding="utf-8"))["entries"]
        restored, deleted, unchanged, preserved, errors = [], [], [], [], []
        seen_paths: set[str] = set()
        for e in reversed(entries):
            rel = e.get("path", "")
            try:
                if not isinstance(rel, str) or not rel or rel in seen_paths:
                    raise ValidationFailure("Checkpoint contains an invalid or duplicate path")
                seen_paths.add(rel)
                if e.get("action") not in ("create", "modify", "delete"):
                    raise ValidationFailure(f"Checkpoint action for {rel!r} is invalid")
                before, after = e.get("before_sha"), e.get("after_sha")
                if before is not None and (not isinstance(before, str) or len(before) != 64):
                    raise ValidationFailure(f"Checkpoint before hash for {rel!r} is invalid")
                if after is not None and (not isinstance(after, str) or len(after) != 64):
                    raise ValidationFailure(f"Checkpoint after hash for {rel!r} is invalid")
                tgt = safe_join(root, rel)
                if tgt.is_symlink():
                    preserved.append(rel)
                    errors.append(f"{rel}: refusing to recover through a symlink")
                    continue
                current = _sha(tgt)
                if current == before:
                    unchanged.append(rel)
                elif current == after:
                    if before is None:
                        self._apply_one(root, FileChange("delete", rel, "recover interrupted apply", "",
                                                         None, after, None))
                        deleted.append(rel)
                        self._prune_empty_dirs(root, tgt.parent, e.get("existed_dirs", []))
                    else:
                        blob = ck / "blobs" / before
                        payload = blob.read_bytes()
                        if sha256_bytes(payload) != before:
                            raise ValidationFailure(f"Checkpoint backup for {rel!r} failed its SHA-256 check")
                        content = payload.decode("utf-8")
                        self._apply_one(root, FileChange("modify", rel, "recover interrupted apply", "",
                                                         content, after, before))
                        restored.append(rel)
                else:
                    preserved.append(rel)  # edited by someone since: do not overwrite their work
            except (OSError, UnicodeError, ValueError, ValidationFailure, SecurityBlock, ConflictFailure) as exc:
                errors.append(f"{rel}: {exc}")
        complete = not preserved and not errors
        status = "rolled_back" if complete else "partially_recovered"
        report = {"status": status, "restored": restored, "deleted": deleted, "unchanged": unchanged,
                  "preserved_user_changes": preserved, "errors": errors, "complete": complete,
                  "remaining": preserved + [x.split(":")[0] for x in errors]}
        if not complete:
            report["note"] = ("Some files were modified after the change or could not be restored; "
                              "they were left untouched. Review them manually.")
        (ck / "recovery.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        plan.status = status
        self.save_plan(plan)
        return report

    @staticmethod
    def _prune_empty_dirs(root: Path, start: Path, pre_existing: list[str]) -> None:
        keep = {(root / d).resolve() for d in pre_existing} | {root.resolve()}
        d = start
        while d.resolve() not in keep and d != root:
            try:
                d.rmdir()
            except OSError:
                break
            d = d.parent

    def status(self, plan_id: str) -> dict:
        plan = self.load_plan(plan_id)
        d = plan.to_dict(include_content=False)
        rec = self._ckpt_dir(plan_id) / "recovery.json"
        if rec.is_file():
            d["recovery"] = json.loads(rec.read_text(encoding="utf-8"))
        return d
