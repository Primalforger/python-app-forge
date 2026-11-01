"""Correctness checks for the opt-in performance benchmark."""
import tempfile
import unittest
from pathlib import Path
from scripts.benchmark_performance import percentile, run_benchmarks
from scripts.check_performance_regression import regression_errors

class PerformanceBenchmarkTests(unittest.TestCase):
    def test_nearest_rank_percentile(self):
        self.assertEqual(percentile([4.,1.,3.,2.],.5),2.)
        self.assertEqual(percentile([4.,1.,3.,2.],.95),4.)
    def test_invalid_percentile_rejected(self):
        with self.assertRaises(ValueError): percentile([],.95)
        with self.assertRaises(ValueError): percentile([1.],0)
    def test_regression_checker_accepts_baseline_and_rejects_slow_workload(self):
        environment = {
            "system": "Linux", "machine": "x86_64", "processor": "x86_64",
            "python_version": "3.11", "python_implementation": "CPython",
            "cpu_count": 4, "runner_image": "ubuntu-24.04",
            "runner_image_version": "20261025.353.1",
            "runner_os": "Linux", "runner_arch": "X64",
        }
        report = {
            "environment": dict(environment),
            "results": {
                "catalog": [
                    {"components": 25, "scan": {"median_seconds": 0.02}, "search": {"median_seconds": 0.0001}},
                    {"components": 100, "scan": {"median_seconds": 0.08}, "search": {"median_seconds": 0.0005}},
                    {"components": 250, "scan": {"median_seconds": 0.19}, "search": {"median_seconds": 0.001}},
                ],
                "project_generation": {"timing": {"median_seconds": 0.006}},
            },
        }
        baseline = {
            "environment": dict(environment),
            "regression_ceilings_seconds": {
                "catalog_scan_25": 0.032, "catalog_search_25": 0.001,
                "catalog_scan_100": 0.120, "catalog_search_100": 0.001,
                "catalog_scan_250": 0.298, "catalog_search_250": 0.003,
                "project_generation": 0.010,
            },
        }
        self.assertEqual(regression_errors(report, baseline), [])
        report["results"]["catalog"][2]["scan"]["median_seconds"] = 0.31
        self.assertTrue(any("catalog_scan_250" in error for error in regression_errors(report, baseline)))

    def test_regression_checker_rejects_host_mismatch(self):
        report = {"environment": {"system": "Windows"}, "results": {}}
        baseline = {"environment": {"system": "Linux"}, "regression_ceilings_seconds": {}}
        errors = regression_errors(report, baseline)
        self.assertTrue(errors)
        self.assertIn("reference host mismatch", errors[0])

    def test_small_catalog_and_project_workloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=run_benchmarks(Path(tmp),[2],1)
        self.assertEqual(report["schema_version"],1)
        self.assertTrue(report["environment"]["python"])
        self.assertEqual(report["results"]["catalog"][0]["components"],2)
        self.assertGreaterEqual(report["results"]["catalog"][0]["scan"]["median_seconds"],0)
        self.assertEqual(report["results"]["project_generation"]["projects_generated"],1)

if __name__=="__main__": unittest.main()
