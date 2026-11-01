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
from app_forge.verification import VerificationEngine
from tests.helpers import ForgeTestCase


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



def test_verification_reports_pre_cancelled_check_without_false_pass(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    token = CancellationToken()
    token.cancel()

    result = VerificationEngine().run(tmp_path, checks=("syntax", "tests"), cancel_token=token)

    assert result["overall"] == "cancelled"
    assert result["passed"] == 0
    assert result["complete"] is False
    assert result["evidence"][0]["status"] == "cancelled"


def test_verification_cancellation_interrupts_test_runner(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_slow.py").write_text(
        "import time\nimport unittest\n"
        "class SlowTests(unittest.TestCase):\n"
        "    def test_wait(self):\n"
        "        time.sleep(30)\n",
        encoding="utf-8",
    )
    token = CancellationToken()
    timer = threading.Timer(0.5, token.cancel)
    timer.start()
    try:
        result = VerificationEngine().run(tmp_path, checks=("tests",), timeout=20, cancel_token=token)
    finally:
        timer.join()

    assert result["overall"] == "cancelled"
    assert result["complete"] is False
    assert not any(row["status"] == "passed" for row in result["evidence"])


class CancellationServiceTests(ForgeTestCase):
    def test_service_records_cancelled_verification_operation(self) -> None:
        services = self.services()
        project = self.make_project(services, name="Cancelled Verify")
        token = CancellationToken()
        token.cancel()

        result = services.verify_project(project, cancel_token=token)

        assert result["overall"] == "cancelled"
        history = services.history()
        operation = next(item for item in history if item["kind"] == "verify_project")
        assert operation["status"] == "cancelled"

    def test_apply_cancellation_recovers_files_after_first_mutation(self) -> None:
        services = self.services()
        project = self.make_project(services, name="Cancelled Apply")
        plan = services.plan_add(project, {"forge.forms-validation": "*"})
        services.approve_plan(plan["plan_id"], "test")
        token = CancellationToken()

        def cancel_after_first_apply(event):
            if event.get("stage") == "apply" and event.get("current") == 1:
                token.cancel()

        result = services.apply_plan(plan["plan_id"], verify=False, cancel_token=token,
                                     progress=cancel_after_first_apply)

        assert result["cancelled"] is True
        assert result["recovery"]["complete"] is True
        assert not (project / "src/cancelled_apply/forms.py").exists()

    def test_apply_cancellation_during_verification_recovers_project(self) -> None:
        services = self.services()
        project = self.make_project(services, name="Cancelled Verify Apply")
        plan = services.plan_add(project, {"forge.forms-validation": "*"})
        services.approve_plan(plan["plan_id"], "test")
        token = CancellationToken()

        def cancel_when_tests_start(event):
            if event.get("stage") == "tests":
                token.cancel()

        result = services.apply_plan(plan["plan_id"], cancel_token=token, progress=cancel_when_tests_start)

        assert result["cancelled"] is True
        assert result["verification"]["overall"] == "cancelled"
        assert result["recovery"]["complete"] is True
        assert not (project / "src/cancelled_verify_apply/forms.py").exists()
