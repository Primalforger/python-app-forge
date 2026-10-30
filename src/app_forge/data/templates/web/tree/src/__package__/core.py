"""Framework-independent domain logic."""
from __future__ import annotations


class ItemStore:
    MAX_NAME = 100

    def __init__(self) -> None:
        self._items: dict[int, str] = {}
        self._next = 1

    def add(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        if len(name) > self.MAX_NAME:
            raise ValueError(f"name must be at most {self.MAX_NAME} characters")
        item = {"id": self._next, "name": name}
        self._items[self._next] = name
        self._next += 1
        return item

    def list(self) -> list[dict]:
        return [{"id": i, "name": n} for i, n in self._items.items()]

    def get(self, item_id: int) -> dict:
        if item_id not in self._items:
            raise KeyError(item_id)
        return {"id": item_id, "name": self._items[item_id]}
