# OWASP ASVS 5.0.0 verification map

This starter maps selected controls to the OWASP Application Security Verification Standard (ASVS) 5.0.0. It is a **starter verification checklist**, not a claim of ASVS conformance, certification, or a complete Level 1 assessment. Select the assurance level and applicable requirements for the deployed system, then record evidence for every applicable requirement.

Reference: [OWASP ASVS 5.0.0](https://github.com/OWASP/ASVS/tree/v5.0.0).

## Verification map

| ASVS area | Starter coverage | Automated evidence | Required deployment / review evidence |
|---|---|---|---|
| V2 Authentication | HS256-only JWT verification; required issuer, audience, subject and time claims; bounded token lifetime; no password/login implementation | `tests/test_asvs.py`: missing/invalid/expired tokens rejected; invalid secret rejected | External identity provider, signing-key custody and rotation, MFA, account lifecycle and recovery |
| V3 Session management | Bearer-token API; no browser cookie session is created | API tests verify bearer-only access | If cookies are introduced: secure/HttpOnly/SameSite attributes, rotation, logout and CSRF controls |
| V4 Access control | Authentication required for reads; editor/admin required for sample writes; deny by default | API tests cover unauthenticated, reader and editor access | Add resource/tenant ownership checks to every object operation; review all new routes |
| V5 Validation and encoding | Pydantic request model bounds item names; framework parameter parsing | API tests cover invalid and oversized input | Validate every new input and output context; review file, URL, query and rich-text handling |
| V8 Data protection | No secrets in source; JWT secret supplied through environment; generic unexpected-error response | Tests verify weak secrets rejected and exception details not reflected | Use a secret manager, TLS, data classification, encryption-at-rest and retention controls |
| V13 API and web service | Explicit host allowlist, CORS origin allowlist, bounded process-local rate limiter, security headers, API docs disabled by default | Tests cover host/CORS rejection, rate limit, headers and docs defaults | Put a shared gateway/rate limiter in front of multi-worker deployments; document API inventory and quotas |
| V14 Configuration | Secure defaults for hosts, CORS, docs and rate limiting; invalid bounds fail closed | Configuration tests exercise unsafe and out-of-range settings | Harden runtime/container, TLS termination, dependency updates, environment separation and drift monitoring |

## Automated checks

Run the generated project's test suite with its development dependencies installed:

```sh
python -m pip install -e ".[dev]"
python -m pytest
```

The ASVS-focused tests exercise the starter's implemented controls. They do not replace a source review, threat model, dependency assessment, deployment review, penetration test, or verification of application-specific routes.

## Known gaps and deployment responsibilities

- Authentication is delegated to an external identity provider. The sample token issuer must only be called after trusted authentication; production signing and key rotation are not provided.
- The in-memory rate limiter is process-local, resets on restart, and is not a substitute for gateway-level abuse protection.
- The sample item store is in-memory and has no tenant or per-object ownership model. New resource routes must enforce object-level authorization.
- TLS, proxy trust, network segmentation, secrets management, persistent audit logging, backups, data retention and production observability are deployment responsibilities.
- SSRF protection, file upload/download safety, outbound request policy, browser CSRF protections and business-flow abuse controls must be designed when those features are added.
- Security headers and CORS settings must be reviewed against the actual frontend and deployment topology. Do not broaden origins or trusted hosts to make a deployment "work" without reviewing the trust boundary.

Record each applicable control as pass, fail, or not applicable with rationale and evidence. An untested or deployment-owned control is not a pass.
