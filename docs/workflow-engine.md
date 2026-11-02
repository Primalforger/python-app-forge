# Small workflow engine

`app_forge.workflow` provides a synchronous, in-process orchestration layer for
trusted Python application code. It complements the durable SQLite job queue:
the workflow engine coordinates steps in one invocation, while
`app_forge.job_queue` persists independently scheduled jobs for workers.

## Define and run a workflow

```python
from app_forge.workflow import WorkflowDefinition, WorkflowEngine, WorkflowStep

workflow = WorkflowDefinition(
    "release-check",
    (
        WorkflowStep("test", "run-tests"),
        WorkflowStep("package", "build-package", depends_on=("test",)),
    ),
)

engine = WorkflowEngine({
    "run-tests": lambda context: {"passed": True},
    "build-package": lambda context: {"artifact": "dist/app.whl"},
})
result = engine.run(workflow)
if not result.succeeded:
    raise RuntimeError(result.error or result.status)
```

A handler receives a `StepContext` with immutable top-level views of its
step inputs, outputs from completed steps, and a cooperative cancellation
token. Handlers are explicitly registered by name; workflow definitions never
load Python modules or execute code from manifest strings.

## Execution guarantees

- Workflows contain 1–100 uniquely identified steps and must form a directed
  acyclic graph. Execution uses a stable topological order.
- Steps execute sequentially. The first failed step stops execution and marks
  all remaining steps skipped; successful earlier outputs remain available.
- Each step can retry up to 10 attempts with a bounded configured delay.
  Retry is unconditional for ordinary handler exceptions; handlers should
  therefore be idempotent when retries are enabled.
- Cancellation is cooperative and checked between attempts and steps. A running
  handler must observe `context.cancellation` itself if it needs to stop
  mid-step.
- Structured lifecycle events can be observed through `on_event`. Observer
  exceptions are allowed to propagate to the caller.
- Results distinguish succeeded, failed and cancelled workflows, with per-step
  attempts, duration, output and error information.

This is deliberately not a distributed scheduler: it does not persist workflow
state, run steps concurrently, or promise recovery after process termination.
Use the persistent job queue for durable worker scheduling.
