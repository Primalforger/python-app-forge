# Durable workflow dispatch

The app_forge.workflow_worker.WorkflowQueueWorker connects the trusted in-process
workflow engine to the persistent SQLite job queue.

## Register and enqueue

~~~python
from pathlib import Path

from app_forge.job_queue import JobQueue
from app_forge.workflow import WorkflowDefinition, WorkflowStep
from app_forge.workflow_worker import WorkflowQueueWorker

workflow = WorkflowDefinition(
    "thumbnail",
    (
        WorkflowStep("decode", "decode-image"),
        WorkflowStep("resize", "resize-image", depends_on=("decode",)),
    ),
)

worker = WorkflowQueueWorker(
    JobQueue(Path("forge-jobs.sqlite3")),
    {"thumbnail": workflow},
    {
        "decode-image": decode_image,
        "resize-image": resize_image,
    },
    worker_id="thumbnail-worker-1",
)
job = worker.enqueue("thumbnail", {"source": "images/input.png"})
~~~

Workflow definitions and Python handlers are registered by trusted application
code when a worker starts. Persisted payloads contain only a registered workflow
identifier and finite JSON input values. A queue message cannot import a module,
select a callable, or execute code.

A worker loop can call run_once() repeatedly. It returns None when no job
is ready, otherwise a WorkflowJobRun containing the updated queue job and
the in-memory WorkflowResult. Step handlers read invocation-level values
from StepContext.workflow_inputs; each step's own static values remain in
StepContext.inputs.

## Delivery and recovery guarantees

- Queue claims use the job queue's atomic lease and worker-ownership rules.
  Expired leases can be reclaimed by another worker. Set lease_seconds longer
  than the expected maximum workflow duration; this worker does not renew a
  lease while a handler is running.
- Successful workflows complete the queue job. Failed or cancelled workflows
  use the queue's retry policy and eventually become dead letters.
- Delivery is **at least once**, not exactly once. If a process exits after a
  side effect but before acknowledging the job, the queue may execute the
  workflow again. Make handlers idempotent or use application-level idempotency
  keys for external side effects.
- A retry starts the workflow from its first step. Individual step outputs and
  progress are not checkpointed across process restarts. The queue stores job
  state and a bounded error summary, not arbitrary workflow outputs.
- Handler and observer exception messages are not copied into the durable queue
  error field; only the exception type is recorded for unexpected exceptions.
- Workflow definitions and handlers must be compatible across worker versions
  while old jobs remain queued. Unknown workflow identifiers fail safely and
  remain subject to the configured retry/dead-letter policy.

This layer deliberately does not execute handlers from queue payloads, create
worker processes, or claim exactly-once side-effect semantics.
