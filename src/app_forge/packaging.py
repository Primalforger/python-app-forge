"""Validated, manifest-driven PyInstaller spec generation and native builds."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_PLATFORMS = frozenset({"linux", "macos", "windows"})


@dataclass(frozen=True)
class PyInstallerConfig:
    """A validated PyInstaller application definition."""

    name: str
    entry_point: str
    onefile: bool = True
    windowed: bool = False
    platforms: tuple[str, ...] = ("linux", "macos", "windows")
    datas: tuple[tuple[str, str], ...] = ()
    hidden_imports: tuple[str, ...] = ()
    collect_submodules: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    icon: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise ValueError("packaging name must be a safe application identifier")
        _relative_path(self.entry_point, "entry_point")
        if not isinstance(self.onefile, bool) or not isinstance(self.windowed, bool):
            raise ValueError("onefile and windowed must be booleans")
        if not isinstance(self.platforms, tuple) or not self.platforms:
            raise ValueError("platforms must be a non-empty tuple")
        if any(not isinstance(item, str) or item not in _PLATFORMS for item in self.platforms):
            raise ValueError("platforms may contain only linux, macos and windows")
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("platforms must not contain duplicates")
        if not isinstance(self.datas, tuple):
            raise ValueError("datas must be a tuple of (source, destination) pairs")
        for pair in self.datas:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("each data entry must be a (source, destination) pair")
            _relative_path(pair[0], "data source")
            _relative_path(pair[1], "data destination", allow_dot=True)
        for field, values in (
            ("hidden_imports", self.hidden_imports),
            ("collect_submodules", self.collect_submodules),
            ("excludes", self.excludes),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not _MODULE.fullmatch(value) for value in values
            ):
                raise ValueError(f"{field} must contain valid dotted Python module names")
            if len(set(values)) != len(values):
                raise ValueError(f"{field} must not contain duplicates")
        if self.icon is not None:
            _relative_path(self.icon, "icon")
            suffix = Path(self.icon).suffix.lower()
            if suffix not in {".ico", ".icns", ".png"}:
                raise ValueError("icon must be an .ico, .icns or .png file")


def _relative_path(value: str, label: str, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise ValueError(f"{label} must be a non-empty relative POSIX path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        if allow_dot and value == ".":
            return value
        raise ValueError(f"{label} must stay inside the project and may not contain dot segments")
    if path.drive or ":" in value:
        raise ValueError(f"{label} must not contain a drive or alternate data stream")
    return value


def pyinstaller_config_from_manifest(manifest: Mapping[str, Any]) -> PyInstallerConfig:
    """Read [packaging.pyinstaller] from a parsed TOML manifest."""
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be a mapping")
    packaging = manifest.get("packaging", {})
    if not isinstance(packaging, Mapping):
        raise ValueError("packaging must be a table")
    raw = packaging.get("pyinstaller")
    if not isinstance(raw, Mapping):
        raise ValueError("manifest requires a [packaging.pyinstaller] table")
    name = raw.get("name")
    entry_point = raw.get("entry_point")
    if not isinstance(name, str) or not isinstance(entry_point, str):
        raise ValueError("packaging.pyinstaller requires string name and entry_point")
    platforms = raw.get("platforms", ["linux", "macos", "windows"])
    datas = raw.get("datas", [])
    if not isinstance(platforms, list) or not isinstance(datas, list):
        raise ValueError("platforms and datas must be arrays")
    parsed_datas: list[tuple[str, str]] = []
    for index, item in enumerate(datas):
        if not isinstance(item, list) or len(item) != 2 or any(not isinstance(v, str) for v in item):
            raise ValueError(f"datas[{index}] must be a two-string array [source, destination]")
        parsed_datas.append((item[0], item[1]))
    for key in ("hidden_imports", "collect_submodules", "excludes"):
        if not isinstance(raw.get(key, []), list):
            raise ValueError(f"{key} must be an array")
    icon = raw.get("icon")
    if icon is not None and not isinstance(icon, str):
        raise ValueError("icon must be a string path")
    return PyInstallerConfig(
        name=name,
        entry_point=entry_point,
        onefile=raw.get("onefile", True),
        windowed=raw.get("windowed", False),
        platforms=tuple(platforms),
        datas=tuple(parsed_datas),
        hidden_imports=tuple(raw.get("hidden_imports", [])),
        collect_submodules=tuple(raw.get("collect_submodules", [])),
        excludes=tuple(raw.get("excludes", [])),
        icon=icon,
    )


def _project_file(root: Path, relative: str, label: str) -> Path:
    base = root.resolve()
    candidate = base.joinpath(*relative.split("/"))
    # Resolve existing symlinks and parent segments before accepting any input.
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(base):
        raise ValueError(f"{label} resolves outside the project directory")
    if candidate.exists() and candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    return resolved


def _py(value: str) -> str:
    """Python string literal used in generated spec source."""
    return repr(value)


def render_pyinstaller_spec(manifest: Mapping[str, Any], project_root: str | Path = ".") -> str:
    """Render a deterministic PyInstaller spec after validating all referenced files."""
    config = pyinstaller_config_from_manifest(manifest)
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")
    entry = _project_file(root, config.entry_point, "entry_point")
    if not entry.is_file():
        raise ValueError(f"entry_point does not exist: {config.entry_point}")
    for source, _destination in config.datas:
        if not _project_file(root, source, "data source").exists():
            raise ValueError(f"data source does not exist: {source}")
    if config.icon:
        icon = _project_file(root, config.icon, "icon")
        if not icon.is_file():
            raise ValueError(f"icon file does not exist: {config.icon}")
        if sys.platform == "win32" and icon.suffix.lower() != ".ico":
            raise ValueError("Windows builds require an .ico icon")
        if sys.platform == "darwin" and icon.suffix.lower() not in {".icns", ".png"}:
            raise ValueError("macOS builds require an .icns or .png icon")
    datas = "[" + ", ".join(f"({_py(str(_project_file(root, src, 'data source')))}, {_py(dst)})"
                              for src, dst in config.datas) + "]"
    hidden = repr(list(config.hidden_imports))
    excludes = repr(list(config.excludes))
    collect_lines = [
        f"hiddenimports.extend(collect_submodules({_py(module)}))"
        for module in config.collect_submodules
    ]
    icon_value = str(_project_file(root, config.icon, "icon")) if config.icon else None
    common = (
        "# -*- mode: python ; coding: utf-8 -*-\n"
        "import sys\nfrom PyInstaller.utils.hooks import collect_submodules\n\n"
        f"hiddenimports = {hidden}\n"
        + ("\n".join(collect_lines) + "\n" if collect_lines else "")
        + "a = Analysis(\n"
        f"    [{_py(str(entry))}],\n"
        f"    pathex=[{_py(str(root))}],\n"
        "    binaries=[],\n"
        f"    datas={datas},\n"
        "    hiddenimports=hiddenimports,\n"
        "    hookspath=[],\n"
        "    hooksconfig={},\n"
        "    runtime_hooks=[],\n"
        f"    excludes={excludes},\n"
        "    noarchive=False,\n"
        ")\n"
        "pyz = PYZ(a.pure)\n"
    )
    icon_arg = f", icon={_py(icon_value)}" if icon_value else ""
    if config.onefile:
        rendered = common + (
            "exe = EXE(\n"
            "    pyz, a.scripts, a.binaries, a.datas, [],\n"
            f"    name={_py(config.name)}, debug=False, bootloader_ignore_signals=False,\n"
            f"    strip=False, upx=True, console={not config.windowed}, disable_windowed_traceback=False,"
            f"{icon_arg}\n"
            ")\n"
        )
        if config.windowed:
            bundle_icon = f", icon={_py(icon_value)}" if icon_value else ""
            rendered += (
                "if sys.platform == 'darwin':\n"
                f"    app = BUNDLE(exe, name={_py(config.name + '.app')}{bundle_icon})\n"
            )
        return rendered
    rendered = common + (
        "exe = EXE(\n"
        "    pyz, a.scripts, [], exclude_binaries=True,\n"
        f"    name={_py(config.name)}, debug=False, bootloader_ignore_signals=False,\n"
        f"    strip=False, upx=True, console={not config.windowed}, disable_windowed_traceback=False,"
        f"{icon_arg}\n"
        ")\n"
        "coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="
        f"{_py(config.name)})\n"
    )
    if config.windowed:
        bundle_icon = f", icon={_py(icon_value)}" if icon_value else ""
        rendered += (
            "if sys.platform == 'darwin':\n"
            f"    app = BUNDLE(coll, name={_py(config.name + '.app')}{bundle_icon})\n"
        )
    return rendered


def write_pyinstaller_spec(
    manifest: Mapping[str, Any], project_root: str | Path = ".", output: str | Path = "forge.spec"
) -> Path:
    """Create a spec file exclusively; never overwrite an existing user file."""
    root = Path(project_root).resolve()
    rendered = render_pyinstaller_spec(manifest, root)
    destination = _project_file(root, _relative_path(str(output), "output"), "output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(destination, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)
    return destination


def build_pyinstaller(
    spec_path: str | Path,
    project_root: str | Path = ".",
    *,
    dist_path: str | Path = "dist",
    work_path: str | Path = "build/pyinstaller",
    clean: bool = False,
    timeout: int = 1800,
    platforms: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run the installed PyInstaller against a project-local spec without a shell."""
    root = Path(project_root).resolve()
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 7200:
        raise ValueError("timeout must be an integer from 1 to 7200 seconds")
    paths = []
    for value, label in ((str(spec_path), "spec_path"), (str(dist_path), "dist_path"),
                         (str(work_path), "work_path")):
        relative = _relative_path(value, label)
        paths.append(_project_file(root, relative, label))
    spec, dist, work = paths
    if not spec.is_file() or spec.suffix.lower() != ".spec":
        raise ValueError("spec_path must name an existing .spec file inside the project")
    if not isinstance(clean, bool):
        raise ValueError("clean must be a boolean")
    if platforms is not None:
        if not platforms or any(item not in _PLATFORMS for item in platforms):
            raise ValueError("platforms must be a non-empty subset of linux, macos and windows")
        current = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
        if current not in platforms:
            raise ValueError(f"manifest does not declare support for the current platform: {current}")
    command = [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm",
               "--distpath", str(dist), "--workpath", str(work)]
    if clean:
        command.append("--clean")
    try:
        result = subprocess.run(
            command, cwd=root, shell=False, check=False, capture_output=True,
            text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"PyInstaller could not complete: {type(exc).__name__}") from None
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": command,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
        "dist_path": str(dist),
    }
