from __future__ import annotations

import hashlib
import hmac

import pytest

from app_forge.webhook_signatures import (
    WebhookSignatureError, sign_webhook_payload, verify_webhook_signature,
)


def test_valid_signature_accepts_raw_payload_and_prefixed_header() -> None:
    payload = b'{"event":"created"}'
    signature = sign_webhook_payload(payload, "secret", 1_700_000_000)
    assert verify_webhook_signature(payload, "secret", signature, "1700000000", now=1_700_000_000)
    assert verify_webhook_signature(payload, "secret", signature.removeprefix("sha256="), 1_700_000_000, now=1_700_000_000)


def test_modified_payload_or_secret_is_rejected() -> None:
    signature = sign_webhook_payload(b"body", b"secret", 100)
    with pytest.raises(WebhookSignatureError, match="verification failed"):
        verify_webhook_signature(b"changed", b"secret", signature, 100, now=100)
    with pytest.raises(WebhookSignatureError, match="verification failed"):
        verify_webhook_signature(b"body", b"other", signature, 100, now=100)


@pytest.mark.parametrize("timestamp,now", [(99, 100), (101, 100)])
def test_timestamp_within_tolerance_is_accepted(timestamp: int, now: int) -> None:
    signature = sign_webhook_payload(b"x", "s", timestamp)
    assert verify_webhook_signature(b"x", "s", signature, timestamp, now=now, tolerance=1)


@pytest.mark.parametrize("timestamp,now", [(98, 100), (102, 100)])
def test_stale_or_future_timestamp_is_rejected(timestamp: int, now: int) -> None:
    signature = sign_webhook_payload(b"x", "s", timestamp)
    with pytest.raises(WebhookSignatureError, match="outside"):
        verify_webhook_signature(b"x", "s", signature, timestamp, now=now, tolerance=1)


def test_sha512_supported_and_wrong_prefix_rejected() -> None:
    signature = sign_webhook_payload(b"x", "s", 10, digest="sha512")
    assert verify_webhook_signature(b"x", "s", signature, 10, now=10, digest="sha512")
    with pytest.raises(WebhookSignatureError, match="digest"):
        verify_webhook_signature(b"x", "s", signature, 10, now=10)


def test_malformed_signatures_and_timestamps_rejected() -> None:
    with pytest.raises(WebhookSignatureError, match="malformed"):
        verify_webhook_signature(b"x", "s", "xyz", 10, now=10)
    with pytest.raises(WebhookSignatureError, match="timestamp"):
        verify_webhook_signature(b"x", "s", "0" * 64, "10.2", now=10)


def test_empty_secret_and_invalid_configuration_rejected() -> None:
    with pytest.raises(ValueError, match="secret"):
        sign_webhook_payload(b"x", "", 10)
    with pytest.raises(ValueError, match="digest"):
        sign_webhook_payload(b"x", "s", 10, digest="md5")
    with pytest.raises(ValueError, match="tolerance"):
        verify_webhook_signature(b"x", "s", "0" * 64, 10, now=10, tolerance=-1)


def test_signature_matches_standard_hmac_construction() -> None:
    payload, secret, timestamp = b"payload", b"key", "123"
    expected = hmac.new(secret, b"123.payload", hashlib.sha256).hexdigest()
    assert sign_webhook_payload(payload, secret, timestamp) == f"sha256={expected}"
