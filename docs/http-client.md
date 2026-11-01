# Retrying HTTP client

The standard-library RetryingHttpClient provides bounded HTTP requests without
adding a runtime dependency. It has a finite per-attempt timeout, a bounded
response-body size, configurable RetryPolicy, and support for Retry-After
seconds or HTTP-date values. Retry-After is capped by the policy maximum delay.

GET, HEAD, OPTIONS, PUT and DELETE are retryable by default for transport
failures and selected transient statuses (408, 425, 429, 500, 502, 503, 504).
POST and other non-idempotent methods are not retried unless the caller
explicitly sets retry_unsafe=True. The caller is responsible for ensuring
server-side idempotency before opting in.

The optional on_retry callback receives method, URL without query/fragment,
attempt number and delay; query strings are omitted to avoid leaking tokens.
Transport exception text is passed through Forge's secret redactor. The client
buffers responses and rejects bodies above max_response_bytes.
