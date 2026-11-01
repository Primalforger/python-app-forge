"""Dependency-free conventional-commit parsing and release-note rendering."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

_VERSION = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_COMMIT = re.compile(
    r"^(?P<type>[a-z][a-z0-9-]*)(?:\((?P<scope>[^()\r\n]+)\))?(?P<breaking>!)?: (?P<subject>.+)$"
)
_SECTIONS = (
    ("Features", "feat"),
    ("Fixes", "fix"),
    ("Performance", "perf"),
)


@dataclass(frozen=True, slots=True)
class ReleaseChange:
    """One user-facing change included in a release."""
    description: str
    change_type: str = "other"
    scope: str | None = None
    breaking: bool = False
    reference: str | None = None


def _single_line(value: str, field: str, *, limit: int = 500) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    value = value.strip()
    if not value or len(value) > limit or "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be a non-empty single line of at most {limit} characters")
    return value


def _validate_change(change: ReleaseChange) -> ReleaseChange:
    if not isinstance(change, ReleaseChange):
        raise TypeError("changes must contain ReleaseChange values")
    description = _single_line(change.description, "description")
    change_type = _single_line(change.change_type, "change_type", limit=30).lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", change_type):
        raise ValueError("change_type must be a lowercase identifier")
    scope = change.scope
    if scope is not None:
        scope = _single_line(scope, "scope", limit=80)
        if any(char in scope for char in "[]()"):
            raise ValueError("scope contains unsupported characters")
    reference = change.reference
    if reference is not None:
        reference = _single_line(reference, "reference", limit=80)
        if not re.fullmatch(r"(?:#|GH-)\d+", reference):
            raise ValueError("reference must be an issue reference such as #123")
    if not isinstance(change.breaking, bool):
        raise TypeError("breaking must be a boolean")
    return ReleaseChange(description, change_type, scope, change.breaking, reference)


def parse_conventional_commit(message: str) -> ReleaseChange:
    """Parse a Conventional Commit message, including breaking-change footers."""
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    lines = message.strip().splitlines()
    if not lines:
        raise ValueError("commit message must not be empty")
    match = _COMMIT.fullmatch(lines[0].strip())
    if match is None:
        raise ValueError("commit subject must follow Conventional Commits")
    footer_breaking = any(
        line.strip().startswith("BREAKING CHANGE:") or line.strip().startswith("BREAKING-CHANGE:")
        for line in lines[1:]
    )
    subject = match.group("subject").strip()
    reference_match = re.search(r"\s+((?:#|GH-)\d+)$", subject)
    reference = reference_match.group(1) if reference_match else None
    if reference:
        subject = subject[:reference_match.start()].rstrip()
    return _validate_change(ReleaseChange(
        description=subject,
        change_type=match.group("type"),
        scope=match.group("scope"),
        breaking=bool(match.group("breaking")) or footer_breaking,
        reference=reference,
    ))


def _changes(values: Iterable[ReleaseChange]) -> tuple[ReleaseChange, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("changes must be an iterable of ReleaseChange values")
    result = tuple(_validate_change(value) for value in values)
    if len(result) > 5000:
        raise ValueError("a release may contain at most 5000 changes")
    return result


def _line(change: ReleaseChange) -> str:
    label = f"**{change.scope}:** " if change.scope else ""
    reference = f" ({change.reference})" if change.reference else ""
    return f"- {label}{change.description}{reference}"


def render_release_notes(
    version: str,
    changes: Iterable[ReleaseChange],
    *,
    release_date: str | None = None,
) -> str:
    """Render deterministic Markdown release notes grouped by change type."""
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("version must be semantic version text, optionally prefixed with v")
    if release_date is None:
        release_date = date.today().isoformat()
    try:
        parsed = date.fromisoformat(release_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("release_date must use YYYY-MM-DD format") from exc
    if parsed.isoformat() != release_date:
        raise ValueError("release_date must use YYYY-MM-DD format")
    items = _changes(changes)
    lines = [f"# {version.lstrip('v')}", "", f"Released: {release_date}", ""]
    breaking = [item for item in items if item.breaking]
    if breaking:
        lines.extend(["## Breaking changes", ""])
        lines.extend(_line(item) for item in breaking)
        lines.append("")
    for heading, kind in _SECTIONS:
        selected = [item for item in items if not item.breaking and item.change_type == kind]
        if selected:
            lines.extend([f"## {heading}", ""])
            lines.extend(_line(item) for item in selected)
            lines.append("")
    other = [item for item in items if not item.breaking and item.change_type not in {"feat", "fix", "perf"}]
    if other:
        lines.extend(["## Other changes", ""])
        lines.extend(_line(item) for item in other)
        lines.append("")
    if not items:
        lines.extend(["No user-facing changes.", ""])
    return "\n".join(lines)


def create_release_notes(
    directory: str | Path,
    version: str,
    changes: Iterable[ReleaseChange],
    *,
    release_date: str | None = None,
) -> Path:
    """Create a versioned release-note file without overwriting existing notes."""
    content = render_release_notes(version, changes, release_date=release_date)
    normalized = version.lstrip("v")
    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("release notes directory must be a real directory, not a symlink")
    target = root / f"{normalized}.md"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return target


__all__ = ["ReleaseChange", "create_release_notes", "parse_conventional_commit", "render_release_notes"]
