"""Conservative SPDX licence-expression scanner for supply-chain inventories.

The scanner is intentionally offline. It identifies denied SPDX identifiers inside
compound expressions and keeps missing licence metadata explicitly unresolved.
"""
from __future__ import annotations

import re
from typing import Any

from app_forge.domain.errors import ValidationFailure

_UNKNOWN = {"", "unknown", "noassertion", "none", "n/a"}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*(?::[A-Za-z0-9][A-Za-z0-9.+-]*)?")
_OPERATORS = {"AND", "OR", "WITH"}


def _tokens(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        if expression[position] in "()":
            tokens.append(expression[position])
            position += 1
            continue
        match = _TOKEN.match(expression, position)
        if match is None:
            raise ValidationFailure(
                f"Invalid SPDX licence expression at character {position}: {expression!r}"
            )
        tokens.append(match.group())
        position = match.end()
    if not tokens:
        raise ValidationFailure("SPDX licence expression must not be empty")
    return tokens


class _ExpressionParser:
    """Small SPDX expression grammar parser; returns licence IDs, not exception IDs."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0
        self.licenses: list[str] = []

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise ValidationFailure("Unexpected end of SPDX licence expression")
        self.index += 1
        return token

    def _identifier(self) -> str:
        token = self._take()
        if token in _OPERATORS or token in ("(", ")"):
            raise ValidationFailure(f"Expected SPDX identifier, found {token!r}")
        return token

    def parse(self) -> list[str]:
        self._or_expression()
        if self._peek() is not None:
            raise ValidationFailure(f"Unexpected token in SPDX licence expression: {self._peek()!r}")
        return self.licenses

    def _or_expression(self) -> None:
        self._and_expression()
        while self._peek() == "OR":
            self._take()
            self._and_expression()

    def _and_expression(self) -> None:
        self._with_expression()
        while self._peek() == "AND":
            self._take()
            self._with_expression()

    def _with_expression(self) -> None:
        if self._peek() == "(":
            self._take()
            self._or_expression()
            if self._take() != ")":
                raise ValidationFailure("Unclosed parenthesis in SPDX licence expression")
            return
        license_id = self._identifier()
        self.licenses.append(license_id)
        if self._peek() == "WITH":
            self._take()
            self._identifier()  # exception identifier is not a licence identifier


def parse_spdx_expression(expression: str) -> tuple[str, ...]:
    """Validate an SPDX expression and return its distinct licence identifiers."""
    if not isinstance(expression, str):
        raise ValidationFailure("Licence expression must be a string")
    tokens = _tokens(expression)
    licenses = _ExpressionParser(tokens).parse()
    return tuple(dict.fromkeys(licenses))


def scan_licenses(
    inventory: dict[str, Any],
    denied_licenses: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Scan component metadata and report denied and unresolved licences separately.

    Python dependencies without resolved package metadata are never inferred to be
    approved. A denied identifier anywhere in an SPDX expression is a finding.
    """
    if not isinstance(inventory, dict):
        raise ValidationFailure("Supply-chain inventory must be an object")
    components = inventory.get("components", [])
    dependencies = inventory.get("python_dependencies", [])
    if not isinstance(components, list) or not isinstance(dependencies, list):
        raise ValidationFailure("Inventory components and python_dependencies must be arrays")
    if not isinstance(denied_licenses, (tuple, list)) or any(
        not isinstance(item, str) or not item.strip() for item in denied_licenses
    ):
        raise ValidationFailure("Denied licence identifiers must be non-empty strings")
    denied = {item.strip().casefold() for item in denied_licenses}
    findings: list[dict[str, Any]] = []
    unknown: list[dict[str, str]] = []
    scanned = 0

    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise ValidationFailure(f"Inventory components[{index}] must be an object")
        name = component.get("id")
        version = component.get("version", "UNKNOWN")
        if not isinstance(name, str) or not name.strip():
            raise ValidationFailure(f"Inventory components[{index}] requires a non-empty id")
        if not isinstance(version, str) or not version.strip():
            raise ValidationFailure(f"Inventory components[{index}] has an invalid version")
        expression = component.get("license")
        if not isinstance(expression, str) or expression.strip().casefold() in _UNKNOWN:
            unknown.append({"component": name, "version": version, "reason": "licence metadata is unavailable"})
            continue
        identifiers = parse_spdx_expression(expression)
        scanned += 1
        matched = sorted({identifier.casefold() for identifier in identifiers} & denied)
        if matched:
            findings.append({
                "component": name,
                "version": version,
                "expression": expression,
                "status": "denied",
                "matched_denied_licenses": matched,
            })

    for dependency in dependencies:
        if not isinstance(dependency, str) or not dependency.strip():
            raise ValidationFailure("Python dependency names must be non-empty strings")
        unknown.append({
            "component": dependency,
            "version": "UNKNOWN",
            "reason": "dependency licence metadata has not been resolved",
        })

    return {
        "policy": {"denied_licenses": sorted(denied)},
        "components_total": len(components),
        "components_with_known_licence": scanned,
        "components_unknown": len(unknown) - len(dependencies),
        "dependencies_unresolved": len(dependencies),
        "findings": findings,
        "unknown": unknown,
        "ok": not findings,
        "disclaimer": (
            "A clean result is not a legal opinion. Unresolved licence metadata is not treated as approved."
        ),
    }
