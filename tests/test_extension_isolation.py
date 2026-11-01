import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_forge.domain.errors import SecurityBlock
from app_forge.extensions import _sandbox_command


class ExtensionSandboxTests(unittest.TestCase):
    def test_linux_profile_disables_network_and_does_not_mount_home(self):
        if sys.platform != "linux":
            self.skipTest("bubblewrap profile is Linux-specific")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with patch("app_forge.extensions.shutil.which", return_value="/usr/bin/bwrap"):
                command = _sandbox_command(
                    sys.executable,
                    python_prefix=Path(sys.prefix),
                    package_root=Path(__file__).resolve().parents[1] / "src",
                    allowed_paths=(workspace,),
                )
        self.assertIn("--unshare-net", command)
        self.assertIn("--unshare-all", command)
        self.assertIn("--bind", command)
        self.assertIn(str(workspace), command)
        self.assertNotIn(str(Path.home().resolve()), command)


    def test_bubblewrap_cannot_read_sibling_host_file(self):
        if sys.platform != "linux":
            self.skipTest("bubblewrap is Linux-specific")
        import shutil
        if not shutil.which("bwrap"):
            self.skipTest("bubblewrap is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            secret = root / "host-secret.txt"
            secret.write_text("host-only-secret", encoding="utf-8")
            command = _sandbox_command(
                sys.executable, python_prefix=Path(sys.prefix),
                package_root=Path(__file__).resolve().parents[1] / "src",
                allowed_paths=(workspace,),
            )
            command = command[:-4] + [
                "--", sys.executable, "-c",
                "from pathlib import Path; import sys; "
                "assert not Path(sys.argv[1]).exists(); "
                "Path(sys.argv[2]).write_text('sandbox-write')",
                str(secret), str(workspace / "result.txt"),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((workspace / "result.txt").read_text(encoding="utf-8"), "sandbox-write")

    def test_missing_bubblewrap_fails_closed(self):
        with patch("app_forge.extensions.sys.platform", "linux"), patch(
            "app_forge.extensions.shutil.which", return_value=None
        ):
            with self.assertRaisesRegex(SecurityBlock, "refusing unsandboxed fallback"):
                _sandbox_command(
                    sys.executable, python_prefix=Path(sys.prefix),
                    package_root=Path(__file__).resolve().parents[1] / "src",
                    allowed_paths=(),
                )

    def test_non_linux_fails_closed(self):
        with patch("app_forge.extensions.sys.platform", "darwin"):
            with self.assertRaisesRegex(SecurityBlock, "only on Linux"):
                _sandbox_command(
                    sys.executable, python_prefix=Path(sys.prefix),
                    package_root=Path(__file__).resolve().parents[1] / "src",
                    allowed_paths=(),
                )
