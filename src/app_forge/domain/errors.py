"""Error taxonomy with stable exit-code categories (spec 6.1)."""
from __future__ import annotations

EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_CONFLICT = 3
EXIT_SECURITY = 4
EXIT_INTERNAL = 5
EXIT_VERIFICATION = 6
EXIT_UNAVAILABLE = 7


class ForgeError(Exception):
    exit_code = EXIT_INTERNAL
    category = "internal"

    def __init__(self, message: str, *, details: list[str] | None = None, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.hint = hint

    def to_dict(self) -> dict:
        return {"category": self.category, "exit_code": self.exit_code, "message": self.message,
                "details": self.details, "hint": self.hint}


class ValidationFailure(ForgeError):
    exit_code = EXIT_VALIDATION
    category = "validation"


class ConflictFailure(ForgeError):
    exit_code = EXIT_CONFLICT
    category = "conflict"


class SecurityBlock(ForgeError):
    exit_code = EXIT_SECURITY
    category = "security"


class VerificationFailed(ForgeError):
    exit_code = EXIT_VERIFICATION
    category = "verification"


class Unavailable(ForgeError):
    """Something needed is not available locally (offline) and we will not fetch it silently."""
    exit_code = EXIT_UNAVAILABLE
    category = "unavailable"
