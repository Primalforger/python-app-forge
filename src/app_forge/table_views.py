"""Persistent named views for the advanced table model.

A view stores presentation state only; it never stores table rows or executable code.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{0,63}$")
_OPERATORS = {"eq", "ne", "contains", "gt", "gte", "lt", "lte", "between", "in"}
_STATE_KEYS = {"columns", "visible_columns", "sort", "filters", "filter_mode", "search_text", "page_size"}


def normalize_view(state: dict[str, Any], column_keys: set[str]) -> dict[str, Any]:
    """Validate and return a JSON-safe, canonical table view."""
    if not isinstance(state, dict):
        raise ValueError("view state must be an object")
    unknown = set(state) - _STATE_KEYS
    if unknown:
        raise ValueError(f"unknown view settings: {sorted(unknown)}")
    columns = state.get("columns", list(column_keys))
    if (not isinstance(columns, list) or any(not isinstance(k, str) for k in columns)
            or len(columns) != len(set(columns)) or set(columns) != column_keys):
        raise ValueError("columns must contain every table column exactly once")
    visible = state.get("visible_columns", columns)\n    if not isinstance(visible, list) or any(not isinstance(k, str) for k in visible) or len(visible) != len(set(visible)) or not set(visible) <= column_keys:\n        raise ValueError("visible_columns must contain unique known column keys")\n    sort = state.get("sort", [])
    if not isinstance(sort, list):
        raise ValueError("sort must be a list")
    normalized_sort = []
    for item in sort:
        if (not isinstance(item, dict) or item.get("column") not in column_keys
                or not isinstance(item.get("descending", False), bool)):
            raise ValueError("each sort entry needs a known column and boolean descending flag")
        normalized_sort.append({"column": item["column"], "descending": item.get("descending", False)})
    filters = state.get("filters", [])
    if not isinstance(filters, list):
        raise ValueError("filters must be a list")
    normalized_filters = []
    for item in filters:
        if (not isinstance(item, dict) or item.get("column") not in column_keys
                or item.get("op") not in _OPERATORS or "value" not in item):
            raise ValueError("each filter needs a known column, supported operator and value")
        normalized_filters.append({"column": item["column"], "op": item["op"], "value": item["value"]})
    mode = state.get("filter_mode", "and")
    search = state.get("search_text", "")
    size = state.get("page_size", 25)
    if mode not in ("and", "or"):
        raise ValueError("filter_mode must be 'and' or 'or'")
    if not isinstance(search, str):
        raise ValueError("search_text must be a string")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 1000:
        raise ValueError("page_size must be an integer from 1 to 1000")
    result = {"columns": columns, "visible_columns": visible, "sort": normalized_sort, "filters": normalized_filters,
              "filter_mode": mode, "search_text": search, "page_size": size}
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("view values must be finite JSON data") from exc
    return result


class TableViewStore:
    """Store named table views in a single JSON file with atomic replacement."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read saved table views: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("views"), dict):
            raise ValueError("saved table views have an unsupported or invalid format")
        return raw["views"]

    def names(self) -> list[str]:
        return sorted(self._read(), key=str.casefold)

    def get(self, name: str, column_keys: set[str]) -> dict[str, Any]:
        views = self._read()
        if name not in views:
            raise KeyError(name)
        entry = views[name]
        if not isinstance(entry, dict) or not isinstance(entry.get("state"), dict):
            raise ValueError(f"saved view {name!r} is malformed")
        return normalize_view(entry["state"], column_keys)

    def save(self, name: str, state: dict[str, Any], column_keys: set[str]) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
            raise ValueError("view name must be 1-64 letters, digits, spaces, dots, underscores or hyphens")
        name = name.strip()
        normalized = normalize_view(state, column_keys)
        views = self._read()
        views[name] = {"state": normalized}
        self._write(views)

    def delete(self, name: str) -> bool:
        views = self._read()
        if name not in views:
            return False
        del views[name]
        self._write(views)
        return True

    def _write(self, views: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema": 1, "views": views}, indent=2, sort_keys=True, allow_nan=False) + "\n"
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


def apply_view(model: Any, state: dict[str, Any]) -> None:
    """Apply a validated view to a TableModel-like object."""
    keys = {column.key for column in model.columns}
    view = normalize_view(state, keys)
    for index, key in enumerate(view["columns"]):
        model.move_column(key, index)
    visible = set(view["columns"])
    for key in keys:
        model.set_visible(key, key in visible)
    model.set_sort(*((item["column"], item["descending"]) for item in view["sort"]))
    model.clear_filters()
    model.filter_mode = view["filter_mode"]
    for item in view["filters"]:
        model.add_filter(item["column"], item["op"], item["value"])
    model.search_text = view["search_text"]
    model.page_size = view["page_size"]
