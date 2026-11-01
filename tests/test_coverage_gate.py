from pathlib import Path
import pytest
from app_forge.coverage_gate import CoverageSummary, check_coverage, evaluate_coverage, parse_cobertura

def write_report(tmp_path: Path, **changes: str) -> Path:
    attrs = {"lines-valid":"100", "lines-covered":"85", "branches-valid":"20", "branches-covered":"15"}
    attrs.update(changes)
    body = " ".join(f'{k}="{v}"' for k,v in attrs.items())
    path = tmp_path / "coverage.xml"
    path.write_text(f"<coverage {body}><packages /></coverage>", encoding="utf-8")
    return path

def test_parse_and_inclusive_thresholds(tmp_path):
    summary = parse_cobertura(write_report(tmp_path))
    assert summary.line_percent == 85
    assert summary.branch_percent == 75
    assert check_coverage(tmp_path / "coverage.xml", minimum_line=85, minimum_branch=75).passed

def test_threshold_failures_are_actionable(tmp_path):
    result = check_coverage(write_report(tmp_path), minimum_line=90, minimum_branch=80)
    assert not result.passed and len(result.failures) == 2
    assert "85.00%" in result.failures[0] and result.to_dict()["passed"] is False

def test_missing_branch_data_fails_only_when_requested(tmp_path):
    path = write_report(tmp_path, **{"branches-valid":"0", "branches-covered":"0"})
    assert check_coverage(path, minimum_line=80).passed
    assert "no branch data" in check_coverage(path, minimum_line=80, minimum_branch=50).failures[0]

@pytest.mark.parametrize("attrs", [{"lines-valid":"0"}, {"lines-covered":"101"},
    {"branches-covered":"21"}, {"lines-covered":"-1"}, {"lines-valid":"x"}])
def test_invalid_totals_rejected(tmp_path, attrs):
    with pytest.raises(ValueError): parse_cobertura(write_report(tmp_path, **attrs))

@pytest.mark.parametrize("value", [-1, 100.1, float("nan"), float("inf"), True])
def test_invalid_threshold_rejected(value):
    summary = CoverageSummary(10, 8, 80, 0, 0, None)
    with pytest.raises((TypeError, ValueError)): evaluate_coverage(summary, minimum_line=value)

def test_empty_invalid_root_and_missing_reports_rejected(tmp_path):
    path = tmp_path / "coverage.xml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"): parse_cobertura(path)
    path.write_text("<not-coverage />", encoding="utf-8")
    with pytest.raises(ValueError, match="root"): parse_cobertura(path)
    with pytest.raises(ValueError, match="cannot read"): parse_cobertura(tmp_path / "missing.xml")

def test_dtd_rejected(tmp_path):
    path = tmp_path / "coverage.xml"
    path.write_text('<!DOCTYPE coverage [<!ENTITY x "boom">]><coverage lines-valid="1" lines-covered="1" />', encoding="utf-8")
    with pytest.raises(ValueError, match="DTD"): parse_cobertura(path)
