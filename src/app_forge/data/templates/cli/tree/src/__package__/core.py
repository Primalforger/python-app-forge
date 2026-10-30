"""CLI-independent logic."""
from __future__ import annotations


def greet(name: str, shout: bool = False) -> str:
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    text = f"Hello, {name}!"
    return text.upper() if shout else text
