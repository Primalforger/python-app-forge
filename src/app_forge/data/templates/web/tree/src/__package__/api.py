"""FastAPI entry point with authentication and a conservative security baseline."""
from __future__ import annotations
import os
from {{package}}.auth import current_principal, require_roles
from {{package}}.core import ItemStore
from {{package}}.readiness import readiness_payload
from {{package}}.problems import install_problem_handlers
from {{package}}.security import configure_security

def _allowed_hosts() -> list[str]:
    raw = os.environ.get("APP_ALLOWED_HOSTS", "127.0.0.1,localhost")
    hosts = [host.strip() for host in raw.split(",") if host.strip()]
    if not hosts or "*" in hosts:
        raise RuntimeError("APP_ALLOWED_HOSTS must contain explicit hostnames; '*' is not allowed")
    return hosts

def create_app():
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from pydantic import BaseModel, Field
    class ItemIn(BaseModel):
        name: str = Field(min_length=1, max_length=100)
    docs_enabled = os.environ.get("APP_ENABLE_API_DOCS", "").lower() in {"1", "true", "yes"}
    app = FastAPI(title="{{name}}", version="0.1.0", docs_url="/docs" if docs_enabled else None,
                  redoc_url=None, openapi_url="/openapi.json" if docs_enabled else None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
    configure_security(app)
    install_problem_handlers(app)
    store = ItemStore()
    @app.get("/health")
    @app.get("/health/live")
    def liveness() -> dict:
        return {"status": "ok"}
    @app.get("/health/ready")
    def readiness():
        from fastapi.responses import JSONResponse
        payload, status_code = readiness_payload()
        return JSONResponse(status_code=status_code, content=payload)
    @app.get("/items")
    def list_items(principal=Depends(current_principal)) -> list[dict]:
        return store.list()
    @app.post("/items", status_code=201)
    def add_item(body: ItemIn, principal=Depends(require_roles("editor", "admin"))) -> dict:
        try:
            return store.add(body.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid item") from exc
    @app.get("/items/{item_id}")
    def get_item(item_id: int, principal=Depends(current_principal)) -> dict:
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
