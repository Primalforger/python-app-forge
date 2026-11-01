"""Dependency-free Architecture Decision Record rendering and creation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

_STATUSES = frozenset({"proposed", "accepted", "rejected", "deprecated", "superseded"})
_MAX_SECTION = 20_000
_MAX_TITLE = 200
_ADR_NAME = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


@dataclass(frozen=True, slots=True)
class ArchitectureDecision:
    """Validated content for one architecture decision record."""
    title: str
    context: str
    decision: str
    consequences: str
    status: str = "proposed"
    decision_date: str | None = None
    decision_makers: tuple[str, ...] = ()
    consulted: tuple[str, ...] = ()
    informed: tuple[str, ...] = ()
    supersedes: str | None = None


def _text(value: str, field: str, *, limit: int = _MAX_SECTION) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be empty")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return value


def _people(values: Iterable[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field} must be an iterable of names, not a string")
    result = tuple(_text(value, field, limit=200) for value in values)
    if len(result) > 100:
        raise ValueError(f"{field} may contain at most 100 names")
    return result


def _validate(record: ArchitectureDecision) -> ArchitectureDecision:
    if not isinstance(record, ArchitectureDecision):
        raise TypeError("record must be an ArchitectureDecision")
    title = _text(record.title, "title", limit=_MAX_TITLE)
    if "\n" in title or "\r" in title:
        raise ValueError("title must be a single line")
    status = _text(record.status, "status", limit=20).lower()
    if status not in _STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(_STATUSES))}")
    decision_date = record.decision_date or date.today().isoformat()
    try:
        parsed_date = date.fromisoformat(decision_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("decision_date must be an ISO-8601 calendar date") from exc
    if parsed_date.isoformat() != decision_date:
        raise ValueError("decision_date must use YYYY-MM-DD format")
    supersedes = record.supersedes
    if supersedes is not None:
        supersedes = _text(supersedes, "supersedes", limit=100)
        if "\n" in supersedes or "\r" in supersedes:
            raise ValueError("supersedes must be a single line")
    return ArchitectureDecision(
        title=title,
        context=_text(record.context, "context"),
        decision=_text(record.decision, "decision"),
        consequences=_text(record.consequences, "consequences"),
        status=status,
        decision_date=decision_date,
        decision_makers=_people(record.decision_makers, "decision_makers"),
        consulted=_people(record.consulted, "consulted"),
        informed=_people(record.informed, "informed"),
        supersedes=supersedes,
    )


def render_adr(record: ArchitectureDecision) -> str:
    """Render a record as conventional, portable Markdown."""
    item = _validate(record)
    lines = [
        f"# {item.title}", "",
        f"- **Status:** {item.status}",
        f"- **Date:** {item.decision_date}",
    ]
    for label, people in (
        ("Decision makers", item.decision_makers),
        ("Consulted", item.consulted),
        ("Informed", item.informed),
    ):
        if people:
            lines.append(f"- **{label}:** {', '.join(people)}")
    if item.supersedes:
        lines.append(f"- **Supersedes:** {item.supersedes}")
    lines.extend([
        "", "## Context", "", item.context,
        "", "## Decision", "", item.decision,
        "", "## Consequences", "", item.consequences, "",
    ])
    return "\n".join(lines)


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    if not slug:
        raise ValueError("title must contain at least one ASCII letter or digit")
    return slug[:80].rstrip("-")


def create_adr(directory: str | Path, record: ArchitectureDecision) -> Path:
    """Create the next numbered ADR without overwriting an existing record."""
    item = _validate(record)
    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("ADR directory must be a real directory, not a symlink")
    highest = 0
    for path in root.iterdir():
        match = _ADR_NAME.fullmatch(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    if highest >= 9999:
        raise ValueError("ADR sequence is exhausted (maximum 9999)")
    target = root / f"{highest + 1:04d}-{_slug(item.title)}.md"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(render_adr(item))
    return target


__all__ = ["ArchitectureDecision", "create_adr", "render_adr"]
