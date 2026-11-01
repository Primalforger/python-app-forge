"""Dependency-free Cobertura coverage parsing and threshold enforcement."""
from __future__ import annotations
import math
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

_MAX_REPORT_BYTES = 10 * 1024 * 1024

@dataclass(frozen=True, slots=True)
class CoverageSummary:
    lines_valid: int
    lines_covered: int
    line_percent: float
    branches_valid: int
    branches_covered: int
    branch_percent: float | None

@dataclass(frozen=True, slots=True)
class CoverageResult:
    summary: CoverageSummary
    minimum_line: float
    minimum_branch: float | None
    passed: bool
    failures: tuple[str, ...]
    def to_dict(self) -> dict[str, object]:
        return {"summary": asdict(self.summary), "minimum_line": self.minimum_line,
                "minimum_branch": self.minimum_branch, "passed": self.passed,
                "failures": list(self.failures)}

def _threshold(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 100:
        raise ValueError(f"{field} must be between 0 and 100")
    return result

def parse_cobertura(path: str | Path) -> CoverageSummary:
    """Parse bounded Cobertura XML aggregate totals."""
    report = Path(path)
    try:
        if report.stat().st_size > _MAX_REPORT_BYTES:
            raise ValueError(f"coverage report exceeds {_MAX_REPORT_BYTES} bytes")
        raw = report.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read coverage report: {exc}") from None
    if not raw:
        raise ValueError("coverage report is empty")
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("DTD and entity declarations are not allowed")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"invalid coverage XML: {exc}") from None
    if root.tag.rsplit("}", 1)[-1] != "coverage":
        raise ValueError("coverage report root element must be <coverage>")
    try:
        lv, lc = int(root.attrib["lines-valid"]), int(root.attrib["lines-covered"])
        bv, bc = int(root.attrib.get("branches-valid", "0")), int(root.attrib.get("branches-covered", "0"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("coverage report must contain valid line and branch totals") from None
    if min(lv, lc, bv, bc) < 0 or lv == 0 or lc > lv or bc > bv:
        raise ValueError("coverage totals are negative, empty, or inconsistent")
    return CoverageSummary(lv, lc, lc * 100.0 / lv, bv, bc, bc * 100.0 / bv if bv else None)

def evaluate_coverage(summary: CoverageSummary, *, minimum_line: float,
                      minimum_branch: float | None = None) -> CoverageResult:
    """Evaluate inclusive line and optional branch thresholds."""
    if not isinstance(summary, CoverageSummary):
        raise TypeError("summary must be a CoverageSummary")
    line_limit = _threshold(minimum_line, "minimum_line")
    branch_limit = _threshold(minimum_branch, "minimum_branch") if minimum_branch is not None else None
    failures: list[str] = []
    if summary.line_percent + 1e-9 < line_limit:
        failures.append(f"line coverage {summary.line_percent:.2f}% is below {line_limit:.2f}%")
    if branch_limit is not None:
        if summary.branch_percent is None:
            failures.append("branch coverage threshold configured but report contains no branch data")
        elif summary.branch_percent + 1e-9 < branch_limit:
            failures.append(f"branch coverage {summary.branch_percent:.2f}% is below {branch_limit:.2f}%")
    return CoverageResult(summary, line_limit, branch_limit, not failures, tuple(failures))

def check_coverage(report: str | Path, *, minimum_line: float,
                   minimum_branch: float | None = None) -> CoverageResult:
    """Parse Cobertura XML and enforce the requested policy."""
    return evaluate_coverage(parse_cobertura(report), minimum_line=minimum_line,
                             minimum_branch=minimum_branch)

__all__ = ["CoverageResult", "CoverageSummary", "check_coverage", "evaluate_coverage", "parse_cobertura"]
