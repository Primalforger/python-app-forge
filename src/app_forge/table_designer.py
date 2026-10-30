"""Table Designer backend (UI-014): validate a table definition and generate code for forge.advanced-table.

The designer edits a plain definition (columns, types, default sort, filters, paging). This module validates it
with explicit, documented semantics and renders Python that configures the component's TableModel.
"""
from __future__ import annotations

import json
import re

from app_forge.domain.errors import ValidationFailure

TYPES = ("text", "number", "date", "bool", "category")
OPS_BY_TYPE = {"text": ("eq", "ne", "contains", "in"), "number": ("eq", "ne", "gt", "gte", "lt", "lte", "between", "in"),
               "date": ("eq", "ne", "gt", "gte", "lt", "lte", "between"), "bool": ("eq", "ne"),
               "category": ("eq", "ne", "in")}
EXPORT_FORMATS_AVAILABLE = ("csv",)  # others need optional adapters that are not installed
_KEY = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")


def normalize_definition(d: dict) -> dict:
    p: list[str] = []
    cols = d.get("columns") or []
    if not cols:
        p.append("at least one column is required")
    seen: dict[str, str] = {}
    out_cols = []
    for i, c in enumerate(cols):
        key, typ = str(c.get("key", "")), c.get("type", "text")
        if not _KEY.match(key):
            p.append(f"column {i + 1}: key {key!r} must be lowercase letters, digits, underscore")
        if key in seen:
            p.append(f"column key {key!r} is duplicated")
        if typ not in TYPES:
            p.append(f"column {key!r}: type must be one of {TYPES}")
        seen[key] = typ
        out_cols.append({"key": key, "title": str(c.get("title") or key.replace("_", " ").title()), "type": typ,
                         "visible": bool(c.get("visible", True))})
    sorts = []
    for s in d.get("default_sort", []):
        if s.get("column") not in seen:
            p.append(f"default_sort references unknown column {s.get('column')!r}")
        sorts.append({"column": s.get("column"), "descending": bool(s.get("descending", False))})
    filters = []
    for f in d.get("filters", []):
        col, op = f.get("column"), f.get("op")
        if col not in seen:
            p.append(f"filter references unknown column {col!r}")
        elif op not in OPS_BY_TYPE.get(seen[col], ()):
            p.append(f"filter on {col!r} ({seen[col]}): operator {op!r} not allowed; use {OPS_BY_TYPE[seen[col]]}")
        filters.append({"column": col, "op": op, "value": f.get("value")})
    mode = d.get("filter_mode", "and")
    if mode not in ("and", "or"):
        p.append("filter_mode must be 'and' or 'or'")
    size = d.get("page_size", 25)
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 1000:
        p.append("page_size must be an integer from 1 to 1000")
    exports = list(d.get("export_formats", ["csv"]))
    for e in exports:
        if e not in EXPORT_FORMATS_AVAILABLE:
            p.append(f"export format {e!r} needs an optional adapter that is not installed (available: "
                     f"{EXPORT_FORMATS_AVAILABLE})")
    name = str(d.get("name", "")).strip()
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,40}$", name):
        p.append("name must be an identifier-like string (letters, digits, underscore)")
    if p:
        raise ValidationFailure("Invalid table definition", details=p)
    return {"name": name, "columns": out_cols, "default_sort": sorts, "filters": filters, "filter_mode": mode,
            "page_size": size, "export_formats": exports}


def to_python(defn: dict, import_path: str) -> str:
    """Render a builder function for the component's TableModel. Values are emitted with json/repr (no eval)."""
    d = normalize_definition(defn)
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", import_path):
        raise ValidationFailure(f"Invalid import path {import_path!r}")
    cols = ",\n".join(f"    Column({c['key']!r}, {c['title']!r}, {c['visible']})" for c in d["columns"])
    lines = [f"from {import_path} import Column, TableModel", "", "COLUMNS = [", cols, "]", "",
             f"def build_{d['name'].lower()}(rows):", "    m = TableModel(COLUMNS, rows)",
             f"    m.page_size = {d['page_size']}", f"    m.filter_mode = {d['filter_mode']!r}"]
    if d["default_sort"]:
        lines.append("    m.set_sort(" + ", ".join(f"({s['column']!r}, {s['descending']})" for s in d["default_sort"]) + ")")
    lines += [f"    m.add_filter({f['column']!r}, {f['op']!r}, {json.loads(json.dumps(f['value']))!r})" for f in d["filters"]]
    lines += ["    return m", ""]
    return "\n".join(lines)
