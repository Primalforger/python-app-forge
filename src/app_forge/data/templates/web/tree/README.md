# FastAPI web template security baseline

This template starts with conservative HTTP security defaults, but it is **not a complete secure application**. Before deployment, review the ASVS mapping in the repository's `docs/web-template-asvs.md`.

## Configuration

- Set `APP_ALLOWED_HOSTS` to a comma-separated list of exact public hostnames (for example, `api.example.com,www.example.com`). The default permits only `127.0.0.1` and `localhost`.
- The app rejects wildcard host configuration. Keep TLS termination at a trusted reverse proxy and ensure the proxy forwards the original HTTPS scheme only when it is trusted.
- The middleware adds defensive browser headers and HSTS on HTTPS requests.
- CORS is not enabled by default. If browser clients on another origin are required, add an explicit origin allowlist; do not use wildcard origins with credentials.
- OpenAPI and interactive docs are disabled by default. Set `APP_ENABLE_API_DOCS=1` only in trusted development environments or explicitly protected deployments.

## Production requirements still owned by the application

This starter has no user identity, authentication, authorization, tenant isolation, rate limiting, persistent secret management, or business-specific audit trail. Add and test those controls before handling sensitive or multi-user data. Validate all input at the API boundary, avoid returning internal exception details, and use parameterized database APIs if persistence is added.

The default in-memory item store is demonstration code, not durable or multi-worker storage.
