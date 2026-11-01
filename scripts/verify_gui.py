"""Run the real-PySide6 GUI tests headlessly and print a clear verdict.

    pip install -e ".[gui]"
    python scripts/verify_gui.py

Exit code 0 = GUI tests ran and passed. 2 = PySide6 missing / nothing ran (nothing was verified). 1 = failures.
The tests run in-process and the process exits via os._exit, so a crash while Qt tears down at interpreter exit
(seen with the offscreen plugin on Windows) cannot turn a passing run into a reported failure.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if importlib.util.find_spec("PySide6") is None:
        print("PySide6 is not installed, so the GUI has NOT been verified.\n"
              'Install it with:  pip install -e ".[gui]"')
        return 2
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    import PySide6
    import app_forge
    print(f"PySide6 {PySide6.__version__}  Python {sys.version.split()[0]}  platform {sys.platform}")
    print(f"app_forge loaded from: {Path(app_forge.__file__).resolve().parent}")
    print("(Messages like 'propagateSizeHints' or 'QFontDatabase: Cannot find font directory' come from the headless\n"
          " 'offscreen' Qt plugin and are harmless. Only test FAIL/ERROR lines matter.)\n")
    import unittest
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromName("tests.test_gui_qt"),
        unittest.defaultTestLoader.loadTestsFromName("tests.test_qt_table"),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    ran = result.testsRun - len(result.skipped)
    if not result.wasSuccessful():
        code, msg = 1, "GUI tests FAILED."
    elif ran == 0:
        code, msg = 2, "No GUI tests actually ran (all skipped): the GUI has NOT been verified."
    else:
        code, msg = 0, f"{ran} GUI tests passed under real Qt (offscreen)."
    print("\nRESULT:", msg)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
