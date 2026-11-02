"""Automated security checks mapped to selected OWASP ASVS 5.0.0 areas."""
from __future__ import annotations

import pytest

# Generated projects can run their dependency-free smoke tests before optional
# web extras are installed. Skip this security suite cleanly until FastAPI exists.
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from {{package}}.api import create_app  # noqa: E402
from {{package}}.auth import issue_token  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_JWT_SECRET", "test-only-secret-with-at-least-32-bytes")
    monkeypatch.setenv("APP_JWT_ISSUER", "test-issuer")
    monkeypatch.setenv("APP_JWT_AUDIENCE", "test-audience")
    monkeypatch.setenv("APP_ALLOWED_HOSTS", "testserver,localhost")
    monkeypatch.delenv("APP_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("APP_ENABLE_API_DOCS", raising=False)
    monkeypatch.setenv("APP_RATE_LIMIT_REQUESTS", "100")
    monkeypatch.setenv("APP_RATE_LIMIT_WINDOW_SECONDS", "60")
    return TestClient(create_app())


def token(roles=("reader",)):
    return issue_token("asvs-test-user", list(roles))


def test_authentication_and_role_authorization(client):
    assert client.get("/items").status_code == 401
    reader = {"Authorization": f"Bearer {token()}"}
    assert client.get("/items", headers=reader).status_code == 200
    assert client.post("/items", json={"name": "blocked"}, headers=reader).status_code == 403
    editor = {"Authorization": f"Bearer {token(('editor',))}"}
    response = client.post("/items", json={"name": "allowed"}, headers=editor)
    assert response.status_code == 201


def test_invalid_and_expired_tokens_are_rejected(client):
    assert client.get("/items", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_input_validation_and_non_reflective_errors(client):
    editor = {"Authorization": f"Bearer {token(('editor',))}"}
    response = client.post("/items", json={"name": "x" * 101}, headers=editor)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert client.post("/items", json={"name": "valid"}).status_code == 401


def test_security_headers_and_docs_are_secure_by_default(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_unsafe_host_and_cors_wildcard_fail_closed(monkeypatch):
    monkeypatch.setenv("APP_ALLOWED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="explicit hostnames"):
        create_app()

    from {{package}}.security import configure_security
    from fastapi import FastAPI

    monkeypatch.setenv("APP_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("APP_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="explicit origins"):
        configure_security(FastAPI())


def test_rate_limit_is_enforced(client, monkeypatch):
    from {{package}}.security import configure_security
    from fastapi import FastAPI

    app = FastAPI()
    monkeypatch.setenv("APP_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("APP_RATE_LIMIT_WINDOW_SECONDS", "60")
    configure_security(app)

    @app.get("/probe")
    def probe():
        return {"ok": True}

    limited = TestClient(app)
    assert limited.get("/probe").status_code == 200
    response = limited.get("/probe")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert int(response.headers["retry-after"]) >= 1


def test_weak_jwt_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("APP_JWT_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        issue_token("user", ["reader"])
