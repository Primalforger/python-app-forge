"""Manifest-driven pre-commit and import-linter configuration generators."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_PACKAGE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_CONTRACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


@dataclass(frozen=True)
class ForbiddenImportContract:
    """A directed import prohibition declared by a project/template manifest."""

    name: str
    source_modules: tuple[str, ...]
    forbidden_modules: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _CONTRACT_NAME.fullmatch(self.name):
            raise ValueError("contract name must be a safe 1-80 character label")
        for field_name, values in (("source_modules", self.source_modules),
                                   ("forbidden_modules", self.forbidden_modules)):
            if not isinstance(values, tuple) or not values:
                raise ValueError(f"{field_name} must be a non-empty tuple")
            if any(not isinstance(value, str) or not _MODULE.fullmatch(value) for value in values):
                raise ValueError(f"{field_name} must contain valid dotted Python module names")
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True)
class QualityConfig:
    """Validated quality-tool settings parsed from a template/project manifest."""

    pre_commit: bool = True
    import_linter: bool = False
    contracts: tuple[ForbiddenImportContract, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.pre_commit, bool) or not isinstance(self.import_linter, bool):
            raise ValueError("pre_commit and import_linter must be booleans")
        if not isinstance(self.contracts, tuple) or any(
            not isinstance(contract, ForbiddenImportContract) for contract in self.contracts
        ):
            raise ValueError("contracts must be a tuple of ForbiddenImportContract values")
        if self.import_linter and not self.contracts:
            raise ValueError("at least one import-linter contract is required when import_linter is enabled")
        names = [contract.name for contract in self.contracts]
        if len(set(names)) != len(names):
            raise ValueError("import-linter contract names must be unique")


def quality_config_from_manifest(manifest: Mapping[str, Any]) -> QualityConfig:
    """Parse the optional [quality] section of a TOML manifest without guessing invalid values."""
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be a mapping")
    raw = manifest.get("quality", {})
    if not isinstance(raw, Mapping):
        raise ValueError("quality manifest section must be a table")
    pre_commit = raw.get("pre_commit", True)
    import_linter = raw.get("import_linter", False)
    raw_contracts = raw.get("contracts", [])
    if not isinstance(raw_contracts, list):
        raise ValueError("quality.contracts must be an array of tables")
    contracts = []
    for index, item in enumerate(raw_contracts):
        if not isinstance(item, Mapping):
            raise ValueError(f"quality.contracts[{index}] must be a table")
        name = item.get("name")
        source = item.get("source_modules")
        forbidden = item.get("forbidden_modules")
        if not isinstance(name, str):
            raise ValueError(f"quality.contracts[{index}].name must be a string")
        if not isinstance(source, list) or not isinstance(forbidden, list):
            raise ValueError(f"quality.contracts[{index}] requires source_modules and forbidden_modules arrays")
        contracts.append(ForbiddenImportContract(name, tuple(source), tuple(forbidden)))
    return QualityConfig(pre_commit, import_linter, tuple(contracts))


def render_pre_commit(config: QualityConfig) -> str:
    """Render pinned, language-agnostic hygiene hooks and a local Ruff hook."""
    if not config.pre_commit:
        raise ValueError("pre-commit generation is disabled by the manifest")
    return (
        "minimum_pre_commit_version: '3.7.0'\n"
        "default_stages: [pre-commit]\n"
        "repos:\n"
        "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
        "    rev: v5.0.0\n"
        "    hooks:\n"
        "      - id: trailing-whitespace\n"
        "      - id: end-of-file-fixer\n"
        "      - id: check-yaml\n"
        "      - id: check-toml\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: ruff\n"
        "        name: ruff\n"
        "        entry: ruff check --force-exclude\n"
        "        language: system\n"
        "        types_or: [python, pyi]\n"
        "        require_serial: true\n"
    )


def _toml_string(value: str) -> str:
    """Encode a validated TOML string without allowing multiline injection."""
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\0"):
        raise ValueError("import-linter values must be non-empty single-line strings")
    return json.dumps(value, ensure_ascii=True)


def render_import_linter(package: str, config: QualityConfig) -> str:
    """Render import-linter's native TOML configuration from validated contracts."""
    if not config.import_linter:
        raise ValueError("import-linter generation is disabled by the manifest")
    if not isinstance(package, str) or not _PACKAGE.fullmatch(package):
        raise ValueError("package must be a valid dotted Python package name")
    lines = [
        "[importlinter]",
        f"root_package = {_toml_string(package)}",
        "include_external_packages = false",
        "",
    ]
    for contract in config.contracts:
        for module in (*contract.source_modules, *contract.forbidden_modules):
            if module != package and not module.startswith(package + "."):
                raise ValueError("contract modules must belong to the configured root package")
        lines.extend([
            "[[importlinter.contracts]]",
            f"name = {_toml_string(contract.name)}",
            'type = "forbidden"',
            "source_modules = " + json.dumps(list(contract.source_modules)),
            "forbidden_modules = " + json.dumps(list(contract.forbidden_modules)),
            "",
        ])
    return "\n".join(lines)


def render_quality_files(manifest: Mapping[str, Any], package: str) -> dict[str, str]:
    """Return generated quality-tool files for a manifest; rendering never writes to disk."""
    config = quality_config_from_manifest(manifest)
    files: dict[str, str] = {}
    if config.pre_commit:
        files[".pre-commit-config.yaml"] = render_pre_commit(config)
    if config.import_linter:
        files[".importlinter"] = render_import_linter(package, config)
    return files
