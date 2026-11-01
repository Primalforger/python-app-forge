"""Cooperative cancellation primitives shared by engines and application shells."""
from __future__ import annotations

import threading
from typing import Any, Callable

from app_forge.domain.errors import OperationCancelled

ProgressCallback = Callable[[dict[str, Any]], None]


class CancellationToken:
    """Thread-safe cancellation signal; recovery code should deliberately ignore it."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for cancellation; returns True when cancellation was requested."""
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelled("Operation cancelled by user")
