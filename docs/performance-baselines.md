# Performance baselines

## Reproduce

From the repository root, with the project installed:

```bash
python scripts/benchmark_performance.py --catalog-sizes 25,100,250 --iterations 7 --output performance-results.json
```

The offline harness creates sealed synthetic catalog datasets by cloning a real built-in component.
It measures catalog scans (manifest parsing, digest/signature checks and filesystem traversal),
warmed catalog text search, and complete CLI-template project generation into fresh directories.
JSON contains raw samples, median, nearest-rank p95, min/max, Python build, platform, architecture,
processor string, CPU count, GitHub runner image identity and timestamp. It makes no network requests.

## Reference host and thresholds

The reference host is the GitHub-hosted `ubuntu-24.04` x64 runner using Python 3.11. Runner labels
do not guarantee a fixed physical machine; each report captures the actual host details. Compare
only materially equivalent environments and retain the raw JSON artifact.

The checked-in `benchmarks/baseline-ubuntu-24.04-py311.json` preserves the first successful
reference-host report, including all seven raw samples per workload. Each ceiling is 150% of the
measured median, rounded up to the nearest millisecond. p95 remains diagnostic. The regression
checker compares system, architecture, processor, Python minor version, CPU count and GitHub runner
image version before comparing timings; a host mismatch fails with an explicit rebaseline message.

CI runs the benchmark and then `scripts/check_performance_regression.py` on the pinned reference
host. Rebaseline when the runner image, Python minor version, or workload definition changes. The
workflow also preserves a 90-day raw JSON artifact for later analysis.
