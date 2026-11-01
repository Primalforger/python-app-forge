# FastAPI web template security baseline

This generated FastAPI starter includes JWT bearer verification, role-based authorization, explicit CORS configuration, bounded in-process rate limiting, RFC 9457 problem details, and liveness/readiness probes. It is a secure baseline, **not a complete identity provider or production deployment**.

## Configuration

- Set `APP_ALLOWED_HOSTS` to exact public hostnames; wildcard hosts are rejected.
- Set `APP_JWT_SECRET` to at least 32 bytes of high-entropy secret material. Configure `APP_JWT_ISSUER` and `APP_JWT_AUDIENCE` for the deployed identity boundary.
- Tokens use HS256 only, require issuer, audience, subject and time claims, and default to a 15-minute lifetime. `issue_token` is for use only after a trusted identity provider has authenticated the subject; this template does not implement passwords, registration or login.
- Set `APP_CORS_ORIGINS` to a comma-separated exact origin allowlist. CORS is disabled when unset; wildcard origins and credentialed CORS are not enabled.
- Rate limiting defaults to 120 requests per 60 seconds per client address. This in-memory limiter is process-local and resets on restart; use a shared gateway/store for multi-worker deployments.
- `APP_RATE_LIMIT_REQUESTS` and `APP_RATE_LIMIT_WINDOW_SECONDS` are bounded configuration values.
- Browser security headers are enabled; HSTS is emitted only for HTTPS requests. API docs remain disabled unless `APP_ENABLE_API_DOCS=1`.

## Authorization

The sample item list/read routes require a valid bearer token. Creating items additionally requires the `editor` or `admin` role. Use `require_roles("role-a", "role-b")` on application routes; authorization is deny-by-default.

## Operations

- `GET /health/live` (also `/health`) reports liveness without dependency checks.
- `GET /health/ready` runs registered checks and returns 503 if any check fails.
- Register checks during startup with `register_readiness_check("database", check_callable)`.
- Errors use RFC 9457 `application/problem+json` responses and do not expose unexpected exception text.

The in-memory item store is demonstration code, not durable or multi-worker storage. Review the repository ASVS mapping and deployment threat model before production use.
