"""A small dependency-free HTTP client with bounded retries and safe diagnostics."""
from __future__ import annotations

import email.utils
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from app_forge.retry import RetryPolicy
from app_forge.security import redact


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Buffered HTTP response with a decoded JSON convenience method."""
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body)


class HttpRequestError(RuntimeError):
    """Raised for invalid requests, exhausted transport failures or response limits."""


class RetryingHttpClient:
    """HTTP client with explicit timeouts, bounded retries and bounded response bodies.

    Retries are restricted to idempotent methods by default. POST/PATCH are
    never retried unless explicitly opted in by the caller.
    """

    RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
    IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        policy: RetryPolicy | None = None,
        max_response_bytes: int = 8_388_608,
        retry_statuses: frozenset[int] | set[int] | None = None,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[str, str, int, float], None] | None = None,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout < float("inf"):
            raise ValueError("timeout must be a finite positive number")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or not 1 <= max_response_bytes <= 1_073_741_824:
            raise ValueError("max_response_bytes must be between 1 and 1073741824")
        statuses = self.RETRYABLE_STATUS if retry_statuses is None else frozenset(retry_statuses)
        if any(isinstance(code, bool) or not isinstance(code, int) or not 100 <= code <= 599 for code in statuses):
            raise ValueError("retry statuses must be HTTP status codes")
        if not callable(sleep) or (opener is not None and not callable(opener)):
            raise TypeError("sleep and opener must be callable")
        if on_retry is not None and not callable(on_retry):
            raise TypeError("on_retry must be callable")
        self.timeout = float(timeout)
        self.policy = policy or RetryPolicy()
        self.max_response_bytes = max_response_bytes
        self.retry_statuses = statuses
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep
        self._on_retry = on_retry

    @staticmethod
    def _validate_url(url: str) -> None:
        if not isinstance(url, str):
            raise TypeError("url must be a string")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError("url must be an absolute HTTP(S) URL without embedded credentials")

    @staticmethod
    def _retry_after(value: str | None, now: float) -> float | None:
        if not value:
            return None
        try:
            seconds = float(value.strip())
            if seconds >= 0 and seconds < float("inf"):
                return seconds
        except ValueError:
            pass
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, parsed.timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _safe_target(url: str) -> str:
        parts = urlsplit(url)
        # Query strings and fragments can contain credentials or personal data.
        return f"{parts.scheme}://{parts.netloc}{parts.path}"

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        json_body: Any = None,
        retry_unsafe: bool = False,
    ) -> HttpResponse:
        self._validate_url(url)
        if not isinstance(method, str) or not method or not method.isascii() or not method.isalpha():
            raise ValueError("method must contain ASCII letters only")
        verb = method.upper()
        if data is not None and json_body is not None:
            raise ValueError("provide either data or json_body, not both")
        if data is not None and not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        request_headers = dict(headers or {})
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in request_headers.items()):
            raise TypeError("headers must map strings to strings")
        payload = data
        if json_body is not None:
            payload = json.dumps(json_body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        can_retry = verb in self.IDEMPOTENT_METHODS or retry_unsafe
        safe_target = self._safe_target(url)
        last_error: Exception | None = None

        for attempt in range(self.policy.max_attempts):
            request = urllib.request.Request(url, data=payload, headers=request_headers, method=verb)
            try:
                response = self._opener(request, timeout=self.timeout)
                try:
                    status = int(response.status)
                    response_headers = dict(response.headers.items())
                    body = response.read(self.max_response_bytes + 1)
                    final_url = response.geturl()
                finally:
                    response.close()
                if len(body) > self.max_response_bytes:
                    raise HttpRequestError("HTTP response exceeds configured size limit")
                result = HttpResponse(status, response_headers, body, final_url)
                if status not in self.retry_statuses or not can_retry or attempt + 1 >= self.policy.max_attempts:
                    return result
                last_error = HttpRequestError(f"retryable HTTP status {status}")
                retry_after = self._retry_after(response_headers.get("Retry-After"), time.time())
            except urllib.error.HTTPError as error:
                try:
                    status = int(error.code)
                    response_headers = dict(error.headers.items()) if error.headers else {}
                    body = error.read(self.max_response_bytes + 1)
                    final_url = error.geturl()
                finally:
                    error.close()
                if len(body) > self.max_response_bytes:
                    raise HttpRequestError("HTTP response exceeds configured size limit") from error
                if status not in self.retry_statuses or not can_retry or attempt + 1 >= self.policy.max_attempts:
                    return HttpResponse(status, response_headers, body, final_url)
                last_error = HttpRequestError(f"retryable HTTP status {status}")
                retry_after = self._retry_after(response_headers.get("Retry-After"), time.time())
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if not can_retry or attempt + 1 >= self.policy.max_attempts:
                    raise HttpRequestError(f"HTTP transport failed: {redact(str(error))}") from error
                last_error = error
                retry_after = None

            delay = self.policy.delay_for(attempt)
            if retry_after is not None:
                delay = min(max(delay, retry_after), self.policy.max_delay)
            if self._on_retry is not None:
                self._on_retry(verb, safe_target, attempt + 1, delay)
            if delay:
                self._sleep(delay)

        raise HttpRequestError("HTTP request exhausted retry attempts") from last_error

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("POST", url, **kwargs)
