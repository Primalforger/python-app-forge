"""Validated, persistent column widths for table presentations.

Only presentation metadata is stored; row data and executable content are never
serialized. Widths are expressed in logical pixels and bounded to avoid corrupt
or unreasonable layouts.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

MIN_WIDTH = 24
MAX_WIDTH = 2000


def normalize_widths(widths: Mapping[str, int], column_keys: set[str]) -> dict[str, int]:
    """Return canonical widths for known columns, rejecting invalid values."""
    if not isinstance(widths, Mapping):
        raise ValueError("column widths must be a mapping")
    result: dict[str, int] = {}
    for key, width in widths.items():
        if not isinstance(key, str) or key not in column_keys:
            raise ValueError(f"unknown column key: {key!r}")
        if not isinstance(width, int) or isinstance(width, bool) or not MIN_WIDTH <= width <= MAX_WIDTH:
            raise ValueError(f"width for {key!r} must be an integer from {MIN_WIDTH} to {MAX_WIDTH}")
        result[key] = width
    return dict(sorted(result.items()))


class ColumnWidthStore:
    """Persist a table's user-adjusted column widths in an atomic JSON file."""

    def __init__(self, path: str | Path, column_keys: set[str]):
        if (not isinstance(column_keys, set) or not column_keys
                or any(not isinstance(key, str) or not key for key in column_keys)):
            raise ValueError("column_keys must be a non-empty set of non-empty strings")
        self.path = Path(path)
        self.column_keys = set(column_keys)

    def load(self) -> dict[str, int]:
        """Load validated widths; a missing file means no saved adjustments."""
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read saved column widths: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("widths"), dict):
            raise ValueError("saved column widths have an unsupported or invalid format")
        return normalize_widths(raw["widths"], self.column_keys)

    def save(self, widths: Mapping[str, int]) -> None:
        """Validate and atomically replace the persisted width map."""
        normalized = normalize_widths(widths, self.column_keys)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema": 1, "widths": normalized}, indent=2, sort_keys=True) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def clear(self) -> bool:
        """Remove saved widths; return whether a file existed."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True
