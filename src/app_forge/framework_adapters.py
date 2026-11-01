"""Static, reversible framework registration adapters for conventional Python projects.

Adapters inspect source with ast only: they never import or execute project code.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

from app_forge.domain.errors import ValidationFailure


@dataclass(frozen=True)
class Registration:
    framework: str
    module: str
    symbol: str
    application: str = ""
    route: str = ""


def _identifier(value: str, label: str) -> None:
    if not value or not all(part.isidentifier() for part in value.split(".")):
        raise ValidationFailure(f"framework registration {label} must be a dotted Python identifier")


def _call_name(node: ast.expr | None) -> str:
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            return fn.attr
    return ""


def _targets(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _locate(source: str, spec: Registration) -> tuple[int, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValidationFailure(f"cannot adapt invalid Python source: {exc}") from None

    if spec.framework in ("fastapi", "flask"):
        constructor = "FastAPI" if spec.framework == "fastapi" else "Flask"
        matches = []
        for node in tree.body:
            for name in _targets(node):
                value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
                if _call_name(value) == constructor and (not spec.application or name == spec.application):
                    matches.append((node.end_lineno or node.lineno, name, node.col_offset))
        if len(matches) != 1:
            raise ValidationFailure(
                f"{spec.framework} adapter expected one unambiguous {constructor} application "
                f"({len(matches)} candidates found); specify application or add an explicit anchor"
            )
        line, _name, indent = matches[0]
        return line, " " * indent

    if spec.framework == "django":
        urlconf_nodes = [candidate for candidate in tree.body if "urlpatterns" in _targets(candidate)]
        if len(urlconf_nodes) != 1:
            raise ValidationFailure(
                f"Django adapter expected one top-level urlpatterns assignment ({len(urlconf_nodes)} found)"
            )
        urlconf_node = urlconf_nodes[0]
        return urlconf_node.end_lineno or urlconf_node.lineno, ""

    raise ValidationFailure(f"unsupported framework adapter {spec.framework!r}")


def registration_content(spec: Registration, application: str = "app") -> str:
    _identifier(spec.module, "module")
    if not spec.symbol.isidentifier():
        raise ValidationFailure("framework registration symbol must be a Python identifier")
    if spec.framework == "fastapi":
        return f"from {spec.module} import {spec.symbol}\n{application}.include_router({spec.symbol})\n"
    if spec.framework == "flask":
        return f"from {spec.module} import {spec.symbol}\n{application}.register_blueprint({spec.symbol})\n"
    if spec.framework == "django":
        route = spec.route
        if any(ch in route for ch in ("\r", "\n", '"', "\\")):
            raise ValidationFailure("Django route must be a simple quoted URL prefix")
        return (
            "from django.urls import include, path\n"
            f'urlpatterns += [path("{route}", include("{spec.module}"))]\n'
        )
    raise ValidationFailure(f"unsupported framework adapter {spec.framework!r}")


def apply_registration(source: str, spec: Registration, component: str, patch_id: str,
                       *, replace: bool = False, expect_sha: str | None = None):
    """Insert a managed registration block immediately after the framework declaration."""
    from app_forge.domain.models import Patch
    from app_forge.patching import _apply_block

    line, indent = _locate(source, spec)
    application = "app"
    if spec.framework in ("fastapi", "flask"):
        tree = ast.parse(source)
        constructor = "FastAPI" if spec.framework == "fastapi" else "Flask"
        names = []
        for node in tree.body:
            for name in _targets(node):
                value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
                if _call_name(value) == constructor and (not spec.application or name == spec.application):
                    names.append(name)
        application = names[0]
    content = registration_content(spec, application)
    patch = Patch(patch_id, "unused.py", "insert", "framework", "after", "#", content)

    def locate(lines):
        return line, indent

    return _apply_block(source, patch, component, content, replace=replace,
                        expect_sha=expect_sha, locate_new=locate)
