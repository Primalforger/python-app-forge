import unittest

from {{package}}.scheduler import Job, Scheduler, run_with_retries


class RetryTests(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls, sleeps = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("boom")

        ok, err = run_with_retries(flaky, retries=3, sleep=sleeps.append)
        self.assertTrue(ok)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_gives_up_and_reports_error(self):
        ok, err = run_with_retries(lambda: 1 / 0, retries=1, sleep=lambda _: None)
        self.assertFalse(ok)
        self.assertIn("ZeroDivisionError", err)


class SchedulerTests(unittest.TestCase):
    def test_interval_and_failure_isolation(self):
        t = [0.0]
        s = Scheduler(lambda: t[0], lambda _: None)
        hits = []
        s.add(Job("good", lambda: hits.append(1), interval_s=10))
        s.add(Job("bad", lambda: 1 / 0, interval_s=10, max_retries=0))
        self.assertEqual(s.tick(), 2)
        self.assertEqual(s.tick(), 0)  # not due yet
        t[0] = 10.0
        self.assertEqual(s.tick(), 2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(s.health.failed_runs, 2)
        self.assertTrue(s.health.jobs["good"]["ok"])

    def test_stop_prevents_further_runs(self):
        s = Scheduler(lambda: 0.0, lambda _: None)
        s.add(Job("j", lambda: None, interval_s=1))
        s.stop()
        self.assertEqual(s.tick(), 0)
        self.assertEqual(s.health.status, "stopping")
