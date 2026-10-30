"""Scheduling, retry and health logic. Clock and sleep are injectable for deterministic tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Job:
    name: str
    func: Callable[[], None]
    interval_s: float
    max_retries: int = 3
    next_run: float = 0.0
    failures: int = 0
    last_error: str = ""


@dataclass
class Health:
    status: str = "starting"
    runs: int = 0
    failed_runs: int = 0
    jobs: dict = field(default_factory=dict)


def run_with_retries(func: Callable[[], None], retries: int, sleep: Callable[[float], None],
                     base_delay: float = 0.5) -> tuple[bool, str]:
    """Run func; retry with exponential backoff. Returns (succeeded, last_error)."""
    error = ""
    for attempt in range(retries + 1):
        try:
            func()
            return True, ""
        except Exception as exc:  # noqa: BLE001 - jobs are untrusted boundaries
            error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                sleep(base_delay * (2 ** attempt))
    return False, error


class Scheduler:
    def __init__(self, clock: Callable[[], float], sleep: Callable[[float], None]):
        self._clock, self._sleep = clock, sleep
        self.jobs: list[Job] = []
        self.health = Health()
        self._stopping = False

    def add(self, job: Job) -> None:
        self.jobs.append(job)

    def stop(self) -> None:
        self._stopping = True
        self.health.status = "stopping"

    @property
    def stopping(self) -> bool:
        return self._stopping

    def tick(self) -> int:
        """Run every job that is due. Returns how many ran. Never raises because of a job."""
        self.health.status = "running" if not self._stopping else "stopping"
        ran = 0
        for job in self.jobs:
            if self._stopping:
                break
            now = self._clock()
            if now < job.next_run:
                continue
            ok, err = run_with_retries(job.func, job.max_retries, self._sleep)
            job.next_run = now + job.interval_s
            ran += 1
            self.health.runs += 1
            if not ok:
                job.failures += 1
                job.last_error = err
                self.health.failed_runs += 1
            self.health.jobs[job.name] = {"ok": ok, "failures": job.failures, "last_error": job.last_error}
        return ran
