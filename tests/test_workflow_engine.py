"""Tests for the dependency-aware in-process workflow engine."""
from __future__ import annotations

import unittest

from app_forge.cancellation import CancellationToken
from app_forge.workflow import WorkflowDefinition, WorkflowEngine, WorkflowStep


class WorkflowEngineTests(unittest.TestCase):
    def test_dependency_order_and_outputs_are_available_to_downstream_steps(self):
        seen = []

        def consume(context):
            seen.append((context.step_id, context.outputs["prepare"]))
            return context.outputs["prepare"] + context.inputs["increment"]

        workflow = WorkflowDefinition("build", (
            WorkflowStep("publish", "consume", ("prepare",), {"increment": 2}),
            WorkflowStep("prepare", "prepare"),
        ))
        result = WorkflowEngine({
            "prepare": lambda _context: 40,
            "consume": consume,
        }).run(workflow)

        self.assertTrue(result.succeeded)
        self.assertEqual(seen, [("publish", 40)])
        self.assertEqual(result.outputs, {"prepare": 40, "publish": 42})
        self.assertEqual([step.id for step in result.steps], ["prepare", "publish"])

    def test_retries_are_bounded_and_emit_events(self):
        calls = []
        events = []

        def flaky(_context):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("transient")
            return "ok"

        workflow = WorkflowDefinition("retry", (
            WorkflowStep("work", "flaky", max_attempts=3, retry_delay=0.01),
        ))
        result = WorkflowEngine({"flaky": flaky}, sleep=lambda _delay: None).run(
            workflow, on_event=events.append
        )
        self.assertEqual((result.status, result.steps[0].attempts, result.outputs["work"]),
                         ("succeeded", 3, "ok"))
        self.assertEqual([event["event"] for event in events].count("step_retrying"), 2)

    def test_first_failure_stops_remaining_steps(self):
        events = []
        workflow = WorkflowDefinition("fail-fast", (
            WorkflowStep("first", "fail"),
            WorkflowStep("later", "ok"),
            WorkflowStep("also-later", "ok"),
        ))
        result = WorkflowEngine({
            "fail": lambda _context: (_ for _ in ()).throw(ValueError("bad input")),
            "ok": lambda _context: self.fail("must not execute after failure"),
        }).run(workflow, on_event=events.append)
        self.assertEqual(result.status, "failed")
        self.assertEqual([step.status for step in result.steps], ["failed", "skipped", "skipped"])
        self.assertIn("ValueError", result.error)
        self.assertEqual(len([e for e in events if e["event"] == "step_skipped"]), 2)

    def test_cooperative_cancellation_stops_before_next_step(self):
        token = CancellationToken()
        workflow = WorkflowDefinition("cancel", (
            WorkflowStep("stop", "cancel"),
            WorkflowStep("never", "never"),
        ))

        def cancel(context):
            context.cancellation.cancel()
            return "finished-current-step"

        result = WorkflowEngine({
            "cancel": cancel,
            "never": lambda _context: self.fail("cancelled workflow continued"),
        }).run(workflow, cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual([step.status for step in result.steps], ["succeeded", "cancelled"])

    def test_pre_cancelled_workflow_does_not_invoke_handlers(self):
        token = CancellationToken()
        token.cancel()
        workflow = WorkflowDefinition("already-cancelled", (WorkflowStep("one", "handler"),))
        result = WorkflowEngine({"handler": lambda _context: self.fail("handler executed")}).run(
            workflow, cancellation=token
        )
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.steps[0].status, "cancelled")

    def test_definition_rejects_duplicate_missing_and_cyclic_dependencies(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            WorkflowDefinition("duplicate", (
                WorkflowStep("same", "handler"), WorkflowStep("same", "handler")
            ))
        with self.assertRaisesRegex(ValueError, "unknown dependencies"):
            WorkflowDefinition("missing", (WorkflowStep("one", "handler", ("absent",)),))
        with self.assertRaisesRegex(ValueError, "cycle"):
            WorkflowDefinition("cycle", (
                WorkflowStep("one", "handler", ("two",)),
                WorkflowStep("two", "handler", ("one",)),
            ))

    def test_missing_handler_and_invalid_limits_are_rejected(self):
        workflow = WorkflowDefinition("unknown", (WorkflowStep("one", "missing"),))
        with self.assertRaisesRegex(ValueError, "unregistered"):
            WorkflowEngine({}).run(workflow)
        with self.assertRaises(ValueError):
            WorkflowStep("one", "handler", max_attempts=0)
        with self.assertRaises(ValueError):
            WorkflowStep("one", "handler", retry_delay=float("inf"))
        with self.assertRaises(ValueError):
            WorkflowDefinition("empty", ())


if __name__ == "__main__":
    unittest.main()
