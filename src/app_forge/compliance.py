"""Compliance Engine (MOD-11): requirements, traceability and status evaluation.

It only consumes evidence. It cannot create passing results; a requirement is Verified only when
every linked check has retained, passing evidence.
"""
from __future__ import annotations

import tomllib
from datetime import date
from typing import Any
from pathlib import Path

from app_forge.domain.errors import ValidationFailure
from app_forge.domain.models import Requirement, Status
from app_forge.observability import utcnow

PRIORITIES = ("P0", "P1", "P2")
DISCLAIMER = ("This report summarises results of automated internal checks against the listed requirements. "
              "It is not a certification of conformance to any standard.")


def load_requirements(path: Path) -> list[Requirement]:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationFailure(f"Requirements file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ValidationFailure(f"Invalid requirements file: {exc}") from None
    out = []
    for raw in data.get("requirement", []):
        known = {k: v for k, v in raw.items() if k in Requirement.__dataclass_fields__}
        if "id" not in known or "title" not in known:
            raise ValidationFailure("Each [[requirement]] needs 'id' and 'title'")
        out.append(Requirement(**known))
    return out


def validate_requirements(reqs: list[Requirement]) -> list[str]:
    problems, ids = [], set()
    for r in reqs:
        if r.id in ids:
            problems.append(f"duplicate requirement id {r.id}")
        ids.add(r.id)
        if r.priority not in PRIORITIES:
            problems.append(f"{r.id}: priority must be one of {PRIORITIES}")
        if not r.acceptance:
            problems.append(f"{r.id}: no acceptance criteria")
        if not r.verified_by and not r.not_applicable and not r.exception:
            problems.append(f"{r.id}: no verification link")
    for r in reqs:
        if r.parent and r.parent not in ids:
            problems.append(f"{r.id}: parent {r.parent} does not exist")
    return problems


def _matches(token: str, check_id: str) -> bool:
    if token.startswith("check:"):
        return check_id == token[6:]
    return check_id == token or check_id.startswith(token + "::")


def evaluate(reqs: list[Requirement], evidence: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    out = []
    for r in reqs:
        rec: dict[str, Any] = {"id": r.id, "title": r.title, "priority": r.priority, "modules": r.modules,
               "components": r.components, "verified_by": r.verified_by, "evidence": 0, "missing": [],
               "reason": ""}
        exc = r.exception
        exc_valid = bool(exc.get("approver") and exc.get("rationale")) and (
            not exc.get("expires") or date.fromisoformat(str(exc["expires"])) >= today)
        if exc and exc_valid:
            rec.update(status=Status.EXCEPTION.value, reason=f"approved by {exc['approver']}: {exc['rationale']}")
        elif r.not_applicable:
            rec.update(status=Status.NOT_APPLICABLE.value, reason=r.not_applicable)
        else:
            if exc and not exc_valid:
                rec["reason"] = "exception is incomplete or expired; ignored. "
            matched: list[dict[str, Any]] = []
            missing: list[str] = []
            for tok in r.verified_by:
                m = [e for e in evidence if _matches(tok, e["check_id"])]
                if m:
                    matched.extend(m)
                else:
                    missing.append(tok)
            rec["evidence"] = len([m for m in matched if isinstance(m, dict)])
            rec["missing"] = [m for m in missing if isinstance(m, str)]
            dicts = [m for m in matched if isinstance(m, dict)]
            if any(e["status"] == "failed" for e in dicts):
                rec["status"] = Status.FAILED.value
                rec["reason"] += "failing evidence: " + ", ".join(
                    sorted({e["check_id"] for e in dicts if e["status"] == "failed"})[:5])
            elif any(e["status"] == "not_run" for e in dicts):
                rec["status"] = Status.BLOCKED.value
                rec["reason"] += "a required check could not run"
            elif r.verified_by and not rec["missing"] and dicts:
                rec["status"] = Status.VERIFIED.value
                rec["reason"] += f"{len(dicts)} passing evidence record(s)"
            elif r.implemented:
                rec["status"] = Status.IMPLEMENTED.value
                rec["reason"] += "implemented; verification incomplete" + (
                    f" (no evidence for: {', '.join(rec['missing'])})" if rec["missing"] else "")
            elif r.verified_by:
                rec["status"] = Status.PLANNED.value
                rec["reason"] += "verification defined but not yet executed"
            else:
                rec["status"] = Status.NOT_ASSESSED.value
        out.append(rec)
    return out


def build_report(reqs: list[Requirement], evidence: list[dict], *, subject: str, run_id: str | None) -> dict:
    results = evaluate(reqs, evidence)
    counts: dict[str, int] = {s.value: 0 for s in Status}
    for r in results:
        counts[r["status"]] += 1
    gaps = [r for r in results if r["status"] not in (Status.VERIFIED.value, Status.NOT_APPLICABLE.value,
                                                      Status.EXCEPTION.value)]
    return {"generated_at": utcnow(), "subject": subject, "evidence_run": run_id, "summary": counts,
            "total": len(results), "requirements": results, "gaps": [g["id"] for g in gaps],
            "scope": "Requirements listed in the register; evidence from the identified run only.",
            "disclaimer": DISCLAIMER}


def to_markdown(report: dict) -> str:
    lines = [f"# Compliance assessment: {report['subject']}", "", f"Generated: {report['generated_at']}  ",
             f"Evidence run: {report['evidence_run'] or 'none'}", "", "## Summary", "",
             "| Status | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report["summary"].items() if v]
    lines += ["", "## Traceability matrix", "", "| ID | Priority | Status | Verified by | Reason |", "|---|---|---|---|---|"]
    for r in report["requirements"]:
        lines.append(f"| {r['id']} | {r['priority']} | {r['status']} | {', '.join(r['verified_by']) or '-'} | "
                     f"{r['reason'].replace('|', '/')} |")
    lines += ["", "## Evidence gaps", ""]
    lines += [f"- {g}" for g in report["gaps"]] or ["- none"]
    lines += ["", "---", report["disclaimer"], ""]
    return "\n".join(lines)
