"""Run available quality tools. A tool that is not installed is reported as NOT RUN, never as passed."""
from __future__ import annotations

import shutil
import subprocess
import sys

CHECKS = [("ruff", ["ruff", "check", "."]), ("mypy", ["mypy", "src"]), ("pip-audit", ["pip-audit"])]


def run_checks(checks=CHECKS, which=shutil.which, runner=subprocess.run) -> dict[str, str]:
    results = {}
    for name, cmd in checks:
        if which(cmd[0]) is None:
            results[name] = "not_run"
            continue
        results[name] = "passed" if runner(cmd).returncode == 0 else "failed"
    return results


def main() -> int:
    results = run_checks()
    for name, status in results.items():
        print(f"{name:<10} {status.upper().replace('_', ' ')}")
    return 1 if "failed" in results.values() else 0


if __name__ == "__main__":
    sys.exit(main())
