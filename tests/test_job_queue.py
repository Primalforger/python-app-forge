"""Tests for the persistent SQLite job queue."""
import tempfile
import threading
import unittest
from pathlib import Path

from app_forge.job_queue import JobQueue


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "jobs.sqlite3"
        self.queue = JobQueue(self.path)

    def test_persistence_claim_complete_and_list(self):
        job = self.queue.enqueue({"task": "build", "options": [1, True]}, now=10)
        reopened = JobQueue(self.path)
        self.assertEqual(reopened.get(job.id).payload, job.payload)
        claimed = reopened.claim("worker-a", lease_seconds=30, now=11)
        self.assertEqual((claimed.id, claimed.status, claimed.attempts), (job.id, "running", 1))
        completed = reopened.complete(job.id, "worker-a", now=12)
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(reopened.list(status="succeeded")[0].id, job.id)
        self.assertIsNone(reopened.claim("worker-b", now=13))

    def test_retry_then_dead_letter_and_manual_redrive(self):
        job = self.queue.enqueue({"work": "retry"}, max_attempts=2, now=100)
        first = self.queue.claim("worker", now=100)
        self.assertEqual(first.attempts, 1)
        pending = self.queue.fail(job.id, "worker", "temporary", retry_delay=5, now=101)
        self.assertEqual((pending.status, pending.available_at, pending.last_error), ("pending", 106, "temporary"))
        self.assertIsNone(self.queue.claim("worker-2", now=105))
        second = self.queue.claim("worker-2", now=106)
        self.assertEqual(second.attempts, 2)
        dead = self.queue.fail(job.id, "worker-2", "permanent", now=107)
        self.assertEqual(dead.status, "dead")
        self.assertEqual([item.id for item in self.queue.dead_letters()], [job.id])
        retried = self.queue.retry_dead(job.id, delay=2, now=108)
        self.assertEqual((retried.status, retried.attempts, retried.available_at), ("pending", 0, 110))
        self.assertIsNone(self.queue.claim("worker-3", now=109))
        self.assertEqual(self.queue.claim("worker-3", now=110).attempts, 1)

    def test_expired_lease_is_reclaimed_and_exhausted_job_dead_letters(self):
        job = self.queue.enqueue({"task": "lease"}, max_attempts=2, now=0)
        first = self.queue.claim("worker-a", lease_seconds=5, now=1)
        self.assertEqual(first.lease_until, 6)
        second = self.queue.claim("worker-b", lease_seconds=5, now=6)
        self.assertEqual((second.id, second.attempts, second.worker_id), (job.id, 2, "worker-b"))
        with self.assertRaises(ValueError):
            self.queue.complete(job.id, "worker-a", now=7)
        self.assertIsNone(self.queue.claim("worker-c", now=7))
        self.assertEqual(self.queue.get(job.id).status, "running")
        self.assertIsNone(self.queue.claim("worker-c", now=11))
        self.assertEqual(self.queue.get(job.id).status, "dead")

    def test_only_owning_worker_can_finish_or_fail(self):
        job = self.queue.enqueue({"task": "owned"})
        self.queue.claim("owner")
        with self.assertRaises(ValueError):
            self.queue.complete(job.id, "intruder")
        with self.assertRaises(ValueError):
            self.queue.fail(job.id, "intruder", "no")
        self.assertEqual(self.queue.get(job.id).status, "running")

    def test_validation_and_duplicate_ids(self):
        for payload in ([], {"bad": object()}, {"nan": float("nan")}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.queue.enqueue(payload)
        with self.assertRaises(ValueError):
            self.queue.enqueue({"x": 1}, max_attempts=True)
        self.queue.enqueue({"x": 1}, job_id="same", now=1)
        with self.assertRaises(Exception):
            self.queue.enqueue({"x": 2}, job_id="same", now=2)
        with self.assertRaises(ValueError):
            JobQueue(self.path, max_payload_bytes=0)
        with self.assertRaises(ValueError):
            self.queue.list(limit=0)
        with self.assertRaises(ValueError):
            self.queue.list(status="unknown")

    def test_two_workers_cannot_claim_the_same_job(self):
        job = self.queue.enqueue({"task": "race"})
        barrier = threading.Barrier(3)
        claimed = []
        errors = []

        def worker(name):
            try:
                barrier.wait()
                claimed.append(self.queue.claim(name))
            except Exception as exc:  # surfaced in the main test thread
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        winners = [item for item in claimed if item is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].id, job.id)


if __name__ == "__main__":
    unittest.main()
