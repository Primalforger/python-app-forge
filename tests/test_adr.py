from __future__ import annotations

from pathlib import Path

import pytest

from app_forge.adr import ArchitectureDecision, create_adr, render_adr


def sample(**changes) -> ArchitectureDecision:
    values = {
        "title": "Use SQLite for local state",
        "context": "The application needs durable local state.",
        "decision": "Use SQLite with transactions.",
        "consequences": "Simple deployment; concurrency is bounded by SQLite.",
    }
    values.update(changes)
    return ArchitectureDecision(**values)


def test_render_adr_includes_required_sections_and_metadata() -> None:
    rendered = render_adr(sample(
        status="accepted", decision_date="2026-11-01",
        decision_makers=("Platform team",), consulted=("Security",),
        informed=("Users",), supersedes="0002-use-json",
    ))
    assert rendered.startswith("# Use SQLite for local state")
    assert "**Status:** accepted" in rendered
    assert "**Date:** 2026-11-01" in rendered
    assert "**Decision makers:** Platform team" in rendered
    assert "**Consulted:** Security" in rendered
    assert "**Informed:** Users" in rendered
    assert "**Supersedes:** 0002-use-json" in rendered
    assert "## Context" in rendered
    assert "## Decision" in rendered
    assert "## Consequences" in rendered


def test_create_adr_numbers_files_and_does_not_overwrite(tmp_path: Path) -> None:
    first = create_adr(tmp_path, sample())
    second = create_adr(tmp_path, sample(title="Adopt typed configuration"))
    assert first.name == "0001-use-sqlite-for-local-state.md"
    assert second.name == "0002-adopt-typed-configuration.md"
    original = first.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_adr(tmp_path, sample())
    assert first.read_text(encoding="utf-8") == original


def test_create_adr_uses_existing_sequence_and_ignores_unrelated_files(tmp_path: Path) -> None:
    (tmp_path / "0003-existing-record.md").write_text("existing", encoding="utf-8")
    (tmp_path / "9999-not-an-adr.txt").write_text("ignore", encoding="utf-8")
    assert create_adr(tmp_path, sample()).name.startswith("0004-")


@pytest.mark.parametrize("status", ["unknown", "", "pending"])
def test_invalid_status_rejected(status: str) -> None:
    with pytest.raises(ValueError, match="status"):
        render_adr(sample(status=status))


@pytest.mark.parametrize("field", ["title", "context", "decision", "consequences"])
def test_required_fields_must_be_nonempty(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        render_adr(sample(**{field: "  "}))


def test_title_must_be_single_line_and_have_slug_characters(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="single line"):
        create_adr(tmp_path, sample(title="Bad\nTitle"))
    with pytest.raises(ValueError, match="ASCII"):
        create_adr(tmp_path, sample(title="你好"))


def test_date_and_people_are_validated() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        render_adr(sample(decision_date="2026-1-1"))
    with pytest.raises(TypeError, match="not a string"):
        render_adr(sample(decision_makers="Alice"))


def test_symlink_directory_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        create_adr(link, sample())


def test_sequence_limit_rejected(tmp_path: Path) -> None:
    (tmp_path / "9999-last-record.md").write_text("last", encoding="utf-8")
    with pytest.raises(ValueError, match="exhausted"):
        create_adr(tmp_path, sample())
