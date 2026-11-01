"""Small framework-independent undo/redo command history."""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class UndoableCommand(Protocol):
    """A reversible operation; ``execute`` and ``redo`` share semantics."""

    def execute(self) -> None: ...
    def undo(self) -> None: ...


class UndoRedoStack:
    """Manage executed commands with bounded history and redo invalidation.

    ``execute`` runs a command before recording it. If execution raises, the
    history is unchanged. Likewise, undo/redo move a command between stacks
    only after its operation succeeds.
    """

    def __init__(self, max_history: int = 100) -> None:
        if isinstance(max_history, bool) or not isinstance(max_history, int) or max_history < 1:
            raise ValueError("max_history must be a positive integer")
        self.max_history = max_history
        self._undo: list[UndoableCommand] = []
        self._redo: list[UndoableCommand] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)

    def execute(self, command: UndoableCommand) -> None:
        """Execute and record a command, discarding any redo branch."""
        self._check_command(command)
        command.execute()
        self._undo.append(command)
        if len(self._undo) > self.max_history:
            del self._undo[: len(self._undo) - self.max_history]
        self._redo.clear()

    def undo(self) -> bool:
        """Undo the newest command; return False when history is empty."""
        if not self._undo:
            return False
        command = self._undo[-1]
        command.undo()
        self._undo.pop()
        self._redo.append(command)
        return True

    def redo(self) -> bool:
        """Re-execute the newest undone command; return False if unavailable."""
        if not self._redo:
            return False
        command = self._redo[-1]
        command.execute()
        self._redo.pop()
        self._undo.append(command)
        if len(self._undo) > self.max_history:
            del self._undo[: len(self._undo) - self.max_history]
        return True

    def clear(self) -> None:
        """Forget both histories without executing or reverting operations."""
        self._undo.clear()
        self._redo.clear()

    @staticmethod
    def _check_command(command: UndoableCommand) -> None:
        if not callable(getattr(command, "execute", None)) or not callable(getattr(command, "undo", None)):
            raise TypeError("command must provide callable execute() and undo() methods")
