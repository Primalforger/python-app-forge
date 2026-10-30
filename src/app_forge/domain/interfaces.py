"""Versioned component interface contract parsing and validation."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app_forge.domain.errors import ValidationFailure
from app_forge.domain.versioning import Constraint, Version

_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True)
class InterfaceSpec:
    name: str
    constraint: Constraint | None = None
    version: Version | None = None


def parse_interface(value: str, *, provider: bool = False) -> InterfaceSpec:
    """Parse 'namespace.name@version-or-constraint'; providers require an exact version."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailure("interface declaration must be a non-empty string")
    raw = value.strip()
    if raw.count("@") > 1:
        raise ValidationFailure(f"invalid interface declaration {value!r}")
    name, separator, version_text = raw.partition("@")
    if not _NAME.fullmatch(name):
        raise ValidationFailure(
            f"invalid interface name {name!r}; use lowercase dot/underscore/hyphen-separated identifiers"
        )
    if provider:
        if not separator:
            raise ValidationFailure(f"provided interface {name!r} must declare an exact version (name@MAJOR.MINOR)")
        try:
            version = Version.parse(version_text)
        except ValidationFailure as exc:
            raise ValidationFailure(f"provided interface {value!r} has an invalid version: {exc.message}") from None
        return InterfaceSpec(name=name, version=version)
    if not separator:
        return InterfaceSpec(name=name)
    try:
        constraint = Constraint.parse(version_text)
    except ValidationFailure as exc:
        raise ValidationFailure(f"required interface {value!r} has an invalid version constraint: {exc.message}") from None
    return InterfaceSpec(name=name, constraint=constraint)


def validate_interface_declarations(provides: tuple[str, ...], requires: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    for label, values, is_provider in (("interfaces.provides", provides, True),
                                        ("interfaces.requires", requires, False)):
        seen: set[str] = set()
        for value in values:
            try:
                spec = parse_interface(value, provider=is_provider)
            except ValidationFailure as exc:
                problems.append(f"{label}: {exc.message}")
                continue
            if spec.name in seen:
                problems.append(f"{label}: duplicate declaration for {spec.name!r}")
            seen.add(spec.name)
    return problems
