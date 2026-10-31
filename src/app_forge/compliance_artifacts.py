"""Structured compliance artifact validation and project-local storage."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from app_forge.domain.errors import ConflictFailure, SecurityBlock, ValidationFailure
from app_forge.observability import utcnow


ARTIFACTS: dict[str, dict[str, Any]] = {
    "CMP-05": {
        "name": "interface-control",
        "required": ("interfaces",),
        "list_fields": ("interfaces",),
        "item_required": ("name", "provider", "version", "contract"),
    },
    "CMP-08": {
        "name": "security-assessment",
        "required": ("scope", "assets", "threats", "mitigations", "residual_risks"),
        "list_fields": ("assets", "threats", "mitigations", "residual_risks"),
    },
    "CMP-09": {
        "name": "change-impact",
        "required": ("change", "impacted_requirements", "impact_assessment"),
        "list_fields": ("impacted_requirements",),
    },
    "CMP-10": {
        "name": "release-evidence",
        "required": ("release", "verification_run", "artifacts", "approvals"),
        "list_fields": ("artifacts", "approvals"),
    },
    "CMP-11": {
        "name": "exceptions-register",
        "required": ("exceptions",),
        "list_fields": ("exceptions",),
        "item_required": ("id", "requirement", "approver", "rationale", "expires"),
    },
}


def validate_artifact(code: str, payload: Any) -> dict:
    """Validate a user-authored record without inferring or fabricating evidence."""
    if code not in ARTIFACTS:
        raise ValidationFailure(f"Unknown compliance artifact {code!r}",
                                details=[f"available: {', '.join(sorted(ARTIFACTS))}"])
    if not isinstance(payload, dict):
        raise ValidationFailure("Compliance artifact input must be a JSON object")
    spec = ARTIFACTS[code]
    missing = [key for key in spec["required"] if key not in payload]
    problems = [f"missing required field: {key}" for key in missing]
    for field in spec.get("list_fields", ()):
        if field in payload and not isinstance(payload[field], list):
            problems.append(f"{field} must be an array")
    item_required = spec.get("item_required", ())
    for field in spec.get("list_fields", ()):
        for index, item in enumerate(payload.get(field, [])):
            if not isinstance(item, dict):
                if item_required:
                    problems.append(f"{field}[{index}] must be an object")
                elif not isinstance(item, str) or not item.strip():
                    problems.append(f"{field}[{index}] must be a non-empty string or object")
                continue
            for key in item_required:
                if not isinstance(item.get(key), str) or not item[key].strip():
                    problems.append(f"{field}[{index}].{key} is required")
    for field in ("scope", "change", "impact_assessment", "release", "verification_run"):
        if field in spec["required"] and field in payload and (
                not isinstance(payload[field], str) or not payload[field].strip()):
            problems.append(f"{field} must be a non-empty string")
    if problems:
        raise ValidationFailure(f"{code} artifact is incomplete", details=problems)
    return payload


def save_artifact(project: str | Path, code: str, payload: Any) -> dict:
    record = validate_artifact(code, payload)
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValidationFailure(f"Project path {str(project)!r} is not a directory")
    forge_dir = root / ".forge"
    if forge_dir.is_symlink() or (forge_dir.exists() and not forge_dir.is_dir()):
        raise SecurityBlock("Project .forge metadata path is not a safe directory")
    directory = forge_dir / "compliance"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise SecurityBlock("Compliance artifact directory is not a safe directory")
    forge_dir.mkdir(exist_ok=True)
    directory.mkdir(exist_ok=True)
    target = directory / f"{ARTIFACTS[code]['name']}.json"
    if target.is_symlink():
        raise SecurityBlock("Refusing to replace a symlinked compliance artifact")
    envelope = {
        "schema_version": 1,
        "artifact": code,
        "name": ARTIFACTS[code]["name"],
        "project": str(root),
        "generated_at": utcnow(),
        "record": record,
    }
    text = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    temporary = directory / f".{target.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if target.is_symlink():
            raise SecurityBlock("Compliance artifact target became a symlink")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"artifact": code, "name": ARTIFACTS[code]["name"], "path": str(target), "valid": True}


def load_artifacts(project: str | Path) -> list[dict]:
    directory = Path(project).resolve() / ".forge" / "compliance"
    if directory.is_symlink():
        raise SecurityBlock("Refusing to read compliance artifacts through a symlink")
    if not directory.exists():
        return []
    records = []
    for code, spec in ARTIFACTS.items():
        path = directory / f"{spec['name']}.json"
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise SecurityBlock(f"Unsafe compliance artifact path: {path.name}")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationFailure(f"Cannot read {path.name}: {exc}") from None
        if not isinstance(envelope, dict) or envelope.get("schema_version") != 1 or envelope.get("artifact") != code:
            raise ValidationFailure(f"Invalid compliance artifact envelope: {path.name}")
        validate_artifact(code, envelope.get("record"))
        records.append(envelope)
    return records
