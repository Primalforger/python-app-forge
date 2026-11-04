"""Durable queue-backed dispatch for trusted, registered workflows.

A queued workflow is delivered at least once. If a worker loses its lease or
processes terminate, the entire workflow may be run again; handlers with
external side effects must therefore be idempotent.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app_forge.cancellation import CancellationToken
from app_forge.job_queue import Job, JobQueue
from app_forge.workflow import (
    EventCallback,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowResult,
)


@dataclass(frozen=True, slots=True)
class WorkflowJobRun:
    """Outcome of one claimed queue job; result is absent for invalid payloads."""

    job: Job
    result: WorkflowResult | None
    error: str | None = None


class WorkflowQueueWorker:
    """Dispatch registered workflows through the durable SQLite job queue.

    Workflow definitions and Python handlers are supplied by trusted application
    code at worker startup. Queue payloads contain only a workflow identifier
    and finite JSON inputs; they can never name/import a Python callable.
    """

    def __init__(
        self,
        queue: JobQueue,
        workflows: Mapping[str, WorkflowDefinition],
        handlers: Mapping[str, Any],
        *,
        worker_id: str,
        lease_seconds: float = 300.0,
        retry_delay: float = 0.0,
    ) -> None:
        if not isinstance(queue, JobQueue):
            raise TypeError("queue must be a JobQueue")
        if not isinstance(workflows, Mapping) or not workflows:
            raise ValueError("workflows must be a non-empty mapping")
        if any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(definition, WorkflowDefinition)
            for name, definition in workflows.items()
        ):
            raise ValueError("workflows must map non-empty names to WorkflowDefinition objects")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string")
        self._queue = queue
        self._workflows = dict(workflows)
        self._engine = WorkflowEngine(handlers)
        self._worker_id = worker_id
        self._lease_seconds = self._positive_duration(lease_seconds, "lease_seconds")
        self._retry_delay = self._positive_duration(retry_delay, "retry_delay", allow_zero=True)

        for name, workflow in self._workflows.items():
            # Validate handler registration before accepting work into the queue.
            missing = {step.handler for step in workflow.steps} - handlers.keys()
            if missing:
                raise ValueError(
                    f"workflow {name!r} references unregistered handlers: {', '.join(sorted(missing))}"
                )

    @staticmethod
    def _positive_duration(value: float, label: str, *, allow_zero: bool = False) -> float:
        import math

        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{label} must be a finite {'non-negative' if allow_zero else 'positive'} number")
        invalid = value < 0 if allow_zero else value <= 0
        if invalid:
            raise ValueError(f"{label} must be {'non-negative' if allow_zero else 'positive'}")
        return float(value)

    def enqueue(
        self,
        workflow_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_attempts: int = 3,
        delay: float = 0.0,
        job_id: str | None = None,
    ) -> Job:
        """Persist an invocation of a registered workflow."""
        if not isinstance(workflow_id, str) or workflow_id not in self._workflows:
            raise ValueError(f"unknown registered workflow: {workflow_id!r}")
        if inputs is not None and not isinstance(inputs, Mapping):
            raise TypeError("workflow inputs must be a mapping")
        return self._queue.enqueue(
            {"kind": "workflow", "workflow_id": workflow_id, "inputs": dict(inputs or {})},
            max_attempts=max_attempts,
            delay=delay,
            job_id=job_id,
        )

    def run_once(
        self,
        *,
        cancellation: CancellationToken | None = None,
        on_event: EventCallback | None = None,
    ) -> WorkflowJobRun | None:
        """Claim and execute one workflow; return None when no job is ready."""
        job = self._queue.claim(self._worker_id, lease_seconds=self._lease_seconds)
        if job is None:
            return None

        workflow_id = job.payload.get("workflow_id")
        inputs = job.payload.get("inputs", {})
        if (
            job.payload.get("kind") != "workflow"
            or not isinstance(workflow_id, str)
            or workflow_id not in self._workflows
            or not isinstance(inputs, dict)
        ):
            message = "invalid or unregistered workflow job payload"
            updated = self._queue.fail(job.id, self._worker_id, message, retry_delay=self._retry_delay)
            return WorkflowJobRun(updated, None, message)

        try:
            result = self._engine.run(
                self._workflows[workflow_id],
                workflow_inputs=inputs,
                cancellation=cancellation,
                on_event=on_event,
            )
        except Exception as exc:
            # Do not persist exception text from arbitrary handlers or observers.
            message = f"workflow execution raised {type(exc).__name__}"
            updated = self._queue.fail(job.id, self._worker_id, message, retry_delay=self._retry_delay)
            return WorkflowJobRun(updated, None, message)

        if result.succeeded:
            updated = self._queue.complete(job.id, self._worker_id)
            return WorkflowJobRun(updated, result)

        failed_step = next((step.id for step in result.steps if step.status == "failed"), None)
        message = (
            f"workflow failed at step {failed_step}" if failed_step
            else f"workflow ended with status {result.status}"
        )
        updated = self._queue.fail(job.id, self._worker_id, message, retry_delay=self._retry_delay)
        return WorkflowJobRun(updated, result, message)
