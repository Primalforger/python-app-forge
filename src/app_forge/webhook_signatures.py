"""Timestamped HMAC verification for inbound webhooks."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable

_DIGESTS = {"sha256": hashlib.sha256, "sha512": hashlib.sha512}


class WebhookSignatureError(ValueError):
    """Raised when a webhook signature is malformed, stale, or invalid."""


def verify_webhook_signature(
    payload: bytes, secret: str | bytes, signature: str, timestamp: str | int, *,
    tolerance: float = 300.0, now: float | None = None, digest: str = "sha256",
    clock: Callable[[], float] = time.time,
) -> bool:
    """Verify HMAC(secret, ASCII(timestamp) + b"." + raw payload).

    Freshness checking limits replay windows; strict one-time delivery also
    requires callers to persist and reject provider event IDs.
    """
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not isinstance(secret, (str, bytes)):
        raise TypeError("secret must be a string or bytes")
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if not key:
        raise ValueError("secret must not be empty")
    if digest not in _DIGESTS:
        raise ValueError("digest must be sha256 or sha512")
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 <= tolerance < float("inf"):
        raise ValueError("tolerance must be a finite non-negative number")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if isinstance(timestamp, bool):
        raise WebhookSignatureError("invalid webhook timestamp")
    timestamp_text = str(timestamp)
    if not re.fullmatch(r"[0-9]{1,16}", timestamp_text):
        raise WebhookSignatureError("invalid webhook timestamp")
    timestamp_value = int(timestamp_text)
    current = clock() if now is None else now
    if isinstance(current, bool) or not isinstance(current, (int, float)) or not 0 <= current < float("inf"):
        raise ValueError("current time must be a finite non-negative number")
    if abs(float(current) - timestamp_value) > tolerance:
        raise WebhookSignatureError("webhook timestamp is outside the allowed window")
    if not isinstance(signature, str):
        raise TypeError("signature must be a string")
    supplied = signature
    if "=" in supplied:
        prefix, separator, supplied = supplied.partition("=")
        if not separator or prefix != digest:
            raise WebhookSignatureError("signature digest does not match")
    expected_length = _DIGESTS[digest]().digest_size * 2
    if len(supplied) != expected_length or not re.fullmatch(r"[0-9a-fA-F]+", supplied):
        raise WebhookSignatureError("malformed webhook signature")
    signed = timestamp_text.encode("ascii") + b"." + payload
    expected = hmac.new(key, signed, _DIGESTS[digest]).hexdigest()
    if not hmac.compare_digest(expected, supplied.lower()):
        raise WebhookSignatureError("webhook signature verification failed")
    return True


def sign_webhook_payload(
    payload: bytes, secret: str | bytes, timestamp: str | int, *,
    digest: str = "sha256",
) -> str:
    """Create a timestamped signature for senders and deterministic tests."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not isinstance(secret, (str, bytes)):
        raise TypeError("secret must be a string or bytes")
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if not key:
        raise ValueError("secret must not be empty")
    if digest not in _DIGESTS:
        raise ValueError("digest must be sha256 or sha512")
    timestamp_text = str(timestamp)
    if not re.fullmatch(r"[0-9]{1,16}", timestamp_text):
        raise ValueError("timestamp must be a non-negative Unix timestamp")
    signed = timestamp_text.encode("ascii") + b"." + payload
    return f"{digest}=" + hmac.new(key, signed, _DIGESTS[digest]).hexdigest()
