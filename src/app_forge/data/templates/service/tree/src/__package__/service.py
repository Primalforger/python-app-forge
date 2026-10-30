"""Service entry point with graceful shutdown on SIGINT/SIGTERM."""
from __future__ import annotations

import logging
import signal
import time

from {{package}}.core import Job, Scheduler

log = logging.getLogger("{{package}}")


def heartbeat() -> None:
    log.info("heartbeat")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    scheduler = Scheduler(time.monotonic, time.sleep)
    scheduler.add(Job("heartbeat", heartbeat, interval_s=5.0))
    # forge:anchor jobs
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: scheduler.stop())
    log.info("service started")
    while not scheduler.stopping:
        scheduler.tick()
        time.sleep(0.2)
    log.info("service stopped cleanly")
    return 0
