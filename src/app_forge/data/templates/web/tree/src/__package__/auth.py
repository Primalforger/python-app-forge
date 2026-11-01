"""JWT bearer authentication and role-based authorization helpers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]

def _settings() -> tuple[str, str, str]:
    secret = os.environ.get("APP_JWT_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("APP_JWT_SECRET must contain at least 32 bytes")
    return secret, os.environ.get("APP_JWT_ISSUER", "python-app-forge"), os.environ.get("APP_JWT_AUDIENCE", "python-app")

def issue_token(subject: str, roles: list[str] | tuple[str, ...], *, expires_in: int = 900) -> str:
    """Issue a short-lived token only after an external identity check."""
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be non-empty")
    if isinstance(expires_in, bool) or not isinstance(expires_in, int) or not 1 <= expires_in <= 86400:
        raise ValueError("expires_in must be between 1 and 86400 seconds")
    if not roles or any(not isinstance(role, str) or not role.strip() for role in roles):
        raise ValueError("roles must contain non-empty strings")
    secret, issuer, audience = _settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "roles": sorted(set(roles)), "iss": issuer, "aud": audience,
                       "iat": now, "nbf": now, "exp": now + timedelta(seconds=expires_in)}, secret, algorithm="HS256")

def decode_token(token: str) -> Principal:
    secret, issuer, audience = _settings()
    claims = jwt.decode(token, secret, algorithms=["HS256"], issuer=issuer, audience=audience,
                        options={"require": ["sub", "iss", "aud", "iat", "nbf", "exp"]})
    subject, roles = claims.get("sub"), claims.get("roles", [])
    if not isinstance(subject, str) or not subject or not isinstance(roles, list):
        raise jwt.InvalidTokenError("invalid identity claims")
    if any(not isinstance(role, str) or not role for role in roles):
        raise jwt.InvalidTokenError("invalid role claims")
    return Principal(subject, frozenset(roles))

def current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return decode_token(credentials.credentials)
    except (jwt.PyJWTError, RuntimeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid or expired bearer token", headers={"WWW-Authenticate": "Bearer"}) from None

def require_roles(*allowed_roles: str) -> Callable:
    if not allowed_roles or any(not isinstance(role, str) or not role for role in allowed_roles):
        raise ValueError("at least one non-empty role is required")
    def authorize(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.roles.intersection(allowed_roles):
            raise HTTPException(status_code=403, detail="insufficient permissions")
        return principal
    return authorize
