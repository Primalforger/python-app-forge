"""CLI Shell (MOD-04). Parses arguments, calls application services, renders output and exit codes.

Exit codes: 0 ok | 2 validation | 3 conflict | 4 security block | 5 internal | 6 verification failed |
7 unavailable offline, or verification incomplete (some checks could not run).
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

import yaml

from app_forge import __version__
from app_forge.domain.errors import EXIT_CONFLICT, EXIT_INTERNAL, EXIT_OK, EXIT_UNAVAILABLE, EXIT_VALIDATION, EXIT_VERIFICATION
from app_forge.domain.errors import ForgeError, ValidationFailure
from app_forge.packaging import build_pyinstaller, pyinstaller_config_from_manifest, write_pyinstaller_spec
from app_forge.services import ForgeServices
from app_forge.settings import ForgeSettings


# ----------------------------------------------------------------------------- rendering
def _fmt(value, indent=0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:\n{_fmt(v, indent + 1)}")
            else:
                out.append(f"{pad}{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}")
        return "\n".join(out)
    if isinstance(value, list):
        if value and all(isinstance(x, dict) for x in value):
            return "\n".join(f"{pad}- " + _fmt(x, indent + 1).lstrip() for x in value)
        return "\n".join(f"{pad}- {x}" for x in value) if value else f"{pad}(none)"
    return f"{pad}{value}"


def _emit_template_update_preview(result: dict) -> None:
    summary = result.get("change_summary", {})
    print(f"Template update preview: {result.get('plan_id', '(unknown plan)')}")
    if result.get("project_path"):
        print(f"Project: {result['project_path']}")
    print(
        "Changes: "
        f"{summary.get('total', 0)} total | "
        f"+{summary.get('create', 0)} create | "
        f"~{summary.get('modify', 0)} modify | "
        f"-{summary.get('delete', 0)} delete | "
        f"{summary.get('manual', 0)} manual"
    )
    print(f"Review: {summary.get('conflicts', 0)} conflicts, {summary.get('warnings', 0)} warnings")

    for group in result.get("review", []):
        print(f"\\n{group.get('action', 'changes').upper()} ({group.get('count', len(group.get('files', [])))})")
        for item in group.get("files", []):
            print(f"  {item.get('path', '(unknown path)')}")
            if item.get("reason"):
                print(f"    Reason: {item['reason']}")
            if "before_state" in item and item["before_state"] != "matches-plan":
                print(f"    Before-state: {item['before_state']}; diff omitted")
            diff = item.get("diff")
            if diff:
                print("".join(f"    {line}" for line in diff.splitlines(keepends=True)), end="")

    for label in ("conflicts", "warnings"):
        entries = result.get(label, [])
        if entries:
            print(f"\\n{label.capitalize()}:")
            for entry in entries:
                if isinstance(entry, dict):
                    path = entry.get("path")
                    code = entry.get("code")
                    message = entry.get("message") or entry.get("resolution") or ""
                    prefix = f"{code}: " if code else ""
                    location = f" [{path}]" if path else ""
                    print(f"  - {prefix}{message}{location}".rstrip())
                    if entry.get("resolution") and entry.get("message"):
                        print(f"      Resolution: {entry['resolution']}")
                else:
                    print(f"  - {entry}")


def _emit_conflict_report(result: dict) -> None:
    conflicts = result.get("conflicts", [])
    print(f"Plan conflicts: {result.get('plan_id', '(unknown plan)')} ({len(conflicts)})")
    if not conflicts:
        print("No conflicts found.")
        return
    for index, conflict in enumerate(conflicts, start=1):
        if not isinstance(conflict, dict):
            print(f"\\n{index}. {conflict}")
            continue
        code = conflict.get("code") or "conflict"
        path = conflict.get("path")
        print(f"\\n{index}. {code}" + (f" — {path}" if path else ""))
        if conflict.get("message"):
            print(f"   {conflict['message']}")
        if conflict.get("resolution"):
            print(f"   Suggested resolution: {conflict['resolution']}")


def _table(value) -> str:
    if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
        return _fmt(value)
    columns = list(dict.fromkeys(key for row in value for key in row))
    cells = [[str(row.get(key, "")) for key in columns] for row in value]
    widths = [max([len(str(key))] + [len(row[i]) for row in cells]) for i, key in enumerate(columns)]
    line = "-+-".join("-" * width for width in widths)
    header = " | ".join(str(key).ljust(widths[i]) for i, key in enumerate(columns))
    body = [" | ".join(row[i].ljust(widths[i]) for i in range(len(columns))) for row in cells]
    return "\n".join([header, line, *body])


def _emit(args, result) -> None:
    output = "json" if getattr(args, "json", False) else getattr(args, "output", "text")
    if output == "json":
        print(json.dumps({"ok": True, "result": result}, indent=2, sort_keys=True, default=str))
    elif output == "yaml":
        print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True, default_flow_style=False), end="")
    elif output == "table":
        print(_table(result))
    elif isinstance(result, dict) and result.get("kind") == "template-update" and "change_summary" in result:
        _emit_template_update_preview(result)
    elif isinstance(result, dict) and result.get("kind") == "conflict-report":
        _emit_conflict_report(result)
    else:
        print(_fmt(result))


def _specs(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        cid, _, c = it.partition("@")
        out[cid] = c or "*"
    return out


def _confirm(args, message: str) -> None:
    if getattr(args, "yes", False):
        return
    if sys.stdin.isatty() and not args.non_interactive:
        if input(f"{message} [y/N] ").strip().lower() in ("y", "yes"):
            return
        raise ValidationFailure("Cancelled by user")
    raise ValidationFailure(f"Confirmation required: {message}", hint="Re-run with --yes to confirm non-interactively.")


# ----------------------------------------------------------------------------- command handlers
# Each returns (result, exit_code).
def c_init(s: ForgeServices, a):
    opts = {"name": a.name, "package": a.package, "description": a.description, "author": a.author,
            "python_version": a.python_version}
    out = a.out or Path.cwd() / (a.name or "project").lower().replace(" ", "-")
    return s.create_project(a.template or a.archetype, opts, out, components=a.component, dry_run=a.dry_run), 0


def c_template(s, a):
    if a.action == "list":
        return s.list_templates(), 0
    if a.action == "inspect":
        return s.inspect_template(a.target), 0
    if a.action == "export":
        if not a.out:
            raise ValidationFailure("usage: forge template export ID --out DIR")
        return s.export_template(a.target, a.out), 0
    if a.action == "import":
        return s.import_template(a.target), 0
    for t in s.list_templates():  # validate: dry-run render each template
        s.create_project(t["id"], {"name": "Validation Probe"}, Path("probe"), dry_run=True)
    return {"validated": [t["id"] for t in s.list_templates()]}, 0


def _plan_result(plan: dict, extra_hint: str = ""):
    code = EXIT_CONFLICT if plan["conflicts"] else 0
    if not plan["conflicts"]:
        plan = {**plan, "next_steps": [f"forge integrate approve {plan['plan_id']} --by <name>",
                                       f"forge integrate apply {plan['plan_id']}"]}
    return plan, code


def _maybe_apply(s, a, plan: dict):
    if not getattr(a, "apply", False) or plan["conflicts"]:
        return _plan_result(plan)
    if not a.by:
        raise ValidationFailure("--apply requires --by <approver>")
    _confirm(a, f"Apply plan {plan['plan_id']} ({len(plan['changes'])} change entries) to {plan['project_path']}?")
    s.approve_plan(plan["plan_id"], a.by)
    rep = s.apply_plan(plan["plan_id"], auto_recover=a.auto_recover)
    return rep, rep["exit_code"]


def c_component(s, a):
    act = a.action
    if act == "search":
        return s.search_components(a.query or "", category=a.category, capability=a.capability,
                                   archetype=a.archetype, state=a.state), 0
    if act == "inspect":
        return s.inspect_component(a.target, a.version), 0
    if act == "verify":
        r = s.verify_component(a.target, a.version)
        return r, EXIT_VERIFICATION if r["overall"] == "failed" else 0
    if act in ("enable", "disable"):
        return s.set_component_enabled(a.target, act == "enable"), 0
    if act == "add":
        return _maybe_apply(s, a, s.plan_add(a.project, _specs(a.ids)))
    if act == "remove":
        return _maybe_apply(s, a, s.plan_remove(a.project, a.ids))
    if act == "new":
        arch = [x for x in (a.archetype or "").split(",") if x] or None
        return s.new_component(a.target, a.out or ".", archetypes=arch, category=a.category or "tooling",
                               summary=a.summary or ""), 0
    if act == "validate":
        r = s.validate_component(a.target)
        return r, 0 if r["ok"] else EXIT_VALIDATION
    if act == "seal":
        return s.seal_component_dir(a.target), 0
    if act == "sign":
        if not a.key or not a.key_id:
            raise ValidationFailure("component sign requires --key PRIVATE_KEY --key-id ID")
        return s.sign_component(a.target, a.key, a.key_id), 0
    if act == "pack":
        return s.pack_component(a.target, a.out or f"{Path(a.target).parent.name}-{Path(a.target).name}.zip"), 0
    if act == "upgrade":
        return _maybe_apply(s, a, s.plan_upgrade(a.project, a.ids))
    if act == "outdated":
        rows = s.project_components(a.project)
        return rows, 0
    raise ValidationFailure(f"Unsupported component action {act!r}")


def c_trust(s, a):
    if a.action == "keygen":
        if not a.private_out or not a.public_out:
            raise ValidationFailure("trust keygen requires --private-out and --public-out")
        return s.generate_component_signing_key(a.target, a.private_out, a.public_out), 0
    if not a.key_id:
        raise ValidationFailure("trust add requires --key-id ID")
    return s.trust_component_key(a.key_id, a.target), 0


def c_catalog(s, a):
    if a.action == "refresh":
        return s.refresh_catalog(a.source or None), 0
    if a.action == "list":
        return s.list_catalog(), 0
    if a.action == "add":
        if not a.path:
            raise ValidationFailure("usage: forge catalog add PATH_OR_ZIP")
        return s.add_to_catalog(a.path), 0
    if a.action == "validate":
        r = s.validate_catalog()
        return r, 0 if r["ok"] else EXIT_VALIDATION
    if a.action == "rebuild":
        return s.rebuild_catalog_index(), 0
    return [{"source": n, "path": str(p)} for n, p in s.registry._roots], 0  # sources


def c_project(s, a):
    if a.action == "update":
        return _plan_result(s.plan_template_update(a.path, a.template))
    if a.action in ("inspect", "analyze"):
        return s.analyze_project(a.path), 0
    if a.action == "inventory":
        return s.project_inventory(a.path), 0
    if a.action == "lock-status":
        return s.lock_status(a.path), 0
    if a.action == "unlock":
        _confirm(a, f"Remove the Forge lock on {a.path}? Only do this if no Forge operation is running.")
        return s.unlock_project(a.path), 0
    if a.action == "adopt":
        if not a.package or not a.archetype:
            raise ValidationFailure("adopt requires --package and --archetype")
        if a.yes:
            return s.adopt_project(a.path, package=a.package, archetype=a.archetype, confirm=True), 0
        return s.adopt_project(a.path, package=a.package, archetype=a.archetype), 0
    r = s.validate_trace(None, a.path)  # validate
    return r, 0 if r["ok"] else EXIT_VALIDATION


def c_integrate(s, a):
    act = a.action
    if act == "plan":
        if a.remove:
            return _plan_result(s.plan_remove(a.project, a.remove))
        if a.upgrade:
            return _plan_result(s.plan_upgrade(a.project, a.upgrade))
        if not a.component:
            raise ValidationFailure("plan requires --component, --remove or --upgrade")
        return _plan_result(s.plan_add(a.project, _specs(a.component)))
    if act == "preview":
        return s.preview_plan(a.plan_id, with_content=a.content), 0
    if act == "conflicts":
        preview = s.preview_plan(a.plan_id, with_content=False)
        conflicts = preview.get("conflicts", [])
        if a.code:
            conflicts = [item for item in conflicts if isinstance(item, dict) and item.get("code") == a.code]
        if a.path:
            conflicts = [item for item in conflicts if isinstance(item, dict) and item.get("path") == a.path]
        return {
            "kind": "conflict-report",
            "plan_id": a.plan_id,
            "count": len(conflicts),
            "conflicts": conflicts,
        }, 0
    if act == "approve":
        return s.approve_plan(a.plan_id, a.by), 0
    if act == "apply":
        rep = s.apply_plan(a.plan_id, verify=not a.no_verify, auto_recover=a.auto_recover)
        return rep, rep["exit_code"]
    if act == "status":
        return s.plan_status(a.plan_id), 0
    rep = s.recover_plan(a.plan_id)
    return rep, 0 if rep["complete"] else EXIT_INTERNAL


def c_dependency(s, a):
    if a.action == "explain":
        e = s.inspect_component(a.ids[0])["manifest"]
        return {"component": e["id"], "requires": e["requires"], "optional": e["optional"],
                "provides": e["provides"], "requires_interfaces": e["requires_interfaces"],
                "python_packages": e["python_packages"]}, 0
    r = s.resolve_dependencies(_specs(a.ids), a.archetype, getattr(a, "project", None))
    return r, 0 if r["ok"] else EXIT_CONFLICT


def c_test(s, a):
    if a.action == "runs":
        return s.list_runs(a.project), 0
    if a.action == "compare":
        r = s.compare_runs(a.project, a.a, a.b)
        return r, EXIT_VERIFICATION if r["regressions"] else 0
    if a.action == "report":
        ev = s.store.list_evidence(str(Path(a.project).resolve()))
        return {"records": len(ev), "evidence": ev}, 0
    rep = s.verify_project(a.project, tuple(a.check) if a.check else ("syntax", "tests"))
    return rep, _verify_code(rep)


def _verify_code(rep: dict) -> int:
    """failed -> 6; some checks could not run (incomplete / not_run) -> 7; all passed -> 0."""
    if rep["overall"] == "failed":
        return EXIT_VERIFICATION
    return EXIT_UNAVAILABLE if rep["overall"] in ("incomplete", "not_run") else 0


def c_quality(s, a):
    check = {"lint": "ruff", "type-check": "mypy", "audit": "pip-audit"}[a.action]
    rep = s.verify_project(a.project, (check,))
    return rep, _verify_code(rep)


def c_architecture(s, a):
    if a.action == "diagram":
        out = s.architecture_graph(a.path, a.format)
        if isinstance(out, str):
            print(out, end="")
            return None, 0
        return out, 0
    r = s.check_architecture(a.path)
    return r, 0 if r["ok"] else EXIT_VALIDATION


def c_trace(s, a):
    if a.action == "validate":
        r = s.validate_trace(a.requirements, a.project)
        return r, 0 if r["ok"] else EXIT_VALIDATION
    rep = s.compliance_report(a.requirements, a.project)
    if a.action == "show":
        return {"summary": rep["summary"], "requirements": [
            {k: r[k] for k in ("id", "status", "verified_by", "reason")} for r in rep["requirements"]]}, 0
    return rep, 0  # export


def c_compliance(s, a):
    if a.action == "artifact":
        if not a.input:
            raise ValidationFailure("usage: forge compliance artifact CMP-05 --input RECORD.json")
        try:
            payload = json.loads(Path(a.input).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationFailure(f"Cannot read compliance artifact input: {exc}") from None
        return s.create_compliance_artifact(a.target, a.project, payload), 0
    if a.action == "package-evidence":
        return s.export_evidence(a.requirements, a.project, a.out), 0
    if a.action == "sbom":
        return s.export_sbom(a.project, a.out), 0
    if a.action == "licenses":
        report = s.supply_chain_report(a.project, a.deny_license)["license_policy"]
        return report, 0 if report["ok"] else EXIT_VALIDATION
    rep = s.compliance_report(a.requirements, a.project)
    if a.action == "report" and a.markdown:
        print(s.compliance_markdown(rep))
        return None, 0
    code = 0
    if a.action == "check" and (rep["summary"]["Failed"] or rep["summary"]["Blocked"]):
        code = EXIT_VERIFICATION
    return rep, code


def c_table(s, a):
    try:
        definition = json.loads(Path(a.definition).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"Cannot read table definition: {exc}") from None
    r = s.design_table(definition, a.import_path)
    if a.python_only:
        print(r["python"], end="")
        return None, 0
    return r, 0


def c_config(s, a):
    return s.show_config(), 0


def c_plugin(s, a):
    if a.action == "list":
        return s.plugin_list(), 0
    if a.action == "inspect":
        return s.plugin_inspect(a.name), 0
    if a.action == "trust":
        _confirm(a, f"Trust extension {a.name!r}? It will be able to run code inside App Forge.")
        return s.plugin_trust(a.name, "trusted"), 0
    if a.action == "untrust":
        return s.plugin_trust(a.name, "untrusted"), 0
    if a.action == "enable":
        return s.plugin_enable(a.name), 0
    if a.action == "disable":
        return s.plugin_disable(a.name), 0
    return s.plugin_inspect(a.name), 0  # validate


def c_doctor(s, a):
    r = s.doctor()
    return r, 0 if r["ok"] else EXIT_INTERNAL


def c_history(s, a):
    if a.action == "compare":
        if not a.target or not a.other:
            raise ValidationFailure("usage: forge history compare OPERATION_A OPERATION_B")
        return s.compare_operations(a.target, a.other), 0
    return (s.history(a.limit) if a.action == "list" else s.history_item(a.target)), 0



def c_audit(s, a):
    if a.action == "verify":
        report = s.audit_verify(a.path)
        return report, 0 if report["ok"] else EXIT_VERIFICATION
    if not a.actor or not a.event:
        raise ValidationFailure("audit append requires --actor and --event JSON")
    try:
        event = json.loads(a.event)
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"Invalid audit event JSON: {exc.msg}") from None
    try:
        record = s.audit_append(a.path, event, actor=a.actor)
    except ValueError as exc:
        raise ValidationFailure(str(exc)) from None
    return {"appended": True, "sequence": record["sequence"], "hash": record["hash"]}, 0


def c_gc(s, a):
    return s.garbage_collect(apply=a.apply), 0



def c_package(_services, a):
    try:
        manifest_path = Path(a.manifest).resolve()
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        config = pyinstaller_config_from_manifest(manifest)
        project = Path(a.project).resolve()
        if a.action == "spec":
            output = write_pyinstaller_spec(manifest, project, a.out)
            return {"spec": str(output), "name": config.name, "platforms": list(config.platforms)}, 0
        result = build_pyinstaller(
            a.spec, project, dist_path=a.distpath, work_path=a.workpath,
            clean=a.clean, timeout=a.timeout, platforms=config.platforms,
        )
        return result, 0 if result["ok"] else EXIT_VERIFICATION
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ValidationFailure(f"Invalid packaging manifest or project: {exc}") from None
    except RuntimeError as exc:
        raise ValidationFailure(str(exc)) from None


def c_completion(_services, a):
    commands = "init template component trust catalog project integrate dependency test quality architecture trace compliance table config plugin doctor gc history audit package completion"
    if a.shell == "bash":
        script = "_forge_completion() {\n  local cur=\"${COMP_WORDS[COMP_CWORD]}\"\n  if [[ $COMP_CWORD -eq 1 ]]; then\n    COMPREPLY=( $(compgen -W \"" + commands + "\" -- \"$cur\") )\n  elif [[ $COMP_CWORD -eq 2 ]]; then\n    case \"${COMP_WORDS[1]}\" in\n      template) COMPREPLY=( $(compgen -W 'list inspect validate export import' -- \"$cur\") ) ;;\n      component) COMPREPLY=( $(compgen -W 'search inspect add remove upgrade outdated verify enable disable new validate seal pack sign' -- \"$cur\") ) ;;\n      integrate) COMPREPLY=( $(compgen -W 'plan preview conflicts approve apply status recover' -- \"$cur\") ) ;;\n      *) ;;\n    esac\n  fi\n}\ncomplete -F _forge_completion forge\n"
    elif a.shell == "zsh":
        script = "# Add this file to fpath and run compinit.\n_forge() {\n  local -a commands\n  commands=(" + commands + ")\n  _arguments '1:command:((" + commands + "))' '2:action:((list inspect validate export import search add remove upgrade verify plan preview approve apply status recover))'\n}\ncompdef _forge forge\n"
    else:
        script = "# Save as ~/.config/fish/completions/forge.fish\ncomplete -c forge -f -n 'not __fish_seen_subcommand_from " + commands + "' -a '" + commands + "'\ncomplete -c forge -f -n '__fish_seen_subcommand_from template' -a 'list inspect validate export import'\ncomplete -c forge -f -n '__fish_seen_subcommand_from component' -a 'search inspect add remove upgrade outdated verify enable disable new validate seal pack sign'\ncomplete -c forge -f -n '__fish_seen_subcommand_from integrate' -a 'plan preview conflicts approve apply status recover'\n"
    return script, 0


# ----------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge", description="Python App Forge: create, extend, verify applications.")
    p.add_argument("--version", action="version", version=f"forge {__version__}")
    p.add_argument("--json", action="store_true", help="deprecated alias for --output json")
    p.add_argument("--output", choices=["text", "json", "yaml", "table"], default="text", help="output format (default: text)")
    p.add_argument("--progress", choices=["auto", "always", "never"], default="auto", help="progress messages on stderr (default: auto)")
    p.add_argument("--home", help="platform data directory (default: $FORGE_HOME or ~/.app_forge)")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("--non-interactive", action="store_true", help="never prompt; fail if confirmation is needed")
    sub = p.add_subparsers(dest="group", required=True, metavar="GROUP")

    def grp(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    def acts(sp, names):
        sp.add_argument("action", choices=names)
        return sp

    sp = grp("init", c_init, "create a new project from a template")
    sp.add_argument("--archetype", choices=["desktop", "web", "cli", "service"])
    sp.add_argument("--template")
    sp.add_argument("--name", required=True)
    sp.add_argument("--out")
    sp.add_argument("--package")
    sp.add_argument("--description")
    sp.add_argument("--author")
    sp.add_argument("--python-version")
    sp.add_argument("--component", action="append", default=[], help="component id (repeatable)")
    sp.add_argument("--dry-run", action="store_true", help="show the generation plan without writing")

    sp = acts(grp("template", c_template, "list/inspect/validate/export/import templates"),
              ["list", "inspect", "validate", "export", "import"])
    sp.add_argument("target", nargs="?")
    sp.add_argument("--out")

    sp = acts(grp("component", c_component, "search/inspect/add/remove/verify components"),
              ["search", "inspect", "add", "remove", "upgrade", "outdated", "verify", "enable", "disable", "new",
               "validate", "seal", "pack", "sign"])
    sp.add_argument("--query")
    sp.add_argument("--category")
    sp.add_argument("--capability")
    sp.add_argument("--archetype")
    sp.add_argument("--state")
    sp.add_argument("--version")
    sp.add_argument("--out", help="for new/pack: output directory or archive")
    sp.add_argument("--summary", help="for new")
    sp.add_argument("--key", help="sign: Ed25519 private key PEM")
    sp.add_argument("--key-id", help="sign: trusted key identifier")
    sp.add_argument("--project", help="for add/remove")
    sp.add_argument("--apply", action="store_true", help="for add/remove: approve and apply immediately")
    sp.add_argument("--by", help="approver identity (with --apply)")
    sp.add_argument("--auto-recover", action="store_true")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("ids", nargs="*", help="component ids (add: id or id@constraint)")
    sp.set_defaults(_component=True)

    sp = acts(grp("trust", c_trust, "manage component signing keys"), ["keygen", "add"])
    sp.add_argument("target", help="key id for keygen; public key path for add")
    sp.add_argument("--key-id", help="trusted key identifier (required for add)")
    sp.add_argument("--private-out", help="keygen: private key output path")
    sp.add_argument("--public-out", help="keygen: public key output path")

    sp = sp = acts(grp("catalog", c_catalog, "manage the local component catalog"),
              ["list", "validate", "rebuild", "sources", "add", "refresh"])
    sp.add_argument("path", nargs="?")
    sp.add_argument("--source", action="append", default=[], help="refresh: catalog index URL (repeatable; overrides configured sources)")

    sp = acts(grp("project", c_project, "inspect and analyze projects"),
              ["inspect", "analyze", "inventory", "validate", "adopt", "lock-status", "unlock", "update"])
    sp.add_argument("path", nargs="?", default=".")
    sp.add_argument("--package")
    sp.add_argument("--archetype")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("--template", help="update target template ID or ID@VERSION")

    sp = acts(grp("integrate", c_integrate, "plan, apply and recover project changes"),
              ["plan", "preview", "conflicts", "approve", "apply", "status", "recover"])
    sp.add_argument("target", nargs="?", help="plan: PROJECT path; others: PLAN_ID")
    sp.add_argument("--component", action="append", default=[])
    sp.add_argument("--remove", action="append", default=[])
    sp.add_argument("--upgrade", action="append", default=[])
    sp.add_argument("--by")
    sp.add_argument("--content", action="store_true", help="preview: include bounded file diffs")
    sp.add_argument("--code", help="conflicts: filter by conflict code")
    sp.add_argument("--path", help="conflicts: filter by exact project-relative path")
    sp.add_argument("--no-verify", action="store_true")
    sp.add_argument("--auto-recover", action="store_true")

    sp = acts(grp("dependency", c_dependency, "resolve and explain dependencies"), ["resolve", "check", "explain"])
    sp.add_argument("ids", nargs="+")
    sp.add_argument("--archetype")
    sp.add_argument("--project")

    sp = acts(grp("test", c_test, "run verification"), ["run", "report", "runs", "compare"])
    sp.add_argument("project", nargs="?", default=".")
    sp.add_argument("--a", help="compare: earlier run id (default: second most recent)")
    sp.add_argument("--b", help="compare: later run id (default: most recent)")
    sp.add_argument("--check", action="append", choices=["syntax", "tests", "ruff", "mypy", "pip-audit"])

    sp = acts(grp("quality", c_quality, "lint, type-check, audit"), ["lint", "type-check", "audit"])
    sp.add_argument("project", nargs="?", default=".")

    sp = acts(grp("architecture", c_architecture, "check rules / draw module graph"), ["check-rules", "diagram"])
    sp.add_argument("path", nargs="?")
    sp.add_argument("--format", choices=["text", "mermaid", "json"], default="text")

    for name, fn, names in (("trace", c_trace, ["show", "validate", "export"]),
                            ("compliance", c_compliance, ["check", "report", "artifact", "licenses", "sbom", "package-evidence"])):
        sp = acts(grp(name, fn, f"{name} requirements and evidence"), names)
        sp.add_argument("--project", default=".")
        sp.add_argument("--requirements")
        sp.add_argument("--out", default="evidence-package")
        sp.add_argument("--markdown", action="store_true")
        sp.add_argument("--input", help="artifact: JSON record to validate and store")
        sp.add_argument("target", nargs="?", help="artifact: CMP-05, CMP-08, CMP-09, CMP-10 or CMP-11")
        sp.add_argument("--deny-license", action="append", default=[],
                        help="licenses: denied SPDX licence identifier (repeatable)")

    sp = acts(grp("table", c_table, "table designer: validate a definition, generate code"), ["design"])
    sp.add_argument("definition", help="JSON table definition file")
    sp.add_argument("--import-path", help="module path of the table component, e.g. my_app.table_model")
    sp.add_argument("--python-only", action="store_true")

    sp = acts(grp("config", c_config, "show configuration"), ["show"])

    sp = acts(grp("plugin", c_plugin, "manage extensions"),
              ["list", "inspect", "trust", "untrust", "enable", "disable", "validate"])
    sp.add_argument("name", nargs="?")
    sp.add_argument("--yes", action="store_true")

    grp("doctor", c_doctor, "environment diagnostics")

    sp = grp("completion", c_completion, "print shell completion definitions")
    sp.add_argument("shell", choices=["bash", "zsh", "fish"])

    sp = grp("gc", c_gc, "preview or remove expired Forge data")
    sp.add_argument("--apply", action="store_true", help="perform deletion (default is a safe dry run)")

    sp = acts(grp("package", c_package, "generate and build PyInstaller desktop applications"), ["spec", "build"])
    sp.add_argument("manifest", help="TOML manifest with [packaging.pyinstaller]")
    sp.add_argument("--project", default=".", help="project root (default: current directory)")
    sp.add_argument("--out", default="forge.spec", help="spec: output path relative to project root")
    sp.add_argument("--spec", default="forge.spec", help="build: existing spec path relative to project root")
    sp.add_argument("--distpath", default="dist")
    sp.add_argument("--workpath", default="build/pyinstaller")
    sp.add_argument("--timeout", type=int, default=1800)
    sp.add_argument("--clean", action="store_true")

    sp = acts(grp("audit", c_audit, "append and verify hash-chained audit events"), ["append", "verify"])
    sp.add_argument("path", help="JSONL audit log path")
    sp.add_argument("--actor", help="append: actor identity")
    sp.add_argument("--event", help="append: event as a JSON object")

    sp = acts(grp("history", c_history, "operation history"), ["list", "inspect", "compare"])
    sp.add_argument("target", nargs="?")
    sp.add_argument("other", nargs="?")
    sp.add_argument("--limit", type=int, default=20)
    return p


def _normalise(a: argparse.Namespace) -> None:
    """Map positional shapes of a few groups onto the handler argument names."""
    if a.group == "component":
        if a.action in ("add", "remove", "upgrade", "outdated"):
            if not a.project and a.ids:
                a.project, a.ids = a.ids[0], a.ids[1:]
            if not a.project or (not a.ids and a.action != "outdated"):
                raise ValidationFailure(f"usage: forge component {a.action} PROJECT ID [ID...] [--apply --by NAME]")
        elif a.action == "search":
            if a.ids and not a.query:
                a.query = " ".join(a.ids)
        elif a.action in ("inspect", "verify", "enable", "disable", "new", "validate", "seal", "pack", "sign"):
            if not a.ids:
                raise ValidationFailure(f"usage: forge component {a.action} ID")
            a.target = a.ids[0]
    elif a.group == "template" and a.action in ("inspect", "export", "import") and not a.target:
        raise ValidationFailure(f"usage: forge template {a.action} {'PATH' if a.action == 'import' else 'ID'}")
    elif a.group == "integrate":
        if a.action == "plan":
            if not a.target:
                raise ValidationFailure("usage: forge integrate plan PROJECT --component ID [--component ID]")
            a.project = a.target
        else:
            if not a.target:
                raise ValidationFailure(f"usage: forge integrate {a.action} PLAN_ID")
            a.plan_id = a.target
            if a.action == "approve" and not a.by:
                raise ValidationFailure("approve requires --by <name>")
    elif a.group == "plugin" and a.action != "list" and not a.name:
        raise ValidationFailure(f"usage: forge plugin {a.action} NAME")
    elif a.group == "history" and a.action == "inspect" and not a.target:
        raise ValidationFailure("usage: forge history inspect OPERATION_ID")
    elif a.group == "dependency" and a.action == "check" and not a.project:
        a.project = None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _normalise(args)
        if args.group == "completion":
            result, code = c_completion(None, args)
            print(result, end="")
            return code
        progress = args.progress == "always" or (args.progress == "auto" and sys.stderr.isatty())
        if progress:
            print("forge: running " + args.group + " " + getattr(args, "action", ""), file=sys.stderr)
        services = ForgeServices(ForgeSettings.load(Path(args.home) if args.home else None), verbosity=args.verbose)
        result, code = args.fn(services, args)
        if progress:
            state = "completed" if code == 0 else "finished with exit code " + str(code)
            print("forge: " + state, file=sys.stderr)
        if result is not None:
            _emit(args, result)
        return code
    except ForgeError as exc:
        if args.json or args.output == "json":
            print(json.dumps({"ok": False, "error": exc.to_dict()}, indent=2, sort_keys=True))
        elif args.output == "yaml":
            print(yaml.safe_dump({"ok": False, "error": exc.to_dict()}, sort_keys=False), end="")
        else:
            print(f"error [{exc.category}]: {exc.message}", file=sys.stderr)
            for d in exc.details:
                print(f"  - {d}", file=sys.stderr)
            if exc.hint:
                print(f"hint: {exc.hint}", file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:  # e.g. output piped to `head`
        return EXIT_OK
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130
    except Exception as exc:  # unexpected: never leak a traceback as success
        if args.json or args.output == "json":
            print(json.dumps({"ok": False, "error": {"category": "internal", "message": f"{type(exc).__name__}: {exc}"}}))
        elif args.output == "yaml":
            print(yaml.safe_dump({"ok": False, "error": {"category": "internal", "message": f"{type(exc).__name__}: {exc}"}}, sort_keys=False), end="")
        else:
            print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
