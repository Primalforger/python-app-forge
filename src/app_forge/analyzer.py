"""Project Analyzer (MOD-08). Read-only: never imports project modules or runs project scripts."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from app_forge.domain.errors import ValidationFailure
from app_forge.projectmeta import FORGE_TOML, read_components, read_forge_toml
from app_forge.security import run_command

SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "dist", "build",
             ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox", ".idea", ".vscode", ".forge"}
MAX_FILES = 20000

FRAMEWORKS = {"pyside6": "pyside6", "pyqt5": "pyqt", "pyqt6": "pyqt", "tkinter": "tkinter", "fastapi": "fastapi",
              "flask": "flask", "django": "django", "starlette": "starlette", "typer": "typer", "click": "click",
              "rich": "rich", "celery": "celery", "apscheduler": "apscheduler", "rq": "rq", "sqlalchemy": "sqlalchemy"}
ARCHETYPE_FROM_FRAMEWORK = {"pyside6": "desktop", "pyqt": "desktop", "tkinter": "desktop", "fastapi": "web",
                            "flask": "web", "django": "web", "starlette": "web", "typer": "cli", "click": "cli",
                            "celery": "service", "apscheduler": "service", "rq": "service"}
LEVEL_NAMES = {1: "App Forge-generated", 2: "Known Python structure", 3: "Conventional third-party",
               4: "Arbitrary / poorly understood"}


def _dep_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[ @]", spec.strip(), maxsplit=1)[0].lower().replace("_", "-")


def walk_files(root: Path):
    count = 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_symlink():
                continue
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.endswith(".egg-info"):
                    stack.append(p)
            else:
                count += 1
                if count > MAX_FILES:
                    return
                yield p


def snapshot_tree(root: Path) -> dict[str, tuple[int, str]]:
    """Path -> (size, sha256) for every file including .git. Used to prove analysis does not mutate."""
    from app_forge.security import sha256_file
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(root).as_posix()] = (p.stat().st_size, sha256_file(p))
    return out


class ProjectAnalyzer:
    def analyze(self, path: Path | str) -> dict:
        root = Path(path).resolve()
        if not root.is_dir():
            raise ValidationFailure(f"Project path {str(path)!r} is not a directory")
        warnings: list[str] = []
        unsupported: list[str] = []
        files = list(walk_files(root))
        rels = [f.relative_to(root).as_posix() for f in files]
        py_files = [r for r in rels if r.endswith(".py")]

        pyproject = None
        if (root / "pyproject.toml").is_file():
            try:
                pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
                warnings.append(f"pyproject.toml could not be parsed: {exc}")
        project = (pyproject or {}).get("project", {})
        poetry = (pyproject or {}).get("tool", {}).get("poetry", {})

        deps: list[str] = list(project.get("dependencies", []))
        if poetry:
            deps += [k for k in poetry.get("dependencies", {}) if k.lower() != "python"]
            unsupported.append("Poetry-managed dependencies: dependency edits must be applied manually")
        for r in rels:
            if re.match(r"^requirements[^/]*\.txt$", r):
                for line in (root / r).read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.split("#")[0].strip()
                    if line and not line.startswith("-"):
                        deps.append(line)
        dep_names = sorted({_dep_name(d) for d in deps if d})
        dep_specs = sorted({d.strip() for d in deps if d and d.strip()})
        lockfiles = [r for r in rels if r in ("poetry.lock", "Pipfile.lock", "uv.lock", "pdm.lock")]
        frameworks = sorted({FRAMEWORKS[n] for n in dep_names if n in FRAMEWORKS})

        scripts = {**project.get("scripts", {}), **project.get("gui-scripts", {})}
        entry_points = [{"name": k, "target": v} for k, v in sorted(scripts.items())]
        for cand in ("manage.py", "main.py", "app.py", "wsgi.py", "asgi.py"):
            if cand in rels:
                entry_points.append({"name": cand, "target": cand})
        entry_points += [{"name": r, "target": r} for r in py_files if r.endswith("__main__.py")]

        packages = sorted({r.split("/")[1] for r in py_files if r.startswith("src/") and r.count("/") >= 2
                           and (root / "src" / r.split("/")[1] / "__init__.py").is_file()})
        layout = "src" if packages else "flat" if any("/" not in r for r in py_files) or py_files else "none"
        if not packages:
            packages = sorted({r.split("/")[0] for r in py_files if "/" in r
                               and not r.startswith(("tests/", "test/", "docs/", "scripts/"))
                               and (root / r.split("/")[0] / "__init__.py").is_file()})

        indicators = sorted({ARCHETYPE_FROM_FRAMEWORK[f] for f in frameworks if f in ARCHETYPE_FROM_FRAMEWORK})
        has_tests = any(r.startswith(("tests/", "test/")) for r in rels) or any(
            re.match(r".*(^|/)test_[^/]*\.py$", r) for r in py_files)
        test_cfg = []
        if "pytest" in str((pyproject or {}).get("tool", {})):
            test_cfg.append("pytest (pyproject)")
        for f in ("pytest.ini", "tox.ini", "setup.cfg", "noxfile.py", "conftest.py"):
            if f in rels:
                test_cfg.append(f)

        git = self._git_state(root)
        licenses = [r for r in rels if re.match(r"^(LICENSE|LICENCE|COPYING)[^/]*$", r, re.I)]
        forge = read_forge_toml(root)
        project_meta = (forge or {}).get("project", {})
        project_archetypes = project_meta.get("archetypes") or (
            [project_meta["archetype"]] if project_meta.get("archetype") else indicators)
        installed = read_components(root)["components"] if (root / ".forge").is_dir() else []

        if "setup.py" in rels and not project:
            unsupported.append("setup.py-only metadata is dynamic and is not evaluated (no code execution)")
        if "manage.py" in rels:
            unsupported.append("Django project: framework-aware integration adapter not available")

        level, reasons = self._classify(forge, pyproject, project, py_files, packages, frameworks, has_tests,
                                        rels)
        ops = {1: ["analyze", "plan-add", "plan-remove", "apply", "recover", "verify"],
               2: ["analyze", "plan-add (new files only)", "apply", "recover", "verify"],
               3: ["analyze", "plan-add (new files only)", "apply", "recover", "verify"],
               4: ["analyze"]}[level]
        if level == 4:
            warnings.append("Insufficient structure recognised; analysis and advice only until an integration "
                            "path is validated.")
        if git["state"] == "dirty":
            warnings.append(f"{len(git['dirty_paths'])} uncommitted change(s); overlapping changes will block a plan.")
        if git["state"] == "none":
            warnings.append("Not a Git repository: recovery relies on Forge checkpoints only.")

        return {
            "path": str(root), "level": level, "level_name": LEVEL_NAMES[level], "confidence_reasons": reasons,
            "name": (forge or {}).get("project", {}).get("name") or project.get("name") or root.name,
            "package": (forge or {}).get("project", {}).get("package") or (packages[0] if packages else None),
            "packages": packages, "layout": layout, "python_requires": project.get("requires-python"),
            "dependencies": dep_names, "dependency_specs": dep_specs, "lockfiles": lockfiles, "frameworks": frameworks,
            "archetype_indicators": indicators, "archetypes": project_archetypes, "entry_points": entry_points,
            "tests": {"present": has_tests, "config": test_cfg},
            "git": git, "licenses": licenses, "forge_project": forge is not None,
            "installed_components": installed, "python_file_count": len(py_files),
            "supported_operations": ops, "unsupported_patterns": unsupported, "warnings": warnings,
        }

    @staticmethod
    def _classify(forge, pyproject, project, py_files, packages, frameworks, has_tests, rels):
        if forge is not None:
            return 1, [f"{FORGE_TOML} present (generated or adopted by App Forge)"]
        if not py_files:
            return 4, ["no Python source files found"]
        reasons = []
        if project.get("name") and packages and (frameworks or has_tests):
            reasons = ["PEP 621 metadata", f"package(s) {packages}", "frameworks/tests recognised"]
            return 2, reasons
        if pyproject or any(r in rels for r in ("setup.py", "setup.cfg")) or any(
                r.startswith("requirements") for r in rels):
            return 3, ["packaging or requirements metadata present", f"{len(py_files)} Python files"]
        return 4, ["Python files present but no packaging metadata"]

    @staticmethod
    def _git_state(root: Path) -> dict:
        if not (root / ".git").exists():
            return {"state": "none", "dirty_paths": []}
        try:
            r = run_command(["git", "--no-optional-locks", "status", "--porcelain", "-uall"], cwd=root, timeout=30)
        except (OSError, Exception):  # git missing or timed out
            return {"state": "unknown", "dirty_paths": []}
        if r.returncode != 0:
            return {"state": "unknown", "dirty_paths": []}
        dirty = []
        for line in r.stdout.splitlines():
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ")[-1]
            dirty.append(path.strip('"'))
        return {"state": "dirty" if dirty else "clean", "dirty_paths": dirty}
