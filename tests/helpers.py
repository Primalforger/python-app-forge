import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app_forge.catalog.registry import seal_component
from app_forge.services import ForgeServices
from app_forge.settings import ForgeSettings

ALL = ("desktop", "web", "cli", "service")


class ForgeTestCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name).resolve()
        self.home = self.tmp / "home"

    def services(self, builtin=True, **kw) -> ForgeServices:
        from app_forge.catalog.registry import BUILTIN_COMPONENTS
        return ForgeServices(ForgeSettings(home=self.home), builtin_root=BUILTIN_COMPONENTS if builtin else None, **kw)

    def make_project(self, services=None, archetype="cli", name="Demo App", components=(), where=None):
        s = services or self.services()
        out = where or self.tmp / "proj"
        s.create_project(archetype, {"name": name}, out, components=list(components))
        return out

    def custom_component(self, cid, version="1.0.0", *, requires=None, archetypes=ALL, files=None,
                         python_packages=(), provides=(), requires_if=(), python=">=3.11", root=None,
                         trust="trusted", seal=True, patches=()):
        root = root or (self.home / "catalog")
        vdir = root / cid / version
        files = files if files is not None else {f"src/{cid.split('.')[-1].replace('-', '_')}.py": "VALUE = 1\n"}
        for name, text in files.items():
            p = vdir / "files" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        arr = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
        t = f'''schema_version = 1
[component]
id = "{cid}"
name = "{cid}"
version = "{version}"
summary = "test component"
category = "tooling"
[ownership]
publisher = "tests"
[licensing]
license = "MIT"
[compatibility]
python = "{python}"
platforms = ["windows", "linux", "macos"]
archetypes = {arr(archetypes)}
[dependencies]
python_packages = {arr(python_packages)}
[dependencies.components]
'''
        for k, v in (requires or {}).items():
            t += f'"{k}" = "{v}"\n'
        t += f'''[interfaces]
provides = {arr(provides)}
requires = {arr(requires_if)}
'''
        for name in files:
            dest = name.replace("src/", "src/{{package}}/", 1) if name.startswith("src/") else name
            t += f'[[integration.files]]\nsrc = "files/{name}"\ndest = "{dest}"\n'
        for ptxt in patches:
            t += ptxt + "\n"
        t += f'''[security]
trust = "{trust}"
permissions = ["filesystem.project"]
network = false
[provenance]
source = "tests"
digest = "sha256:{'0' * 64}"
[support]
status = "stable"
'''
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "component.toml").write_text(t, encoding="utf-8")
        if seal:
            seal_component(vdir)
        return vdir

    def git_init(self, path: Path):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "init"]):
            subprocess.run(cmd, cwd=path, check=True, env=env, capture_output=True)
