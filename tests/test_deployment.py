from __future__ import annotations
import pytest
from app_forge.deployment import DeploymentConfig, render_deployment_files, render_dockerfile, render_systemd_unit, render_windows_service

def cfg(**kw):
    values = {"package": "example_app", "module": "example_app.service", "service_name": "example-app"}
    values.update(kw)
    return DeploymentConfig(**values)

def test_dockerfile_non_root_json_command_and_port():
    text = render_dockerfile(cfg(port=8080))
    assert "FROM python:3.12-slim" in text
    assert "USER app:app" in text and "EXPOSE 8080" in text
    assert 'CMD ["python","-m","example_app.service"]' in text

def test_systemd_hardening_and_environment():
    text = render_systemd_unit(cfg(environment=(("APP_MODE", "prod"),)))
    assert "NoNewPrivileges=true" in text and "ProtectSystem=strict" in text
    assert 'Environment="APP_MODE=prod"' in text
    assert 'ExecStart="python" "-m" "example_app.service"' in text

def test_systemd_quotes_percent_and_rejects_newlines():
    assert "100%%" in render_systemd_unit(cfg(description="worker 100%"))
    with pytest.raises(ValueError):
        cfg(description="bad\nExecStart=/bin/sh")

def test_windows_service_host_and_scripts():
    files = render_windows_service(cfg())
    assert "ServiceFramework" in files["deploy/windows/example-app_service.py"]
    assert "subprocess.Popen" in files["deploy/windows/example-app_service.py"]
    assert "HandleCommandLine" in files["deploy/windows/example-app_service.py"]
    assert "pip install pywin32" in files["deploy/windows/install_example-app.ps1"]
    assert " remove" in files["deploy/windows/remove_example-app.ps1"]

def test_all_artifacts_are_deterministic():
    files = render_deployment_files(cfg())
    assert list(files) == sorted(files)
    assert len(files) == 5
    assert render_deployment_files(cfg()) == files

@pytest.mark.parametrize("kw", [
    {"package": "../escape"}, {"module": "bad-module"}, {"service_name": "../root"},
    {"python_version": "3.10"}, {"port": 0}, {"port": True},
    {"working_directory": "relative"}, {"stop_timeout_seconds": 0},
    {"environment": (("bad-key", "value"),)}, {"environment": (("TOKEN", "a\nb"),)},
])
def test_invalid_configuration_rejected(kw):
    with pytest.raises(ValueError):
        cfg(**kw)

def test_command_is_argument_vector():
    config = cfg(command=("python", "-m", "example_app.worker", "--label", "hello world"))
    assert '"hello world"' in render_dockerfile(config)
    assert '"hello world"' in render_systemd_unit(config)
