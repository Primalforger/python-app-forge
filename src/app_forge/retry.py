"""Retry policies and a thread-safe circuit breaker for transient failures."""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff; max_attempts includes the initial call."""
    max_attempts: int = 3
    initial_delay: float = 0.25
    multiplier: float = 2.0
    max_delay: float = 10.0
    jitter: float = 0.2

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        for name in ("initial_delay", "multiplier", "max_delay", "jitter"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not float("-inf") < value < float("inf"):
                raise ValueError(f"{name} must be a finite number")
        if self.initial_delay < 0 or self.multiplier < 1 or self.max_delay < 0 or not 0 <= self.jitter <= 1:
            raise ValueError("delays must be non-negative, multiplier >= 1 and jitter between 0 and 1")

    def delay_for(self, retry_index: int, *, random_value: float | None = None) -> float:
        if isinstance(retry_index, bool) or not isinstance(retry_index, int) or retry_index < 0:
            raise ValueError("retry_index must be a non-negative integer")
        base = min(self.initial_delay * self.multiplier**retry_index, self.max_delay)
        if not self.jitter or not base:
            return base
        sample = random.uniform(-1.0, 1.0) if random_value is None else random_value
        if not -1 <= sample <= 1:
            raise ValueError("random_value must be between -1 and 1")
        return max(0.0, base * (1 + self.jitter * sample))


def retry_call(operation: Callable[[], T], policy: RetryPolicy | None = None, *,
               retry_if: Callable[[Exception], bool] | None = None,
               sleep: Callable[[float], None] = time.sleep,
               on_retry: Callable[[Exception, int, float], None] | None = None) -> T:
    """Retry an operation a bounded number of times and preserve its final exception."""
    if not callable(operation):
        raise TypeError("operation must be callable")
    selected = policy or RetryPolicy()
    should_retry = retry_if or (lambda _error: True)
    for attempt in range(selected.max_attempts):
        try:
            return operation()
        except Exception as error:
            if attempt + 1 >= selected.max_attempts or not should_retry(error):
                raise
            delay = selected.delay_for(attempt)
            if on_retry is not None:
                on_retry(error, attempt + 1, delay)
            if delay:
                sleep(delay)
    raise RuntimeError("unreachable retry state")


class CircuitOpenError(RuntimeError):
    """Raised when the circuit is open or a half-open probe is already running."""
    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(0.0, retry_after)
        super().__init__(f"circuit is open; retry after {self.retry_after:.3f}s")


class CircuitBreaker:
    """Thread-safe closed/open/half-open circuit breaker with a single probe."""
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if isinstance(failure_threshold, bool) or not isinstance(failure_threshold, int) or failure_threshold < 1:
            raise ValueError("failure_threshold must be a positive integer")
        if isinstance(reset_timeout, bool) or not isinstance(reset_timeout, (int, float)) or not 0 <= reset_timeout < float("inf"):
            raise ValueError("reset_timeout must be a finite non-negative number")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.failure_threshold = failure_threshold
        self.reset_timeout = float(reset_timeout)
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "closed"
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> str:
        with self._lock:
            self._refresh_state()
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failures

    def call(self, operation: Callable[[], T]) -> T:
        if not callable(operation):
            raise TypeError("operation must be callable")
        with self._lock:
            self._refresh_state()
            if self._state == "open":
                assert self._opened_at is not None
                raise CircuitOpenError(self.reset_timeout - (self._clock() - self._opened_at))
            if self._state == "half-open":
                if self._probe_in_flight:
                    raise CircuitOpenError(0.0)
                self._probe_in_flight = True
            probe = self._state == "half-open"
        try:
            result = operation()
        except BaseException:
            with self._lock:
                if probe or self._state == "half-open":
                    self._open()
                else:
                    self._failures += 1
                    if self._failures >= self.failure_threshold:
                        self._open()
            raise
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False
        return result

    def reset(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def _refresh_state(self) -> None:
        if self._state == "open" and self._opened_at is not None:
            if self._clock() - self._opened_at >= self.reset_timeout:
                self._state = "half-open"
                self._probe_in_flight = False

    def _open(self) -> None:
        self._state = "open"
        self._opened_at = self._clock()
        self._probe_in_flight = False
