"""Explicit CORS, in-process rate limiting and browser security headers."""
from __future__ import annotations
import os
import time
from collections import defaultdict, deque
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def configure_security(app: FastAPI) -> None:
    origins = [v.strip() for v in os.environ.get("APP_CORS_ORIGINS", "").split(",") if v.strip()]
    if "*" in origins:
        raise RuntimeError("APP_CORS_ORIGINS must use explicit origins; '*' is not allowed")
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                           allow_headers=["Authorization", "Content-Type", "X-Request-ID"], max_age=600)
    try:
        limit = int(os.environ.get("APP_RATE_LIMIT_REQUESTS", "120"))
        window = float(os.environ.get("APP_RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("rate-limit settings must be numeric") from exc
    if not 1 <= limit <= 10000 or not 1 <= window <= 3600:
        raise RuntimeError("rate-limit settings are outside supported bounds")
    requests: dict[str, deque[float]] = defaultdict(deque)
    @app.middleware("http")
    async def rate_limit_and_headers(request, call_next):
        now = time.monotonic()
        client = request.client.host if request.client else "unknown"
        if client not in requests and len(requests) >= 10000:
            oldest = next(iter(requests))
            del requests[oldest]
        bucket = requests[client]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            from fastapi.responses import JSONResponse
            retry_after = str(max(1, int(window - (now - bucket[0]))))
            response = JSONResponse(status_code=429, content={
                "type": "about:blank", "title": "Too Many Requests", "status": 429,
                "detail": "rate limit exceeded"
            }, media_type="application/problem+json", headers={"Retry-After": retry_after})
        else:
            bucket.append(now)
            response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
