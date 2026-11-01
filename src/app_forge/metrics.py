"Optional Prometheus metrics primitives with bounded, explicit labels."
from __future__ import annotations

import math
import re
from typing import Any

_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"}


class PrometheusMetrics:
    """Own an isolated registry and low-cardinality HTTP metric instruments.

    Route labels must be framework route templates, never raw request paths,
    user IDs, query strings, or other unbounded values.
    """

    def __init__(self, *, namespace: str = "app", registry: Any | None = None) -> None:
        if not isinstance(namespace, str) or not _METRIC_NAME.fullmatch(namespace):
            raise ValueError("namespace must be a valid Prometheus metric-name prefix")
        try:
            from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
        except ImportError as exc:
            raise ImportError(
                "Prometheus metrics require the optional 'prometheus' extra; "
                "install python-app-forge[prometheus]"
            ) from exc

        self.registry = registry if registry is not None else CollectorRegistry()
        self.requests = Counter(
            "http_requests_total", "Total HTTP requests.",
            ("method", "route", "status"), namespace=namespace, registry=self.registry,
        )
        self.duration = Histogram(
            "http_request_duration_seconds", "HTTP request duration in seconds.",
            ("method", "route"), namespace=namespace, registry=self.registry,
        )
        self.in_flight = Gauge(
            "http_requests_in_flight", "HTTP requests currently being processed.",
            namespace=namespace, registry=self.registry,
        )

    def record_http_request(
        self, method: str, route: str, status_code: int, duration_seconds: float
    ) -> None:
        """Record one completed request using a route template, not a raw URL."""
        normalized_method = method.upper() if isinstance(method, str) else ""
        if normalized_method not in _ALLOWED_METHODS:
            normalized_method = "OTHER"
        if (
            not isinstance(route, str)
            or not route.startswith("/")
            or len(route) > 200
            or "?" in route
            or "#" in route
        ):
            raise ValueError("route must be a bounded framework route template")
        if isinstance(status_code, bool) or not isinstance(status_code, int) or not 100 <= status_code <= 599:
            raise ValueError("status_code must be an HTTP status from 100 to 599")
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or duration_seconds < 0
        ):
            raise ValueError("duration_seconds must be finite and non-negative")
        self.requests.labels(normalized_method, route, str(status_code)).inc()
        self.duration.labels(normalized_method, route).observe(float(duration_seconds))

    def render(self) -> tuple[bytes, str]:
        """Return Prometheus text exposition bytes and their content type."""
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return generate_latest(self.registry), CONTENT_TYPE_LATEST


def instrument_fastapi(app: Any, metrics: PrometheusMetrics, *, endpoint: str = "/metrics") -> None:
    """Attach low-cardinality HTTP instrumentation and an explicit scrape route."""
    if not isinstance(endpoint, str) or not endpoint.startswith("/") or endpoint == "/" or "?" in endpoint:
        raise ValueError("metrics endpoint must be a non-root absolute path")

    from fastapi import Response

    @app.middleware("http")
    async def _prometheus_metrics_middleware(request: Any, call_next: Any) -> Any:
        import time

        started = time.perf_counter()
        metrics.in_flight.inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", None) or "unmatched"
            metrics.record_http_request(
                request.method, route if route.startswith("/") else "/unmatched",
                status_code, time.perf_counter() - started,
            )
            metrics.in_flight.dec()

    async def _metrics_endpoint() -> Response:
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type.split(";", 1)[0])

    app.add_api_route(endpoint, _metrics_endpoint, methods=["GET"], include_in_schema=False)
