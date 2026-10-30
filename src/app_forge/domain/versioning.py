"""Semantic versions and constraints. Deterministic, dependency-free."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app_forge.domain.errors import ValidationFailure

_VER = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int = 0
    patch: int = 0

    @classmethod
    def parse(cls, text: str) -> "Version":
        m = _VER.match(str(text).strip())
        if not m:
            raise ValidationFailure(f"Invalid version {text!r}; expected MAJOR.MINOR.PATCH")
        return cls(int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def is_semver(text: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", str(text).strip()))


@dataclass(frozen=True)
class Constraint:
    """Comma-separated clauses: >=, <=, >, <, ==, !=, ^, ~ or '*'."""
    clauses: tuple[tuple[str, Version], ...]
    text: str = "*"

    @classmethod
    def parse(cls, text: str) -> "Constraint":
        text = (text or "*").strip()
        if text in ("*", ""):
            return cls((), "*")
        out: list[tuple[str, Version]] = []
        for raw in text.split(","):
            raw = raw.strip()
            m = re.match(r"^(>=|<=|==|!=|>|<|\^|~)?\s*(\d+(?:\.\d+){0,2})$", raw)
            if not m:
                raise ValidationFailure(f"Invalid version constraint {raw!r} in {text!r}")
            op = m.group(1) or "=="
            v = Version.parse(m.group(2))
            if op == "^":
                upper = Version(v.major + 1) if v.major > 0 else (
                    Version(0, v.minor + 1) if v.minor > 0 else Version(0, 0, v.patch + 1))
                out += [(">=", v), ("<", upper)]
            elif op == "~":
                out += [(">=", v), ("<", Version(v.major, v.minor + 1))]
            else:
                out.append((op, v))
        return cls(tuple(out), text)

    def allows(self, version: Version) -> bool:
        ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
               "<": lambda a, b: a < b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
        return all(ops[op](version, bound) for op, bound in self.clauses)

    def __str__(self) -> str:
        return self.text
