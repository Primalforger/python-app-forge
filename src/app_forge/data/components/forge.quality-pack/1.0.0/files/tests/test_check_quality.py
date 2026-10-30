import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("check_quality",
                                              Path(__file__).resolve().parent.parent / "scripts" / "check_quality.py")
cq = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cq)


class QualityTests(unittest.TestCase):
    def test_missing_tool_is_not_run_never_passed(self):
        r = cq.run_checks([("x", ["no-such-tool"])], which=lambda _: None)
        self.assertEqual(r, {"x": "not_run"})

    def test_failure_and_pass(self):
        runner = lambda cmd: SimpleNamespace(returncode=1 if cmd[0] == "bad" else 0)
        r = cq.run_checks([("a", ["good"]), ("b", ["bad"])], which=lambda c: "/bin/" + c, runner=runner)
        self.assertEqual(r, {"a": "passed", "b": "failed"})
