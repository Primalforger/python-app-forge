from __future__ import annotations

import pytest

from app_forge.cicd import (
    CICDConfig,
    render_cicd_files,
    render_github_actions,
    render_gitlab_ci,
)


def config(**kwargs):
    return CICDConfig(project_name="example-app", **kwargs)


def test_github_actions_has_matrix_and_read_only_permissions():
    output = render_github_actions(config(python_versions=("3.11", "3.12")))
    assert 'python-version: ["3.11", "3.12"]' in output
    assert "permissions:\n  contents: read" in output
    assert "pull_request:" in output
    assert "actions/checkout@v4" in output


def test_github_actions_has_test_lint_and_build_steps():
    output = render_github_actions(config())
    assert "ruff check ." in output
    assert "python -m pytest -q" in output
    assert "python -m build" in output


def test_github_actions_optional_steps_can_be_disabled():
    output = render_github_actions(config(lint_command=None, build=False))
    assert "Lint" not in output
    assert "Build distributions" not in output


def test_security_audit_is_opt_in():
    assert "pip_audit" not in render_github_actions(config())
    assert "pip_audit" in render_github_actions(config(security_audit=True))


def test_gitlab_pipeline_has_parallel_matrix_and_cache():
    output = render_gitlab_ci(config(python_versions=("3.11", "3.13")))
    assert 'PYTHON_VERSION: ["3.11", "3.13"]' in output
    assert "parallel:" in output
    assert ".cache/pip" in output
    assert "python -m pytest -q" in output


def test_gitlab_pipeline_uses_configured_commands():
    output = render_gitlab_ci(config(test_command=("pytest", "tests", "-q")))
    assert '"pytest tests -q"' in output


def test_file_map_is_deterministic_and_complete():
    cfg = config()
    assert render_cicd_files(cfg) == render_cicd_files(cfg)
    assert list(render_cicd_files(cfg)) == [".github/workflows/ci.yml", ".gitlab-ci.yml"]


@pytest.mark.parametrize("name", ["", "../bad", "name with spaces", "x" * 101])
def test_rejects_unsafe_project_names(name):
    with pytest.raises(ValueError):
        CICDConfig(project_name=name)


@pytest.mark.parametrize("versions", [(), ("3.10",), ("3.15",), ("3.11", "3.11")])
def test_rejects_invalid_python_matrices(versions):
    with pytest.raises(ValueError):
        config(python_versions=versions)


@pytest.mark.parametrize("field", ["install_command", "test_command"])
def test_rejects_empty_or_invalid_commands(field):
    with pytest.raises(ValueError):
        config(**{field: ()})
    with pytest.raises(ValueError):
        config(**{field: ("python", "bad\\ncommand")})


def test_rejects_non_boolean_flags():
    with pytest.raises(ValueError):
        config(build="yes")


def test_rendering_has_no_secret_values_or_write_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    output = render_cicd_files(config())
    assert set(tmp_path.iterdir()) == before
    assert all("TOKEN" not in value and "SECRET" not in value for value in output.values())
