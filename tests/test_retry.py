import unittest

from app_forge.retry import CircuitBreaker, CircuitOpenError, RetryPolicy, retry_call


class RetryTests(unittest.TestCase):
    def test_backoff_cap_and_jitter(self):
        policy = RetryPolicy(initial_delay=1, multiplier=2, max_delay=3, jitter=0.25)
        self.assertEqual(policy.delay_for(0, random_value=0), 1)
        self.assertEqual(policy.delay_for(1, random_value=1), 2.5)
        self.assertEqual(policy.delay_for(8, random_value=-1), 2.25)

    def test_policy_validation(self):
        for kwargs in ({"max_attempts": 0}, {"max_attempts": True}, {"initial_delay": -1},
                       {"multiplier": 0.5}, {"max_delay": float("inf")}, {"jitter": 1.1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RetryPolicy(**kwargs)

    def test_retry_success_and_final_exception(self):
        calls, delays = [], []
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise OSError("temporary")
            return "ok"
        self.assertEqual(retry_call(flaky, RetryPolicy(max_attempts=3, initial_delay=0.5, jitter=0),
                                    sleep=delays.append), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(delays, [0.5, 1.0])
        with self.assertRaisesRegex(OSError, "last"):
            retry_call(lambda: (_ for _ in ()).throw(OSError("last")),
                       RetryPolicy(max_attempts=2, initial_delay=0))

    def test_retry_predicate_stops_early(self):
        calls = []
        with self.assertRaises(ValueError):
            retry_call(lambda: (calls.append(1), (_ for _ in ()).throw(ValueError("stop")))[1],
                       RetryPolicy(max_attempts=4), retry_if=lambda _e: False)
        self.assertEqual(len(calls), 1)


class CircuitBreakerTests(unittest.TestCase):
    def test_opens_and_rejects(self):
        breaker = CircuitBreaker(2, 10)
        for _ in range(2):
            with self.assertRaises(OSError):
                breaker.call(lambda: (_ for _ in ()).throw(OSError("down")))
        self.assertEqual(breaker.state, "open")
        with self.assertRaises(CircuitOpenError) as caught:
            breaker.call(lambda: None)
        self.assertEqual(caught.exception.retry_after, 10)

    def test_half_open_probe_closes_or_reopens(self):
        now = [0.0]
        breaker = CircuitBreaker(1, 5, clock=lambda: now[0])
        with self.assertRaises(OSError):
            breaker.call(lambda: (_ for _ in ()).throw(OSError()))
        now[0] = 5
        self.assertEqual(breaker.state, "half-open")
        self.assertEqual(breaker.call(lambda: "recovered"), "recovered")
        self.assertEqual(breaker.state, "closed")
        with self.assertRaises(OSError):
            breaker.call(lambda: (_ for _ in ()).throw(OSError()))
        now[0] = 10
        with self.assertRaises(OSError):
            breaker.call(lambda: (_ for _ in ()).throw(OSError()))
        self.assertEqual(breaker.state, "open")

    def test_reset_and_validation(self):
        breaker = CircuitBreaker(1, 3)
        with self.assertRaises(ValueError):
            CircuitBreaker(0, 3)
        with self.assertRaises(ValueError):
            CircuitBreaker(1, -1)
        with self.assertRaises(TypeError):
            breaker.call(None)
        with self.assertRaises(OSError):
            breaker.call(lambda: (_ for _ in ()).throw(OSError()))
        breaker.reset()
        self.assertEqual(breaker.state, "closed")
        self.assertEqual(breaker.failure_count, 0)


if __name__ == "__main__":
    unittest.main()
