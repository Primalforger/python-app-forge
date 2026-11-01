"""Tests for optional Prometheus metrics primitives."""
import unittest

from app_forge.metrics import PrometheusMetrics


class PrometheusMetricsTests(unittest.TestCase):
    def setUp(self):
        self.metrics = PrometheusMetrics(namespace="forge_test")

    def test_records_counter_and_histogram_with_route_template(self):
        self.metrics.record_http_request("get", "/items/{item_id}", 200, 0.125)
        payload, content_type = self.metrics.render()
        text = payload.decode("utf-8")
        self.assertIn("forge_test_http_requests_total", text)
        self.assertIn('route="/items/{item_id}"', text)
        self.assertIn('status="200"', text)
        self.assertIn("forge_test_http_request_duration_seconds_count", text)
        self.assertIn("text/plain", content_type)

    def test_registry_is_isolated_by_default(self):
        first = PrometheusMetrics(namespace="first")
        second = PrometheusMetrics(namespace="second")
        first.record_http_request("GET", "/health", 200, 0.01)
        first_text = first.render()[0].decode()
        second_text = second.render()[0].decode()
        self.assertIn("first_http_requests_total", first_text)
        self.assertNotIn("first_http_requests_total", second_text)

    def test_unknown_method_is_normalized(self):
        self.metrics.record_http_request("CUSTOM", "/health", 200, 0)
        self.assertIn('method="OTHER"', self.metrics.render()[0].decode())

    def test_rejects_unbounded_or_invalid_labels_and_values(self):
        for route in ("items/1", "/items/1?secret=value", "/" + "x" * 201):
            with self.subTest(route=route), self.assertRaises(ValueError):
                self.metrics.record_http_request("GET", route, 200, 0.1)
        for status in (99, 600, True):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.metrics.record_http_request("GET", "/health", status, 0.1)
        for duration in (-1, float("nan"), float("inf"), True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.metrics.record_http_request("GET", "/health", 200, duration)

    def test_invalid_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            PrometheusMetrics(namespace="bad namespace")


if __name__ == "__main__":
    unittest.main()
