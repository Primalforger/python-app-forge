from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app_forge.packaging import (
    PyInstallerConfig,
    build_pyinstaller,
    pyinstaller_config_from_manifest,
    render_pyinstaller_spec,
    write_pyinstaller_spec,
)


def manifest(**settings):
    return {"packaging": {"pyinstaller": {
        "name": "SampleApp", "entry_point": "src/main.py", **settings,
    }}}


def project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "logo.png").write_bytes(b"png")
    return tmp_path


def test_manifest_parses_defaults_and_optional_settings():
    config = pyinstaller_config_from_manifest(manifest())
    assert config.name == "SampleApp"
    assert config.onefile is True
    assert config.windowed is False
    assert set(config.platforms) == {"linux", "macos", "windows"}
    configured = pyinstaller_config_from_manifest(manifest(
        onefile=False, windowed=True, platforms=["linux"],
        datas=[["assets/logo.png", "assets"]],
        hidden_imports=["sample_app.plugins"],
        collect_submodules=["sample_app.plugins"], excludes=["tkinter"],
    ))
    assert configured.datas == (("assets/logo.png", "assets"),)
    assert configured.windowed is True


@pytest.mark.parametrize("settings", [
    {"name": "../escape"}, {"entry_point": "../outside.py"},
    {"onefile": "yes"}, {"platforms": ["linux", "plan9"]},
    {"datas": [["../secret", "."]]}, {"hidden_imports": ["bad-name"]},
    {"icon": "../icon.ico"}, {"platforms": []},
])
def test_invalid_manifest_settings_fail_closed(settings):
    with pytest.raises(ValueError):
        pyinstaller_config_from_manifest(manifest(**settings))


def test_spec_generation_is_deterministic_and_includes_configuration(tmp_path):
    root = project(tmp_path)
    settings = {
        "onefile": False, "windowed": True, "datas": [["assets/logo.png", "assets"]],
        "hidden_imports": ["sample_app.plugins"], "collect_submodules": ["sample_app.plugins"],
        "excludes": ["tkinter"],
    }
    first = render_pyinstaller_spec(manifest(**settings), root)
    assert first == render_pyinstaller_spec(manifest(**settings), root)
    assert "exclude_binaries=True" in first
    assert "console=False" in first
    assert "collect_submodules('sample_app.plugins')" in first
    assert "assets/logo.png" in first
    assert "tkinter" in first


def test_spec_generation_requires_existing_entry_and_data(tmp_path):
    root = project(tmp_path)
    with pytest.raises(ValueError, match="entry_point"):
        render_pyinstaller_spec(manifest(entry_point="missing.py"), root)
    with pytest.raises(ValueError, match="data source"):
        render_pyinstaller_spec(manifest(datas=[["missing.dat", "."]]), root)


def test_spec_rejects_symlink_escape(tmp_path):
    root = project(tmp_path)
    outside = tmp_path.parent / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    link = root / "src" / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ValueError, match="outside"):
        render_pyinstaller_spec(manifest(entry_point="src/linked.py"), root)


def test_spec_writer_never_overwrites_existing_file(tmp_path):
    root = project(tmp_path)
    output = write_pyinstaller_spec(manifest(), root, "packaging/forge.spec")
    assert output.is_file()
    with pytest.raises(FileExistsError):
        write_pyinstaller_spec(manifest(), root, "packaging/forge.spec")


def test_build_uses_argument_vector_and_reports_result(tmp_path):
    root = project(tmp_path)
    (root / "forge.spec").write_text("# spec", encoding="utf-8")
    completed = type("Completed", (), {
        "returncode": 0, "stdout": "built", "stderr": "",
    })()
    with patch("app_forge.packaging.subprocess.run", return_value=completed) as run:
        result = build_pyinstaller("forge.spec", root, clean=True)
    args, kwargs = run.call_args
    assert args[0][:3] == [sys.executable, "-m", "PyInstaller"]
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == root
    assert "--clean" in args[0]
    assert result["ok"] is True


def test_build_rejects_escape_paths_and_invalid_timeout(tmp_path):
    root = project(tmp_path)
    with pytest.raises(ValueError):
        build_pyinstaller("../outside.spec", root)
    (root / "forge.spec").write_text("# spec", encoding="utf-8")
    with pytest.raises(ValueError, match="timeout"):
        build_pyinstaller("forge.spec", root, timeout=0)
