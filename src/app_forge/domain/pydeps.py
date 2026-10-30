"""Python requirement specifiers: parse, intersect and compare (PEP 440 subset, no I/O).

Supported operators: ==, !=, >=, <=, >, <, ~= and ==X.Y.*. Pre/post/dev releases, ===, and environment
markers are reported as 'unknown' so a human decides; they are never guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[[^\]]*\])?\s*(.*)$")
_CLAUSE = re.compile(r"^(===|==|!=|~=|<=|>=|<|>)\s*([0-9]+(?:\.[0-9]+)*(?:\.\*)?)$")


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _vt(text: str) -> tuple[int, ...]:
    parts = [int(p) for p in text.split(".")]
    return tuple(parts + [0] * (4 - len(parts))) if len(parts) < 4 else tuple(parts)


@dataclass(frozen=True)
class Req:
    name: str
    raw: str
    clauses: tuple[tuple[str, str], ...] = ()
    unknown: str = ""  # reason the specifier cannot be reasoned about


def parse_requirement(spec: str) -> Req:
    m = _NAME.match(spec)
    if not m:
        return Req(normalize_name(spec), spec, unknown="not a valid requirement")
    name, rest = normalize_name(m.group(1)), m.group(3).strip()
    if ";" in rest:
        return Req(name, spec, unknown="has an environment marker")
    rest = rest.strip("() ")
    if rest.startswith("@"):
        return Req(name, spec, unknown="direct URL reference")
    clauses = []
    for raw in filter(None, (c.strip() for c in rest.split(","))):
        cm = _CLAUSE.match(raw)
        if not cm:
            return Req(name, spec, unknown=f"unsupported specifier {raw!r}")
        if cm.group(1) == "===":
            return Req(name, spec, unknown="arbitrary equality (===)")
        if cm.group(2).endswith(".*") and cm.group(1) not in ("==", "!="):
            return Req(name, spec, unknown=f"wildcard not allowed with {cm.group(1)}")
        clauses.append((cm.group(1), cm.group(2)))
    return Req(name, spec, tuple(clauses))


@dataclass
class _Range:
    lo: tuple | None = None   # (version tuple, inclusive)
    hi: tuple | None = None
    excluded: tuple = ()
    unknown: bool = False


def _tighten_lo(cur, new):
    if new is None or cur is None:
        return new or cur
    if new[0] != cur[0]:
        return new if new[0] > cur[0] else cur
    return (cur[0], cur[1] and new[1])


def _tighten_hi(cur, new):
    if new is None or cur is None:
        return new or cur
    if new[0] != cur[0]:
        return new if new[0] < cur[0] else cur
    return (cur[0], cur[1] and new[1])


def _to_range(req: Req) -> _Range:
    r = _Range()
    for op, v in req.clauses:
        if v.endswith(".*"):
            base = [int(p) for p in v[:-2].split(".")]
            lo, hi = _vt(".".join(map(str, base))), _vt(".".join(map(str, base[:-1] + [base[-1] + 1])))
            if op == "==":
                r.lo, r.hi = _tighten_lo(r.lo, (lo, True)), _tighten_hi(r.hi, (hi, False))
            else:
                r.unknown = True
            continue
        t = _vt(v)
        if op == ">=":
            r.lo = _tighten_lo(r.lo, (t, True))
        elif op == ">":
            r.lo = _tighten_lo(r.lo, (t, False))
        elif op == "<=":
            r.hi = _tighten_hi(r.hi, (t, True))
        elif op == "<":
            r.hi = _tighten_hi(r.hi, (t, False))
        elif op == "==":
            r.lo, r.hi = _tighten_lo(r.lo, (t, True)), _tighten_hi(r.hi, (t, True))
        elif op == "!=":
            r.excluded += (t,)
        elif op == "~=":
            parts = [int(p) for p in v.split(".")]
            if len(parts) < 2:
                r.unknown = True
                continue
            up = parts[:-1]
            up[-1] += 1
            r.lo, r.hi = _tighten_lo(r.lo, (t, True)), _tighten_hi(r.hi, (_vt(".".join(map(str, up))), False))
    return r


def _nonempty(r: _Range) -> bool:
    if r.lo and r.hi:
        if r.lo[0] > r.hi[0]:
            return False
        if r.lo[0] == r.hi[0]:
            return r.lo[1] and r.hi[1] and r.lo[0] not in r.excluded
    return True


def _subset(a: _Range, b: _Range) -> bool:
    """Is every version allowed by `a` also allowed by `b`?"""
    if b.lo and (not a.lo or a.lo[0] < b.lo[0] or (a.lo[0] == b.lo[0] and a.lo[1] and not b.lo[1])):
        return False
    if b.hi and (not a.hi or a.hi[0] > b.hi[0] or (a.hi[0] == b.hi[0] and a.hi[1] and not b.hi[1])):
        return False
    for x in b.excluded:  # b forbids x; a must forbid it too, or never reach it
        inside = (not a.lo or a.lo[0] < x or (a.lo[0] == x and a.lo[1])) and (
            not a.hi or a.hi[0] > x or (a.hi[0] == x and a.hi[1]))
        if inside and x not in a.excluded:
            return False
    return True


def compare(existing: Req, wanted: Req) -> dict:
    """How does the project's current requirement relate to what a component needs?

    verdict: satisfied (existing already guarantees wanted) | compatible (overlap, but existing allows more)
             | incompatible (no version satisfies both) | unknown (needs a human)
    """
    if existing.unknown or wanted.unknown:
        why = existing.unknown or wanted.unknown
        return {"verdict": "unknown", "message": f"cannot compare {existing.raw!r} with {wanted.raw!r}: {why}"}
    if not wanted.clauses:
        return {"verdict": "satisfied", "message": f"{wanted.raw} has no version constraint"}
    if not existing.clauses:
        return {"verdict": "compatible", "message": f"project allows any {existing.name}; component needs {wanted.raw}"}
    a, b = _to_range(existing), _to_range(wanted)
    if a.unknown or b.unknown:
        return {"verdict": "unknown", "message": f"cannot compare {existing.raw!r} with {wanted.raw!r}"}
    merged = _Range(_tighten_lo(a.lo, b.lo), _tighten_hi(a.hi, b.hi), a.excluded + b.excluded)
    if not _nonempty(merged):
        return {"verdict": "incompatible",
                "message": f"project requires {existing.raw!r} but the component needs {wanted.raw!r}: no version satisfies both"}
    if _subset(a, b):
        return {"verdict": "satisfied", "message": f"{existing.raw} already satisfies {wanted.raw}"}
    return {"verdict": "compatible",
            "message": f"{existing.raw} overlaps {wanted.raw} but also allows versions the component does not support"}


def combine(reqs: list[Req]) -> Req:
    """Merge several wants for the same package into one requirement (clauses are ANDed)."""
    name = reqs[0].name
    clauses = tuple(dict.fromkeys(c for r in reqs for c in r.clauses))
    unknown = next((r.unknown for r in reqs if r.unknown), "")
    text = name + ",".join(f"{o}{v}" for o, v in clauses)
    return Req(name, text, clauses, unknown)


def satisfiable(req: Req) -> bool:
    """Can any version satisfy all clauses of this requirement at once?"""
    return _nonempty(_to_range(req))
