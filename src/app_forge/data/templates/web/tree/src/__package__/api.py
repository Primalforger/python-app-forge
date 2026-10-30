"""FastAPI entry point. Binds to localhost by default; change deliberately."""
from __future__ import annotations

from {{package}}.core import ItemStore


def create_app():
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    class ItemIn(BaseModel):
        name: str

    app = FastAPI(title="{{name}}", version="0.1.0")
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
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
