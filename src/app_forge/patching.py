"""Patch engine (G-01): safe, idempotent, reversible edits to files a component does not own.

Every inserted block is wrapped in `forge:begin/forge:end` marker comments, so Forge can recognise it,
skip it when it is already present, replace it on upgrade, and remove it again, but only if nobody edited it.
Nothing here touches the filesystem: callers pass text in and get text back, so plans stay reviewable.
"""
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field

import yaml

from app_forge.domain.models import Patch
from app_forge.security import sha256_text
from app_forge.templates.engine import render_text


class PatchConflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class PatchResult:
    new_text: str
    sha256: str       # of the managed block (insert/toml-table) or of the merged data (json-merge)
    status: str       # applied | unchanged
    ownership: list[dict] = field(default_factory=list)


def _n(text: str) -> str:
    """Normalise line endings so a CRLF<->LF conversion by an editor is not mistaken for an edit."""
    return text.replace("\r\n", "\n")


def _nsha(text: str) -> str:
    return sha256_text(_n(text))


def _nl(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def target_path(patch: Patch, package: str, *, flat: bool = False) -> str:
    rel = render_text(patch.file, {"package": package})
    return rel[len("src/"):] if flat and rel.startswith(f"src/{package}/") else rel


def _render_data(value, variables):
    if isinstance(value, str):
        return render_text(value, variables)
    if isinstance(value, dict):
        return {k: _render_data(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_data(v, variables) for v in value]
    return value


# ----------------------------------------------------------------------------------- marked blocks
def _markers(comp: str, pid: str, comment: str) -> tuple[str, str]:
    return f"{comment} forge:begin {comp}:{pid}", f"{comment} forge:end {comp}:{pid}"


def find_block(lines: list[str], comp: str, pid: str) -> tuple[int, int] | None:
    begin, end = f"forge:begin {comp}:{pid}", f"forge:end {comp}:{pid}"
    start = next((i for i, l in enumerate(lines) if begin in l), None)
    if start is None:
        return None
    stop = next((i for i in range(start + 1, len(lines)) if end in lines[i]), None)
    if stop is None:
        raise PatchConflict("patch-block-corrupt", f"found {begin!r} without its end marker")
    return start, stop


def _build_block(comp: str, pid: str, comment: str, content: str, indent: str, nl: str) -> list[str]:
    begin, end = _markers(comp, pid, comment)
    body = [(indent + ln) if ln.strip() else ln for ln in content.rstrip("\r\n").splitlines()]
    return [f"{indent}{begin}{nl}", *[f"{ln}{nl}" for ln in body], f"{indent}{end}{nl}"]


def _apply_block(text: str, patch: Patch, comp: str, content: str, *, replace: bool, expect_sha: str | None,
                 locate_new) -> PatchResult:
    lines, nl = text.splitlines(keepends=True), _nl(text)
    existing = find_block(lines, comp, patch.id)
    if existing:
        s, e = existing
        current = "".join(lines[s:e + 1])
        indent_match = re.match(r"\s*", lines[s])
        indent = indent_match.group(0) if indent_match else ""
        block = _build_block(comp, patch.id, patch.comment, content, indent, nl)
        new_block = "".join(block)
        if _n(current) == _n(new_block):
            return PatchResult(text, _nsha(new_block), "unchanged")
        if not replace:
            raise PatchConflict("patch-exists-different",
                                f"a block for {comp}:{patch.id} already exists with different content")
        if expect_sha is not None and _nsha(current) != expect_sha:
            raise PatchConflict("patch-modified", f"the {comp}:{patch.id} block was edited after installation")
        return PatchResult("".join(lines[:s] + block + lines[e + 1:]), _nsha(new_block), "applied")
    index, indent = locate_new(lines)
    block = _build_block(comp, patch.id, patch.comment, content, indent, nl)
    if index > 0 and not lines[index - 1].endswith(("\n", "\r")):
        lines[index - 1] += nl  # anchor was the last line without a trailing newline
    return PatchResult("".join(lines[:index] + block + lines[index:]), _nsha("".join(block)), "applied")


# ----------------------------------------------------------------------------------- insert
def _locate_anchor(patch: Patch):
    rx = re.compile(rf"forge:anchor\s+{re.escape(patch.anchor)}(?![\w-])")

    def locate(lines):
        hits = [i for i, l in enumerate(lines) if rx.search(l)]
        if not hits:
            raise PatchConflict("anchor-missing", f"anchor 'forge:anchor {patch.anchor}' not found in {patch.file}")
        if len(hits) > 1:
            raise PatchConflict("anchor-ambiguous", f"anchor {patch.anchor!r} appears {len(hits)} times in {patch.file}")
        i = hits[0]
        indent_match = re.match(r"\s*", lines[i])
        return (i if patch.position == "before" else i + 1), indent_match.group(0) if indent_match else ""
    return locate


# ----------------------------------------------------------------------------------- toml tables
def _leaf_tables(d: dict, prefix: tuple = ()) -> list[tuple]:
    out = []
    for k, v in d.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            raise PatchConflict("patch-invalid", "arrays of tables are not supported by toml-table patches")
        if isinstance(v, dict):
            if not v or any(not isinstance(x, dict) for x in v.values()):
                out.append(prefix + (k,))
            out += _leaf_tables(v, prefix + (k,))
    return out


def _dig(d: dict, path: tuple):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _locate_toml_end(patch: Patch, content: str):
    def locate(lines):
        try:
            existing = tomllib.loads("".join(lines))
        except tomllib.TOMLDecodeError as exc:
            raise PatchConflict("target-unparseable", f"{patch.file} is not valid TOML: {exc}") from None
        try:
            new = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise PatchConflict("patch-invalid", f"patch content is not valid TOML: {exc}") from None
        first = next((l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith("#")), "")
        if not first.startswith("["):
            raise PatchConflict("patch-invalid", "toml-table content must consist of tables only ([name] headers)")
        leaves = _leaf_tables(new)
        same = [p for p in leaves if _dig(existing, p) == _dig(new, p)]
        for p in leaves:
            cur = _dig(existing, p)
            if cur is not None and cur != _dig(new, p):
                raise PatchConflict("config-key-conflict",
                                    f"[{'.'.join(p)}] already exists in {patch.file} with different values")
        if leaves and len(same) == len(leaves):
            raise _AlreadyPresent()
        if same:
            raise PatchConflict("config-key-conflict", f"part of the patch's tables already exist in {patch.file}")
        return len(lines), ""
    return locate


class _AlreadyPresent(Exception):
    pass


# ----------------------------------------------------------------------------------- json merge
def _merge(target: dict, data: dict, path: list, owned: list[dict]) -> None:
    for key, value in data.items():
        here = path + [key]
        if key not in target:
            target[key] = value
            owned.append({"path": here, "list_item": False, "value": value})
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge(target[key], value, here, owned)
        elif isinstance(target[key], list) and isinstance(value, list):
            for item in value:
                if item not in target[key]:
                    target[key].append(item)
                    owned.append({"path": here, "list_item": True, "value": item})
        elif target[key] != value:
            raise PatchConflict("config-key-conflict", f"{'.'.join(map(str, here))} already has a different value")


def _structured_load(text: str, patch: Patch, yaml_format: bool):
    try:
        doc = yaml.safe_load(text) if yaml_format else json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise PatchConflict("target-unparseable", f"{patch.file} is not valid {'YAML' if yaml_format else 'JSON'}: {exc}") from None
    if not isinstance(doc, dict):
        raise PatchConflict("target-unparseable", f"{patch.file} must contain a mapping/object")
    return doc


def _structured_dump(doc: dict, text: str, yaml_format: bool) -> str:
    rendered = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True) if yaml_format else json.dumps(doc, indent=2, ensure_ascii=False)
    return rendered + (_nl(text) if text.endswith(("\n", "\r")) else "")


def _apply_structured(text: str, patch: Patch, package: str, yaml_format: bool) -> PatchResult:
    doc = _structured_load(text, patch, yaml_format)
    data = _render_data(patch.data, {"package": package})
    owned: list[dict] = []
    _merge(doc, data, [], owned)
    sha = sha256_text(json.dumps(data, sort_keys=True))
    if not owned:
        return PatchResult(text, sha, "unchanged", [])
    return PatchResult(_structured_dump(doc, text, yaml_format), sha, "applied", owned)


def _remove_structured(text: str, ownership: list[dict] | None, patch_file: str, yaml_format: bool) -> str:
    if not ownership:
        raise PatchConflict("patch-ownership-missing", f"ownership metadata for {patch_file} is missing; refusing unsafe automatic removal")
    doc = _structured_load(text, Patch("remove", patch_file, "yaml-merge" if yaml_format else "json-merge"), yaml_format)
    for item in reversed(ownership):
        path = item.get("path")
        if not isinstance(path, list) or not path:
            raise PatchConflict("patch-ownership-corrupt", "stored structured-patch ownership is invalid")
        parent = doc
        for key in path[:-1]:
            if not isinstance(parent, dict) or key not in parent:
                raise PatchConflict("patch-modified", f"owned value at {'.'.join(map(str, path))} is missing or changed")
            parent = parent[key]
        key = path[-1]
        if item.get("list_item"):
            values = parent.get(key) if isinstance(parent, dict) else None
            value = item.get("value")
            if not isinstance(values, list) or value not in values:
                raise PatchConflict("patch-modified", f"owned list item at {'.'.join(map(str, path))} is missing or changed")
            values.remove(value)
        else:
            if not isinstance(parent, dict) or key not in parent or parent[key] != item.get("value"):
                raise PatchConflict("patch-modified", f"owned value at {'.'.join(map(str, path))} was edited; Forge will not delete it")
            del parent[key]
    return _structured_dump(doc, text, yaml_format)


# ----------------------------------------------------------------------------------- public API
def _toml_existing_table(text: str, content: str, patch: Patch, comp_id: str):
    try:
        current = tomllib.loads(text)
        incoming = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    leaves = _leaf_tables(incoming)
    if len(leaves) != 1:
        return None
    path = leaves[0]
    target = _dig(current, path)
    additions = _dig(incoming, path)
    if not isinstance(target, dict) or not isinstance(additions, dict):
        return None
    lines = content.splitlines()
    assignments = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue
        match = re.match(r"^([A-Za-z0-9_-]+)\s*=", stripped)
        if not match:
            raise PatchConflict("patch-invalid", "existing-table TOML patches support single-line key assignments only")
        assignments.append((match.group(1), line))
    if not assignments:
        raise PatchConflict("patch-invalid", "existing-table TOML patch must add at least one key")
    block_lines = []
    for key, line in assignments:
        if key in target and target[key] != additions[key]:
            raise PatchConflict("config-key-conflict", f"{'.'.join(path)}.{key} already has a different value")
        if key not in target:
            block_lines.append(line)
    if not block_lines:
        raise _AlreadyPresent()
    marker = find_block(text.splitlines(keepends=True), comp_id, patch.id)
    if marker:
        return "\n".join(block_lines) + "\n", None
    header = re.compile(r"^\s*\[" + re.escape(".".join(path)) + r"\]\s*(?:#.*)?$")
    matches = [idx for idx, line in enumerate(text.splitlines()) if header.match(line)]
    if len(matches) != 1:
        return None
    return "\n".join(block_lines) + "\n", matches[0] + 1


def apply_patch(text: str, patch: Patch, comp_id: str, package: str, *, replace: bool = False,
                expect_sha: str | None = None) -> PatchResult:
    """Apply one patch to `text`. Raises PatchConflict for anything unsafe or ambiguous."""
    if patch.kind in ("json-merge", "yaml-merge"):
        return _apply_structured(text, patch, package, patch.kind == "yaml-merge")
    content = render_text(patch.content, {"package": package})
    if patch.kind == "insert":
        return _apply_block(text, patch, comp_id, content, replace=replace, expect_sha=expect_sha,
                            locate_new=_locate_anchor(patch))
    if patch.kind == "toml-table":
        existing_block = find_block(text.splitlines(keepends=True), comp_id, patch.id)
        try:
            existing = _toml_existing_table(text, content, patch, comp_id)
            if existing is not None:
                block_content, insertion = existing
                def locate(lines):
                    if insertion is None:
                        raise PatchConflict("patch-invalid", "could not locate existing TOML table header")
                    return insertion, ""
                res = _apply_block(text, patch, comp_id, block_content, replace=replace,
                                   expect_sha=expect_sha, locate_new=locate)
            else:
                leading = "\n" if not existing_block else ""
                res = _apply_block(text, patch, comp_id, content, replace=replace, expect_sha=expect_sha,
                                   locate_new=_locate_toml_end(patch, content))
                if res.status == "applied" and not existing_block and leading:
                    nl = _nl(text)
                    res.new_text = res.new_text.replace(f"{patch.comment} forge:begin {comp_id}:{patch.id}",
                                                        f"{nl}{patch.comment} forge:begin {comp_id}:{patch.id}", 1)
        except _AlreadyPresent:
            return PatchResult(text, sha256_text(content), "unchanged")
        if res.status == "applied":
            try:
                tomllib.loads(res.new_text)
            except tomllib.TOMLDecodeError as exc:
                raise PatchConflict("patch-invalid", f"result would not be valid TOML: {exc}") from None
        return res
    raise PatchConflict("patch-invalid", f"unknown patch kind {patch.kind!r}")


def remove_patch(text: str, comp_id: str, pid: str, expect_sha: str | None, *, kind: str = "insert", ownership: list[dict] | None = None) -> str:
    """Remove a marked block or only the unchanged structured values Forge owns."""
    if kind in ("json-merge", "yaml-merge"):
        return _remove_structured(text, ownership, pid, kind == "yaml-merge")
    lines = text.splitlines(keepends=True)
    found = find_block(lines, comp_id, pid)
    if not found:
        raise PatchConflict("patch-block-missing", f"no block for {comp_id}:{pid} found")
    s, e = found
    if expect_sha is not None and _nsha("".join(lines[s:e + 1])) != expect_sha:
        raise PatchConflict("patch-modified", f"the {comp_id}:{pid} block was edited; Forge will not delete your changes")
    if s > 0 and lines[s - 1].strip() == "" and (e + 1 >= len(lines) or lines[e + 1].strip() == "" or e + 1 == len(lines)):
        s -= 1  # also drop the blank separator Forge added before an appended table
    return "".join(lines[:s] + lines[e + 1:])
