"""Schema-driven form validation (framework independent)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "str"  # str | int | float | bool | choice
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    choices: tuple = ()
    label: str = ""


def validate(schema: list[Field], data: dict[str, Any]) -> dict[str, str]:
    """Return {field_name: message}. An empty dict means the data is valid."""
    errors: dict[str, str] = {}
    for f in schema:
        label = f.label or f.name
        raw = data.get(f.name)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if f.required:
                errors[f.name] = f"{label} is required"
            continue
        try:
            value: Any = raw
            if f.kind == "int":
                value = int(raw)
            elif f.kind == "float":
                value = float(raw)
            elif f.kind == "bool":
                if not isinstance(raw, bool):
                    raise ValueError
            elif f.kind == "choice":
                if raw not in f.choices:
                    errors[f.name] = f"{label} must be one of: {', '.join(map(str, f.choices))}"
                continue
            else:
                value = str(raw)
        except (TypeError, ValueError):
            errors[f.name] = f"{label} must be a valid {f.kind}"
            continue
        if f.kind in ("int", "float"):
            if f.minimum is not None and value < f.minimum:
                errors[f.name] = f"{label} must be at least {f.minimum}"
            elif f.maximum is not None and value > f.maximum:
                errors[f.name] = f"{label} must be at most {f.maximum}"
        if f.kind == "str":
            if f.minimum is not None and len(value) < f.minimum:
                errors[f.name] = f"{label} must have at least {int(f.minimum)} characters"
            elif f.maximum is not None and len(value) > f.maximum:
                errors[f.name] = f"{label} must have at most {int(f.maximum)} characters"
            elif f.pattern and not re.fullmatch(f.pattern, value):
                errors[f.name] = f"{label} has an invalid format"
    return errors
