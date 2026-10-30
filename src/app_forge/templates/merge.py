"""Deterministic three-way text and template-tree merge primitives.

The base is the exact template content last applied by Forge. Local changes are
preserved when upstream edits do not overlap them; overlapping edits are
reported instead of guessed or silently overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class TextConflict:
    base_start: int
    base_end: int
    local: tuple[str, ...]
    incoming: tuple[str, ...]


@dataclass(frozen=True)
class TextMerge:
    text: str | None
    conflicts: tuple[TextConflict, ...]

    @property
    def clean(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True)
class FileConflict:
    path: str
    kind: str


@dataclass(frozen=True)
class FileMerge:
    files: dict[str, str]
    conflicts: tuple[FileConflict, ...]

    @property
    def clean(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: tuple[str, ...]
    side: str


def _edits(base: list[str], changed: list[str], side: str) -> list[_Edit]:
    matcher = SequenceMatcher(a=base, b=changed, autojunk=False)
    return [
        _Edit(i1, i2, tuple(changed[j1:j2]), side)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _overlap(left: _Edit, right: _Edit) -> bool:
    # Two insertions at one boundary compete. An insertion at the beginning
    # of a replacement also competes; one at its end is an independent edit.
    if left.start == left.end and right.start == right.end:
        return left.start == right.start
    if left.start == left.end:
        return right.start <= left.start < right.end
    if right.start == right.end:
        return left.start <= right.start < left.end
    return max(left.start, right.start) < min(left.end, right.end)


def merge_text(base: str, local: str, incoming: str) -> TextMerge:
    """Merge independent line edits; return conflicts without partial output."""
    if local == incoming:
        return TextMerge(local, ())
    if local == base:
        return TextMerge(incoming, ())
    if incoming == base:
        return TextMerge(local, ())

    base_lines = base.splitlines(keepends=True)
    local_edits = _edits(base_lines, local.splitlines(keepends=True), "local")
    incoming_edits = _edits(base_lines, incoming.splitlines(keepends=True), "incoming")
    accepted: list[_Edit] = []
    conflicts: list[TextConflict] = []

    for edit in local_edits:
        accepted.append(edit)
    for edit in incoming_edits:
        overlaps = [other for other in local_edits if _overlap(other, edit)]
        if not overlaps:
            accepted.append(edit)
            continue
        if len(overlaps) == 1:
            other = overlaps[0]
            if (other.start, other.end, other.replacement) == (edit.start, edit.end, edit.replacement):
                continue
        for other in overlaps:
            conflicts.append(TextConflict(
                min(other.start, edit.start), max(other.end, edit.end),
                other.replacement, edit.replacement,
            ))

    if conflicts:
        unique = {
            (c.base_start, c.base_end, c.local, c.incoming): c
            for c in conflicts
        }
        return TextMerge(None, tuple(sorted(unique.values(), key=lambda c: (c.base_start, c.base_end))))

    output: list[str] = []
    cursor = 0
    for edit in sorted(accepted, key=lambda e: (e.start, e.end, e.side)):
        output.extend(base_lines[cursor:edit.start])
        output.extend(edit.replacement)
        cursor = edit.end
    output.extend(base_lines[cursor:])
    return TextMerge("".join(output), ())


def merge_file_maps(base: dict[str, str], local: dict[str, str], incoming: dict[str, str]) -> FileMerge:
    """Three-way merge a template file tree, including additions and deletions."""
    merged: dict[str, str] = {}
    conflicts: list[FileConflict] = []

    for path in sorted(set(base) | set(local) | set(incoming)):
        old = base.get(path)
        ours = local.get(path)
        theirs = incoming.get(path)

        if old is None:
            if ours is None:
                if theirs is not None:
                    merged[path] = theirs
            elif theirs is None or ours == theirs:
                merged[path] = ours
            else:
                conflicts.append(FileConflict(path, "add-add"))
            continue

        if ours is None and theirs is None:
            continue
        if ours is None:
            if theirs == old:
                continue
            conflicts.append(FileConflict(path, "delete-modify"))
            continue
        if theirs is None:
            if ours == old:
                continue
            conflicts.append(FileConflict(path, "modify-delete"))
            continue

        result = merge_text(old, ours, theirs)
        if result.clean:
            assert result.text is not None
            merged[path] = result.text
        else:
            conflicts.append(FileConflict(path, "content-conflict"))

    return FileMerge(merged, tuple(conflicts))
