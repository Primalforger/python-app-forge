"""Correctness checks for the opt-in performance benchmark."""
import tempfile
import unittest
from pathlib import Path
from scripts.benchmark_performance import percentile, run_benchmarks

class PerformanceBenchmarkTests(unittest.TestCase):
    def test_nearest_rank_percentile(self):
        self.assertEqual(percentile([4.,1.,3.,2.],.5),2.)
        self.assertEqual(percentile([4.,1.,3.,2.],.95),4.)
    def test_invalid_percentile_rejected(self):
        with self.assertRaises(ValueError): percentile([],.95)
        with self.assertRaises(ValueError): percentile([1.],0)
    def test_small_catalog_and_project_workloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=run_benchmarks(Path(tmp),[2],1)
        self.assertEqual(report["schema_version"],1)
        self.assertTrue(report["environment"]["python"])
        self.assertEqual(report["results"]["catalog"][0]["components"],2)
        self.assertGreaterEqual(report["results"]["catalog"][0]["scan"]["median_seconds"],0)
        self.assertEqual(report["results"]["project_generation"]["projects_generated"],1)

if __name__=="__main__": unittest.main()
