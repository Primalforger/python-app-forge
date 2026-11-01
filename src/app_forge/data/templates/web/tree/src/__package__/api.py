"""FastAPI entry point with a conservative web-security baseline."""
from __future__ import annotations

import os

from {{package}}.core import ItemStore


def _allowed_hosts() -> list[str]:
    """Configure accepted Host values; never default to an unrestricted wildcard."""
    raw = os.environ.get("APP_ALLOWED_HOSTS", "127.0.0.1,localhost")
    hosts = [host.strip() for host in raw.split(",") if host.strip()]
    if not hosts or "*" in hosts:
        raise RuntimeError("APP_ALLOWED_HOSTS must contain explicit hostnames; '*' is not allowed")
    return hosts


def create_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from pydantic import BaseModel, Field

    class ItemIn(BaseModel):
        name: str = Field(min_length=1, max_length=100)

    docs_enabled = os.environ.get("APP_ENABLE_API_DOCS", "").lower() in {"1", "true", "yes"}
    app = FastAPI(
        title="{{name}}",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    store = ItemStore()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/items")
    def list_items() -> list[dict]:
        return store.list()

    @app.post("/items", status_code=201)
    def add_item(body: ItemIn) -> dict:
        try:
            return store.add(body.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid item") from exc

    @app.get("/items/{item_id}")
    def get_item(item_id: int) -> dict:
        try:
            return store.get(item_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="item not found") from None

    # forge:anchor routers
    return app


def main() -> int:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
    return 0
