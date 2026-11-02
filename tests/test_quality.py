from __future__ import annotations

import tomllib

import pytest

from app_forge.quality import (
    ForbiddenImportContract,
    QualityConfig,
    quality_config_from_manifest,
    render_import_linter,
    render_pre_commit,
    render_quality_files,
)


def manifest(**quality):
    return {"quality": quality}


def test_manifest_generates_pre_commit_and_import_linter_files():
    config = {
        "pre_commit": True,
        "import_linter": True,
        "contracts": [{
            "name": "domain stays isolated",
            "source_modules": ["sample_app.domain"],
            "forbidden_modules": ["sample_app.infrastructure", "sample_app.gui"],
        }],
    }
    files = render_quality_files(manifest(**config), "sample_app")
    assert list(files) == [".pre-commit-config.yaml", ".importlinter"]
    assert "rev: v5.0.0" in files[".pre-commit-config.yaml"]
    assert "ruff check --force-exclude" in files[".pre-commit-config.yaml"]
    assert "root_package = sample_app" in files[".importlinter"]
    assert "source_modules = sample_app.domain" in files[".importlinter"]
    assert "forbidden_modules = sample_app.infrastructure, sample_app.gui" in files[".importlinter"]


def test_pre_commit_only_manifest_omits_import_linter_file():
    files = render_quality_files(manifest(pre_commit=True, import_linter=False), "sample_app")
    assert list(files) == [".pre-commit-config.yaml"]


def test_disabled_tools_produce_no_files():
    assert render_quality_files(manifest(pre_commit=False, import_linter=False), "sample_app") == {}


def test_manifest_defaults_to_pre_commit_only():
    config = quality_config_from_manifest({})
    assert config.pre_commit is True
    assert config.import_linter is False
    assert render_quality_files({}, "sample_app") == {".pre-commit-config.yaml": render_pre_commit(config)}


def test_contracts_are_validated_and_names_are_unique():
    first = ForbiddenImportContract("domain boundary", ("sample_app.domain",), ("sample_app.gui",))
    with pytest.raises(ValueError, match="unique"):
        QualityConfig(import_linter=True, contracts=(first, first))


@pytest.mark.parametrize("value", [None, "yes", 1])
def test_manifest_tool_switches_must_be_boolean(value):
    with pytest.raises(ValueError, match="booleans"):
        quality_config_from_manifest(manifest(pre_commit=value, import_linter=False))


@pytest.mark.parametrize("contract", [
    {},
    {"name": "bad", "source_modules": "sample_app", "forbidden_modules": ["other"]},
    {"name": "bad", "source_modules": ["../escape"], "forbidden_modules": ["other"]},
    {"name": "bad", "source_modules": ["sample_app"], "forbidden_modules": []},
])
def test_invalid_manifest_contracts_are_rejected(contract):
    with pytest.raises(ValueError):
        quality_config_from_manifest(manifest(import_linter=True, contracts=[contract]))


@pytest.mark.parametrize("package", ["", "../escape", "sample-app", "sample_app;bad", "sample_app\nother"])
def test_import_linter_rejects_unsafe_package_names(package):
    config = QualityConfig(import_linter=True, contracts=(
        ForbiddenImportContract("boundary", ("sample_app.domain",), ("sample_app.gui",)),
    ))
    with pytest.raises(ValueError):
        render_import_linter(package, config)


def test_renderer_is_deterministic_and_has_no_filesystem_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = QualityConfig(pre_commit=True, import_linter=True, contracts=(
        ForbiddenImportContract("boundary", ("sample_app.domain",), ("sample_app.gui",)),
    ))
    before = set(tmp_path.iterdir())
    first = render_quality_files({"quality": {
        "pre_commit": True, "import_linter": True,
        "contracts": [{"name": "boundary", "source_modules": ["sample_app.domain"],
                       "forbidden_modules": ["sample_app.gui"]}],
    }}, "sample_app")
    assert first == render_quality_files({"quality": {
        "pre_commit": True, "import_linter": True,
        "contracts": [{"name": "boundary", "source_modules": ["sample_app.domain"],
                       "forbidden_modules": ["sample_app.gui"]}],
    }}, "sample_app")
    assert set(tmp_path.iterdir()) == before
    assert render_import_linter("sample_app", cfg) == first[".importlinter"]


def test_yaml_and_ini_outputs_have_expected_formats():
    yaml = render_pre_commit(QualityConfig())
    assert tomllib.loads("enabled = true")["enabled"] is True
    assert yaml.startswith("minimum_pre_commit_version:")
    assert "[importlinter]" in render_import_linter("sample_app", QualityConfig(
        import_linter=True, contracts=(
            ForbiddenImportContract("boundary", ("sample_app.domain",), ("sample_app.gui",)),
        )
    ))
