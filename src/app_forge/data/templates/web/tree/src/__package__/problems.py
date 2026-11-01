"""RFC 9457 problem-details handlers with non-reflective server errors."""
from __future__ import annotations
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

def _problem(status_code: int, title: str, detail: str, errors: list[dict] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status_code, "detail": detail}
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(status_code=status_code, content=body, media_type="application/problem+json", headers=headers)

def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException):
        titles = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                  405: "Method Not Allowed", 409: "Conflict", 422: "Unprocessable Content", 429: "Too Many Requests"}
        detail = exc.detail if isinstance(exc.detail, str) else "request failed"
        return _problem(exc.status_code, titles.get(exc.status_code, "Request Failed"), detail, headers=exc.headers)
    @app.exception_handler(RequestValidationError)
    async def validation_problem(request: Request, exc: RequestValidationError):
        errors = [{"location": list(error.get("loc", ())), "message": str(error.get("msg", "invalid value")),
                   "code": str(error.get("type", "validation_error"))} for error in exc.errors()]
        return _problem(422, "Unprocessable Content", "request validation failed", errors)
    @app.exception_handler(Exception)
    async def unexpected_problem(request: Request, exc: Exception):
        return _problem(500, "Internal Server Error", "an unexpected error occurred")
