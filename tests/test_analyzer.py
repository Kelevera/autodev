"""Tests for autodev.core.analyzer and autodev.core.planner."""

from autodev.core import analyzer, planner
from autodev.core.scanner import Issue


def make_issue(file_path="src/mod.py", line=1, issue_type="missing_docstring",
               severity="medium", description="desc"):
    return Issue(file_path=file_path, line_no=line, issue_type=issue_type,
                 severity=severity, description=description)


ISSUES = [
    make_issue("b.py", 5, "missing_type_hints", "low"),
    make_issue("a.py", 1, "missing_tests", "critical"),
    make_issue("b.py", 2, "high_complexity", "high"),
    make_issue("a.py", 3, "missing_docstring", "medium"),
]


def test_prioritize_orders_by_severity():
    ordered = analyzer.prioritize(ISSUES)
    assert [i.severity for i in ordered] == ["critical", "high", "medium", "low"]


def test_group_by_file():
    grouped = analyzer.group_by_file(ISSUES)
    assert set(grouped) == {"a.py", "b.py"}
    assert [i.severity for i in grouped["b.py"]] == ["high", "low"]


def test_top_severity():
    assert analyzer.top_severity(ISSUES) == "critical"
    assert analyzer.top_severity([]) == "low"


def test_summarize_counts_types():
    counts = analyzer.summarize(ISSUES)
    assert counts["missing_tests"] == 1
    assert counts["missing_type_hints"] == 1


def test_build_plans_job_type_follows_most_severe_issue():
    plans = planner.build_plans(ISSUES)
    by_file = {p.target_file: p for p in plans}
    assert by_file["a.py"].job_type == "add_tests"
    assert by_file["a.py"].priority == "critical"
    assert by_file["b.py"].job_type == "refactor"
    assert plans[0].target_file == "a.py"  # critical sorts first


def test_plan_contains_all_suggested_changes():
    plans = planner.build_plans(ISSUES)
    by_file = {p.target_file: p for p in plans}
    assert len(by_file["a.py"].suggested_changes) == 2
    assert any("line 3" in c for c in by_file["a.py"].suggested_changes)


def test_effort_scales_with_issue_count():
    few = planner.build_plans([make_issue(line=i) for i in range(2)])
    many = planner.build_plans([make_issue(line=i) for i in range(12)])
    assert few[0].estimated_effort == "low"
    assert many[0].estimated_effort == "high"


def test_docstring_issues_map_to_docstring_job():
    plans = planner.build_plans([make_issue(issue_type="missing_docstring", severity="medium")])
    assert plans[0].job_type == "add_docstrings"
