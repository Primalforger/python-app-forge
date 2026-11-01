# Web template OWASP ASVS 4.0.3 baseline

**Scope:** the built-in `web-fastapi` template only. This is a starter baseline and a gap register, not a claim of ASVS compliance or certification. ASVS control applicability depends on the application's data, deployment, and threat model. Reassess the mapping when upgrading the ASVS version or changing the template.

Status meanings:
- **Implemented (baseline):** a concrete default exists and is regression-tested.
- **Partial:** a narrow safeguard exists; the full control requires application-specific design.
- **Not implemented:** the template deliberately does not invent an identity, data, or deployment model.
- **Not applicable to starter:** the current stateless, in-memory example does not exercise the control; reassess if the application adds the relevant capability.

| ASVS 4.0.3 area | Status | Template evidence / required follow-up |
|---|---|---|
| V1 Architecture, Design and Threat Modeling | Partial | This document records the starter's scope and explicit gaps. Each generated product still needs a threat model and trust-boundary review. |
| V2 Authentication | Not implemented | No user identity or login exists. Add an established authentication provider/library, account lifecycle, MFA policy where appropriate, and tests before multi-user use. |
| V3 Session Management | Not applicable to starter | The template issues no application sessions or cookies. Reassess if browser sessions are introduced. |
| V4 Access Control | Not implemented | No authorization or tenant isolation exists. Define deny-by-default resource policies and test cross-user/tenant access. |
| V5 Validation, Sanitization and Encoding | Partial | Pydantic validates request shape and `ItemStore` bounds/normalizes names. Add domain-specific constraints, output-context encoding, and abuse limits for each new endpoint. |
| V6 Stored Cryptography | Not applicable to starter | No passwords, tokens, or sensitive records are stored. Use vetted password hashing and key management if such data is added; never invent cryptography. |
| V7 Error Handling and Logging | Partial | Expected validation and missing-item errors avoid returning exception text. Add structured, redacted security logs and a tested global error policy before production. |
| V8 Data Protection | Partial | The demo stores only transient sample item names and has no secrets. Define classification, retention, minimization, and backup protections for real data. |
| V9 Communications | Partial | HSTS is emitted only when the ASGI request is HTTPS. Configure TLS at a trusted edge, secure proxy headers, and deployment-level TLS policy. |
| V10 Malicious Code | Partial | The template does not dynamically evaluate uploaded or user-supplied code. Add dependency and supply-chain controls appropriate to the deployment. |
| V11 Business Logic | Partial | The sample enforces non-empty and bounded item names. Add authorization-aware business invariants, transaction boundaries, and abuse/rate controls. |
| V12 Files and Resources | Not applicable to starter | No upload or file-serving endpoint exists. Add safe storage, content inspection, size limits, and path controls before file handling. |
| V13 API and Web Service | Partial | Host allowlisting, request-model validation, and defensive headers are present. Authentication, authorization, rate limiting, pagination limits, and API-specific abuse controls remain application work. |
| V14 Configuration | Partial | `APP_ALLOWED_HOSTS` requires explicit hosts and rejects wildcard configuration. Configure production secrets, docs exposure, proxy trust, CORS allowlists, and environment-specific settings explicitly. |

## Automated regression checks

The repository test `tests/test_web_template_asvs.py` verifies that the generated web entry point retains:
- an explicit Host allowlist with no wildcard default;
- the expected browser security headers and HTTPS-only HSTS;
- Pydantic request-model validation and non-reflective error responses;
- the absence of an enabled CORS wildcard middleware.

These checks protect the baseline from accidental removal; they do not prove that a deployed system satisfies ASVS. Run the full test suite and assess the actual deployment configuration.

## Release/deployment checklist

- [ ] Identify sensitive data, trust boundaries, roles, and abuse cases; record a threat model.
- [ ] Add authentication and deny-by-default authorization before exposing non-public data.
- [ ] Configure `APP_ALLOWED_HOSTS` for the exact deployed hostnames.
- [ ] Terminate TLS securely; trust forwarded headers only from known proxies.
- [ ] Disable or protect `/docs` and `/openapi.json` where schema disclosure is undesirable.
- [ ] Add explicit CORS origins only if cross-origin browser access is required.
- [ ] Add rate limits, request-size limits, operational monitoring, and redacted security logs.
- [ ] Review dependencies, secrets, data retention, backups, and production error handling.
