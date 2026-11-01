"""Compare a fresh performance report with the pinned reference-host baseline."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

HOST_FIELDS = (
    "system", "machine", "processor", "python_version",
    "python_implementation", "cpu_count", "runner_image",
    "runner_image_version", "runner_os", "runner_arch",
)

def workload_medians(report: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for entry in report["results"]["catalog"]:
        count = int(entry["components"])
        values[f"catalog_scan_{count}"] = float(entry["scan"]["median_seconds"])
        values[f"catalog_search_{count}"] = float(entry["search"]["median_seconds"])
    values["project_generation"] = float(
        report["results"]["project_generation"]["timing"]["median_seconds"]
    )
    return values

def host_mismatches(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    return [
        f"{field}: expected {expected.get(field)!r}, got {actual.get(field)!r}"
        for field in HOST_FIELDS if actual.get(field) != expected.get(field)
    ]

def regression_errors(report: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors = host_mismatches(report["environment"], baseline["environment"])
    if errors:
        return ["reference host mismatch; rebaseline required: " + "; ".join(errors)]
    actual = workload_medians(report)
    ceilings = baseline["regression_ceilings_seconds"]
    for workload, ceiling in ceilings.items():
        if workload not in actual:
            errors.append(f"missing workload {workload}")
        elif actual[workload] > float(ceiling):
            errors.append(
                f"{workload} median {actual[workload]:.6f}s exceeds "
                f"{float(ceiling):.6f}s ceiling"
            )
    unexpected = sorted(set(actual) - set(ceilings))
    if unexpected:
        errors.append("baseline has no ceilings for: " + ", ".join(unexpected))
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--baseline", type=Path,
        default=Path("benchmarks/baseline-ubuntu-24.04-py311.json"),
    )
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        errors = regression_errors(report, baseline)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    if errors:
        for error in errors:
            print(f"PERFORMANCE REGRESSION: {error}")
        return 1
    print("Performance regression check passed on the pinned reference host.")
    for name, value in sorted(workload_medians(report).items()):
        print(f"  {name}: {value * 1000:.3f} ms")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
