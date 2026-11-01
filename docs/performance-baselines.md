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
processor string, CPU count and timestamp. It makes no network requests.

## Reference host and thresholds

The reference host is the GitHub-hosted `ubuntu-24.04` x64 runner using Python 3.11. Runner labels
do not guarantee a fixed physical machine; each report captures the actual host details. Compare
only materially equivalent environments and retain the raw JSON artifact.

After the first successful reference-host run, check its report into this document's companion
baseline data file and set each workload ceiling to 150% of its measured median, rounded up to the
nearest millisecond. Keep p95 as diagnostic data. Rebaseline when the runner image, Python minor
version, or workload definition changes. Do not invent timing values or enforce developer-machine
measurements as a universal threshold.

The benchmark workflow preserves a 90-day JSON artifact. Until an actual report has been captured,
no numeric baseline or regression ceiling is claimed. The smoke test verifies harness correctness,
not performance.
