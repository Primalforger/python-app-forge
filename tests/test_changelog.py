from __future__ import annotations

from pathlib import Path

import pytest

from app_forge.changelog import (
    ReleaseChange,
    create_release_notes,
    parse_conventional_commit,
    render_release_notes,
)


def test_parse_conventional_commit_and_breaking_footer() -> None:
    parsed = parse_conventional_commit(
        "feat(api)!: add token rotation #42\n\nBREAKING CHANGE: old tokens are invalid"
    )
    assert parsed == ReleaseChange(
        "add token rotation", "feat", "api", True, "#42"
    )


def test_parse_rejects_non_conventional_and_malformed_messages() -> None:
    with pytest.raises(ValueError, match="Conventional Commits"):
        parse_conventional_commit("Added a feature")
    with pytest.raises(ValueError, match="empty"):
        parse_conventional_commit("  ")


def test_render_release_notes_groups_changes_deterministically() -> None:
    changes = [
        ReleaseChange("add export endpoint", "feat", "api", reference="#12"),
        ReleaseChange("fix stale cache", "fix"),
        ReleaseChange("replace auth token format", "feat", breaking=True),
        ReleaseChange("refresh examples", "docs"),
        ReleaseChange("speed up lookup", "perf"),
    ]
    rendered = render_release_notes("v1.2.0", changes, release_date="2026-11-01")
    assert rendered.startswith("# 1.2.0\n\nReleased: 2026-11-01")
    assert rendered.index("## Breaking changes") < rendered.index("## Features")
    assert rendered.index("## Features") < rendered.index("## Fixes")
    assert rendered.index("## Fixes") < rendered.index("## Performance")
    assert rendered.index("## Performance") < rendered.index("## Other changes")
    assert "**api:** add export endpoint (#12)" in rendered
    assert rendered.count("replace auth token format") == 1


@pytest.mark.parametrize("version", ["", "../1.0.0", "1.0", "01.2.3", "v1.2.3/evil"])
def test_invalid_versions_rejected(version: str) -> None:
    with pytest.raises(ValueError, match="version"):
        render_release_notes(version, [])


def test_invalid_change_and_date_rejected() -> None:
    with pytest.raises(ValueError, match="single line"):
        render_release_notes("1.0.0", [ReleaseChange("bad\nentry")])
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        render_release_notes("1.0.0", [], release_date="2026-1-1")
    with pytest.raises(TypeError, match="ReleaseChange"):
        render_release_notes("1.0.0", ["feat: nope"])


def test_create_release_notes_is_exclusive_and_deterministic(tmp_path: Path) -> None:
    first = create_release_notes(
        tmp_path, "v2.0.0", [ReleaseChange("ship it", "feat")],
        release_date="2026-11-01",
    )
    original = first.read_text(encoding="utf-8")
    assert first.name == "2.0.0.md"
    with pytest.raises(FileExistsError):
        create_release_notes(tmp_path, "2.0.0", [], release_date="2026-11-01")
    assert first.read_text(encoding="utf-8") == original


def test_symlink_directory_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        create_release_notes(link, "1.0.0", [], release_date="2026-11-01")
