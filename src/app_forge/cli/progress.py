"""TTY-aware progress reporting for CLI commands."""
from __future__ import annotations

import sys
from typing import TextIO


class ProgressReporter:
    """Emit concise progress messages to stderr, never stdout."""

    def __init__(self, mode: str = "auto", *, stream: TextIO | None = None) -> None:
        if mode not in {"auto", "always", "never"}:
            raise ValueError(f"Unsupported progress mode: {mode}")
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = mode == "always" or (mode == "auto" and self.stream.isatty())

    def emit(self, message: str) -> None:
        if self.enabled:
            print(message, file=self.stream)

    def start(self, group: str, action: str = "") -> None:
        self.emit("forge: running " + group + (" " + action if action else ""))

    def finish(self, exit_code: int) -> None:
        state = "completed" if exit_code == 0 else f"finished with exit code {exit_code}"
        self.emit("forge: " + state)
