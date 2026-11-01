from __future__ import annotations

from pathlib import Path

import pytest

from app_forge.documentation_scaffold import (
    DocumentationProject,
    create_documentation_scaffold,
    render_documentation,
    validate_documentation_project,
)


def sample(**changes) -> DocumentationProject:
    values = {
        "name": "Example Project",
        "description": "A useful Python package.",
        "package_name": "example_project",
        "python_requires": ">=3.11",
        "license": "MIT",
        "repository_url": "https://github.com/example/project",
    }
    values.update(changes)
    return DocumentationProject(**values)


def test_render_documentation_returns_complete_deterministic_site_tree() -> None:
    first = render_documentation(sample())
    assert first == render_documentation(sample())
    assert set(first) == {
        "mkdocs.yml",
        "docs/index.md",
        "docs/getting-started.md",
        "docs/configuration.md",
        "docs/cli.md",
        "docs/architecture.md",
        "docs/security.md",
        "docs/contributing.md",
        "docs/api/index.md",
    }
    assert 'site_name: "Example Project"' in first["mkdocs.yml"]
    assert "https://github.com/example/project" in first["docs/index.md"]
    assert "not a security assessment or certification" in first["docs/security.md"]
    assert "example_project" in first["docs/api/index.md"]


def test_mkdocs_metadata_is_quoted_safely() -> None:
    rendered = render_documentation(sample(
        name="Project: 'One'",
        description='A "quoted" description: yes',
    ))
    assert 'site_name: "Project: \'One\'"' in rendered["mkdocs.yml"]
    assert 'site_description: "A \\"quoted\\" description: yes"' in rendered["mkdocs.yml"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "bad\nname"}, "single line"),
        ({"package_name": "not a package"}, "Python identifier"),
        ({"package_name": "a..b"}, "Python identifier"),
        ({"python_requires": "latest"}, "version constraint"),
        ({"license": "MIT\nInjected: yes"}, "single line"),
        ({"repository_url": "http://example.com"}, "HTTPS"),
        ({"repository_url": "https://user:secret@example.com"}, "credentials"),
        ({"description": " "}, "description"),
    ],
)
def test_invalid_project_metadata_is_rejected(changes: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_documentation_project(sample(**changes))


def test_wrong_project_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="DocumentationProject"):
        validate_documentation_project({"name": "bad"})


def test_create_scaffold_writes_all_files_and_does_not_overwrite(tmp_path: Path) -> None:
    created = create_documentation_scaffold(tmp_path, sample())
    assert len(created) == 9
    assert (tmp_path / "mkdocs.yml").is_file()
    assert (tmp_path / "docs/api/index.md").is_file()
    original = (tmp_path / "docs/index.md").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_documentation_scaffold(tmp_path, sample())
    assert (tmp_path / "docs/index.md").read_text(encoding="utf-8") == original


def test_existing_target_prevents_partial_scaffold_creation(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    existing = tmp_path / "docs/security.md"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_documentation_scaffold(tmp_path, sample())
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "mkdocs.yml").exists()


def test_symlinked_documentation_root_and_subdirectory_are_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    root_link = tmp_path / "root-link"
    try:
        root_link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        create_documentation_scaffold(root_link, sample())

    root = tmp_path / "project"
    root.mkdir()
    docs_link = root / "docs"
    docs_link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        create_documentation_scaffold(root, sample())
