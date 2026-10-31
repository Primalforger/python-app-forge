"""Application Services (MOD-02). The single entry point used by both the CLI and the GUI.

Every user-visible operation is a method here; shells only parse input and render output.
"""
from __future__ import annotations

import base64
import ctypes
import difflib
import errno
import importlib.util
import json
import os
import platform
import secrets
import shutil
import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from app_forge import __version__
from app_forge.analyzer import ProjectAnalyzer
from app_forge.architecture import check_rules, graph_to_mermaid, graph_to_text, module_graph
from app_forge.catalog import authoring
from app_forge.catalog.registry import BUILTIN_COMPONENTS, ComponentRegistry, current_platform, seal_component
from app_forge.compliance import build_report, load_requirements, to_markdown, validate_requirements
from app_forge.compliance_artifacts import load_artifacts, save_artifact
from app_forge.supply_chain import build_cyclonedx, build_spdx, check_license_policy
from app_forge.table_designer import normalize_definition, to_python
from app_forge.domain.errors import ConflictFailure, ForgeError, SecurityBlock, ValidationFailure
from app_forge.domain.models import ChangePlan
from app_forge.extensions import ExtensionHost
from app_forge.locks import lock_path, project_lock, read_lock
from app_forge.integration import IntegrationEngine, component_contributions
from app_forge.observability import get_logger, new_operation_id, utcnow
from app_forge.patching import PatchConflict, apply_patch, target_path
from app_forge.persistence import SqliteStore
from app_forge.projectmeta import components_text, forge_toml_text, read_components
from app_forge.resolver import resolve
from app_forge.security import safe_join, sha256_bytes, sha256_text
from app_forge.settings import ForgeSettings
from app_forge.templates.baseline import BASELINE_PATH, create_baseline
from app_forge.templates.engine import (TEMPLATES_ROOT, TemplateEngine, add_dependencies,
                                        package_name_problems)
from app_forge.verification import ALL_CHECKS, VerificationEngine, compare_evidence


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename a directory without ever replacing an existing destination."""
    if os.name == "nt":
        # Windows rename fails when the destination already exists.
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        renameat2 = libc.renameat2
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(os.fsencode(source), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    else:
        raise OSError(errno.ENOTSUP, "atomic no-clobber directory rename is unavailable", str(destination))
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def _set_default_directory_mode(directory: Path) -> None:
    """Give a staged directory the same umask-filtered mode as Path.mkdir()."""
    if os.name != "posix":
        return
    probe = directory / f".forge-mode-{secrets.token_hex(8)}"
    fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    try:
        file_mode = os.fstat(fd).st_mode & 0o777
    finally:
        os.close(fd)
        probe.unlink(missing_ok=True)
    umask = 0o666 & ~file_mode
    os.chmod(directory, 0o777 & ~umask)


class ForgeServices:
    def __init__(self, settings: ForgeSettings | None = None, *, store=None, verbosity: int = 0,
                 builtin_root: Path | None = BUILTIN_COMPONENTS):
        self.settings = settings or ForgeSettings.load()
        self.settings.ensure()
        self.store = store or SqliteStore(self.settings.db_path)
        self.log = get_logger(verbosity)
        roots = ([("builtin", builtin_root)] if builtin_root else []) + [("user", self.settings.user_catalog)] + [
            (f"extra:{p.name}", p) for p in self.settings.extra_catalog_roots]
        self.registry = ComponentRegistry(roots, self.store, self.settings.revocations_file)
        self.templates = TemplateEngine([TEMPLATES_ROOT, self.settings.home / "templates"])
        self.analyzer = ProjectAnalyzer()
        self.verifier = VerificationEngine()
        self.integration = IntegrationEngine(self.settings, self.registry, self.store,
                                             analyzer=self.analyzer, verifier=self.verifier,
                                             templates=self.templates)
        self.extensions = ExtensionHost(self.store)

    # ------------------------------------------------------------------ operations
    @contextmanager
    def operation(self, kind: str, target: object = "") -> Iterator[dict]:
        op: dict[str, Any] = {"operation_id": new_operation_id(), "kind": kind, "target": str(target), "status": "running",
              "started": utcnow(), "summary": {}}
        self.log.info("started", extra={"operation_id": op["operation_id"], "operation": kind, "target": str(target)})
        try:
            yield op
        except ForgeError as exc:
            op["status"] = "failed"
            op["summary"]["error"] = exc.to_dict()
            raise
        except Exception as exc:
            op["status"] = "failed"
            op["summary"]["error"] = {"category": "internal", "message": f"{type(exc).__name__}: {exc}"}
            raise
        else:
            if op["status"] == "running":
                op["status"] = "succeeded"
        finally:
            op["finished"] = utcnow()
            self.store.record_operation(op)
            self.log.info("finished", extra={"operation_id": op["operation_id"], "operation": kind,
                                             "outcome": op["status"]})

    # ------------------------------------------------------------------ templates
    def list_templates(self) -> list[dict]:
        return [t.to_dict() for t in self.templates.list()]

    def inspect_template(self, template: str) -> dict:
        return self.templates.get(template).to_dict()

    # ------------------------------------------------------------------ project creation (FR-001/002)
    def create_project(self, template: str, options: dict, out_dir: str | Path, *,
                       components: Sequence[str] = (), dry_run: bool = False) -> dict:
        with self.operation("create_project", out_dir) as op:
            info = self.templates.get(template)
            variables = self.templates.validate_inputs(info, options)
            files = self.templates.render(info, variables)
            # Preserve the exact rendered template as the three-way merge base.
            # Component contributions and Forge metadata have independent ownership.
            template_baseline = create_baseline(info.id, info.version, info.archetype, files)
            package = variables["package"]
            res = resolve(self.registry, {c: "*" for c in components}, archetype=info.archetype)
            res.raise_if_failed()
            comps, managed, pkgs = [], [], []
            file_modes: dict[str, int] = {}
            for entry in res.order:
                m = entry.manifest
                comps.append({"id": m.id, "version": m.version, "digest": m.digest})
                for dest, content, encoding, mode in component_contributions(entry, package):
                    safe_join(Path(tempfile.gettempdir()), dest)  # path-safety check only
                    if dest in files:
                        raise ConflictFailure(f"Component {m.id} would overwrite template file {dest}")
                    payload = base64.b64decode(content) if encoding == "base64" else content.encode("utf-8")
                    files[dest] = payload if encoding == "base64" else content
                    file_modes[dest] = mode
                    managed.append({"path": dest, "sha256": sha256_bytes(payload), "component": m.id})
                pkgs += list(m.python_packages)
            dep_changes = []
            if pkgs:
                new_text, added = add_dependencies(files["pyproject.toml"], pkgs)
                if new_text is not None:
                    files["pyproject.toml"] = new_text
                dep_changes = added
            patch_records = []
            for entry in res.order:
                for patch in entry.manifest.patches:
                    rel = target_path(patch, package)
                    if rel not in files:
                        raise ConflictFailure(f"{entry.manifest.id}:{patch.id} patches {rel}, which the project does not have")
                    try:
                        if not isinstance(files[rel], str):
                        raise ConflictFailure(f"{entry.manifest.id}:{patch.id} cannot patch binary file {rel}")
                    pr = apply_patch(files[rel], patch, entry.manifest.id, package)
                    except PatchConflict as exc:
                        raise ConflictFailure(f"{entry.manifest.id}:{patch.id}: [{exc.code}] {exc.message}") from None
                    files[rel] = pr.new_text
                    if pr.status == "applied":
                        patch_records.append({"component": entry.manifest.id, "id": patch.id, "file": rel,
                                              "kind": patch.kind, "sha256": pr.sha256})
            files["forge.toml"] = forge_toml_text(variables, info.id, info.version)
            if BASELINE_PATH in files:
                raise ConflictFailure(f"Template output reserves {BASELINE_PATH}")
            files[BASELINE_PATH] = template_baseline
            if comps:
                files[".forge/components.toml"] = components_text({"components": comps, "managed_files": managed,
                                                                   "patches": patch_records})
            files = dict(sorted(files.items()))
            plan = {"template": f"{info.id}@{info.version}", "archetype": info.archetype, "package": package,
                    "components": [f"{c['id']}@{c['version']}" for c in comps], "added_dependencies": dep_changes,
                    "patches": [f"{r['component']}:{r['id']} -> {r['file']}" for r in patch_records],
                    "files": [{"path": p, "bytes": len(c) if isinstance(c, bytes) else len(c.encode())}
                              for p, c in files.items()],
                    "configuration": {k: variables[k] for k in ("name", "package", "description", "author",
                                                               "python_version")}}
            # Keep the final path itself unresolved so a symlink at that path is rejected,
            # rather than silently redirecting generation to its target.
            out = Path(os.path.abspath(os.fspath(out_dir)))
            if dry_run:
                op["summary"] = {"dry_run": True, "files": len(files)}
                return {"operation_id": op["operation_id"], "dry_run": True, "path": str(out), **plan}
            # Render and validate the complete tree in a private sibling directory. Only
            # promote it after every file has been written and the generated metadata parses.
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() or out.is_symlink():
                raise ConflictFailure(f"Target directory {out} already exists")
            stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.forge-create-", dir=out.parent))
            try:
                for rel, content in files.items():
                    target = safe_join(stage, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
                    if rel in file_modes:
                        os.chmod(target, file_modes[rel])
                if set(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()) != set(files):
                    raise ValidationFailure("Staged project does not match the rendered file manifest")
                tomllib.loads((stage / "forge.toml").read_text(encoding="utf-8"))
                if "pyproject.toml" in files:
                    tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))
                # Keep the staging tree private until validation is complete, then apply
                # the normal umask-filtered root mode immediately before promotion.
                _set_default_directory_mode(stage)
                # No-clobber rename closes the check/promote race: a destination created
                # after preflight is never replaced, even if it is an empty directory.
                _rename_directory_noreplace(stage, out)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            op["summary"] = {"files": len(files), "template": info.id}
            return {"operation_id": op["operation_id"], "dry_run": False, "path": str(out), **plan}

    # ------------------------------------------------------------------ catalog / components
    def search_components(self, query: str = "", **filters) -> list[dict]:
        return [e.summary() for e in self.registry.search(query, **filters)]

    def inspect_component(self, component_id: str, version: str | None = None) -> dict:
        e = self.registry.require(component_id, version)
        return {**e.summary(), "manifest": e.manifest.to_dict(),
                "other_versions": [x.manifest.version for x in self.registry.versions(component_id)]}

    def list_catalog(self) -> dict:
        res = self.registry.scan(refresh=True)
        return {"components": [e.summary() for e in res.entries], "remote_known": res.remote_known,
                "quarantined": res.quarantined, "network_required": False}

    def validate_catalog(self) -> dict:
        with self.operation("catalog_validate") as op:
            r = self.registry.validate()
            op["summary"] = {"valid": r["valid"], "quarantined": len(r["quarantined"])}
            return r

    def rebuild_catalog_index(self) -> dict:
        with self.operation("catalog_rebuild") as op:
            r = self.registry.rebuild_index()
            op["summary"] = {"indexed": r["indexed"]}
            return r

    def set_component_enabled(self, component_id: str, enabled: bool) -> dict:
        with self.operation("component_enable" if enabled else "component_disable", component_id):
            self.registry.require(component_id)
            self.store.set_disabled(component_id, not enabled)
            self.registry.scan(refresh=True)
            return self.inspect_component(component_id)

    def resolve_dependencies(self, requested: dict[str, str], archetype: str | None = None,
                             project: str | Path | None = None) -> dict:
        already = {}
        if project:
            already = {c["id"]: c["version"] for c in read_components(Path(project))["components"]}
        return resolve(self.registry, requested, archetype=archetype, already=already).to_dict()

    def verify_component(self, component_id: str, version: str | None = None) -> dict:
        """Contract test: build a throwaway project with the component and run its verification."""
        with self.operation("component_verify", component_id) as op:
            entry = self.registry.require(component_id, version)
            archetype = entry.manifest.archetypes[0]
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "probe"
                self.create_project(archetype, {"name": "Verify Probe"}, out, components=[component_id])
                rep = self.verifier.run(out, checks=("syntax", "tests"))
            self.store.add_evidence([{**r, "subject": f"component:{component_id}@{entry.manifest.version}"}
                                     for r in rep["evidence"]])
            op["summary"] = {"overall": rep["overall"]}
            if rep["overall"] == "failed":
                op["status"] = "failed"
            return {"component": f"{component_id}@{entry.manifest.version}", "archetype_probe": archetype, **{
                k: rep[k] for k in ("overall", "passed", "failed", "not_run", "complete")}}

    # ------------------------------------------------------------------ existing projects
    def analyze_project(self, path: str | Path) -> dict:
        with self.operation("analyze_project", path) as op:
            a = self.analyzer.analyze(path)
            op["summary"] = {"level": a["level"]}
            return {"operation_id": op["operation_id"], **a}

    def project_inventory(self, path: str | Path) -> dict:
        """Dependency and component inventory for export (FR-013 / CMP-06)."""
        a = self.analyzer.analyze(path)
        comps = []
        for c in a["installed_components"]:
            e = self.registry.get(c["id"], c["version"])
            comps.append({**c, "license": e.manifest.license if e else "unknown (not in local catalog)",
                          "publisher": e.manifest.publisher if e else "unknown",
                          "python_packages": list(e.manifest.python_packages) if e else []})
        return {"generated_at": utcnow(), "project": a["name"], "path": a["path"],
                "python_requires": a["python_requires"], "python_dependencies": a["dependencies"],
                "lockfiles": a["lockfiles"], "components": comps, "licenses": a["licenses"]}

    def adopt_project(self, path: str | Path, *, package: str, archetype: str, confirm: bool = False) -> dict:
        """Add a forge.toml to an existing project so it can be managed (integration level 1)."""
        root = Path(path).resolve()
        a = self.analyzer.analyze(root)
        if a["forge_project"]:
            raise ConflictFailure("Project already has a forge.toml")
        if archetype not in ("desktop", "web", "cli", "service"):
            raise ValidationFailure("archetype must be desktop|web|cli|service")
        package_problems = package_name_problems(package)
        if package_problems:
            raise ValidationFailure("Invalid package identifier", details=package_problems)
        if package not in a["packages"]:
            raise ValidationFailure(
                f"Package {package!r} was not discovered in this project",
                details=[f"discovered packages: {a['packages']}"])
        text = forge_toml_text({"name": a["name"], "package": package, "archetype": archetype,
                                "python_version": "3.11", "description": "", "author": "",
                                "forge_version": __version__}, "adopted", "0.0.0")
        if not confirm:
            return {"preview": True, "writes": ["forge.toml"], "content": text}
        with self.operation("adopt_project", root):
            with project_lock(self.settings.locks_dir, root, "adopt_project"):
                # Re-analyze while holding the lock: the preview may have gone stale.
                current = self.analyzer.analyze(root)
                if current["forge_project"]:
                    raise ConflictFailure("Project already has a forge.toml")
                if package not in current["packages"]:
                    raise ConflictFailure("The selected package changed after adoption preview")
                if current["git"]["state"] == "dirty" and "forge.toml" in current["git"]["dirty_paths"]:
                    raise ConflictFailure("forge.toml has uncommitted changes")
                target = root / "forge.toml"
                if target.exists() or target.is_symlink():
                    raise ConflictFailure("forge.toml already exists")
                # Use O_EXCL with mode 0666 so the process umask determines the
                # resulting metadata permissions, as it did with Path.write_text().
                for _ in range(10):
                    tmp = root / f".forge.toml.{secrets.token_hex(8)}.tmp"
                    try:
                        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                        break
                    except FileExistsError:
                        continue
                else:
                    raise ConflictFailure("Could not allocate a temporary forge.toml file")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(text)
                        fh.flush()
                        os.fsync(fh.fileno())
                    if target.exists() or target.is_symlink():
                        raise ConflictFailure("forge.toml appeared while adoption was being committed")
                    os.replace(tmp, target)
                finally:
                    tmp.unlink(missing_ok=True)
        return {"preview": False, "writes": ["forge.toml"]}

    def plan_template_update(self, project: str | Path, template: str | None = None) -> dict:
        with self.operation("plan_template_update", project) as op:
            plan = self.integration.plan_template_update(project, template)
            op["summary"] = {"plan_id": plan.plan_id, "conflicts": len(plan.conflicts)}
            return {"operation_id": op["operation_id"], **plan.to_dict(include_content=False)}

    def plan_add(self, project: str | Path, requested: dict[str, str]) -> dict:
        with self.operation("plan_add", project) as op:
            plan = self.integration.plan_add(project, requested)
            op["summary"] = {"plan_id": plan.plan_id, "conflicts": len(plan.conflicts)}
            return {"operation_id": op["operation_id"], **plan.to_dict(include_content=False)}

    def plan_remove(self, project: str | Path, ids: list[str]) -> dict:
        with self.operation("plan_remove", project) as op:
            plan = self.integration.plan_remove(project, ids)
            op["summary"] = {"plan_id": plan.plan_id, "conflicts": len(plan.conflicts)}
            return {"operation_id": op["operation_id"], **plan.to_dict(include_content=False)}

    def preview_plan(self, plan_id: str, with_content: bool = False) -> dict:
        plan = self.integration.load_plan(plan_id)
        preview = plan.to_dict(include_content=with_content)
        if plan.kind != "template-update":
            return preview

        actions = ("create", "modify", "delete", "manual")
        counts = {action: sum(change.action == action for change in plan.changes) for action in actions}
        preview["change_summary"] = {
            **counts,
            "total": len(plan.changes),
            "conflicts": len(plan.conflicts),
            "warnings": len(plan.warnings),
        }
        root = Path(plan.project_path)
        grouped = []
        for action in actions:
            entries = []
            for change in sorted((c for c in plan.changes if c.action == action), key=lambda c: c.path):
                item: dict[str, Any] = {"path": change.path, "reason": change.reason}
                if with_content:
                    target = root / change.path
                    before_text = ""
                    state = "matches-plan"
                    if change.before_sha is None:
                        if target.exists() or target.is_symlink():
                            state = "drifted"
                    elif target.is_symlink() or not target.is_file():
                        state = "drifted"
                    else:
                        try:
                            before_text = target.read_text(encoding="utf-8")
                        except (OSError, UnicodeError):
                            state = "unavailable"
                        else:
                            if sha256_text(before_text) != change.before_sha:
                                state = "drifted"
                    item["before_state"] = state
                    if state == "matches-plan":
                        after_text = change.content if change.action != "delete" else ""
                        if after_text is not None:
                            lines = list(difflib.unified_diff(
                                before_text.splitlines(keepends=True),
                                after_text.splitlines(keepends=True),
                                fromfile=f"a/{change.path}",
                                tofile=f"b/{change.path}",
                                n=3,
                            ))
                            truncated = len(lines) > 100
                            item["diff"] = "".join(lines[:100])
                            if truncated:
                                item["diff"] += "\\n... diff truncated (100 lines shown) ...\\n"
                    else:
                        item["diff"] = None
                entries.append(item)
            if entries:
                grouped.append({"action": action, "count": len(entries), "files": entries})
        preview["review"] = grouped
        return preview

    def approve_plan(self, plan_id: str, approver: str) -> dict:
        with self.operation("approve_plan", plan_id):
            return self.integration.approve(plan_id, approver).to_dict(include_content=False)

    def apply_plan(self, plan_id: str, *, verify: bool = True, auto_recover: bool = False) -> dict:
        with self.operation("apply_plan", plan_id) as op:
            rep = self.integration.apply(plan_id, verify=verify, auto_recover=auto_recover)
            op["summary"] = {"status": rep["status"]}
            if not rep["ok"]:
                op["status"] = "failed"
            return {"operation_id": op["operation_id"], **rep}

    def recover_plan(self, plan_id: str) -> dict:
        with self.operation("recover_plan", plan_id) as op:
            rep = self.integration.recover(plan_id)
            op["summary"] = {"status": rep["status"]}
            if not rep["complete"]:
                op["status"] = "partial"
            return {"operation_id": op["operation_id"], **rep}

    def plan_status(self, plan_id: str) -> dict:
        return self.integration.status(plan_id)

    # ------------------------------------------------------------------ verification / quality
    def verify_project(self, path: str | Path, checks: tuple[str, ...] = ("syntax", "tests")) -> dict:
        for c in checks:
            if c not in ALL_CHECKS:
                raise ValidationFailure(f"Unknown check {c!r}", details=[f"available: {ALL_CHECKS}"])
        with self.operation("verify_project", path) as op:
            if not Path(path).is_dir():
                raise ValidationFailure(f"Project path {str(path)!r} is not a directory")
            rep = self.verifier.run(path, checks)
            self.store.add_evidence(rep["evidence"])
            op["summary"] = {"overall": rep["overall"], "run_id": rep["run_id"]}
            if rep["overall"] == "failed":
                op["status"] = "failed"
            return {"operation_id": op["operation_id"], **rep}

    def check_architecture(self, package_dir: str | Path | None = None) -> dict:
        target = Path(package_dir) if package_dir else Path(__file__).resolve().parent
        v = check_rules(target)
        return {"package": str(target), "violations": v, "ok": not v}

    # ------------------------------------------------------------------ traceability / compliance
    def _requirements(self, requirements: str | Path | None, project: str | Path) -> tuple[list, Path]:
        path = Path(requirements) if requirements else Path(project) / "requirements.toml"
        return load_requirements(path), path

    def validate_trace(self, requirements: str | Path | None, project: str | Path = ".") -> dict:
        reqs, path = self._requirements(requirements, project)
        problems = validate_requirements(reqs)
        return {"requirements_file": str(path), "count": len(reqs), "problems": problems, "ok": not problems}

    def compliance_report(self, requirements: str | Path | None, project: str | Path = ".") -> dict:
        with self.operation("compliance_report", project) as op:
            reqs, path = self._requirements(requirements, project)
            subject = str(Path(project).resolve())
            ev = self.store.list_evidence(subject)
            rep = build_report(reqs, ev, subject=subject, run_id=ev[0]["run_id"] if ev else None)
            op["summary"] = {"summary": rep["summary"]}
            return {"operation_id": op["operation_id"], **rep}

    def supply_chain_report(self, project: str | Path, denied_licenses: list[str] | None = None) -> dict:
        inventory = self.project_inventory(project)
        return {
            "cyclonedx": build_cyclonedx(inventory),
            "spdx": build_spdx(inventory),
            "license_policy": check_license_policy(inventory, denied_licenses),
        }

    def export_sbom(self, project: str | Path, out_dir: str | Path) -> dict:
        report = self.supply_chain_report(project)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        files = {
            "sbom.cyclonedx.json": json.dumps(report["cyclonedx"], indent=2, sort_keys=True),
            "sbom.spdx.json": json.dumps(report["spdx"], indent=2, sort_keys=True),
            "license-policy.json": json.dumps(report["license_policy"], indent=2, sort_keys=True),
        }
        manifest = {}
        for name, content in files.items():
            (out / name).write_text(content + "\\n", encoding="utf-8")
            manifest[name] = sha256_text(content + "\\n")
        (out / "MANIFEST.sha256.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
        return {"directory": str(out), "files": sorted([*files, "MANIFEST.sha256.json"]),
                "license_policy_ok": report["license_policy"]["ok"],
                "unknown_licenses": len(report["license_policy"]["unknown"])}

    def create_compliance_artifact(self, code: str, project: str | Path, payload: dict) -> dict:
        with self.operation("compliance_artifact", project) as op:
            result = save_artifact(project, code, payload)
            op["summary"] = {"artifact": code, "path": result["path"]}
            return {"operation_id": op["operation_id"], **result}

    def export_evidence(self, requirements: str | Path | None, project: str | Path, out_dir: str | Path) -> dict:
        """Write compliance reports, evidence, inventory and validated compliance artifacts."""
        report = self.compliance_report(requirements, project)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        ev = self.store.list_evidence(str(Path(project).resolve()))
        artifacts = load_artifacts(project)
        supply_chain = self.supply_chain_report(project)
        files = {"compliance-report.json": json.dumps(report, indent=1, sort_keys=True),
                 "compliance-report.md": to_markdown(report),
                 "evidence.json": json.dumps(ev, indent=1, sort_keys=True),
                 "inventory.json": json.dumps(self.project_inventory(project), indent=1, sort_keys=True),
                 "compliance-artifacts.json": json.dumps(artifacts, indent=1, sort_keys=True),
                 "sbom.cyclonedx.json": json.dumps(supply_chain["cyclonedx"], indent=2, sort_keys=True),
                 "sbom.spdx.json": json.dumps(supply_chain["spdx"], indent=2, sort_keys=True),
                 "license-policy.json": json.dumps(supply_chain["license_policy"], indent=2, sort_keys=True)}
        manifest = {}
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
            manifest[name] = sha256_text(text)
        (out / "MANIFEST.sha256.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
        return {"directory": str(out), "files": sorted([*files, "MANIFEST.sha256.json"]),
                "evidence_records": len(ev), "compliance_artifacts": len(artifacts), "gaps": report["gaps"]}

    # ------------------------------------------------------------------ misc
    def history(self, limit: int = 50) -> list[dict]:
        return self.store.list_operations(limit)

    def history_item(self, operation_id: str) -> dict:
        op = self.store.get_operation(operation_id)
        if not op:
            raise ValidationFailure(f"No such operation {operation_id!r}")
        return op

    def show_config(self) -> dict:
        return {**self.settings.to_dict(), "platform": current_platform(), "forge_version": __version__}

    def doctor(self) -> dict:
        def tool(name):
            return {"available": shutil.which(name) is not None, "path": shutil.which(name)}

        def module(name):
            try:
                return {"available": importlib.util.find_spec(name) is not None}
            except (ImportError, ValueError):  # e.g. a module loaded without a spec
                return {"available": False}
        cat = self.registry.validate()
        try:
            probe = self.settings.home / ".write-test"
            probe.write_text("x")
            probe.unlink()
            writable = True
        except OSError:
            writable = False
        checks = [
            {"check": "python>=3.11", "ok": sys.version_info >= (3, 11), "detail": platform.python_version()},
            {"check": "home writable", "ok": writable, "detail": str(self.settings.home)},
            {"check": "catalog valid", "ok": cat["ok"], "detail": f"{cat['valid']} valid, "
                                                                  f"{len(cat['quarantined'])} quarantined"},
        ]
        return {"forge_version": __version__, "installed_from": str(Path(__file__).resolve().parent),
                "platform": current_platform(), "offline_mode": self.settings.offline,
                "checks": checks, "ok": all(c["ok"] for c in checks),
                "tools": {"git": tool("git"), "ruff": tool("ruff"), "mypy": tool("mypy"), "pip-audit": tool("pip-audit")},
                "modules": {"pytest": module("pytest"), "PySide6": module("PySide6"), "typer": module("typer")},
                "note": "No network access is attempted by diagnostics. Unavailable optional tools make the "
                        "related checks report 'not_run', never 'passed'."}

    # plugins
    def plugin_list(self) -> list[dict]:
        return self.extensions.discover()

    def plugin_inspect(self, name: str) -> dict:
        return self.extensions.inspect(name)

    def plugin_trust(self, name: str, level: str = "trusted") -> dict:
        with self.operation("plugin_trust", name):
            return self.extensions.trust(name, level)

    def plugin_enable(self, name: str) -> dict:
        with self.operation("plugin_enable", name):
            return self.extensions.enable(name)

    def plugin_disable(self, name: str) -> dict:
        with self.operation("plugin_disable", name):
            return self.extensions.disable(name)


    # ------------------------------------------------------------------ upgrades (UI-008)
    def plan_upgrade(self, project: str | Path, ids: list[str]) -> dict:
        with self.operation("plan_upgrade", project) as op:
            plan = self.integration.plan_upgrade(project, ids)
            op["summary"] = {"plan_id": plan.plan_id, "conflicts": len(plan.conflicts), "changes": len(plan.changes)}
            return {"operation_id": op["operation_id"], **plan.to_dict(include_content=False)}

    def project_components(self, project: str | Path) -> list[dict]:
        return self.integration.upgrade_candidates(project)

    # ------------------------------------------------------------------ architecture explorer (UI-016)
    def architecture_graph(self, package_dir: str | Path | None = None, fmt: str = "json") -> dict | str:
        g = module_graph(Path(package_dir) if package_dir else Path(__file__).resolve().parent)
        if fmt == "mermaid":
            return graph_to_mermaid(g)
        if fmt == "text":
            return graph_to_text(g)
        if fmt != "json":
            raise ValidationFailure("format must be json, mermaid or text")
        return g

    # ------------------------------------------------------------------ evidence / history comparison
    def list_runs(self, project: str | Path, limit: int = 20) -> list[dict]:
        return self.store.list_runs(str(Path(project).resolve()), limit)

    def compare_runs(self, project: str | Path, run_a: str | None = None, run_b: str | None = None) -> dict:
        subject = str(Path(project).resolve())
        if not run_a or not run_b:
            runs = self.store.list_runs(subject, 2)
            if len(runs) < 2:
                raise ValidationFailure("Need at least two verification runs to compare",
                                        hint=f"Run `forge test run {project}` again, or pass --a and --b.")
            run_b, run_a = runs[0]["run_id"], runs[1]["run_id"]
        before, after = self.store.list_evidence(subject, run_a), self.store.list_evidence(subject, run_b)
        if not before or not after:
            raise ValidationFailure("Unknown run id for this project")
        return {"run_a": run_a, "run_b": run_b, **compare_evidence(before, after)}

    def compare_operations(self, id_a: str, id_b: str) -> dict:
        a, b = self.history_item(id_a), self.history_item(id_b)
        diff = {k: {"a": a.get(k), "b": b.get(k)} for k in ("kind", "target", "status") if a.get(k) != b.get(k)}
        sa, sb = a.get("summary", {}), b.get("summary", {})
        diff["summary"] = {k: {"a": sa.get(k), "b": sb.get(k)} for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)}
        return {"a": id_a, "b": id_b, "differences": diff, "identical": not diff["summary"] and len(diff) == 1}

    def compliance_markdown(self, report: dict) -> str:
        return to_markdown(report)

    # ------------------------------------------------------------------ table designer (UI-014)
    def design_table(self, definition: dict, import_path: str | None = None) -> dict:
        d = normalize_definition(definition)
        out: dict[str, Any] = {"definition": d}
        if import_path:
            out["python"] = to_python(d, import_path)
        return out

    # ------------------------------------------------------------------ template import/export
    def export_template(self, template: str, out_dir: str | Path) -> dict:
        import shutil
        info = self.templates.get(template)
        out = Path(out_dir).resolve()
        if out.exists() and any(out.iterdir()):
            raise ConflictFailure(f"{out} exists and is not empty")
        shutil.copytree(info.root, out, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if not info.standalone:  # make the export self-contained by merging the shared files underneath
            common = (info.root.parent / "_common" / "tree")
            common = common if common.is_dir() else TEMPLATES_ROOT / "_common" / "tree"
            for f in common.rglob("*"):
                dest = out / "tree" / f.relative_to(common)
                if f.is_file() and not dest.exists() and "__pycache__" not in f.parts:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(f.read_bytes())
            tf = out / "template.toml"
            tf.write_text(tf.read_text(encoding="utf-8").replace("[template]\n", "[template]\nstandalone = true\n", 1),
                          encoding="utf-8")
        return {"exported": f"{info.id}@{info.version}", "path": str(out), "standalone": True}

    def import_template(self, path: str | Path) -> dict:
        import shutil
        with self.operation("import_template", path) as op:
            src = Path(path).resolve()
            if not (src / "template.toml").is_file():
                raise ValidationFailure(f"{src} has no template.toml")
            if any(p.is_symlink() for p in src.rglob("*")):
                raise SecurityBlock("Templates containing symlinks are not imported")
            info = self.templates._load(src)
            if any(t.id == info.id and t.version == info.version for t in self.templates.list()):
                raise ConflictFailure(f"Template {info.id}@{info.version} is already installed")
            self.templates.render(info, self.templates.validate_inputs(info, {"name": "Import Probe"}))  # must render
            dest = self.settings.home / "templates" / src.name
            if dest.exists():
                raise ConflictFailure(f"{dest} already exists")
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            op["summary"] = {"template": info.id}
            return {"imported": f"{info.id}@{info.version}", "path": str(dest)}

    # ------------------------------------------------------------------ locks (G-05)
    def lock_status(self, project: str | Path) -> dict:
        path = lock_path(self.settings.locks_dir, Path(project))
        held = read_lock(path) if path.exists() else None
        return {"locked": held is not None or path.exists(), "lock": held}

    def unlock_project(self, project: str | Path) -> dict:
        with self.operation("unlock_project", project):
            path = lock_path(self.settings.locks_dir, Path(project))
            existed = path.exists()
            path.unlink(missing_ok=True)
            return {"unlocked": existed}

    # ------------------------------------------------------------------ component authoring (G-07)
    def new_component(self, component_id: str, out_dir: str | Path, *, archetypes: list[str] | None = None,
                      category: str = "tooling", summary: str = "", publisher: str = "Your Name") -> dict:
        with self.operation("component_new", component_id):
            v = authoring.scaffold_component(Path(out_dir), component_id, archetypes=archetypes, category=category,
                                             summary=summary, publisher=publisher)
            return {"created": str(v), "next_steps": [f"edit {v / 'component.toml'} and files/",
                                                      f"forge component validate {v}", f"forge catalog add {v}"]}

    def validate_component(self, path: str | Path) -> dict:
        return authoring.validate_component_dir(Path(path))

    def seal_component_dir(self, path: str | Path) -> dict:
        with self.operation("component_seal", path):
            digest = seal_component(Path(path))
            return {"sealed": str(path), "digest": digest}

    def pack_component(self, path: str | Path, out: str | Path) -> dict:
        with self.operation("component_pack", path):
            z = authoring.pack_component(Path(path), Path(out))
            return {"archive": str(z)}

    def add_to_catalog(self, path: str | Path) -> dict:
        with self.operation("catalog_add", path):
            r = authoring.add_to_catalog(Path(path), self.settings.user_catalog)
            self.registry.scan(refresh=True)
            return r
