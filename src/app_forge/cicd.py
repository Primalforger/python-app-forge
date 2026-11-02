"""Deterministic CI/CD pipeline artifact generators."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass

_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_VERSION = re.compile(r"^3\\.(?:11|12|13|14)$")


def _command(value: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{field} must be a non-empty tuple of arguments")
    if any(not isinstance(part, str) or not part or any(c in part for c in "\\r\\n\\0") for part in value):
        raise ValueError(f"{field} arguments must be non-empty single-line strings")
    return value


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


@dataclass(frozen=True)
class CICDConfig:
    """Validated inputs shared by supported CI provider renderers."""

    project_name: str
    python_versions: tuple[str, ...] = ("3.11", "3.12", "3.13", "3.14")
    install_command: tuple[str, ...] = ("python", "-m", "pip", "install", "-e", ".")
    test_command: tuple[str, ...] = ("python", "-m", "pytest", "-q")
    lint_command: tuple[str, ...] | None = ("ruff", "check", ".")
    build: bool = True
    security_audit: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.project_name, str) or not _PROJECT.fullmatch(self.project_name):
            raise ValueError("project_name must be a safe 1-100 character identifier")
        if not isinstance(self.python_versions, tuple) or not self.python_versions:
            raise ValueError("python_versions must be a non-empty tuple")
        if len(set(self.python_versions)) != len(self.python_versions):
            raise ValueError("python_versions must be unique")
        if any(not isinstance(version, str) or not _VERSION.fullmatch(version) for version in self.python_versions):
            raise ValueError("python_versions must contain supported versions: 3.11 through 3.14")
        _command(self.install_command, "install_command")
        _command(self.test_command, "test_command")
        if self.lint_command is not None:
            _command(self.lint_command, "lint_command")
        if not isinstance(self.build, bool) or not isinstance(self.security_audit, bool):
            raise ValueError("build and security_audit must be booleans")


def render_github_actions(config: CICDConfig) -> str:
    """Render a least-privilege GitHub Actions test/build workflow."""
    versions = ", ".join(_yaml_string(version) for version in config.python_versions)
    steps = [
        "      - name: Check out source",
        "        uses: actions/checkout@v4",
        "      - name: Set up Python",
        "        uses: actions/setup-python@v5",
        "        with:",
        "          python-version: ${{ matrix.python-version }}",
        "      - name: Install project",
        f"        run: {shlex.join(config.install_command)}",
    ]
    if config.lint_command is not None:
        steps.extend(["      - name: Lint", f"        run: {shlex.join(config.lint_command)}"])
    steps.extend(["      - name: Test", f"        run: {shlex.join(config.test_command)}"])
    if config.security_audit:
        steps.extend(["      - name: Audit dependencies", "        run: python -m pip_audit"])
    if config.build:
        steps.extend([
            "      - name: Build distributions",
            "        run: python -m pip install build && python -m build",
        ])
    return (
        "name: CI\n\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "  pull_request:\n"
        "    branches: [main]\n"
        "  workflow_dispatch:\n\n"
        "permissions:\n"
        "  contents: read\n\n"
        "concurrency:\n"
        "  group: ci-${{ github.workflow }}-${{ github.ref }}\n"
        "  cancel-in-progress: true\n\n"
        "jobs:\n"
        "  quality:\n"
        "    name: Python ${{ matrix.python-version }}\n"
        "    runs-on: ubuntu-latest\n"
        "    strategy:\n"
        "      fail-fast: false\n"
        "      matrix:\n"
        f"        python-version: [{versions}]\n"
        "    steps:\n"
        + "\n".join(steps)
        + "\n"
    )


def render_gitlab_ci(config: CICDConfig) -> str:
    """Render a GitLab CI pipeline with a Python-version parallel matrix."""
    versions = ", ".join(_yaml_string(version) for version in config.python_versions)
    commands = [shlex.join(config.install_command)]
    if config.lint_command is not None:
        commands.append(shlex.join(config.lint_command))
    commands.append(shlex.join(config.test_command))
    if config.security_audit:
        commands.append("python -m pip_audit")
    if config.build:
        commands.append("python -m pip install build && python -m build")
    script = "\n".join(f"    - { _yaml_string(command) }" for command in commands)
    return (
        f"# CI pipeline for {config.project_name}\n"
        "stages:\n"
        "  - verify\n\n"
        "default:\n"
        "  image: python:${PYTHON_VERSION}-slim\n"
        "  cache:\n"
        "    key: pip-${PYTHON_VERSION}\n"
        "    paths:\n"
        "      - .cache/pip\n"
        "  before_script:\n"
        "    - python -m pip install --upgrade pip\n\n"
        "variables:\n"
        "  PIP_CACHE_DIR: \"$CI_PROJECT_DIR/.cache/pip\"\n\n"
        "verify:\n"
        "  stage: verify\n"
        "  parallel:\n"
        "    matrix:\n"
        f"      - PYTHON_VERSION: [{versions}]\n"
        "  script:\n"
        f"{script}\n"
    )


def render_cicd_files(config: CICDConfig) -> dict[str, str]:
    """Return deterministic project-relative workflows for both providers."""
    return {
        ".github/workflows/ci.yml": render_github_actions(config),
        ".gitlab-ci.yml": render_gitlab_ci(config),
    }
