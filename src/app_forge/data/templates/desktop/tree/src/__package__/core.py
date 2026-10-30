"""Application logic with no GUI imports, so it can be tested headlessly."""
from __future__ import annotations

from dataclasses import dataclass


def greeting(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}!"


@dataclass
class AppState:
    title: str = "{{name}}"
    counter: int = 0

    def increment(self) -> int:
        self.counter += 1
        return self.counter
