"""Tests for durable queue-backed workflow dispatch."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from app_forge.job_queue import JobQueue
from app_forge.workflow import WorkflowDefinition, WorkflowStep
from app_forge.workflow_worker import WorkflowQueueWorker


class WorkflowQueueWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = JobQueue(Path(self.tmp.name) / "jobs.sqlite3")
        self.workflow = WorkflowDefinition(
            "compile",
            (
                WorkflowStep("prepare", "prepare"),
                WorkflowStep("build", "build", depends_on=("prepare",)),
            ),
        )

    def worker(self, handlers, *, retry_delay=0.0):
        return WorkflowQueueWorker(
            self.queue,
            {"compile": self.workflow},
            handlers,
            worker_id="worker-a",
            retry_delay=retry_delay,
        )

    def test_enqueue_persists_json_inputs_and_worker_runs_registered_workflow(self):
        observed = []

        def prepare(context):
            observed.append(dict(context.workflow_inputs))
            return context.workflow_inputs["version"]

        def build(context):
            return f"{context.outputs['prepare']}-built"

        worker = self.worker({"prepare": prepare, "build": build})
        job = worker.enqueue("compile", {"version": "2.4"})
        self.assertEqual(job.status, "pending")

        execution = worker.run_once()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.job.status, "succeeded")
        self.assertTrue(execution.result.succeeded)
        self.assertEqual(execution.result.outputs["build"], "2.4-built")
        self.assertEqual(observed, [{"version": "2.4"}])
        self.assertEqual(self.queue.get(job.id).status, "succeeded")
        self.assertIsNone(worker.run_once())

    def test_failed_workflow_is_requeued_and_restarts_from_first_step(self):
        calls = []
        should_fail = [True]

        def prepare(_context):
            calls.append("prepare")
            return "ready"

        def build(_context):
            if should_fail[0]:
                raise RuntimeError("temporary failure")
            calls.append("build")
            return "done"

        worker = self.worker({"prepare": prepare, "build": build})
        job = worker.enqueue("compile", max_attempts=2)

        first = worker.run_once()
        self.assertEqual(first.job.status, "pending")
        self.assertEqual(first.result.status, "failed")
        self.assertEqual(first.job.attempts, 1)
        self.assertEqual(calls, ["prepare"])

        should_fail[0] = False
        second = worker.run_once()
        self.assertEqual(second.job.status, "succeeded")
        self.assertEqual(second.job.attempts, 2)
        self.assertEqual(calls, ["prepare", "prepare", "build"])
        self.assertEqual(self.queue.get(job.id).status, "succeeded")

    def test_dead_letter_after_exhausted_workflow_attempts(self):
        worker = self.worker({
            "prepare": lambda _context: "ready",
            "build": lambda _context: (_ for _ in ()).throw(ValueError("bad")),
        })
        job = worker.enqueue("compile", max_attempts=1)
        result = worker.run_once()
        self.assertEqual(result.job.status, "dead")
        self.assertEqual(self.queue.dead_letters()[0].id, job.id)
        self.assertEqual(result.job.last_error, "workflow failed at step build")

    def test_unknown_workflow_and_non_json_inputs_are_rejected_before_enqueue(self):
        worker = self.worker({"prepare": lambda _context: None, "build": lambda _context: None})
        with self.assertRaisesRegex(ValueError, "unknown registered workflow"):
            worker.enqueue("not-registered")
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            worker.enqueue("compile", {"bad": object()})

    def test_worker_rejects_malformed_or_unregistered_queue_payload(self):
        job = self.queue.enqueue({"kind": "workflow", "workflow_id": "missing", "inputs": {}})
        worker = self.worker({"prepare": lambda _context: None, "build": lambda _context: None})
        result = worker.run_once()
        self.assertEqual(result.job.id, job.id)
        self.assertIsNone(result.result)
        self.assertEqual(result.job.status, "pending")
        self.assertIn("invalid", result.error)

    def test_handler_exception_text_is_not_written_to_queue_error(self):
        worker = self.worker({
            "prepare": lambda _context: "ready",
            "build": lambda _context: (_ for _ in ()).throw(RuntimeError("password=hunter2")),
        })
        job = worker.enqueue("compile", max_attempts=1)
        result = worker.run_once()
        self.assertEqual(result.job.status, "dead")
        self.assertNotIn("hunter2", result.job.last_error)
        self.assertEqual(self.queue.get(job.id).last_error, result.job.last_error)

    def test_long_workflow_renews_lease_so_second_worker_cannot_reclaim(self):
        started = threading.Event()
        renewed = threading.Event()

        def slow_prepare(_context):
            started.set()
            time.sleep(1.2)
            return "ready"

        worker = WorkflowQueueWorker(
            self.queue, {"compile": self.workflow},
            {"prepare": slow_prepare, "build": lambda _context: "done"},
            worker_id="worker-a", lease_seconds=0.6,
        )
        job = worker.enqueue("compile", max_attempts=2)
        outcome = []
        original_extend = self.queue.extend_lease

        def extend_and_signal(*args, **kwargs):
            result = original_extend(*args, **kwargs)
            renewed.set()
            return result

        thread = threading.Thread(target=lambda: outcome.append(worker.run_once()))
        with mock.patch.object(self.queue, "extend_lease", side_effect=extend_and_signal):
            thread.start()
            self.assertTrue(started.wait(timeout=2))
            # Wait for an actual successful heartbeat instead of assuming the
            # scheduler ran the heartbeat thread within a fixed sleep interval.
            self.assertTrue(renewed.wait(timeout=2))
            self.assertIsNone(self.queue.claim("worker-b", lease_seconds=1))
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome[0].job.status, "succeeded")
        self.assertEqual(self.queue.get(job.id).attempts, 1)

    def test_constructor_validates_registered_workflows_and_worker_settings(self):
        with self.assertRaisesRegex(ValueError, "unregistered handlers"):
            self.worker({"prepare": lambda _context: None})
        with self.assertRaisesRegex(ValueError, "worker_id"):
            WorkflowQueueWorker(self.queue, {"compile": self.workflow},
                                {"prepare": lambda _context: None, "build": lambda _context: None},
                                worker_id="")
        with self.assertRaisesRegex(ValueError, "lease_seconds"):
            WorkflowQueueWorker(self.queue, {"compile": self.workflow},
                                {"prepare": lambda _context: None, "build": lambda _context: None},
                                worker_id="worker", lease_seconds=0)


if __name__ == "__main__":
    unittest.main()
