"""Verification Engine (MOD-10): runs checks and produces machine-readable evidence.

A check that cannot run is recorded as ``not_run`` with the reason; it is never reported as passed.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import tomllib
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from app_forge.analyzer import walk_files
from app_forge.cancellation import CancellationToken, ProgressCallback
from app_forge.domain.errors import OperationCancelled
from app_forge.observability import utcnow
from app_forge.security import redact, run_command, safe_environ

ALL_CHECKS = ("syntax", "tests", "ruff", "mypy", "pip-audit")


def _tail(text: str, n: int = 1500) -> str:
    return redact(text[-n:])


class VerificationEngine:
    def run(self, project: Path | str, checks: tuple[str, ...] = ("syntax", "tests"),
            timeout: float = 600, *, cancel_token: CancellationToken | None = None,
            progress: ProgressCallback | None = None) -> dict:
        root = Path(project).resolve()
        run_id = "run-" + uuid.uuid4().hex[:10]
        rows: list[dict] = []

        def add(check_id, status, detail="", duration=0.0):
            rows.append({"run_id": run_id, "subject": str(root), "check_id": check_id, "status": status,
                         "detail": detail, "duration_s": round(duration, 3), "recorded_at": utcnow()})

        cancelled = False
        for index, check in enumerate(checks, 1):
            t0 = time.monotonic()
            if progress:
                progress({"stage": check, "message": f"Starting {check}", "current": index, "total": len(checks)})
            try:
                if cancel_token:
                    cancel_token.raise_if_cancelled()
                if check == "syntax":
                    self._syntax(root, add, t0, cancel_token, progress)
                elif check == "tests":
                    self._tests(root, add, timeout, cancel_token, progress)
                elif check in ("ruff", "mypy", "pip-audit"):
                    self._tool(root, check, add, timeout, cancel_token, progress)
                else:
                    add(check, "not_run", "unknown check")
                if cancel_token:
                    cancel_token.raise_if_cancelled()
            except OperationCancelled:
                add(check, "cancelled", "cancelled by user", time.monotonic() - t0)
                cancelled = True
                break
        failed = [r for r in rows if r["status"] == "failed"]
        passed = [r for r in rows if r["status"] == "passed"]
        not_run = [r["check_id"] for r in rows if r["status"] == "not_run"]
        # "passed" is only claimed when every requested check actually ran and passed
        overall = ("cancelled" if cancelled else
                   "failed" if failed else "not_run" if not passed else "incomplete" if not_run else "passed")
        return {"run_id": run_id, "subject": str(root), "overall": overall, "passed": len(passed),
                "failed": len(failed), "not_run": not_run, "complete": not not_run and not cancelled, "evidence": rows}

    # -- individual checks ------------------------------------------------------------------
    def _syntax(self, root: Path, add, t0: float, cancel_token=None, progress=None) -> None:
        bad = []
        n = 0
        seen = 0
        excludes = self._excludes(root)
        for f in walk_files(root):
            if cancel_token:
                cancel_token.raise_if_cancelled()
            seen += 1
            if progress and seen % 25 == 0:
                progress({"stage": "syntax", "message": f"Scanning {f.relative_to(root).as_posix()}",
                          "current": seen, "total": None})
            if f.suffix == ".py" and not any(f.relative_to(root).as_posix().startswith(x) for x in excludes):
                n += 1
                try:
                    compile(f.read_text(encoding="utf-8"), str(f), "exec", dont_inherit=True)  # no execution
                except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
                    bad.append(f"{f.relative_to(root).as_posix()}: {exc}")
        if bad:
            add("syntax", "failed", "; ".join(bad)[:1500], time.monotonic() - t0)
        elif n == 0:
            add("syntax", "not_run", "no Python files", time.monotonic() - t0)
        else:
            add("syntax", "passed", f"{n} files compiled", time.monotonic() - t0)

    @staticmethod
    def project_python(root: Path) -> tuple[str, str]:
        """The project's own interpreter if it has a virtualenv (.venv/venv), else Forge's. Returns (path, source)."""
        for name in (".venv", "venv"):
            for rel in ("bin/python", "Scripts/python.exe"):
                cand = root / name / rel
                if cand.is_file():
                    return str(cand), f"{name} virtual environment"
        return sys.executable, "the interpreter running Forge"

    @staticmethod
    def _has_module(python: str, module: str, env: dict, cancel_token=None) -> bool:
        try:
            r = run_command([python, "-c", f"import {module}"], cwd=Path.cwd(), timeout=60, env=env,
                            inherit_env=False, cancel_token=cancel_token)
            return r.returncode == 0
        except OperationCancelled:
            raise
        except Exception:
            return False

    @staticmethod
    def _verify_config(root: Path) -> dict:
        try:
            data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
            return data.get("tool", {}).get("forge", {}).get("verify", {})
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    @staticmethod
    def _own_modules(root: Path) -> set[str]:
        """Top-level names that belong to the project itself (a missing one is a real failure, not a missing dep)."""
        names = {"tests", "test"}
        for base in (root, root / "src"):
            if base.is_dir():
                for p in base.iterdir():
                    if p.is_dir() and (p / "__init__.py").is_file() or p.suffix == ".py":
                        names.add(p.stem if p.suffix == ".py" else p.name)
        return names

    @staticmethod
    def _excludes(root: Path) -> list[str]:
        """Explicit path prefixes from [tool.forge.verify] exclude in pyproject.toml (e.g. template payloads)."""
        return [str(x) for x in VerificationEngine._verify_config(root).get("exclude", [])]

    def _tests(self, root: Path, add, timeout: float, cancel_token=None, progress=None) -> None:
        if not (root / "tests").is_dir() and not list(root.glob("test_*.py")):
            add("tests", "not_run", "no tests directory found")
            return
        cfg = self._verify_config(root)
        env = {**safe_environ(tuple(cfg.get("env_passthrough", []))),
               "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)]), "PYTHONDONTWRITEBYTECODE": "1"}
        python, source = self.project_python(root)
        t0 = time.monotonic()
        try:
            if self._has_module(python, "pytest", env, cancel_token):
                with tempfile.TemporaryDirectory() as tmp:
                    xml = Path(tmp) / "junit.xml"
                    proc = run_command([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"],
                                       cwd=root, timeout=timeout, env=env, inherit_env=False, cancel_token=cancel_token)
                    cases = self._parse_junit(xml, root) if xml.is_file() else []
                runner = "pytest"
            else:
                has_init = (root / "tests" / "__init__.py").is_file()
                cmd = [python, "-m", "unittest", "discover", "-s", "tests", "-v"] + (["-t", "."] if has_init else [])
                proc = run_command(cmd, cwd=root, timeout=timeout, env=env, inherit_env=False, cancel_token=cancel_token)
                cases = self._parse_unittest(proc.stderr + proc.stdout, "" if has_init else "tests/")
                runner = "unittest"
        except OperationCancelled:
            raise
        except Exception as exc:  # timeouts, missing interpreter
            add("tests", "failed", _tail(f"{type(exc).__name__}: {exc}"), time.monotonic() - t0)
            return
        dur = time.monotonic() - t0
        output = proc.stdout + proc.stderr
        missing = self._missing_dependencies(output, root)
        if missing and (proc.returncode != 0 or not cases):
            # The environment cannot run these tests: that is "blocked", never a pass and not a code failure.
            detail = (f"blocked: missing dependencies {sorted(missing)} in {source} ({python}). "
                      "Install them there (or create a .venv in the project) and re-run.")
            add("tests", "not_run", detail, dur)
            for f in sorted((root / "tests").glob("test_*.py")) if (root / "tests").is_dir() else []:
                add(f"tests/{f.name}", "not_run", detail)
            return
        for cid, status in cases:
            add(cid, status)
        if not cases:
            add("tests", "failed" if proc.returncode not in (0, 5) else "not_run",
                _tail(output) or "no tests collected", dur)
            return
        failed = sum(1 for _, s in cases if s == "failed")
        add(f"tests:{runner}", "failed" if failed or proc.returncode not in (0,) else "passed",
            f"{len(cases)} tests, {failed} failed (interpreter: {source})" + ("" if not failed else "\n" + _tail(output)),
            dur)

    def _missing_dependencies(self, output: str, root: Path) -> set[str]:
        own = self._own_modules(root)
        found = {m.split(".")[0] for m in re.findall(r"No module named '([\w.]+)'", output)}
        return {m for m in found if m not in own}

    @staticmethod
    def _parse_junit(xml: Path, root: Path) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        try:
            tree = ET.parse(xml)
        except ET.ParseError:
            return out
        for tc in tree.iter("testcase"):
            cls, name = tc.get("classname", ""), tc.get("name", "")
            parts = cls.split(".")
            idx = next((i for i, p in enumerate(parts) if p[:1].isupper()), len(parts))
            module = "/".join(parts[:idx]) + ".py"
            cid = module + ("::" + "::".join(parts[idx:]) if parts[idx:] else "") + "::" + name
            bad = tc.find("failure") is not None or tc.find("error") is not None
            skipped = tc.find("skipped") is not None
            if not skipped:
                out.append((cid, "failed" if bad else "passed"))
        return out

    @staticmethod
    def _parse_unittest(text: str, prefix: str = "") -> list[tuple[str, str]]:
        out = []
        for m in re.finditer(r"^(\w+) \(([\w.]+)\)(?:\n[^\n]*)? \.\.\. (ok|FAIL|ERROR|skipped.*|expected failure)$",
                             text, re.M):
            if "_FailedTest" in m.group(2):
                continue  # reported by the import-failure pass below
            dotted = m.group(2).split(".")
            idx = next((i for i, p in enumerate(dotted) if p[:1].isupper()), len(dotted) - 1)
            cid = prefix + ("/".join(dotted[:idx]) + ".py::" + "::".join(dotted[idx:-1] + [m.group(1)])
                            if dotted[idx:-1] else "/".join(dotted[:-1]) + ".py::" + m.group(1))
            status = m.group(3)
            if status.startswith("skipped"):
                continue
            out.append((cid, "passed" if status in ("ok", "expected failure") else "failed"))
        # import failures show as "unittest.loader._FailedTest" lines
        for m in re.finditer(r"^(\w*_FailedTest\w*|\w+) \(unittest\.loader\._FailedTest\.(\w+)\) \.\.\. (ERROR|FAIL)$",
                             text, re.M):
            out.append((f"tests/{m.group(2)}.py::import", "failed"))  # module failed to import
        return out

    @staticmethod
    def _pip_audit_commands(root: Path) -> tuple[list[tuple[list[str], str]] | None, str]:
        """Build independent audit invocations for this project; never audit Forge's environment."""
        lockfiles = sorted(root.glob("pylock*.toml"))
        if lockfiles:
            return [(["pip-audit", "--locked", str(root)], "project lockfile(s): " + ", ".join(
                p.name for p in lockfiles
            ))], ""
        if (root / "pyproject.toml").is_file():
            return [(["pip-audit", str(root)], "project metadata: pyproject.toml")], ""

        requirements = sorted(root.glob("requirements*.txt"))
        requirements.extend(sorted((root / "requirements").glob("*.txt"))
                            if (root / "requirements").is_dir() else [])
        files = list(dict.fromkeys(p for p in requirements if p.is_file()))
        if files:
            # Each file can define a distinct environment (runtime, dev, platform, etc.).
            # Audit independently so incompatible pins across files are not conflated.
            return [
                (["pip-audit", "--requirement", path.relative_to(root).as_posix()],
                 f"requirements file: {path.relative_to(root).as_posix()}")
                for path in files
            ], ""
        return None, "no supported dependency manifest found (pylock*.toml, pyproject.toml, or requirements*.txt)"

    def _tool(self, root: Path, tool: str, add, timeout: float, cancel_token=None, progress=None) -> None:
        executable = shutil.which(tool)
        if executable is None:
            add(tool, "not_run", f"{tool} is not installed")
            return
        commands: list[tuple[list[str], str]]
        if tool == "ruff":
            commands = [([executable, "check", "."], "")]
        elif tool == "mypy":
            commands = [([executable, "src"] if (root / "src").is_dir() else [executable, "."], "")]
        elif tool == "pip-audit":
            audit_commands, missing_detail = self._pip_audit_commands(root)
            if audit_commands is None:
                add(tool, "not_run", missing_detail)
                return
            commands = [([executable if i == 0 else arg for i, arg in enumerate(cmd)], label)
                        for cmd, label in audit_commands]
        else:
            add(tool, "not_run", f"unsupported tool: {tool}")
            return

        t0 = time.monotonic()
        outputs = []
        failed = False
        for cmd, label in commands:
            try:
                proc = run_command(cmd, cwd=root, timeout=timeout, env=safe_environ(), inherit_env=False,
                                   cancel_token=cancel_token)
                failed = failed or proc.returncode != 0
                output = _tail(proc.stdout + proc.stderr)
            except OperationCancelled:
                raise
            except Exception as exc:
                failed = True
                output = _tail(f"{type(exc).__name__}: {exc}")
            outputs.append(f"{label}: {output}".strip(": ") if label else output)
        detail = _tail("\n".join(part for part in outputs if part))
        add(tool, "failed" if failed else "passed", detail, time.monotonic() - t0)


def compare_evidence(before: list[dict], after: list[dict]) -> dict:
    """Compare two evidence runs check-by-check. Regressions are new failures (including newly failing checks)."""
    a = {e["check_id"]: e["status"] for e in before}
    b = {e["check_id"]: e["status"] for e in after}
    regressions = sorted(k for k, v in b.items() if v == "failed" and a.get(k) != "failed")
    fixed = sorted(k for k, v in a.items() if v == "failed" and b.get(k) == "passed")
    return {"regressions": regressions, "fixed": fixed,
            "added": sorted(k for k in b if k not in a), "removed": sorted(k for k in a if k not in b),
            "status_changes": sorted(f"{k}: {a[k]} -> {b[k]}" for k in a if k in b and a[k] != b[k]),
            "unchanged": sum(1 for k in a if k in b and a[k] == b[k]),
            "verdict": "regression" if regressions else "no-regression"}
