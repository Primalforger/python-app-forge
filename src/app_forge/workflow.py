"""Small deterministic workflow engine with dependency-aware execution.

Definitions are trusted Python objects; manifests never import or execute handlers.
The engine is intentionally synchronous and sequential. Durable scheduling belongs
to :mod:`app_forge.job_queue`, not this in-process orchestration layer.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic
from types import MappingProxyType
from typing import Any

from app_forge.cancellation import CancellationToken

WorkflowHandler = Callable[["StepContext"], Any]
EventCallback = Callable[[dict[str, Any]], None]
_ALLOWED_STEP_STATUSES = {"pending", "running", "succeeded", "failed", "skipped", "cancelled"}


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One named handler invocation and its explicit dependency edges."""

    id: str
    handler: str
    depends_on: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    max_attempts: int = 1
    retry_delay: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip() or len(self.id) > 80:
            raise ValueError("step id must be a non-empty string of at most 80 characters")
        if not isinstance(self.handler, str) or not self.handler.strip() or len(self.handler) > 128:
            raise ValueError("handler must be a non-empty registered handler name")
        if not isinstance(self.depends_on, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.depends_on
        ):
            raise ValueError("depends_on must be a tuple of non-empty step IDs")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"step {self.id!r} contains duplicate dependencies")
        if self.id in self.depends_on:
            raise ValueError(f"step {self.id!r} cannot depend on itself")
        if not isinstance(self.inputs, Mapping):
            raise ValueError("step inputs must be a mapping")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be an integer from 1 to 10")
        if isinstance(self.retry_delay, bool) or not isinstance(self.retry_delay, (int, float)):
            raise ValueError("retry_delay must be a finite non-negative number")
        if not 0 <= self.retry_delay < float("inf"):
            raise ValueError("retry_delay must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    """A bounded directed acyclic graph of named steps."""

    id: str
    steps: tuple[WorkflowStep, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip() or len(self.id) > 128:
            raise ValueError("workflow id must be a non-empty string of at most 128 characters")
        if not isinstance(self.steps, tuple) or not self.steps or len(self.steps) > 100:
            raise ValueError("workflow must contain between 1 and 100 steps")
        if any(not isinstance(step, WorkflowStep) for step in self.steps):
            raise ValueError("workflow steps must be WorkflowStep instances")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("workflow step IDs must be unique")
        known = set(ids)
        for step in self.steps:
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError(f"step {step.id!r} has unknown dependencies: {', '.join(sorted(missing))}")
        self.topological_order()

    def topological_order(self) -> tuple[WorkflowStep, ...]:
        """Return stable insertion-order topological order; reject dependency cycles."""
        by_id = {step.id: step for step in self.steps}
        pending = {step.id: set(step.depends_on) for step in self.steps}
        ordered: list[WorkflowStep] = []
        while pending:
            ready = [step.id for step in self.steps if step.id in pending and not pending[step.id]]
            if not ready:
                raise ValueError("workflow dependencies contain a cycle")
            for step_id in ready:
                ordered.append(by_id[step_id])
                del pending[step_id]
                for dependencies in pending.values():
                    dependencies.discard(step_id)
        return tuple(ordered)


@dataclass(frozen=True, slots=True)
class StepContext:
    """Read-only view of a step's inputs, completed dependency outputs and cancellation."""

    workflow_id: str
    step_id: str
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    cancellation: CancellationToken


@dataclass(frozen=True, slots=True)
class StepResult:
    id: str
    status: str
    attempts: int
    output: Any = None
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    id: str
    status: str
    steps: tuple[StepResult, ...]
    outputs: Mapping[str, Any]
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


class WorkflowEngine:
    """Execute a validated workflow sequentially with bounded retries and cancellation."""

    def __init__(self, handlers: Mapping[str, WorkflowHandler], *,
                 sleep: Callable[[float], None] | None = None) -> None:
        if not isinstance(handlers, Mapping) or any(
            not isinstance(name, str) or not name.strip() or not callable(handler)
            for name, handler in handlers.items()
        ):
            raise ValueError("handlers must map non-empty names to callables")
        self._handlers = dict(handlers)
        self._sleep = sleep

    def run(self, workflow: WorkflowDefinition, *,
            cancellation: CancellationToken | None = None,
            on_event: EventCallback | None = None) -> WorkflowResult:
        """Run steps in stable dependency order; first failure stops the workflow."""
        if not isinstance(workflow, WorkflowDefinition):
            raise TypeError("workflow must be a WorkflowDefinition")
        missing = sorted({step.handler for step in workflow.steps} - self._handlers.keys())
        if missing:
            raise ValueError(f"workflow references unregistered handlers: {', '.join(missing)}")
        if on_event is not None and not callable(on_event):
            raise TypeError("on_event must be callable")
        token = cancellation or CancellationToken()
        outputs: dict[str, Any] = {}
        results: list[StepResult] = []
        failed = False
        cancelled = False

        def emit(event: str, **details: Any) -> None:
            if on_event is not None:
                on_event({"workflow_id": workflow.id, "event": event, **details})

        for step in workflow.topological_order():
            if failed:
                results.append(StepResult(step.id, "skipped", 0))
                emit("step_skipped", step_id=step.id, reason="previous_step_failed")
                continue
            if token.cancelled:
                cancelled = True
                results.append(StepResult(step.id, "cancelled", 0))
                emit("step_cancelled", step_id=step.id)
                continue

            handler = self._handlers[step.handler]
            started = monotonic()
            error: Exception | None = None
            output: Any = None
            attempts = 0
            emit("step_started", step_id=step.id)
            for attempt in range(1, step.max_attempts + 1):
                if token.cancelled:
                    cancelled = True
                    break
                attempts = attempt
                context = StepContext(
                    workflow_id=workflow.id,
                    step_id=step.id,
                    inputs=MappingProxyType(dict(step.inputs)),
                    outputs=MappingProxyType(dict(outputs)),
                    cancellation=token,
                )
                try:
                    output = handler(context)
                    error = None
                    break
                except Exception as exc:
                    error = exc
                    if attempt >= step.max_attempts:
                        break
                    emit("step_retrying", step_id=step.id, attempt=attempt, error=type(exc).__name__)
                    if step.retry_delay:
                        if self._sleep is None:
                            token.wait(step.retry_delay)
                        else:
                            self._sleep(step.retry_delay)
            duration = max(0.0, monotonic() - started)
            if cancelled:
                results.append(StepResult(step.id, "cancelled", attempts, duration_seconds=duration))
                emit("step_cancelled", step_id=step.id)
                continue
            if error is not None:
                failed = True
                message = f"{type(error).__name__}: {error}"
                results.append(StepResult(step.id, "failed", attempts, error=message, duration_seconds=duration))
                emit("step_failed", step_id=step.id, attempts=attempts, error=type(error).__name__)
                continue
            outputs[step.id] = output
            results.append(StepResult(step.id, "succeeded", attempts, output=output, duration_seconds=duration))
            emit("step_succeeded", step_id=step.id, attempts=attempts)

        if failed:
            status = "failed"
        elif cancelled or token.cancelled:
            status = "cancelled"
        else:
            status = "succeeded"
        error_text = next((item.error for item in results if item.status == "failed"), None)
        emit("workflow_finished", status=status)
        return WorkflowResult(workflow.id, status, tuple(results),
                              MappingProxyType(dict(outputs)), error=error_text)
