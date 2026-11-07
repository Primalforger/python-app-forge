"""Build and launch the frozen Forge GUI on the current native platform."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_forge.packaging import build_pyinstaller, write_pyinstaller_spec


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    platform = (
        "windows" if sys.platform == "win32"
        else "macos" if sys.platform == "darwin"
        else "linux"
    )
    manifest = {
        "packaging": {
            "pyinstaller": {
                "name": "ForgeDesktop",
                "entry_point": "src/app_forge/gui/app.py",
                "onefile": False,
                "windowed": False,
                "platforms": ["windows", "macos", "linux"],
            }
        }
    }
    spec = write_pyinstaller_spec(manifest, root, "build/packaging/forge-gui-ci.spec")
    result = build_pyinstaller(
        spec.relative_to(root).as_posix(), root, dist_path="dist",
        work_path="build/pyinstaller", clean=True, timeout=1200,
        platforms=[platform],
    )
    if not result["ok"]:
        print(result["stdout"], file=sys.stdout)
        print(result["stderr"], file=sys.stderr)
        return result["returncode"] or 1

    executable = root / "dist" / "ForgeDesktop"
    executable /= "ForgeDesktop.exe" if sys.platform == "win32" else "ForgeDesktop"
    if not executable.is_file():
        print(f"Packaged executable was not created: {executable}", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["FORGE_GUI_SMOKE_TEST"] = "1"
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        launched = subprocess.run(
            [str(executable)], cwd=root, env=environment,
            capture_output=True, text=True, timeout=45, check=False,
        )
    except subprocess.TimeoutExpired:
        print("Packaged GUI did not exit within 45 seconds", file=sys.stderr)
        return 1
    if launched.stdout:
        print(launched.stdout, end="")
    if launched.stderr:
        print(launched.stderr, file=sys.stderr, end="")
    if launched.returncode != 0 or "FORGE_GUI_SMOKE_OK" not in launched.stdout:
        print(f"Packaged GUI smoke test failed (exit {launched.returncode})", file=sys.stderr)
        return launched.returncode or 1
    print(f"Packaged Forge GUI built and launched successfully on {platform}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
