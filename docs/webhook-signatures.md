# Webhook signature verification

Verify an inbound webhook before parsing or acting on it. Pass the exact raw
request body, shared secret, signature header value, and Unix timestamp header:

    from app_forge.webhook_signatures import verify_webhook_signature

    verify_webhook_signature(
        request_body,
        webhook_secret,
        request.headers["X-Forge-Signature"],
        request.headers["X-Forge-Timestamp"],
    )

The signed message is ASCII(timestamp) + b"." + raw_body. SHA-256 is the
default; SHA-512 is also supported. Signatures use sha256=<hex> (or
sha512=<hex>) and are compared in constant time. The default timestamp
tolerance is 300 seconds; configure it to match the sender's delivery policy.
Malformed, mismatched, stale, future-dated, and invalid signatures raise
WebhookSignatureError.

Timestamp freshness limits replay to the accepted time window, but does not
guarantee one-time delivery. For strict replay prevention, also validate and
persist the provider's unique event/delivery ID with an atomic uniqueness
constraint. Keep secrets outside source control and verify the signature
before deserializing or processing the body.
