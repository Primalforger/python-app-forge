"""Reusable, deterministic CLI output formatters."""
from __future__ import annotations

import json
from typing import Any, TextIO

import yaml


def format_text(value: Any, indent: int = 0) -> str:
    """Render nested values as readable, stable text."""
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:\n{format_text(item, indent + 1)}")
            else:
                rendered = json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item
                lines.append(f"{pad}{key}: {rendered}")
        return "\n".join(lines)
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return "\n".join(f"{pad}- " + format_text(item, indent + 1).lstrip() for item in value)
        return "\n".join(f"{pad}- {item}" for item in value) if value else f"{pad}(none)"
    return f"{pad}{value}"


def format_table(value: Any) -> str:
    """Render a list of mappings as a deterministic plain-text table."""
    if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
        return format_text(value)
    columns = list(dict.fromkeys(key for row in value for key in row))
    if not columns:
        return "(none)"
    cells = [[str(row.get(key, "")) for key in columns] for row in value]
    widths = [max(len(str(key)), *(len(row[index]) for row in cells)) for index, key in enumerate(columns)]
    header = " | ".join(str(key).ljust(widths[index]) for index, key in enumerate(columns))
    rule = "-+-".join("-" * width for width in widths)
    body = [" | ".join(row[index].ljust(widths[index]) for index in range(len(columns))) for row in cells]
    return "\n".join([header, rule, *body])


def format_output(value: Any, output: str = "text", *, color: bool = False) -> str:
    """Format a value as text, JSON, YAML, or a table.

    ANSI styling is intentionally limited to table headers; structured formats
    never contain terminal escape sequences.
    """
    if output == "json":
        return json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False)
    if output == "yaml":
        return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip("\n")
    if output == "table":
        rendered = format_table(value)
        if color and isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
            first_line, separator, remainder = rendered.partition("\n")
            if separator:
                return f"\033[1m{first_line}\033[0m{separator}{remainder}"
        return rendered
    if output != "text":
        raise ValueError(f"Unsupported output format: {output}")
    return format_text(value)
