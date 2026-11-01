"""Validated STRIDE threat-model authoring and Markdown rendering.

This module records analyst-authored threats; it does not discover threats or
certify that a system is secure.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class STRIDECategory(str, Enum):
    """The six STRIDE threat categories."""

    SPOOFING = "Spoofing"
    TAMPERING = "Tampering"
    REPUDIATION = "Repudiation"
    INFORMATION_DISCLOSURE = "Information Disclosure"
    DENIAL_OF_SERVICE = "Denial of Service"
    ELEVATION_OF_PRIVILEGE = "Elevation of Privilege"


@dataclass(frozen=True, slots=True)
class Threat:
    """One analyst-identified threat and its treatment."""

    id: str
    category: STRIDECategory
    asset: str
    description: str
    impact: str
    mitigation: str
    residual_risk: str


@dataclass(frozen=True, slots=True)
class ThreatModel:
    """Threat-model scope, assets, trust boundaries, and identified threats."""

    system: str
    scope: str
    assets: tuple[str, ...]
    trust_boundaries: tuple[str, ...]
    threats: tuple[Threat, ...]


def _required(value: str, field: str, *, limit: int = 4000) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    if len(cleaned) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return cleaned


def _items(values: Iterable[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field} must be an iterable of strings")
    result = tuple(_required(value, field, limit=500) for value in values)
    if not result:
        raise ValueError(f"{field} must contain at least one entry")
    if len(result) > 200:
        raise ValueError(f"{field} may contain at most 200 entries")
    if len({value.casefold() for value in result}) != len(result):
        raise ValueError(f"{field} entries must be unique")
    return result


def validate_threat_model(model: ThreatModel) -> ThreatModel:
    """Validate a model and return a normalized immutable copy."""
    if not isinstance(model, ThreatModel):
        raise TypeError("model must be a ThreatModel")
    system = _required(model.system, "system", limit=200)
    scope = _required(model.scope, "scope")
    assets = _items(model.assets, "assets")
    if isinstance(model.trust_boundaries, (str, bytes)):
        raise TypeError("trust_boundaries must be an iterable of strings")
    boundaries = tuple(
        _required(item, "trust_boundaries", limit=500)
        for item in model.trust_boundaries
    )
    if len(boundaries) > 200 or len({item.casefold() for item in boundaries}) != len(boundaries):
        raise ValueError("trust_boundaries must contain at most 200 unique entries")
    if len(model.threats) > 1000:
        raise ValueError("threats may contain at most 1000 entries")
    threats: list[Threat] = []
    seen_ids: set[str] = set()
    for index, threat in enumerate(model.threats):
        if not isinstance(threat, Threat):
            raise TypeError(f"threats[{index}] must be a Threat")
        identifier = _required(threat.id, f"threats[{index}].id", limit=80)
        if identifier.casefold() in seen_ids:
            raise ValueError(f"duplicate threat id: {identifier}")
        seen_ids.add(identifier.casefold())
        if not isinstance(threat.category, STRIDECategory):
            raise ValueError(f"threats[{index}].category must be a STRIDECategory")
        asset = _required(threat.asset, f"threats[{index}].asset", limit=500)
        if asset.casefold() not in {item.casefold() for item in assets}:
            raise ValueError(f"threats[{index}].asset must match a declared asset")
        threats.append(Threat(
            id=identifier,
            category=threat.category,
            asset=asset,
            description=_required(threat.description, f"threats[{index}].description"),
            impact=_required(threat.impact, f"threats[{index}].impact"),
            mitigation=_required(threat.mitigation, f"threats[{index}].mitigation"),
            residual_risk=_required(threat.residual_risk, f"threats[{index}].residual_risk"),
        ))
    return ThreatModel(system, scope, assets, boundaries, tuple(threats))


def to_compliance_record(model: ThreatModel) -> dict[str, object]:
    """Convert the model into the CMP-08 security-assessment payload."""
    item = validate_threat_model(model)
    threats = [
        f"{threat.id} [{threat.category.value}] — {threat.asset}: "
        f"{threat.description} Impact: {threat.impact}"
        for threat in item.threats
    ]
    mitigations = [
        f"{threat.id}: {threat.mitigation}" for threat in item.threats
    ]
    residual = [
        f"{threat.id}: {threat.residual_risk}" for threat in item.threats
    ]
    if not threats:
        threats = ["No threats have been recorded yet; assessment remains incomplete."]
        mitigations = ["No mitigations have been recorded yet."]
        residual = ["Residual risks have not yet been assessed."]
    return {
        "scope": f"{item.system}: {item.scope}",
        "assets": list(item.assets),
        "threats": threats,
        "mitigations": mitigations,
        "residual_risks": residual,
    }


def render_threat_model(model: ThreatModel) -> str:
    """Render an auditable STRIDE worksheet as Markdown."""
    item = validate_threat_model(model)
    lines = [
        f"# STRIDE Threat Model: {item.system}", "",
        "> Analyst-authored assessment worksheet. This document is not an "
        "automated security scan or a security certification.", "",
        "## System and scope", "", item.scope, "",
        "## Assets", "",
    ]
    lines.extend(f"- {asset}" for asset in item.assets)
    lines.extend(["", "## Trust boundaries", ""])
    if item.trust_boundaries:
        lines.extend(f"- {boundary}" for boundary in item.trust_boundaries)
    else:
        lines.append("_No trust boundaries have been recorded._")
    by_category: dict[STRIDECategory, list[Threat]] = {
        category: [] for category in STRIDECategory
    }
    for threat in item.threats:
        by_category[threat.category].append(threat)
    lines.extend(["", "## STRIDE analysis", ""])
    prompts = {
        STRIDECategory.SPOOFING: "Can an actor impersonate a user, service, or component?",
        STRIDECategory.TAMPERING: "Can data, code, configuration, or messages be modified without authorization?",
        STRIDECategory.REPUDIATION: "Can an actor deny an action because reliable evidence is absent?",
        STRIDECategory.INFORMATION_DISCLOSURE: "Can information be exposed to an unauthorized party?",
        STRIDECategory.DENIAL_OF_SERVICE: "Can availability or resource capacity be disrupted?",
        STRIDECategory.ELEVATION_OF_PRIVILEGE: "Can an actor gain permissions beyond those intended?",
    }
    for category in STRIDECategory:
        lines.extend([f"### {category.value}", "", prompts[category], ""])
        entries = by_category[category]
        if not entries:
            lines.append("_No threats recorded in this category; this is not evidence that the category is inapplicable._")
        for threat in entries:
            lines.extend([
                f"#### {threat.id}: {threat.asset}", "",
                f"**Threat:** {threat.description}", "",
                f"**Impact:** {threat.impact}", "",
                f"**Mitigation:** {threat.mitigation}", "",
                f"**Residual risk:** {threat.residual_risk}", "",
            ])
    lines.extend([
        "## Review checklist", "",
        "- [ ] Confirm system boundaries and external dependencies",
        "- [ ] Review each STRIDE category, including categories with no recorded threats",
        "- [ ] Validate mitigations with evidence and assign owners",
        "- [ ] Accept, transfer, or remediate each residual risk explicitly",
        "- [ ] Record reviewer, review date, and approval in the project process",
        "",
    ])
    return "\n".join(lines)


__all__ = [
    "STRIDECategory", "Threat", "ThreatModel", "render_threat_model",
    "to_compliance_record", "validate_threat_model",
]
