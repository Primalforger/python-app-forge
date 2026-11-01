"""Dependency-free project documentation scaffold rendering and creation.

Generated pages are starter material: project owners must review and complete
operational, security, deployment, and API details before publishing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_PACKAGE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_MAX_DESCRIPTION = 2000


@dataclass(frozen=True, slots=True)
class DocumentationProject:
    """Validated metadata used to render a project's documentation starter."""

    name: str
    description: str
    package_name: str
    python_requires: str = ">=3.11"
    license: str = "Specify a license"
    repository_url: str | None = None


def _required(value: str, field: str, *, limit: int = 200) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field} must not be empty")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return result


def validate_documentation_project(project: DocumentationProject) -> DocumentationProject:
    """Validate project metadata and return a normalized immutable copy."""
    if not isinstance(project, DocumentationProject):
        raise TypeError("project must be a DocumentationProject")
    name = _required(project.name, "name")
    if "\n" in name or "\r" in name:
        raise ValueError("name must be a single line")
    description = _required(project.description, "description", limit=_MAX_DESCRIPTION)
    package_name = _required(project.package_name, "package_name", limit=300)
    if not _PACKAGE.fullmatch(package_name):
        raise ValueError("package_name must be a dotted Python identifier")
    python_requires = _required(project.python_requires, "python_requires", limit=80)
    if not python_requires.startswith((">=", "==", "~=")):
        raise ValueError("python_requires must be a supported version constraint")
    license_name = _required(project.license, "license", limit=100)\n    if "\\n" in license_name or "\\r" in license_name:\n        raise ValueError("license must be a single line")
    repository_url = project.repository_url
    if repository_url is not None:
        repository_url = _required(repository_url, "repository_url", limit=500)
        parsed = urlparse(repository_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("repository_url must be an HTTPS URL without embedded credentials")
    return DocumentationProject(
        name=name, description=description, package_name=package_name,
        python_requires=python_requires, license=license_name,
        repository_url=repository_url,
    )


def render_documentation(project: DocumentationProject) -> dict[str, str]:
    """Render a deterministic MkDocs-ready documentation tree in memory."""
    item = validate_documentation_project(project)
    repo = f"\nRepository: {item.repository_url}" if item.repository_url else ""
    files = {
        "mkdocs.yml": (
            f"site_name: {json.dumps(item.name, ensure_ascii=False)}\n"
            f"site_description: {json.dumps(item.description, ensure_ascii=False)}\n"
            "docs_dir: docs\n"
            "nav:\n"
            "  - Home: index.md\n"
            "  - Getting started: getting-started.md\n"
            "  - Configuration: configuration.md\n"
            "  - CLI: cli.md\n"
            "  - Architecture: architecture.md\n"
            "  - Security: security.md\n"
            "  - API: api/index.md\n"
            "  - Contributing: contributing.md\n"
        ),
        "docs/index.md": (
            f"# {item.name}\n\n{item.description}\n\n"
            f"**Package:** `{item.package_name}`  \n"
            f"**Python:** `{item.python_requires}`  \n"
            f"**License:** {item.license}{repo}\n\n"
            "## What this project does\n\n"
            "_Describe the primary use cases, intended users, and key capabilities._\n"
        ),
        "docs/getting-started.md": (
            f"# Getting started\n\n## Requirements\n\n"
            f"- Python {item.python_requires}\n\n"
            "## Install\n\n"
            "Document the supported installation command and any optional extras.\n\n"
            "## First use\n\n"
            f"Add a minimal, verified example that imports `{item.package_name}`.\n"
        ),
        "docs/configuration.md": (
            "# Configuration\n\n"
            "Document each supported setting, its type, default, validation rules, "
            "and whether it contains sensitive data. Do not include real secrets.\n"
        ),
        "docs/cli.md": (
            "# Command-line interface\n\n"
            "List supported commands, required arguments, exit codes, and safe examples. "
            "Identify commands that modify or delete user data.\n"
        ),
        "docs/architecture.md": (
            "# Architecture\n\n"
            "Describe major modules, trust boundaries, data flows, external dependencies, "
            "and important design decisions. Link to relevant ADRs.\n"
        ),
        "docs/security.md": (
            "# Security\n\n"
            "Document the threat model, security-sensitive defaults, data handling, "
            "supported disclosure channel, and known limitations. This starter is not "
            "a security assessment or certification.\n"
        ),
        "docs/contributing.md": (
            "# Contributing\n\n"
            "Document the development environment, formatting and test commands, "
            "pull-request expectations, and review process.\n"
        ),
        "docs/api/index.md": (
            f"# API reference\n\n"
            f"Document the supported public API for `{item.package_name}`. "
            "Include stable import paths and runnable examples; omit private internals.\n"
        ),
    }
    return files


def create_documentation_scaffold(
    directory: str | Path, project: DocumentationProject
) -> tuple[Path, ...]:
    """Create the rendered documentation tree without replacing existing files.

    Existing target files cause FileExistsError. Files created by a failed
    attempt are removed before the exception is propagated.
    """
    rendered = render_documentation(project)
    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("documentation directory must be a real directory, not a symlink")
    targets = [root / relative for relative in rendered]
    for target in targets:
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        current = parent
        while current != root.parent:
            if current.is_symlink():
                raise ValueError("documentation paths must not contain symlink directories")
            if current == root:
                break
            current = current.parent
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"documentation file already exists: {target}")
    created: list[Path] = []
    try:
        for target, content in zip(targets, rendered.values()):
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            created.append(target)
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return tuple(targets)


__all__ = [
    "DocumentationProject",
    "create_documentation_scaffold",
    "render_documentation",
    "validate_documentation_project",
]
