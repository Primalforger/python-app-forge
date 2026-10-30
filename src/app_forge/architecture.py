"""Architecture rule checker: enforces the dependency direction rules of spec section 3.3 via AST scan."""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_IN_DOMAIN = {"PySide6", "fastapi", "typer", "sqlite3", "requests", "urllib", "http", "socket",
                       "subprocess", "os", "pathlib", "shutil", "tomllib"}
FRONTENDS = ("app_forge.gui", "app_forge.cli")
ALLOWED_FOR_FRONTENDS = ("app_forge.services", "app_forge.domain", "app_forge.observability",
                         "app_forge.settings")
EVIDENCE_PRODUCERS = ("app_forge.verification", "app_forge.integration")


def _imports(tree: ast.AST, module: str, is_pkg: bool) -> list[tuple[int, str]]:
    out = []
    base = module.split(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = base if is_pkg else base[:-1]
                anchor = anchor[:len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                name = ".".join(anchor + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            if node.module is None and node.level == 0:
                continue
            out.append((node.lineno, name))
            if name == "app_forge":  # "from app_forge import services" imports a submodule
                out += [(node.lineno, f"app_forge.{a.name}") for a in node.names]
    return out


def check_rules(package_dir: Path) -> list[dict]:
    package_dir = Path(package_dir)
    violations: list[dict] = []
    for f in sorted(package_dir.rglob("*.py")):
        if "data" in f.relative_to(package_dir).parts:  # template/component payloads are not platform code
            continue
        rel = f.relative_to(package_dir.parent)
        is_pkg = f.name == "__init__.py"
        parts = list(rel.with_suffix("").parts)
        if is_pkg:
            parts = parts[:-1]
        module = ".".join(parts)
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for line, imp in _imports(tree, module, is_pkg):
            def bad(rule: str) -> None:
                violations.append({"file": rel.as_posix(), "line": line, "import": imp, "rule": rule})
            top = imp.split(".")[0]
            if module.startswith("app_forge.domain"):
                if top in FORBIDDEN_IN_DOMAIN:
                    bad("Domain Core must not depend on GUI, network, database or filesystem implementations")
                if top == "app_forge" and not imp.startswith("app_forge.domain"):
                    bad("Domain Core may only depend on itself")
            for me, other in (("app_forge.gui", "app_forge.cli"), ("app_forge.cli", "app_forge.gui")):
                if module.startswith(me) and imp.startswith(other):
                    bad("GUI and CLI shells must not import each other")
            if module.startswith(FRONTENDS) and top == "app_forge":
                own = ".".join(module.split(".")[:2])
                dunder = imp.split(".")[-1].startswith("__")  # e.g. app_forge.__version__
                if not (imp == "app_forge" or dunder or imp == own or imp.startswith(own + ".")
                        or any(imp == a or imp.startswith(a + ".") for a in ALLOWED_FOR_FRONTENDS)):
                    bad("Shells may call only application services (plus domain, settings, observability)")
            if top == "sqlite3" and module != "app_forge.persistence":
                bad("SQLite must be accessed only through the persistence adapter")
            if module == "app_forge.compliance" and imp.startswith(EVIDENCE_PRODUCERS):
                bad("Compliance consumes evidence through data, not by importing verification producers")
    return violations


def _node(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "app_forge" or len(parts) < 2 or parts[1].startswith("__"):
        return None
    return ".".join(parts[:2])


def module_graph(package_dir: Path) -> dict:
    """Module-level dependency graph (second-level modules), with rule violations attached."""
    package_dir = Path(package_dir)
    nodes: set[str] = set()
    edges: dict[tuple[str, str], int] = {}
    for f in sorted(package_dir.rglob("*.py")):
        if "data" in f.relative_to(package_dir).parts:
            continue
        rel = f.relative_to(package_dir.parent)
        parts = list(rel.with_suffix("").parts)
        is_pkg = f.name == "__init__.py"
        if is_pkg:
            parts = parts[:-1]
        module = ".".join(parts)
        src = _node(module)
        if not src:
            continue
        nodes.add(src)
        for _, imp in _imports(ast.parse(f.read_text(encoding="utf-8")), module, is_pkg):
            dst = _node(imp)
            if dst and dst != src:
                nodes.add(dst)
                edges[(src, dst)] = edges.get((src, dst), 0) + 1
    return {"nodes": sorted(nodes), "edges": [{"from": a, "to": b, "imports": n} for (a, b), n in sorted(edges.items())],
            "violations": check_rules(package_dir)}


def graph_to_mermaid(graph: dict) -> str:
    ident = lambda n: n.replace(".", "_")
    lines = ["graph LR"] + [f'  {ident(n)}["{n}"]' for n in graph["nodes"]]
    lines += [f"  {ident(e['from'])} --> {ident(e['to'])}" for e in graph["edges"]]
    return "\n".join(lines) + "\n"


def graph_to_text(graph: dict) -> str:
    out = []
    for n in graph["nodes"]:
        deps = sorted(e["to"] for e in graph["edges"] if e["from"] == n)
        out.append(f"{n} -> {', '.join(deps) if deps else '(none)'}")
    out.append(f"violations: {len(graph['violations'])}")
    return "\n".join(out) + "\n"
