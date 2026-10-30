"""Tiny TOML writer for the subset used by Forge metadata (reading uses stdlib tomllib)."""
from __future__ import annotations

import json
from typing import Any


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    raise TypeError(f"Unsupported TOML value: {v!r}")


def dumps(data: dict) -> str:
    lines: list[str] = []

    def emit_table(prefix: str, table: dict) -> None:
        simple = {k: v for k, v in table.items() if not isinstance(v, dict) and not _is_aot(v)}
        for k, v in simple.items():
            lines.append(f"{k} = {_scalar(v)}")
        for k, v in table.items():
            if isinstance(v, dict):
                lines.append("")
                lines.append(f"[{prefix + k}]")
                emit_table(prefix + k + ".", v)
            elif _is_aot(v):
                for item in v:
                    lines.append("")
                    lines.append(f"[[{prefix + k}]]")
                    emit_table(prefix + k + ".", item)

    emit_table("", data)
    return "\n".join(lines).strip() + "\n"


def _is_aot(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)
