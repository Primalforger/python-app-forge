"""Validated, portable persistence for the template content used to create a project.

The baseline stores UTF-8 source text (not just hashes), because a future
three-way merge needs the original content. A canonical envelope checksum and
per-file hashes detect accidental or untrusted edits before merge planning.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
BASELINE_PATH = ".forge/template-baseline.json"


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _valid_path(path: str) -> bool:
    if not path or "\\" in path or "\x00" in path:
        return False
    candidate = PurePosixPath(path)
    return (not candidate.is_absolute() and all(part not in ("", ".", "..") for part in candidate.parts)
            and candidate.as_posix() == path and path != BASELINE_PATH)


def create_baseline(template_id: str, template_version: str, archetype: str,
                    files: dict[str, str]) -> str:
    """Serialize an immutable snapshot of rendered template-owned files."""
    if not all(isinstance(v, str) and v for v in (template_id, template_version, archetype)):
        raise ValueError("template identity, version, and archetype must be non-empty strings")
    if not isinstance(files, dict):
        raise ValueError("baseline files must be a mapping")
    snapshot: dict[str, dict[str, str]] = {}
    for path, content in sorted(files.items()):
        if not isinstance(path, str) or not _valid_path(path):
            raise ValueError(f"invalid template baseline path: {path!r}")
        if not isinstance(content, str):
            raise ValueError(f"template baseline content for {path!r} must be text")
        encoded = content.encode("utf-8")
        snapshot[path] = {"sha256": hashlib.sha256(encoded).hexdigest(), "content": content}
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "template": {"id": template_id, "version": template_version, "archetype": archetype},
        "files": snapshot,
    }
    envelope = {**payload, "sha256": hashlib.sha256(_canonical(payload)).hexdigest()}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load_baseline(text: str) -> dict[str, Any]:
    """Parse and verify a stored baseline; reject unsupported or tampered data."""
    try:
        envelope = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("template baseline is not valid JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "template", "files", "sha256"}:
        raise ValueError("template baseline has an invalid document shape")
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported template baseline schema: {envelope['schema_version']!r}")
    template = envelope["template"]
    files = envelope["files"]
    if not isinstance(template, dict) or set(template) != {"id", "version", "archetype"}:
        raise ValueError("template baseline identity is invalid")
    if not all(isinstance(template[k], str) and template[k] for k in ("id", "version", "archetype")):
        raise ValueError("template baseline identity fields must be non-empty strings")
    if not isinstance(files, dict):
        raise ValueError("template baseline files must be an object")
    for path, record in files.items():
        if not isinstance(path, str) or not _valid_path(path):
            raise ValueError(f"invalid template baseline path: {path!r}")
        if not isinstance(record, dict) or set(record) != {"sha256", "content"}:
            raise ValueError(f"invalid template baseline record for {path!r}")
        content, digest = record["content"], record["sha256"]
        if not isinstance(content, str) or not isinstance(digest, str):
            raise ValueError(f"invalid template baseline content for {path!r}")
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not hashlib.compare_digest(actual, digest):
            raise ValueError(f"template baseline content checksum mismatch for {path!r}")
    payload = {key: envelope[key] for key in ("schema_version", "template", "files")}
    expected = hashlib.sha256(_canonical(payload)).hexdigest()
    if not isinstance(envelope["sha256"], str) or not hashlib.compare_digest(expected, envelope["sha256"]):
        raise ValueError("template baseline checksum mismatch")
    return payload
