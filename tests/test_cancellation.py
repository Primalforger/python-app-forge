from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app_forge.cancellation import CancellationToken
from app_forge.domain.errors import OperationCancelled
from app_forge.security import run_command


def test_cancelled_token_prevents_process_start(tmp_path: Path) -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        run_command([sys.executable, "-c", "raise SystemExit(9)"], cwd=tmp_path, cancel_token=token)


def test_cancellation_terminates_and_reaps_subprocess(tmp_path: Path) -> None:
    token = CancellationToken()
    timer = threading.Timer(0.2, token.cancel)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(OperationCancelled):
            run_command([sys.executable, "-c", "import time; time.sleep(30)"],
                        cwd=tmp_path, timeout=10, cancel_token=token, poll_interval=0.02)
    finally:
        timer.join()
    assert time.monotonic() - started < 5


def test_run_command_preserves_completed_process_contract(tmp_path: Path) -> None:
    result = run_command([sys.executable, "-c", "print('ok')"], cwd=tmp_path)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
