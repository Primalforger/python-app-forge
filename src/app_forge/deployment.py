"""Deterministic, side-effect-free deployment artifact generators."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass

_PACKAGE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,62}$")
_ENV = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")

def _quote(value: str) -> str:
    if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
        raise ValueError("systemd values must be single-line text")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

@dataclass(frozen=True)
class DeploymentConfig:
    package: str
    module: str
    service_name: str
    python_version: str = "3.12"
    port: int | None = None
    command: tuple[str, ...] = ()
    working_directory: str = "/opt/app"
    description: str = "Python application service"
    environment: tuple[tuple[str, str], ...] = ()
    stop_timeout_seconds: int = 30

    def __post_init__(self):
        if not isinstance(self.package, str) or not _PACKAGE.fullmatch(self.package):
            raise ValueError("package must be a dotted Python identifier")
        if not isinstance(self.module, str) or not _PACKAGE.fullmatch(self.module):
            raise ValueError("module must be a dotted Python identifier")
        if not isinstance(self.service_name, str) or not _SERVICE.fullmatch(self.service_name):
            raise ValueError("service_name must contain 1-63 safe characters")
        if self.python_version not in {"3.11", "3.12", "3.13", "3.14"}:
            raise ValueError("python_version must be 3.11, 3.12, 3.13 or 3.14")
        if self.port is not None and (isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535):
            raise ValueError("port must be an integer from 1 to 65535")
        if self.command and (not isinstance(self.command, tuple) or any(not isinstance(x, str) or not x or "\0" in x for x in self.command)):
            raise ValueError("command must be a tuple of non-empty argument strings")
        if not isinstance(self.working_directory, str) or not self.working_directory.startswith("/") or any(c in self.working_directory for c in "\r\n\0"):
            raise ValueError("working_directory must be an absolute POSIX path")
        if not isinstance(self.description, str) or not self.description or any(c in self.description for c in "\r\n\0"):
            raise ValueError("description must be non-empty single-line text")
        if isinstance(self.stop_timeout_seconds, bool) or not isinstance(self.stop_timeout_seconds, int) or not 1 <= self.stop_timeout_seconds <= 600:
            raise ValueError("stop_timeout_seconds must be between 1 and 600")
        seen = set()
        for pair in self.environment:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("environment entries must be (KEY, VALUE) tuples")
            key, value = pair
            if not isinstance(key, str) or not _ENV.fullmatch(key) or key in seen:
                raise ValueError("environment keys must be unique uppercase identifiers")
            if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
                raise ValueError("environment values must be single-line strings")
            seen.add(key)

def _argv(c):
    return c.command or ("python", "-m", c.module)

def render_dockerfile(config: DeploymentConfig) -> str:
    cmd = json.dumps(list(_argv(config)), ensure_ascii=True, separators=(",", ":"))
    port = f"\nEXPOSE {config.port}" if config.port is not None else ""
    return (f"FROM python:{config.python_version}-slim\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\n"
            f"WORKDIR {config.working_directory}\n"
            "RUN groupadd --system app && useradd --system --gid app --create-home app\n"
            "COPY --chown=app:app . .\n"
            "RUN python -m pip install --no-cache-dir .\n"
            f"USER app:app{port}\nCMD {cmd}\n")

def render_systemd_unit(config: DeploymentConfig) -> str:
    env = "".join(f"Environment={_quote(k + '=' + v)}\n" for k, v in config.environment)
    return ("[Unit]\n"
            f"Description={config.description}\nWants=network-online.target\nAfter=network-online.target\n\n"
            "[Service]\nType=simple\n"
            f"WorkingDirectory={_quote(config.working_directory)}\n"
            "ExecStart=" + " ".join(_quote(x) for x in _argv(config)) + "\n"
            f"Restart=on-failure\nRestartSec=5s\nTimeoutStopSec={config.stop_timeout_seconds}\n"
            "User=app\nGroup=app\nNoNewPrivileges=true\nPrivateTmp=true\n"
            "ProtectSystem=strict\nProtectHome=true\n"
            f"ReadWritePaths=/var/lib/{config.service_name}\n"
            + env + "\n[Install]\nWantedBy=multi-user.target\n")

def render_windows_service(config: DeploymentConfig) -> dict[str, str]:
    command = repr(list(_argv(config)))
    name = config.service_name
    desc = config.description.replace("'", "''")
    host = f'''"""pywin32 service host for {name}."""
import subprocess
import sys
import servicemanager
import win32event
import win32service
import win32serviceutil

COMMAND = {command}

class GeneratedService(win32serviceutil.ServiceFramework):
    _svc_name_ = {name!r}
    _svc_display_name_ = {desc!r}
    _svc_description_ = {desc!r}

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout={config.stop_timeout_seconds})
            except subprocess.TimeoutExpired:
                self.process.kill()

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("{name} starting")
        argv = [sys.executable, *COMMAND[1:]] if COMMAND and COMMAND[0] == "python" else COMMAND
        self.process = subprocess.Popen(argv)
        while self.process.poll() is None:
            if win32event.WaitForSingleObject(self.stop_event, 1000) == win32event.WAIT_OBJECT_0:
                break
        if self.process.poll() is None:
            self.SvcStop()
        code = self.process.wait()
        if code:
            raise RuntimeError("service process exited with code " + str(code))

if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(GeneratedService)
'''
    install = f'''$ErrorActionPreference = "Stop"
# Run from an elevated PowerShell prompt.
python -m pip install pywin32
python "{name}_service.py" install
python "{name}_service.py" start
'''
    remove = f'''$ErrorActionPreference = "Stop"
# Run from an elevated PowerShell prompt.
python "{name}_service.py" stop
python "{name}_service.py" remove
'''
    return {f"deploy/windows/{name}_service.py": host,
            f"deploy/windows/install_{name}.ps1": install,
            f"deploy/windows/remove_{name}.ps1": remove}

def render_deployment_files(config: DeploymentConfig) -> dict[str, str]:
    """Return deterministic project-relative artifacts for all three platforms."""
    files = {"Dockerfile": render_dockerfile(config),
             f"deploy/systemd/{config.service_name}.service": render_systemd_unit(config)}
    files.update(render_windows_service(config))
    return dict(sorted(files.items()))
