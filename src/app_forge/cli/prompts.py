"""Safe confirmation prompts shared by CLI commands."""
from __future__ import annotations

import sys
from collections.abc import Callable

from app_forge.domain.errors import ValidationFailure


def confirm(
    message: str,
    *,
    yes: bool = False,
    non_interactive: bool = False,
    input_fn: Callable[[str], str] = input,
    stdin=None,
) -> None:
    """Require explicit confirmation, refusing implicit approval in CI."""
    if yes:
        return
    source = stdin if stdin is not None else sys.stdin
    if source.isatty() and not non_interactive:
        if input_fn(f"{message} [y/N] ").strip().lower() in {"y", "yes"}:
            return
        raise ValidationFailure("Cancelled by user")
    raise ValidationFailure(
        f"Confirmation required: {message}",
        hint="Re-run with --yes to confirm non-interactively.",
    )
