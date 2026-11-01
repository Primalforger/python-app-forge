"""Tests for the retrying HTTP client."""
import io
import unittest
import urllib.error

from app_forge.retry import RetryPolicy
from app_forge.http_client import HttpRequestError, RetryingHttpClient


class FakeResponse:
    def __init__(self, status=200, body=b"ok", headers=None, url="https://example.test/path"):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._url = url
        self.closed = False

    def read(self, size=-1):
        return self._body[:size]

    def geturl(self):
        return self._url

    def close(self):
        self.closed = True


class HttpClientTests(unittest.TestCase):
    def client(self, outcomes, **kwargs):
        calls = []
        def opener(request, timeout):
            calls.append((request, timeout))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return RetryingHttpClient(opener=opener, sleep=lambda _delay: None,
                                  policy=RetryPolicy(max_attempts=3, initial_delay=0, jitter=0),
                                  **kwargs), calls

    def test_success_json_and_headers(self):
        client, calls = self.client([FakeResponse(body=b'{"ok":true}')])
        response = client.get("https://example.test/data", headers={"X-Test": "yes"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(calls[0][0].get_header("X-test"), "yes")
        self.assertEqual(calls[0][1], 10.0)

    def test_retries_server_error_and_honors_retry_after_with_cap(self):
        delays, events = [], []
        client, calls = self.client(
            [FakeResponse(503, headers={"Retry-After": "30"}), FakeResponse(200)],
            sleep=delays.append, on_retry=lambda *event: events.append(event),
        )
        response = client.get("https://example.test/data?token=do-not-log")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(delays, [10.0])
        self.assertNotIn("token", events[0][1])

    def test_transport_errors_retry_then_succeed(self):
        client, calls = self.client([TimeoutError("password=hidden"), FakeResponse()])
        response = client.get("https://example.test")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(calls), 2)

    def test_post_is_not_retried_by_default(self):
        client, calls = self.client([TimeoutError("offline"), FakeResponse()])
        with self.assertRaises(HttpRequestError):
            client.post("https://example.test", json_body={"a": 1})
        self.assertEqual(len(calls), 1)

    def test_post_retry_requires_explicit_opt_in(self):
        client, calls = self.client([TimeoutError("offline"), FakeResponse()])
        response = client.request("POST", "https://example.test", json_body={"a": 1}, retry_unsafe=True)
        self.assertEqual(response.status, 200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0].data, b'{"a": 1}')

    def test_http_error_is_returned_when_not_retryable(self):
        error = urllib.error.HTTPError("https://example.test", 404, "missing", {}, io.BytesIO(b"no"))
        client, calls = self.client([error])
        response = client.get("https://example.test")
        self.assertEqual(response.status, 404)
        self.assertEqual(response.body, b"no")
        self.assertEqual(len(calls), 1)

    def test_response_size_limit(self):
        client, _ = self.client([FakeResponse(body=b"12345")], max_response_bytes=4)
        with self.assertRaises(HttpRequestError):
            client.get("https://example.test")

    def test_rejects_invalid_urls_and_arguments(self):
        client = RetryingHttpClient()
        for url in ("file:///etc/passwd", "https://user:pass@example.test", "/relative"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.get(url)
        with self.assertRaises(ValueError):
            client.request("GET", "https://example.test", data=b"x", json_body={})
        with self.assertRaises(ValueError):
            RetryingHttpClient(timeout=0)
        with self.assertRaises(ValueError):
            RetryingHttpClient(max_response_bytes=0)


if __name__ == "__main__":
    unittest.main()
