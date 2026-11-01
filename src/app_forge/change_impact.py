"""Validated change-impact records and CMP-09 compliance integration.

Records capture analyst assessments; they do not infer affected requirements or
replace review and approval by accountable owners.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

_IMPACT_LEVELS = frozenset({"none", "low", "moderate", "high", "critical"})
_CHANGE_TYPES = frozenset({"feature", "fix", "security", "dependency", "configuration", "migration", "operational", "other"})
_MAX_TEXT = 4000
_REQUIREMENT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")


@dataclass(frozen=True, slots=True)
class ChangeImpact:
    """An analyst-authored impact assessment for a proposed or completed change."""

    change_id: str
    title: str
    description: str
    change_type: str
    affected_systems: tuple[str, ...]
    impacted_requirements: tuple[str, ...]
    impact_level: str
    impact_assessment: str
    compatibility: str
    security_privacy: str
    operational: str
    data_migration: str
    rollback_plan: str
    verification_plan: str
    owner: str
    assessment_date: str | None = None
    status: str = "proposed"


def _text(value: str, field: str, *, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field} must not be empty")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return result


def _items(values: Iterable[str], field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field} must be an iterable of strings, not a string")
    result = tuple(_text(value, field, limit=200) for value in values)
    if len(result) > 200:
        raise ValueError(f"{field} may contain at most 200 entries")
    if not allow_empty and not result:
        raise ValueError(f"{field} must contain at least one entry")
    if len({item.casefold() for item in result}) != len(result):
        raise ValueError(f"{field} entries must be unique")
    return result


def validate_change_impact(record: ChangeImpact) -> ChangeImpact:
    """Validate and normalize a change-impact record."""
    if not isinstance(record, ChangeImpact):
        raise TypeError("record must be a ChangeImpact")
    change_id = _text(record.change_id, "change_id", limit=80)
    if not _REQUIREMENT_ID.fullmatch(change_id):
        raise ValueError("change_id must contain only letters, digits, dot, underscore, or hyphen")
    title = _text(record.title, "title", limit=200)
    if "\n" in title or "\r" in title:
        raise ValueError("title must be a single line")
    change_type = _text(record.change_type, "change_type", limit=30).lower()
    if change_type not in _CHANGE_TYPES:
        raise ValueError(f"change_type must be one of: {', '.join(sorted(_CHANGE_TYPES))}")
    impact_level = _text(record.impact_level, "impact_level", limit=20).lower()
    if impact_level not in _IMPACT_LEVELS:
        raise ValueError(f"impact_level must be one of: {', '.join(sorted(_IMPACT_LEVELS))}")
    status = _text(record.status, "status", limit=20).lower()
    if status not in {"proposed", "in_review", "approved", "implemented", "rejected"}:
        raise ValueError("status must be proposed, in_review, approved, implemented, or rejected")
    systems = _items(record.affected_systems, "affected_systems")
    requirements = _items(record.impacted_requirements, "impacted_requirements", allow_empty=True)
    for requirement in requirements:
        if not _REQUIREMENT_ID.fullmatch(requirement):
            raise ValueError(f"invalid requirement identifier: {requirement!r}")
    assessment_date = record.assessment_date
    if assessment_date is not None:
        try:
            parsed = date.fromisoformat(assessment_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("assessment_date must use YYYY-MM-DD format") from exc
        if parsed.isoformat() != assessment_date:
            raise ValueError("assessment_date must use YYYY-MM-DD format")
    return ChangeImpact(
        change_id=change_id, title=title,
        description=_text(record.description, "description"),
        change_type=change_type, affected_systems=systems,
        impacted_requirements=requirements, impact_level=impact_level,
        impact_assessment=_text(record.impact_assessment, "impact_assessment"),
        compatibility=_text(record.compatibility, "compatibility"),
        security_privacy=_text(record.security_privacy, "security_privacy"),
        operational=_text(record.operational, "operational"),
        data_migration=_text(record.data_migration, "data_migration"),
        rollback_plan=_text(record.rollback_plan, "rollback_plan"),
        verification_plan=_text(record.verification_plan, "verification_plan"),
        owner=_text(record.owner, "owner", limit=200),
        assessment_date=assessment_date, status=status,
    )


def to_compliance_record(record: ChangeImpact) -> dict[str, object]:
    """Adapt a record to the existing CMP-09 change-impact schema."""
    item = validate_change_impact(record)
    summary = (
        f"{item.change_id} — {item.title} [{item.impact_level} impact, {item.status}]. "
        f"{item.impact_assessment} Compatibility: {item.compatibility} "
        f"Security/privacy: {item.security_privacy} Operational: {item.operational} "
        f"Data migration: {item.data_migration} Rollback: {item.rollback_plan} "
        f"Verification: {item.verification_plan} Owner: {item.owner}"
    )
    return {
        "change": f"{item.change_id}: {item.title} — {item.description}",
        "impacted_requirements": list(item.impacted_requirements) or [
            "No requirement IDs identified; impact review remains incomplete."
        ],
        "impact_assessment": summary,
        "affected_systems": list(item.affected_systems),
        "change_type": item.change_type,
        "impact_level": item.impact_level,
        "assessment_date": item.assessment_date,
        "status": item.status,
        "owner": item.owner,
    }


def render_change_impact(record: ChangeImpact) -> str:
    """Render a reviewable Markdown change-impact report."""
    item = validate_change_impact(record)
    lines = [
        f"# Change Impact: {item.change_id} — {item.title}", "",
        f"- **Status:** {item.status}",
        f"- **Type:** {item.change_type}",
        f"- **Impact level:** {item.impact_level}",
        f"- **Assessment date:** {item.assessment_date or 'Not recorded'}",
        f"- **Owner:** {item.owner}", "",
        "## Change description", "", item.description, "",
        "## Affected systems", "",
    ]
    lines.extend(f"- {system}" for system in item.affected_systems)
    lines.extend(["", "## Impacted requirements", ""])
    if item.impacted_requirements:
        lines.extend(f"- {requirement}" for requirement in item.impacted_requirements)
    else:
        lines.append("_No requirement IDs identified; traceability review remains incomplete._")
    for heading, value in (
        ("Overall impact assessment", item.impact_assessment),
        ("Compatibility and interfaces", item.compatibility),
        ("Security and privacy", item.security_privacy),
        ("Operations and availability", item.operational),
        ("Data and migration", item.data_migration),
        ("Rollback and recovery", item.rollback_plan),
        ("Verification and evidence", item.verification_plan),
    ):
        lines.extend(["", f"## {heading}", "", value])
    lines.extend([
        "", "## Review and approval checklist", "",
        "- [ ] Confirm affected systems and requirement traceability",
        "- [ ] Review security, privacy, compatibility, and operational impacts",
        "- [ ] Validate migration and rollback plans with responsible owners",
        "- [ ] Define verification evidence and acceptance criteria",
        "- [ ] Record approvals and any residual risks before implementation",
        "",
        "> This is an analyst-authored assessment. It does not automatically discover dependencies or approve a change.",
        "",
    ])
    return "\n".join(lines)


__all__ = ["ChangeImpact", "render_change_impact", "to_compliance_record", "validate_change_impact"]
